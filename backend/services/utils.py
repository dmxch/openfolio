import asyncio
import logging
from datetime import date as _date_type, timedelta

import yfinance as yf
from yf_patch import yf_download
import pandas as pd

from services import cache

logger = logging.getLogger(__name__)

EMERGENCY_FX = {"USDCHF": 0.88, "EURCHF": 0.95, "CADCHF": 0.63, "GBPCHF": 1.12, "JPYCHF": 0.006}


def get_fallback_fx() -> dict[str, float]:
    """Load last known FX rates from DB as fallback."""
    from services.cache_service import get_cached_price_sync
    fallbacks = {}
    for pair in ["USDCHF=X", "EURCHF=X", "CADCHF=X", "GBPCHF=X", "JPYCHF=X"]:
        cached_rate = get_cached_price_sync(pair, fallback_days=30)
        if cached_rate:
            key = pair.replace("=X", "")
            fallbacks[key] = cached_rate["price"]

    # Only if DB is completely empty: hardcoded emergency rates
    if not fallbacks:
        logger.critical("NO FX DATA IN DB - using emergency hardcoded rates")
        fallbacks = dict(EMERGENCY_FX)

    return fallbacks


def _resolve_extended_fx(currency: str) -> float | None:
    """CCY→CHF für Währungen ausserhalb des Standard-Batchs (SEK, AUD, HKD, …).

    Review 2026-07-02, H2: vorher fiel alles ausserhalb {USD,EUR,CAD,GBP,JPY}
    still auf 1.0 zurück (SEK-Beträge ~11× zu hoch). Reihenfolge: Redis →
    DB-Preiscache ({CCY}CHF=X) → yfinance (5d, letzter Close). Sync — Aufrufer
    im async Context müssen via asyncio.to_thread kommen (wie get_fx_rate).
    """
    cache_key = f"fx_ext:{currency}"
    cached = cache.get(cache_key)
    if cached is not None:
        # 0.0 = negativ gecachter Fehlschlag (Audit-Nit #4: sonst löst eine
        # dauerhaft unauflösbare Währung pro Aufruf einen yf_download aus)
        return cached if cached > 0 else None

    pair = f"{currency}CHF=X"
    from services.cache_service import get_cached_price_sync
    db_cached = get_cached_price_sync(pair, fallback_days=30)
    if db_cached:
        rate = float(db_cached["price"])
        cache.set(cache_key, rate, ttl=3600)
        return rate

    try:
        data = yf_download(pair, period="5d", progress=False, threads=False)
        if data is not None and not data.empty:
            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close) > 0:
                rate = float(close.iloc[-1])
                cache.set(cache_key, rate, ttl=3600)
                return rate
    except Exception as e:
        logger.warning(f"Extended FX fetch failed for {pair}: {e}")
    cache.set(cache_key, 0.0, ttl=300)  # Negative-Cache 5 min
    return None


def get_fx_rate(from_currency: str, to_currency: str = "CHF") -> float:
    if from_currency == to_currency:
        return 1.0
    rates = get_fx_rates_batch()

    def _to_chf(ccy: str) -> float:
        if ccy in rates:
            return rates[ccy]
        # DB-Fallback nur bei Batch-Miss laden (Review 2026-07-02, M26:
        # get_fallback_fx macht 5 Sync-DB-Queries — nicht bei jedem Aufruf).
        fb = get_fallback_fx().get(f"{ccy}CHF")
        if fb is not None:
            return fb
        ext = _resolve_extended_fx(ccy)
        if ext is not None:
            return ext
        logger.warning(f"FX rate {ccy}->CHF unresolvable, falling back to 1.0")
        return 1.0

    from_chf = _to_chf(from_currency)
    if to_currency == "CHF":
        return from_chf
    to_chf = _to_chf(to_currency)
    if to_chf == 0:
        return from_chf
    return from_chf / to_chf


