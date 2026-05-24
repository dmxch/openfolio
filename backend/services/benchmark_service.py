"""Benchmark index returns — monthly (heatmap) + exact-window (like-for-like)."""

import logging
from datetime import date

import pandas as pd

from services import cache
from yf_patch import yf_download

logger = logging.getLogger(__name__)

CACHE_TTL = 86400  # 24h

BENCHMARK_NAMES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^STOXX50E": "Euro Stoxx 50",
    "^SSMI": "SMI",
    "URTH": "MSCI World",
}


def get_benchmark_name(ticker: str) -> str:
    """Anzeigename eines Benchmark-Tickers (Fallback: Ticker selbst)."""
    return BENCHMARK_NAMES.get(ticker, ticker)


def get_benchmark_monthly_returns(ticker: str = "^GSPC") -> dict:
    """Calculate monthly returns for a benchmark index.

    Returns:
        {"months": [{"year": 2024, "month": 1, "return_pct": 2.5}, ...],
         "annual_totals": {2024: 12.3, ...},
         "ticker": "^GSPC", "name": "S&P 500"}
    """
    cache_key = f"benchmark_monthly:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    names = BENCHMARK_NAMES

    try:
        data = yf_download(ticker, period="5y", progress=False)
        if data is None or data.empty:
            logger.warning(f"No benchmark data for {ticker}")
            return {"months": [], "annual_totals": {}, "ticker": ticker, "name": names.get(ticker, ticker)}

        close_raw = data["Close"]
        # yf_download returns MultiIndex columns for single ticker — flatten
        if hasattr(close_raw, "columns"):
            close_raw = close_raw.iloc[:, 0] if len(close_raw.columns) == 1 else close_raw[ticker]
        close = close_raw.dropna()
        if close.empty:
            return {"months": [], "annual_totals": {}, "ticker": ticker, "name": names.get(ticker, ticker)}

        # Group by year-month, take first and last close per month
        monthly = []
        by_month: dict[tuple[int, int], list[float]] = {}
        for dt in close.index:
            key = (dt.year, dt.month)
            if key not in by_month:
                by_month[key] = []
            by_month[key].append(float(close[dt]))

        sorted_months = sorted(by_month.keys())
        prev_close = None
        for year, month in sorted_months:
            prices = by_month[(year, month)]
            month_close = prices[-1]  # Last trading day close
            if prev_close is not None and prev_close > 0:
                ret = (month_close / prev_close - 1) * 100
                monthly.append({"year": year, "month": month, "return_pct": round(ret, 2)})
            prev_close = month_close

        # Annual totals: compound monthly returns per year
        annual_totals: dict[int, float] = {}
        for year in set(m["year"] for m in monthly):
            compound = 1.0
            for m in monthly:
                if m["year"] == year:
                    compound *= (1 + m["return_pct"] / 100)
            annual_totals[year] = round((compound - 1) * 100, 2)

        result = {
            "months": monthly,
            "annual_totals": annual_totals,
            "ticker": ticker,
            "name": names.get(ticker, ticker),
        }
        cache.set(cache_key, result, ttl=CACHE_TTL)
        return result

    except Exception as e:
        logger.warning(f"Benchmark monthly returns failed for {ticker}: {e}")
        return {"months": [], "annual_totals": {}, "ticker": ticker, "name": names.get(ticker, ticker)}


def get_benchmark_window_return(ticker: str, start: date, end: date) -> float | None:
    """Exakte Preis-Rendite (%) eines Benchmark-Index ueber [start, end].

    Nutzt den letzten Close am-oder-vor jedem Rand-Datum, damit das Fenster zur
    tatsaechlichen Snapshot-Spanne eines Buckets passt (like-for-like) statt zur
    Monats-Granularitaet von get_benchmark_monthly_returns. None, wenn fuer das
    Fenster keine Daten verfuegbar sind.
    """
    cache_key = f"benchmark_window:{ticker}:{start.isoformat()}:{end.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached.get("return_pct")

    try:
        data = yf_download(ticker, period="5y", progress=False)
        if data is None or data.empty:
            return None

        close_raw = data["Close"]
        if hasattr(close_raw, "columns"):
            close_raw = close_raw.iloc[:, 0] if len(close_raw.columns) == 1 else close_raw[ticker]
        close = close_raw.dropna()
        if close.empty:
            return None

        # Index auf tz-naive Tagesstempel normalisieren, damit der .loc-Slice
        # nicht an tz-aware vs. tz-naive Vergleichen scheitert.
        idx = pd.to_datetime(close.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        close.index = idx

        base = close.loc[: pd.Timestamp(start)]
        last = close.loc[: pd.Timestamp(end)]
        if base.empty or last.empty:
            return None
        base_px = float(base.iloc[-1])
        last_px = float(last.iloc[-1])
        if base_px <= 0:
            return None

        ret = round((last_px / base_px - 1) * 100, 2)
        cache.set(cache_key, {"return_pct": ret}, ttl=CACHE_TTL)
        return ret

    except Exception as e:
        logger.warning(f"Benchmark window return failed for {ticker}: {e}")
        return None
