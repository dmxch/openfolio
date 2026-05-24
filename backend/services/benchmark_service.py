"""Benchmark index returns — monthly (heatmap) + exact-window (like-for-like)."""

import bisect
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


def _get_benchmark_closes(ticker: str) -> list[tuple[date, float]] | None:
    """Taegliche Schlusskurse eines Index als (date, close)-Liste, aufsteigend.

    Gecacht pro Ticker (nicht pro Fenster), damit ein einziger 5y-Download alle
    Fenster-Returns eines Tages bedient — sonst churnt der Cache, weil das
    Fenster-Ende (heute) taeglich weiterwandert und jeder Tag einen Miss + neuen
    Download je aktivem Bucket ausloeste.
    """
    cache_key = f"benchmark_closes:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return [(date.fromisoformat(d), c) for d, c in cached]

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
        # Index auf tz-naive Tagesstempel normalisieren (tz-aware vs. naive).
        idx = pd.to_datetime(close.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        series = sorted((ts.date(), float(v)) for ts, v in zip(idx, close.to_numpy()))
        cache.set(cache_key, [[d.isoformat(), c] for d, c in series], ttl=CACHE_TTL)
        return series
    except Exception as e:
        logger.warning(f"Benchmark close series failed for {ticker}: {e}")
        return None


def _last_close_on_or_before(series: list[tuple[date, float]], d: date) -> float | None:
    """Letzter Close mit Datum <= d (series aufsteigend sortiert)."""
    i = bisect.bisect_right(series, d, key=lambda s: s[0])
    return series[i - 1][1] if i > 0 else None


def get_benchmark_window_return(ticker: str, start: date, end: date) -> float | None:
    """Exakte Preis-Rendite (%) eines Benchmark-Index ueber [start, end].

    Nutzt den letzten Close am-oder-vor jedem Rand-Datum, damit das Fenster zur
    tatsaechlichen Snapshot-Spanne eines Buckets passt (like-for-like) statt zur
    Monats-Granularitaet von get_benchmark_monthly_returns. None, wenn fuer das
    Fenster keine Daten verfuegbar sind.
    """
    series = _get_benchmark_closes(ticker)
    if not series:
        return None
    base_px = _last_close_on_or_before(series, start)
    last_px = _last_close_on_or_before(series, end)
    if base_px is None or last_px is None or base_px <= 0:
        return None
    return round((last_px / base_px - 1) * 100, 2)
