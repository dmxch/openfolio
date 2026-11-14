"""Correlation matrix service.

Liefert paarweise Korrelationen der aktiven Portfolio-Positionen plus
HHI/Konzentrations-Metriken. Reine pandas-Implementierung — keine numpy/scipy
Dependencies.

Design-Entscheidungen siehe `.claude/plans/declarative-napping-glade.md`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from services import cache
from services.portfolio_service import get_portfolio_summary_cached
from yf_patch import yf_download

logger = logging.getLogger(__name__)

# Asset-Typen, die niemals in der Korrelations-Matrix erscheinen.
# Grund: Korrelationsberechnung braucht handelbare Zeitreihen; PE/RE haben
# keine Daily-Prices. Auch aus dem HHI fallen sie faktisch raus: der Input
# stammt aus get_portfolio_summary(), das PE/RE hart ausschliesst (siehe
# _compute_portfolio_concentration; dokumentiertes Ist-Verhalten in
# docs/EXTERNAL_API.md).
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

# Asset-Typen, die als investiertes Risiko-Kapital fuer den HHI zaehlen.
# Cash und Pension sind explizit raus (Dry Powder / Vorsorge, kein
# Konzentrationsrisiko im investierten Portfolio). private_equity und
# real_estate stehen bewusst NICHT im Set: der Input kommt aus
# get_portfolio_summary(), das beide nie liefert — die frühere Mitgliedschaft
# war toter Vorsatz und widersprach der Doku (docs/EXTERNAL_API.md: PE und
# Immobilien immer ausgeschlossen, auch aus dem HHI).
_HHI_INVESTED_TYPES: set[str] = {
    AssetType.stock.value,
    AssetType.etf.value,
    AssetType.bond.value,
    AssetType.crypto.value,
    AssetType.commodity.value,
}

_MIN_COMMON_DAYS = 20
_HIGH_CORR_THRESHOLD = 0.7
_CORR_DECIMALS = 4

# Cache-TTLs fuer die Endpoint-Schicht (portfolio.py + external_v1.py teilen
# sich den Key). Degeneriert = mindestens ein Ticker kam ohne jede Preisreihe
# zurueck (no_price_data) — die Signatur eines transienten Yahoo-Rate-Limits
# (Vorfall 01.07.2026: 7/14 Requests weg, Ergebnis 24h gepinnt). Solche
# Resultate nur kurz cachen, damit der naechste Compute sich selbst heilt;
# gleiches Muster wie der Broken-Score-Guard (Review 2026-07-02, M15).
CACHE_TTL = 86400
DEGENERATE_CACHE_TTL = 60


def result_cache_ttl(data: dict) -> int:
    """TTL fuer ein compute_correlation_matrix-Resultat (60s wenn degeneriert)."""
    warnings = data.get("warnings") or []
    if any(str(w).startswith("no_price_data:") for w in warnings):
        return DEGENERATE_CACHE_TTL
    return CACHE_TTL

# Rohkurse je (Ticker-Liste, Periode), kurz und nur im Prozess: parallele
# Aufrufe und Filter-Kombinationen mit denselben handelbaren Tickern (Cash und
# Vorsorge haben keine Kursreihe) teilen sich EINEN Download. Eigener, kleiner
# Speicher statt services.cache: dort bleiben abgelaufene Eintraege liegen, bis
# der Cache voll ist — fuer Frames dieser Groesse zu teuer.
_CLOSE_CACHE_TTL = 300.0
# Unvollstaendige Frames (Yahoo-Ausfall) kuerzer als DEGENERATE_CACHE_TTL
# halten, sonst heilt sich das Ergebnis nicht mehr nach 60 Sekunden.
_CLOSE_CACHE_DEGENERATE_TTL = 30.0
_CLOSE_CACHE_MAX_ENTRIES = 16
_close_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_close_cache_lock = threading.Lock()

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
    yf_period = _YF_PERIOD_ALIAS.get(period, period)
    # Als Liste: ein Element ist genau ein Symbol (K023).
    raw = yf_download(
        unique,
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


def _close_cache_get(key: str) -> pd.DataFrame | None:
    with _close_cache_lock:
        entry = _close_cache.get(key)
        if entry is None:
            return None
        expires_at, frame = entry
        if time.monotonic() >= expires_at:
            del _close_cache[key]
            return None
        return frame


def _close_cache_put(key: str, frame: pd.DataFrame, ttl: float) -> None:
    now = time.monotonic()
    with _close_cache_lock:
        for stale in [k for k, (expires_at, _) in _close_cache.items() if now >= expires_at]:
            del _close_cache[stale]
        _close_cache.pop(key, None)
        while len(_close_cache) >= _CLOSE_CACHE_MAX_ENTRIES:
            del _close_cache[next(iter(_close_cache))]  # aeltester Eintrag
        _close_cache[key] = (now + ttl, frame)


def _fetch_close_matrix_shared(tickers: list[str], period: str) -> pd.DataFrame:
    """Blocking: wie ``_fetch_close_matrix``, aber hoechstens ein Download je
    (Ticker-Liste, Periode) gleichzeitig und je ``_CLOSE_CACHE_TTL``."""
    unique = list(dict.fromkeys(tickers))
    digest = hashlib.sha256("\n".join(unique).encode()).hexdigest()[:32]
    key = f"{period}:{digest}"

    cached = _close_cache_get(key)
    if cached is not None:
        return cached

    with cache.single_flight(f"corr_close:{key}") as leader:
        cached = _close_cache_get(key)
        if cached is not None:
            return cached
        if not leader:
            # Der Leader ist gescheitert. Nicht hinterherladen — bei einem
            # Yahoo-Ausfall liefe sonst doch jeder Wartende einzeln los. Der
            # leere Frame ergibt ein degeneriertes, nur kurz gecachtes Resultat.
            return pd.DataFrame()
        frame = _fetch_close_matrix(unique, period)
        complete = all(t in frame.columns for t in unique)
        _close_cache_put(
            key, frame, _CLOSE_CACHE_TTL if complete else _CLOSE_CACHE_DEGENERATE_TTL
        )
        return frame


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


def _compute_portfolio_concentration(positions: list[dict]) -> dict:
    """HHI + Konzentrations-Metriken auf dem investierten Kapital.

    Universum: stock, etf, bond, crypto, commodity. Cash und Pension sind
    raus — kein Konzentrationsrisiko im investierten Portfolio. Private
    Equity und Immobilien sind immer ausgeschlossen (dokumentiertes
    Verhalten, docs/EXTERNAL_API.md): der Input stammt aus
    get_portfolio_summary(), das beide hart ausschliesst; das Set spiegelt
    diesen Ausschluss explizit.

    Input-Positions stammen aus `get_portfolio_summary()["positions"]` und
    enthalten `type`, `ticker`, `name`, `weight_pct` (Anteil am
    Gesamtportfolio, kann durch Cash/Pension < 100% summieren). Die Funktion
    renormalisiert auf 100% des investierten Kapital-Subsets.

    Classification per CFA convention: < 0.10 low, 0.10-0.18 moderate, > 0.18 high.
    """
    invested = [
        p for p in positions
        if p.get("type") in _HHI_INVESTED_TYPES
        and float(p.get("weight_pct") or 0.0) > 0
    ]

    total_pct = sum(float(p.get("weight_pct") or 0.0) for p in invested)
    if total_pct <= 0 or not invested:
        return {
            "hhi": 0.0,
            "effective_n": 0.0,
            "nominal_count": 0,
            "max_weight_ticker": None,
            "max_weight_name": None,
            "max_weight_pct": 0.0,
            "classification": "unknown",
        }

    hhi = 0.0
    max_p: dict | None = None
    max_frac = -1.0
    for p in invested:
        w = float(p.get("weight_pct") or 0.0)
        frac = w / total_pct  # in [0, 1]
        hhi += frac * frac
        if frac > max_frac:
            max_frac = frac
            max_p = p

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
        "nominal_count": len(invested),
        "max_weight_ticker": max_p.get("ticker") if max_p else None,
        "max_weight_name": max_p.get("name") if max_p else None,
        "max_weight_pct": round(max_frac * 100, 2),
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


def _build_matrix(
    close_df: pd.DataFrame,
    yf_tickers: list[str],
    pos_meta: dict[str, dict],
) -> dict[str, Any]:
    """Blocking: Returns, Korrelationsmatrix und Paare mit hoher Korrelation.

    Laeuft im Thread: die Aufbereitung ist O(N²) in der Zahl der Ticker und
    hielte sonst den Event-Loop an.
    """
    # Tickers that yfinance didn't return at all → warning.
    warnings: list[str] = [
        f"no_price_data:{t}" for t in yf_tickers if t not in close_df.columns
    ]

    returns, return_warnings = _compute_returns(close_df)
    warnings.extend(return_warnings)

    matrix_list: list[list[float | None]] = []
    matrix_tickers: list[str] = []
    high_correlations: list[dict] = []

    if not returns.empty and len(returns.columns) >= 1:
        corr = returns.corr()
        matrix_tickers = list(corr.columns)
        # Einmal in Python-Listen wandeln statt N² Einzelzugriffe ueber corr.iat.
        # NaN ist der einzige Wert, der sich selbst ungleich ist.
        values: list[list[float]] = corr.to_numpy(dtype=float).tolist()
        matrix_list = [
            [None if v != v else round(v, _CORR_DECIMALS) for v in row]
            for row in values
        ]

        # Upper-triangle high-correlation pairs.
        for i, row in enumerate(values):
            t1 = matrix_tickers[i]
            for j in range(i + 1, len(row)):
                v = row[j]
                if v != v or abs(v) < _HIGH_CORR_THRESHOLD:
                    continue
                t2 = matrix_tickers[j]
                high_correlations.append({
                    "ticker_a": t1,
                    "ticker_b": t2,
                    "correlation": round(v, _CORR_DECIMALS),
                    "interpretation": _classify_correlation_pair(t1, t2, v, pos_meta),
                })
        high_correlations.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    return {
        "matrix_tickers": matrix_tickers,
        "matrix": matrix_list,
        "high_correlations": high_correlations,
        "warnings": warnings,
        "observations": int(len(returns)) if not returns.empty else 0,
    }


# --- Public API ---------------------------------------------------------


async def compute_correlation_matrix(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str = "90d",
    include_cash: bool = False,
    include_pension: bool = False,
    include_commodity: bool = True,
    include_crypto: bool = True,
    bucket_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Compute the pairwise correlation matrix + HHI for a user's portfolio.

    Bei gesetztem ``bucket_id``: filtert auf Positionen des Buckets. Default
    None liefert das Gesamtportfolio (heutiges Verhalten, Backward-Compat).

    Raises `ValueError` if after filtering there are no tickers to correlate
    (the API layer translates this to HTTP 400).
    """
    summary = await get_portfolio_summary_cached(db, user_id)
    all_positions: list[dict] = summary.get("positions", [])

    if bucket_id is not None:
        bid = str(bucket_id)
        all_positions = [p for p in all_positions if p.get("bucket_id") == bid]

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

    # --- Fetch close prices and build the matrix (both off the event loop) ---
    close_df = await asyncio.to_thread(_fetch_close_matrix_shared, yf_tickers, period)
    built = await asyncio.to_thread(_build_matrix, close_df, yf_tickers, pos_meta)
    matrix_tickers: list[str] = built["matrix_tickers"]

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

    # --- HHI / Konzentration auf dem investierten Kapital (Portfolio-weit) ---
    # Entkoppelt von der Matrix-Filterung: Cash und Pension fallen raus (kein
    # Investment); PE/RE sind nie im Input (get_portfolio_summary schliesst
    # sie aus). Die include_*-Flags der Matrix beeinflussen den HHI bewusst
    # NICHT — Konzentration ist eine Portfolio-Eigenschaft, keine
    # Matrix-Eigenschaft.
    concentration = _compute_portfolio_concentration(all_positions)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "observations": built["observations"],
        "filters": {
            "include_cash": include_cash,
            "include_pension": include_pension,
            "include_commodity": include_commodity,
            "include_crypto": include_crypto,
        },
        "tickers": tickers_out,
        "matrix": built["matrix"],
        "high_correlations": built["high_correlations"],
        "concentration": concentration,
        "warnings": built["warnings"],
    }
