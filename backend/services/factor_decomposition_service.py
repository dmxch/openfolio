"""Serverseitige Faktor-Decomposition (OLS) des liquiden Portfolios.

Hintergrund (Claude-Finance /risk-factor Feedback, Finding A+B, 5.6.2026)
-----------------------------------------------------------------------
Die Skill zog bisher 8 TradingView-Serien (je ~165k Zeichen) und stueckte sie
clientseitig per numpy-OLS zusammen — inkl. hart verdrahteter Exchange-Quirks
(SPY=AMEX, MTUM/VLUE/QUAL=CBOE, USDCHF=FX_IDC, BTC=COINBASE) und einer
Handelstag-Misalignment: portfolio_indexed ist 7/7 (BTC handelt am Wochenende),
die Faktor-ETFs nur werktags. Die clientseitige Regression alignte per
Kalendertag → Wochenend-Krypto-Bewegungen fielen raus, das BTC-Beta war
unterschaetzt und die Stichprobe halbierte sich (1088 → 594 Tage).

Dieser Service rechnet die Regression serverseitig gegen die ROHE taegliche
Liquid-Rekonstruktion (history_service, downsample=False → jede echte
Tagesbeobachtung, liquid=True → ohne Cash/Vorsorge, ohne PE/Immobilien) und
alignt alle Serien auf den NYSE-Handelskalender. Wochenend-Bewegungen werden
in die naechste Session kompoundiert (Level-Forward-Fill → pct_change), womit
sowohl die Portfolio- als auch die BTC/FX-Returns das Wochenende behalten —
das BTC-Beta wird nicht mehr unterschaetzt und die Stichprobe bleibt voll.

USDCHF=X laeuft als EIGENER Faktor mit (nicht als Waehrungsumrechnung der
Equity-Faktoren): die Regression attribuiert die CHF-Sicht-FX-Exposure auf das
USDCHF-Beta, exakt wie das bisherige Skill-Setup.

Reine Lese-Operation — beruehrt KEINE Performance-Berechnung (HEILIGE Regel 1).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, timedelta

from services import cache
from services.history_service import get_portfolio_history
from yf_patch import yf_download

logger = logging.getLogger(__name__)

# Faktor-Menu fix, gleiche Reihenfolge wie die Skill.
# (interner Key, yfinance-Ticker)
FACTORS: list[tuple[str, str]] = [
    ("SPY", "SPY"),        # Markt
    ("MTUM", "MTUM"),      # Momentum
    ("VLUE", "VLUE"),      # Value
    ("QUAL", "QUAL"),      # Quality
    ("IWM", "IWM"),        # Size (Small-Cap)
    ("GLD", "GLD"),        # Gold
    ("BTCUSD", "BTC-USD"), # Krypto
    ("USDCHF", "USDCHF=X"),# FX (CHF-Sicht)
]

MIN_OBS = 30           # weniger ueberlappende Handelstage → Regression nicht aussagekraeftig
CACHE_TTL = 3600       # Faktordaten aendern sich taeglich; 1h Cache
TRADING_DAYS_PER_YEAR = 252


def _extract_close(raw, yf_ticker: str):
    """Close-Serie eines Tickers aus dem yf_download-DataFrame ziehen.

    Bei mehreren Tickern liefert yfinance einen MultiIndex (Feld, Ticker);
    bei genau einem Ticker flache Spalten. Gibt None zurueck, wenn die Serie
    fehlt (Ticker nicht aufloesbar / Datenausfall).
    """
    try:
        import pandas as pd

        if isinstance(raw.columns, pd.MultiIndex):
            if ("Close", yf_ticker) in raw.columns:
                return raw[("Close", yf_ticker)]
            return None
        if "Close" in raw.columns:
            return raw["Close"]
        return None
    except Exception:
        return None


def _run_ols(ret) -> dict:
    """OLS der Spalte 'PF' auf [1, Faktoren]. ret ist ein pandas.DataFrame mit
    bereits aligned + dropna'ten Tagesrenditen, Spalte 'PF' + Faktor-Keys.
    """
    import numpy as np

    factor_keys = [k for k, _ in FACTORS if k in ret.columns and k != "PF"]
    y = ret["PF"].to_numpy(dtype=float)
    X = np.column_stack(
        [np.ones(len(ret))] + [ret[k].to_numpy(dtype=float) for k in factor_keys]
    )
    n, k = X.shape

    beta, _res, _rank, _sv = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = n - k
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof if dof > 0 else 0.0

    # Standardfehler via sigma^2 * (X'X)^-1
    sigma2 = ss_res / dof if dof > 0 else 0.0
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
        se = np.sqrt(np.clip(np.diag(xtx_inv) * sigma2, 0.0, None))
    except np.linalg.LinAlgError:
        se = np.full(k, float("nan"))

    def _t(i: int) -> float | None:
        if se[i] and se[i] > 0:
            return round(float(beta[i] / se[i]), 2)
        return None

    alpha_daily = float(beta[0])
    # annualisiertes Alpha (geometrisch, 252 Handelstage)
    alpha_ann_pct = ((1.0 + alpha_daily) ** TRADING_DAYS_PER_YEAR - 1.0) * 100.0

    factors_out = {}
    for idx, key in enumerate(factor_keys, start=1):
        factors_out[key] = {
            "beta": round(float(beta[idx]), 4),
            "std_err": round(float(se[idx]), 4) if se[idx] == se[idx] else None,  # NaN-safe
            "t_stat": _t(idx),
        }

    return {
        "alpha": {
            "daily": round(alpha_daily, 6),
            "annualized_pct": round(alpha_ann_pct, 2),
            "std_err": round(float(se[0]), 6) if se[0] == se[0] else None,
            "t_stat": _t(0),
        },
        "factors": factors_out,
        "r_squared": round(r2, 4),
        "adj_r_squared": round(adj_r2, 4),
        "n_obs": int(n),
    }


async def factor_decomposition(
    db,
    start_date: date,
    end_date: date,
    user_id: uuid.UUID | None = None,
) -> dict:
    """Regressiert die liquiden Portfolio-Tagesrenditen auf das Faktor-Menu.

    Returns dict mit alpha, factors{key:{beta,std_err,t_stat}}, r_squared,
    adj_r_squared, n_obs, window, missing_factors, method. Bei zu wenig
    ueberlappender Historie: {"error": "insufficient_history", "n_obs": N}.
    """
    cache_key = f"factor_decomp:{user_id}:{start_date}:{end_date}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    hist = await get_portfolio_history(
        db,
        start_date,
        end_date,
        user_id=user_id,
        downsample=False,  # rohe taegliche Rekonstruktion (raw=true)
        liquid=True,       # nur Rendite-Risikobuch (ohne Cash/Vorsorge/PE/Immobilien)
    )
    points = hist.get("data", [])
    if len(points) < MIN_OBS:
        return {"error": "insufficient_history", "n_obs": len(points)}

    import pandas as pd

    pf = pd.Series({p["date"]: float(p["portfolio_indexed"]) for p in points})
    pf.index = pd.to_datetime(pf.index)
    pf = pf.sort_index()

    # Ein einziger gebuendelter Download fuer alle 8 Ticker → genau ein Request.
    # Verhindert den yfinance-Burst-429 (Universe-wide parallele Calls bannen die
    # IP fuer Stunden — siehe feedback_yfinance_burst_429).
    yf_tickers = [yf for _, yf in FACTORS]
    fetch_start = pf.index.min().date().isoformat()
    fetch_end = (pf.index.max().date() + timedelta(days=1)).isoformat()  # yf end ist exklusiv
    try:
        raw = await asyncio.to_thread(
            yf_download,
            yf_tickers,
            start=fetch_start,
            end=fetch_end,
            interval="1d",
            auto_adjust=True,  # Total-Return (Dividenden reinvestiert) — korrekte Faktor-Returns
        )
    except Exception:
        logger.exception("Faktor-Download (yfinance) fehlgeschlagen")
        return {"error": "factor_fetch_failed", "n_obs": 0}

    if raw is None or len(raw) == 0:
        return {"error": "factor_fetch_failed", "n_obs": 0}

    closes: dict[str, "pd.Series"] = {}
    for key, yf in FACTORS:
        s = _extract_close(raw, yf)
        if s is not None and not s.dropna().empty:
            closes[key] = s.astype(float)
    missing = [key for key, _ in FACTORS if key not in closes]

    if "SPY" not in closes:
        # SPY definiert den NYSE-Handelskalender — ohne Markt-Faktor keine Regression.
        logger.warning("Faktor-Decomposition: SPY-Serie fehlt, Abbruch")
        return {"error": "factor_fetch_failed", "n_obs": 0}

    # NYSE-Handelskalender = SPY-Handelstage (Equity-Werktagskalender).
    calendar = closes["SPY"].dropna().index

    def aligned_returns(level: "pd.Series") -> "pd.Series":
        # Level auf den Handelskalender forward-fillen, dann pct_change.
        # Fuer 7/7-Serien (PF, BTC, USDCHF) kompoundiert das Wochenend-Bewegungen
        # in die Montags-Session; fuer Werktags-ETFs ist es die normale Tagesrendite.
        lvl = level.reindex(level.index.union(calendar)).sort_index().ffill()
        return lvl.reindex(calendar).pct_change()

    ret = pd.DataFrame({"PF": aligned_returns(pf)})
    for key, series in closes.items():
        ret[key] = aligned_returns(series)
    ret = ret.dropna()

    if len(ret) < MIN_OBS:
        return {"error": "insufficient_history", "n_obs": int(len(ret))}

    stats = _run_ols(ret)
    result = {
        **stats,
        "window": {
            "start": ret.index.min().date().isoformat(),
            "end": ret.index.max().date().isoformat(),
        },
        "missing_factors": missing,
        "method": (
            "OLS, taegliche Returns, NYSE-Session-aligned "
            "(Wochenende vorwaerts kompoundiert); liquid=True, raw=true"
        ),
    }
    cache.set(cache_key, result, CACHE_TTL)
    return result