def get_fx_rates_batch() -> dict[str, float]:
    cached = cache.get("fx_rates")
    if cached is not None:
        return cached

    rates = {"CHF": 1.0}
    currencies = ["USD", "EUR", "CAD", "GBP", "JPY"]
    tickers = [f"{ccy}CHF=X" for ccy in currencies]

    # Try DB cache first
    from services.cache_service import get_cached_price_sync
    db_hit = True
    for ccy, ticker in zip(currencies, tickers):
        db_cached = get_cached_price_sync(ticker, fallback_days=2)
        if db_cached:
            rates[ccy] = db_cached["price"]
        else:
            db_hit = False
            break

    if db_hit and len(rates) > 1:
        cache.set("fx_rates", rates)
        return rates

    # yfinance live
    rates = {"CHF": 1.0}
    fallback_fx = get_fallback_fx()
    try:
        data = yf_download(tickers, period="5d", progress=False, group_by="ticker")
        if data.empty:
            raise ValueError("empty")
        for ccy, ticker in zip(currencies, tickers):
            try:
                close = data[ticker]["Close"].dropna()
                if len(close) > 0:
                    rates[ccy] = float(close.iloc[-1])
                else:
                    fb = fallback_fx.get(f"{ccy}CHF")
                    if fb:
                        rates[ccy] = fb
                        logger.warning(f"FX {ccy}: using DB fallback rate {fb}")
            except (KeyError, IndexError):
                fb = fallback_fx.get(f"{ccy}CHF")
                if fb:
                    rates[ccy] = fb
                    logger.warning(f"FX {ccy}: using DB fallback rate {fb}")
    except Exception:
        logger.debug("FX batch download failed, using DB fallback", exc_info=True)
        # DB fallback (last 30 days)
        for ccy, ticker in zip(currencies, tickers):
            db_fallback = get_cached_price_sync(ticker, fallback_days=30)
            if db_fallback:
                rates[ccy] = db_fallback["price"]
            else:
                fb = fallback_fx.get(f"{ccy}CHF")
                if fb:
                    rates[ccy] = fb
                    logger.warning(f"FX {ccy}: using emergency fallback rate {fb}")

    cache.set("fx_rates", rates)
    return rates


def prefetch_close_series(tickers: list[str]) -> None:
    """Batch-download close series for all tickers to avoid yfinance thread-safety issues.

    Optimization (M-2): Only downloads 2y data and derives 1y from the last 252 trading days,
    eliminating the redundant second yfinance call.
    """
    # Only download tickers that don't have 2y data cached
    uncached = [t for t in tickers if cache.get(f"close:{t}:2y") is None]

    if uncached:
        try:
            ticker_str = " ".join(uncached)
            data = yf_download(ticker_str, period="2y", progress=False, group_by="ticker")
            if not data.empty:
                for ticker in uncached:
                    try:
                        if len(uncached) == 1:
                            try:
                                close = data[ticker]["Close"]
                            except (KeyError, TypeError):
                                close = data["Close"]
                            if isinstance(close, pd.DataFrame):
                                close = close.iloc[:, 0]
                            close = close.dropna()
                        else:
                            close = data[ticker]["Close"]
                            if isinstance(close, pd.DataFrame):
                                close = close.iloc[:, 0]
                            close = close.dropna()
                        if len(close) > 0:
                            cache.set(f"close:{ticker}:2y", close, ttl=86400)
                            # Derive 1y from 2y (last ~252 trading days)
                            close_1y = close.tail(252)
                            if len(close_1y) > 0:
                                cache.set(f"close:{ticker}:1y", close_1y, ttl=86400)
                    except (KeyError, IndexError):
                        continue
        except Exception:
            logger.debug("Prefetch close series failed for period 2y", exc_info=True)

    # For tickers that already had 2y cached but not 1y, derive 1y from 2y
    for ticker in tickers:
        if cache.get(f"close:{ticker}:1y") is None:
            close_2y = cache.get(f"close:{ticker}:2y")
            if close_2y is not None and len(close_2y) > 0:
                cache.set(f"close:{ticker}:1y", close_2y.tail(252), ttl=86400)


def _get_close_series(ticker: str, period: str = "1y") -> pd.Series | None:
    """Download and cache close price series for a ticker."""
    cache_key = f"close:{ticker}:{period}"
    # Historical close data changes at most daily — use 24h TTL for long periods
    ttl = 86400 if period in ("1y", "2y", "5y") else 900
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Try yfinance first
    try:
        data = yf_download(ticker, period=period, progress=False)
        if not data.empty:
            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close) > 0:
                cache.set(cache_key, close, ttl=ttl)
                return close
    except Exception:
        logger.debug(f"yfinance close series download failed for {ticker} ({period})", exc_info=True)

    # Fallback: price_cache DB table
    try:
        from services.cache_service import get_close_series_from_db
        close = get_close_series_from_db(ticker, period)
        if close is not None and len(close) > 0:
            logger.info(f"Using DB fallback for {ticker} ({period}): {len(close)} rows")
            cache.set(cache_key, close, ttl=ttl)
            return close
    except Exception as e:
        logger.debug(f"DB fallback failed for {ticker}: {e}")

    return None


def compute_moving_averages(ticker: str, periods: list[int] = None) -> dict[str, float | None]:
    if periods is None:
        periods = [50, 100, 150, 200]

    cache_key = f"ma:{ticker}:{','.join(map(str, periods))}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    close = _get_close_series(ticker, "1y")
    if close is None or close.empty:
        return {"current": None, **{f"ma{p}": None for p in periods}}

    result = {"current": float(close.iloc[-1])}
    for p in periods:
        if len(close) >= p:
            result[f"ma{p}"] = float(close.rolling(p).mean().iloc[-1])
        else:
            result[f"ma{p}"] = None
    cache.set(cache_key, result, ttl=3600)
    return result


