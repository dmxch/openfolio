"""Dividend tracking via yfinance."""
import logging
from datetime import date

import yfinance as yf

from services import cache
from services.utils import get_fx_rate

logger = logging.getLogger(__name__)


def fetch_dividends(ticker: str, since_date: date, shares: float, currency: str = "USD") -> list[dict]:
    """Fetch dividend history for a ticker and compute expected payouts.

    Returns list of dicts with: date, dividend_per_share, currency, shares_held, total_chf
    """
    cache_key = f"divs:{ticker}:{since_date.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or divs.empty:
            return []

        # Filter to since_date
        divs = divs[divs.index >= str(since_date)]
        if divs.empty:
            return []

        # Get FX rate for conversion
        div_currency = getattr(t.fast_info, "currency", currency)
        fx = get_fx_rate(div_currency, "CHF")

        result = []
        for dt, amount in divs.items():
            total_chf = round(shares * float(amount) * fx, 2)
            result.append({
                "date": dt.date().isoformat(),
                "dividend_per_share": round(float(amount), 4),
                "currency": div_currency,
                "shares_held": shares,
                "total_chf": total_chf,
                "fx_rate": fx,
            })

        cache.set(cache_key, result, ttl=3600)
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch dividends for {ticker}: {e}")
        return []
