"""Patch yfinance before any other module imports it.

Must be imported at the very top of main.py, before any service imports.
Fixes:
1. Suppresses noisy "failed to get ticker" log messages
2. Updates the outdated User-Agent (Chrome 39) that Yahoo Finance now blocks with 429
3. Suppresses Pandas4Warning deprecation spam from yfinance internals
4. Provides thread-safe yf_download() wrapper for use with asyncio.to_thread()
"""
import logging
import warnings

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

import requests  # noqa: E402 — intentional: yfinance requires requests.Session, no httpx alternative
import yfinance as yf  # noqa: E402
import yfinance.data as yfdata  # noqa: E402

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

yfdata.YfData.user_agent_headers = {"User-Agent": _USER_AGENT}
if hasattr(yfdata.YfData, "_instances"):
    yfdata.YfData._instances = {}

# Must be set AFTER yfinance/pandas are imported, as they register their own filters
from pandas.errors import Pandas4Warning  # noqa: E402

warnings.filterwarnings("ignore", category=Pandas4Warning)


def yf_download(tickers, **kwargs):
    """Thread-safe wrapper for yf.download().

    Creates a fresh requests.Session per call to avoid shared state
    when multiple downloads run concurrently via asyncio.to_thread().
    Also forces threads=False (yfinance internal threading conflicts
    with asyncio thread pool).
    """
    kwargs.setdefault("progress", False)
    kwargs["threads"] = False
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    kwargs["session"] = session
    try:
        return yf.download(tickers, **kwargs)
    finally:
        session.close()


import threading  # noqa: E402

# yf.Ticker-Zugriffe (.info/.fast_info/.calendar) teilen YfData._instances
# über Threads und sind NICHT thread-safe (Cross-Ticker-Datenverschmutzung,
# dokumentiert in unusual_volume_service). Ein Lock serialisiert die Zugriffe;
# Durchsatz ist hier unkritisch, Korrektheit nicht.
_ticker_lock = threading.Lock()


def yf_ticker_attr(ticker: str, attr: str):
    """Thread-safe access to yf.Ticker(...).<attr> (info, fast_info, calendar).

    Blocking — only call via asyncio.to_thread() from async context.
    Returns the attribute value or raises whatever yfinance raises.
    """
    with _ticker_lock:
        session = requests.Session()
        session.headers.update({"User-Agent": _USER_AGENT})
        try:
            t = yf.Ticker(ticker, session=session)
            return getattr(t, attr)
        finally:
            session.close()


def yf_quote_currency(ticker: str) -> str | None:
    """Quote currency from yfinance fast_info ('GBp' for pence-quoted LSE).

    Returns None on any failure — callers must treat None as unknown.
    """
    try:
        fi = yf_ticker_attr(ticker, "fast_info")
        cur = getattr(fi, "currency", None) or (fi.get("currency") if hasattr(fi, "get") else None)
        return str(cur) if cur else None
    except Exception:
        return None
