"""Correlation matrix service.

Liefert paarweise Korrelationen der aktiven Portfolio-Positionen plus
HHI/Konzentrations-Metriken. Reine pandas-Implementierung — keine numpy/scipy
Dependencies.

Design-Entscheidungen siehe `.claude/plans/declarative-napping-glade.md`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from services.portfolio_service import get_portfolio_summary
from yf_patch import yf_download

logger = logging.getLogger(__name__)

# Asset-Typen, die niemals in der Matrix oder HHI erscheinen (HEILIGE Regeln 4/6).
_ALWAYS_EXCLUDED: set[str] = {
    AssetType.real_estate.value,
    AssetType.private_equity.value,
}

# Asset-Typen, die per Default in der Matrix sind, aber per Query-Flag rausfallen.
_FLAG_CONTROLLED: dict[str, str] = {
    "cash": "include_cash",
    "pension": "include_pension",
    "commodity": "include_commodity",
    "crypto": "include_crypto",
}

_MIN_COMMON_DAYS = 20
_HIGH_CORR_THRESHOLD = 0.7
_CORR_DECIMALS = 4

# yfinance akzeptiert nur bestimmte Period-Strings. Unsere oeffentlichen
# Query-Werte (30d/90d/180d/1y) werden hier auf die yfinance-Aliasse gemappt.
_YF_PERIOD_ALIAS: dict[str, str] = {
    "30d": "1mo",
    "90d": "3mo",
    "180d": "6mo",
    "1y": "1y",
}


# --- Helpers ------------------------------------------------------------


def _resolve_yf_ticker(pos: Position) -> str | None:
    """Map a Position model row to a yfinance ticker string.

    Returns None for positions that cannot be priced via yfinance (cash,
    pension, or positions without any ticker).
    """
    if pos.type == AssetType.cash:
        return None
    if pos.type == AssetType.pension:
        return None
    if pos.gold_org:
        from services.precious_metals_service import get_metal_futures
        fut = get_metal_futures(pos.ticker)
        return fut[0] if fut else "GC=F"
    t = pos.yfinance_ticker or pos.ticker
    if not t:
        return None
    if t.startswith("CASH_"):
        return None
    return t


def _filter_universe(
    positions: list[dict],
    *,
    include_cash: bool,
    include_pension: bool,
    include_commodity: bool,
    include_crypto: bool,
) -> list[dict]:
    """Return only positions that should be included in the correlation matrix.

    `real_estate` and `private_equity` are ALWAYS excluded (HEILIGE Regeln 4/6).
    """
    flags = {
        "cash": include_cash,
        "pension": include_pension,
        "commodity": include_commodity,
        "crypto": include_crypto,
    }
    out: list[dict] = []
    for p in positions:
        ptype = p.get("type")
        if ptype in _ALWAYS_EXCLUDED:
            continue
        if ptype in flags and not flags[ptype]:
            continue
        out.append(p)
    return out


def _fetch_close_matrix(tickers: list[str], period: str) -> pd.DataFrame:
    """Blocking: fetch daily close prices for multiple tickers via yf_download.

    Returns a DataFrame with a DatetimeIndex and one column per ticker. Missing
    tickers are silently dropped from the output (caller will see fewer columns).
    """
    if not tickers:
        return pd.DataFrame()

    unique = list(dict.fromkeys(tickers))  # preserve order, dedupe
    tickers_str = " ".join(unique)
    yf_period = _YF_PERIOD_ALIAS.get(period, period)
    raw = yf_download(
        tickers_str,
        period=yf_period,
        group_by="ticker",
        auto_adjust=True,
    )

    if raw is None or raw.empty:
        return pd.DataFrame()

    closes: dict[str, pd.Series] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for t in unique:
            if t in raw.columns.get_level_values(0):
                sub = raw[t]
                if "Close" in sub.columns:
                    series = sub["Close"].dropna()
                    if not series.empty:
                        closes[t] = series
    else:
        # Single ticker: raw is a flat DataFrame with Close column
        if "Close" in raw.columns and len(unique) == 1:
            series = raw["Close"].dropna()
            if not series.empty:
                closes[unique[0]] = series

    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes)


def _compute_returns(
    close_df: pd.DataFrame, min_days: int = _MIN_COMMON_DAYS
) -> tuple[pd.DataFrame, list[str]]:
    """Compute simple daily returns, align on common dates, drop under-sampled.

    Returns `(returns_df, warnings)`. Tickers with fewer than `min_days`
    non-null observations are removed from the returns frame and recorded in
    `warnings` as `insufficient_history:{ticker}:{days}_days`.
    """
    warnings: list[str] = []
    if close_df.empty:
        return pd.DataFrame(), warnings

    returns = close_df.pct_change().dropna(how="all")
    # Count per-ticker observations before any joint alignment.
    keep: list[str] = []
    for col in returns.columns:
        count = int(returns[col].notna().sum())
        if count < min_days:
            warnings.append(f"insufficient_history:{col}:{count}_days")
        else:
            keep.append(col)

    returns = returns[keep]
    # Align on joint dates — drop rows where any remaining ticker is NaN.
    if not returns.empty:
        returns = returns.dropna(how="any")

    # After joint alignment, re-check min_days on the joint index.
    if not returns.empty and len(returns) < min_days:
        warnings.append(
            f"insufficient_joint_history:{len(returns)}_days"
        )
        return pd.DataFrame(), warnings

    return returns, warnings


def _compute_concentration(weights: list[tuple[str, float]]) -> dict:
    """HHI, effective_n, max_weight_ticker from (ticker, weight_pct) pairs.

    Renormalisiert die Eingabe-Gewichte auf 100% des **übergebenen Universums**
    und rechnet HHI darauf. Der Caller ist dafür verantwortlich, nur die
    Tickers zu übergeben, die wirklich in der Matrix landen — sonst entsteht
    Inkonsistenz zwischen `tickers[]` und `concentration` (siehe HEILIGE
    Test-Erkenntnis: ohne Renormalisierung wird ein gefilterter Cash-Eintrag
    weiterhin als max_weight_ticker angezeigt).

    `max_weight_pct` ist der renormalisierte Wert (Anteil am gefilterten
    Universum, in Prozent), nicht der Original-Anteil am Gesamtportfolio.

    Classification per CFA convention: < 0.10 low, 0.10-0.18 moderate, > 0.18 high.
    """
    total_pct = sum(w for _, w in weights)
    if total_pct <= 0:
        return {
            "hhi": 0.0,
            "effective_n": 0.0,
            "max_weight_ticker": None,
            "max_weight_pct": 0.0,
            "classification": "unknown",
        }

    hhi = 0.0
    max_t: str | None = None
    max_frac = -1.0
    for t, w in weights:
        frac = w / total_pct  # in [0, 1]
        hhi += frac * frac
        if frac > max_frac:
            max_frac = frac
            max_t = t

    effective_n = (1.0 / hhi) if hhi > 0 else 0.0

    if hhi < 0.10:
        classification = "low"
    elif hhi <= 0.18:
        classification = "moderate"
    else:
        classification = "high"

    return {
        "hhi": round(hhi, 4),
        "effective_n": round(effective_n, 2),
        "max_weight_ticker": max_t,
        "max_weight_pct": round(max_frac * 100, 2),  # in % des gefilterten Universums
        "classification": classification,
    }


def _classify_correlation_pair(
    t1: str, t2: str, r: float, pos_meta: dict[str, dict]
) -> str:
    """Short human-readable classification for a correlated pair.

    Looks up sector/type in `pos_meta` (keyed by the yf-ticker used in the matrix).
    """
    meta1 = pos_meta.get(t1, {})
    meta2 = pos_meta.get(t2, {})
    type1, type2 = meta1.get("type"), meta2.get("type")
    sec1, sec2 = meta1.get("sector"), meta2.get("sector")

    direction = "positiv" if r >= 0 else "negativ"
    strength = "stark" if abs(r) >= 0.85 else "erhöht"

    if type1 and type2 and type1 == type2 and sec1 and sec2 and sec1 == sec2:
        return f"gleicher Sektor ({sec1}) — {strength} {direction} korreliert"
    if type1 and type2 and type1 == type2:
        return f"gleicher Asset-Typ ({type1}) — {strength} {direction} korreliert"
    if sec1 and sec2 and sec1 == sec2:
        return f"gleicher Sektor ({sec1}) — {strength} {direction} korreliert"
    return f"{strength} {direction} korreliert"


# --- Public API ---------------------------------------------------------


async def compute_correlation_matrix(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str = "90d",
    include_cash: bool = False,
    include_pension: bool = False,
    include_commodity: bool = True,
    include_crypto: bool = True,
) -> dict[str, Any]:
    """Compute the pairwise correlation matrix + HHI for a user's portfolio.

    Raises `ValueError` if after filtering there are no tickers to correlate
    (the API layer translates this to HTTP 400).
    """
    summary = await get_portfolio_summary(db, user_id)
    all_positions: list[dict] = summary.get("positions", [])

    # --- Matrix universe ---
    matrix_positions = _filter_universe(
        all_positions,
        include_cash=include_cash,
        include_pension=include_pension,
        include_commodity=include_commodity,
        include_crypto=include_crypto,
    )

    if not matrix_positions:
        raise ValueError("Keine Positionen nach Filterung übrig")

    # Load full Position rows (for yfinance_ticker / gold_org — the summary
    # dict doesn't expose those fields).
    pos_ids = [uuid.UUID(p["id"]) for p in matrix_positions if p.get("id")]
    pos_rows: list[Position] = []
    if pos_ids:
        res = await db.execute(
            select(Position).where(
                Position.id.in_(pos_ids),
                Position.user_id == user_id,
            )
        )
        pos_rows = list(res.scalars().all())

    # Map summary dicts keyed by id for metadata lookups.
    summary_by_id = {p["id"]: p for p in matrix_positions}

    # Resolve yf tickers, drop cash/pension/untickered rows.
    # pos_meta is keyed by the *yf ticker* — the same label pandas will use.
    pos_meta: dict[str, dict] = {}
    yf_tickers: list[str] = []
    for pos in pos_rows:
        yf = _resolve_yf_ticker(pos)
        if not yf:
            continue
        yf_tickers.append(yf)
        sdict = summary_by_id.get(str(pos.id), {})
        pos_meta[yf] = {
            "ticker": pos.ticker,
            "name": pos.name,
            "type": pos.type.value if pos.type else None,
            "sector": pos.sector,
            "weight_pct": float(sdict.get("weight_pct") or 0.0),
        }

    if not yf_tickers:
        raise ValueError("Keine handelbaren Tickers nach Filterung")

    # --- Fetch close prices (off the event loop) ---
    close_df = await asyncio.to_thread(_fetch_close_matrix, yf_tickers, period)

    # Tickers that yfinance didn't return at all → warning.
    warnings: list[str] = []
    missing = [t for t in yf_tickers if t not in close_df.columns]
    for t in missing:
        warnings.append(f"no_price_data:{t}")

    returns, return_warnings = _compute_returns(close_df)
    warnings.extend(return_warnings)

    matrix_list: list[list[float]] = []
    matrix_tickers: list[str] = []
    high_correlations: list[dict] = []

    if not returns.empty and len(returns.columns) >= 1:
        corr = returns.corr()
        matrix_tickers = list(corr.columns)
        for i, t1 in enumerate(matrix_tickers):
            row = []
            for j, t2 in enumerate(matrix_tickers):
                v = corr.iat[i, j]
                if pd.isna(v):
                    row.append(None)
                else:
                    row.append(round(float(v), _CORR_DECIMALS))
            matrix_list.append(row)

        # Upper-triangle high-correlation pairs.
        pairs: list[dict] = []
        for i in range(len(matrix_tickers)):
            for j in range(i + 1, len(matrix_tickers)):
                v = corr.iat[i, j]
                if pd.isna(v):
                    continue
                if abs(float(v)) >= _HIGH_CORR_THRESHOLD:
                    t1, t2 = matrix_tickers[i], matrix_tickers[j]
                    pairs.append({
                        "ticker_a": t1,
                        "ticker_b": t2,
                        "correlation": round(float(v), _CORR_DECIMALS),
                        "interpretation": _classify_correlation_pair(
                            t1, t2, float(v), pos_meta
                        ),
                    })
        pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)
        high_correlations = pairs

    # Ticker metadata (only for what's in the matrix).
    tickers_out = [
        {
            "yf_ticker": t,
            "ticker": pos_meta.get(t, {}).get("ticker") or t,
            "name": pos_meta.get(t, {}).get("name"),
            "type": pos_meta.get(t, {}).get("type"),
            "sector": pos_meta.get(t, {}).get("sector"),
            "weight_pct": pos_meta.get(t, {}).get("weight_pct", 0.0),
        }
        for t in matrix_tickers
    ]

    # --- HHI / Konzentration auf demselben Universum wie die Matrix ---
    # Wichtig: nur Tickers, die wirklich in tickers_out landen — sonst entsteht
    # Inkonsistenz (z.B. bei include_cash=False wuerde ein gefilterter Cash-
    # Eintrag sonst weiterhin als max_weight_ticker erscheinen). Wir nutzen den
    # Display-`ticker` (nicht den yf_ticker), damit max_weight_ticker dem
    # entspricht, was der Konsument auch in tickers[].ticker sieht.
    matrix_weights: list[tuple[str, float]] = [
        (entry["ticker"], float(entry.get("weight_pct") or 0.0))
        for entry in tickers_out
    ]
    concentration = _compute_concentration(matrix_weights)

    observations = int(len(returns)) if not returns.empty else 0

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "observations": observations,
        "filters": {
            "include_cash": include_cash,
            "include_pension": include_pension,
            "include_commodity": include_commodity,
            "include_crypto": include_crypto,
        },
        "tickers": tickers_out,
        "matrix": matrix_list,
        "high_correlations": high_correlations,
        "concentration": concentration,
        "warnings": warnings,
    }