def compute_mansfield_rs(ticker: str, benchmark: str = "^GSPC", period: int = 13) -> float | None:
    cache_key = f"mrs:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        stock_close = _get_close_series(ticker, "2y")
        bench_close = _get_close_series(benchmark, "2y")
        if stock_close is None or bench_close is None:
            return None

        stock_weekly = stock_close.resample("W-FRI").last().dropna()
        bench_weekly = bench_close.resample("W-FRI").last().dropna()

        common_idx = stock_weekly.index.intersection(bench_weekly.index)
        if len(common_idx) < period + 1:
            return None

        stock_weekly = stock_weekly.loc[common_idx]
        bench_weekly = bench_weekly.loc[common_idx]

        rs = stock_weekly / bench_weekly
        rs_ma = rs.ewm(span=period, adjust=False).mean()

        if rs_ma.iloc[-1] == 0 or pd.isna(rs_ma.iloc[-1]):
            return None

        mansfield = ((rs.iloc[-1] / rs_ma.iloc[-1]) - 1) * 100
        result = round(float(mansfield), 2)
        cache.set(cache_key, result, ttl=3600)
        return result
    except Exception:
        logger.debug(f"MRS calculation failed for {ticker}", exc_info=True)
        return None


def get_52w_range(ticker: str) -> dict[str, float | None]:
    cache_key = f"52w:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    close = _get_close_series(ticker, "1y")
    if close is None or close.empty:
        return {"high_52w": None, "low_52w": None, "pct_from_high": None}

    high = float(close.max())
    low = float(close.min())
    current = float(close.iloc[-1])
    pct_from_high = round(((current - high) / high) * 100, 2) if high else None
    result = {"high_52w": round(high, 2), "low_52w": round(low, 2), "pct_from_high": pct_from_high}
    cache.set(cache_key, result, ttl=3600)
    return result


# --- Historical FX (extracted from swissquote_parser, R5 of dividend plan) ---


async def _yf_fx_close(ticker: str, start: str, end: str) -> float | None:
    """Fetch a single closing FX rate from yfinance. Returns None on failure.

    Uses the thread-safe ``yf_download`` wrapper (sets a fresh requests.Session
    per call) via ``asyncio.to_thread`` (Heilige Regel #7).
    """
    try:
        data = await asyncio.to_thread(
            yf_download, ticker,
            start=start, end=end,
            progress=False, threads=False,
        )
        if data is not None and not data.empty:
            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close) > 0:
                return round(float(close.iloc[0]), 6)
    except Exception as e:
        logger.warning(f"yfinance FX fetch failed for {ticker}: {e}")
    return None


async def get_historical_fx_rate(currency: str, txn_date) -> float | None:
    """Fetch historical FX rate (foreign-currency → CHF) for a specific date.

    ``txn_date`` may be either an ISO string (``"2026-02-07"``) or a
    ``datetime.date``. Tries the direct pair (``USDCHF=X``), falls back to a
    cross-rate via USD (``USDCHF=X * CCYUSD=X`` or ``USDCHF=X / USDCCY=X``)
    if yfinance has no quotes for the direct pair.

    Returns the CHF-per-1-foreign-unit rate as a float, or ``None`` if all
    yfinance lookups fail (caller should fall back to the live rate or skip).
    """
    if isinstance(txn_date, str):
        d = _date_type.fromisoformat(txn_date)
    else:
        d = txn_date

    if currency == "CHF":
        return 1.0

    # Historische Raten ändern sich nicht — lang cachen. Review 2026-07-02,
    # H9: /dividends/pending feuerte sonst pro Zeile einen yf_download.
    cache_key = f"fx_hist:{currency}:{d.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start = d.isoformat()
    end = (d + timedelta(days=5)).isoformat()

    # Direct pair
    rate = await _yf_fx_close(f"{currency}CHF=X", start, end)
    if rate is not None:
        cache.set(cache_key, rate, ttl=7 * 24 * 3600)
        return rate

    # Cross-rate via USD: CCY→USD × USD→CHF
    logger.info(
        f"Direct FX pair {currency}CHF=X unavailable, trying cross-rate via USD for {start}"
    )
    ccy_usd = await _yf_fx_close(f"{currency}USD=X", start, end)
    usd_chf = await _yf_fx_close("USDCHF=X", start, end)
    if ccy_usd is not None and usd_chf is not None:
        rate = round(ccy_usd * usd_chf, 6)
        cache.set(cache_key, rate, ttl=7 * 24 * 3600)
        return rate

    # Inverse cross-rate: 1/USD→CCY × USD→CHF
    usd_ccy = await _yf_fx_close(f"USD{currency}=X", start, end)
    if usd_ccy is not None and usd_ccy > 0 and usd_chf is not None:
        rate = round((1.0 / usd_ccy) * usd_chf, 6)
        cache.set(cache_key, rate, ttl=7 * 24 * 3600)
        return rate

    logger.warning(f"All FX lookups failed for {currency} on {start}")
    return None
