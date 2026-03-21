"""Fetch next earnings dates from yfinance."""

import logging
from datetime import datetime

import yfinance as yf

from services import cache

logger = logging.getLogger(__name__)


def get_next_earnings_date(ticker: str) -> datetime | None:
    """Fetch next earnings date for a ticker. Returns None if unavailable."""
    cache_key = f"earnings:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "none" else None

    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
            # yfinance returns calendar as a dict with 'Earnings Date' key
            # or as a DataFrame depending on the version
            if isinstance(cal, dict):
                dates = cal.get("Earnings Date")
                if dates and len(dates) > 0:
                    ed = dates[0]
                    if isinstance(ed, str):
                        ed = datetime.fromisoformat(ed)
                    elif hasattr(ed, 'to_pydatetime'):
                        ed = ed.to_pydatetime()
                    cache.set(cache_key, ed, ttl=86400)  # cache 24h
                    return ed
            else:
                # DataFrame format
                if "Earnings Date" in cal.columns:
                    vals = cal["Earnings Date"].tolist()
                    if vals:
                        ed = vals[0]
                        if hasattr(ed, 'to_pydatetime'):
                            ed = ed.to_pydatetime()
                        cache.set(cache_key, ed, ttl=86400)
                        return ed
    except Exception as e:
        logger.debug(f"Could not fetch earnings for {ticker}: {e}")

    cache.set(cache_key, "none", ttl=86400)
    return None
