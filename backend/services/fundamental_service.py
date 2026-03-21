"""Fundamental metrics extracted from yfinance ticker.info.

Uses a dedicated yfinance call with aggressive caching (24h) to avoid
hitting rate limits. Falls back gracefully when Yahoo is unavailable.
"""

import logging

import httpx
import yfinance as yf

from services import cache

logger = logging.getLogger(__name__)


def get_key_metrics(ticker: str) -> dict:
    """Fetch key fundamental metrics from yfinance ticker.info."""
    cache_key = f"key_metrics:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        if not info.get("marketCap"):
            logger.info(f"No yfinance info available for {ticker}")
            return {"ticker": ticker}

        from services.industry_averages import get_industry_averages

        industry = info.get("industry")
        sector = info.get("sector")
        peer_avg = get_industry_averages(industry, sector)

        result = {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName"),
            "revenue": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),
            "gross_margins": info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "profit_margins": info.get("profitMargins"),
            "debt_to_equity": _de_ratio(info.get("debtToEquity")),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),
            "market_cap": info.get("marketCap"),
            "trailing_eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
            "current_ratio": info.get("currentRatio"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "earnings_growth": info.get("earningsGrowth"),
            "sector": sector,
            "industry": industry,
            "industry_avg": peer_avg,
        }

        cache.set(cache_key, result, ttl=86400)  # 24h
        return result
    except Exception as e:
        logger.warning(f"yfinance key metrics failed for {ticker}: {e}")
        return {"ticker": ticker}


def _de_ratio(val):
    """yfinance returns D/E as percentage (e.g. 42.0 means 0.42)."""
    if val is None:
        return None
    return round(val / 100, 2)
