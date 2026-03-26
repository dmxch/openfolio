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
            "roic": _calc_roic(t, info),
            "roic_is_roe": _roic_is_roe(t, info),
            "currency": info.get("currency"),
            "sector": sector,
            "industry": industry,
            "industry_avg": peer_avg,
        }

        cache.set(cache_key, result, ttl=86400)  # 24h
        return result
    except Exception as e:
        logger.warning(f"yfinance key metrics failed for {ticker}: {e}")
        return {"ticker": ticker}


def _calc_roic(ticker_obj, info: dict) -> float | None:
    """Calculate ROIC with extended fallback chain.

    1. returnOnCapital from .info
    2. returnOnInvestedCapital from .info
    3. operatingIncome / (totalStockholderEquity + longTermDebt) from financials
    4. returnOnEquity from .info (ROE as approximation)
    """
    # Fallback 1: returnOnCapital
    roc = info.get("returnOnCapital")
    if roc is not None:
        return round(roc, 4)

    # Fallback 2: returnOnInvestedCapital
    roic = info.get("returnOnInvestedCapital")
    if roic is not None:
        return round(roic, 4)

    # Fallback 3: Calculate from financials (operatingIncome / invested capital)
    try:
        bs = ticker_obj.balance_sheet
        inc = ticker_obj.income_stmt
        if bs is not None and not bs.empty and inc is not None and not inc.empty:
            oi = inc.iloc[:, 0].get("Operating Income")
            eq = bs.iloc[:, 0].get("Stockholders Equity") or bs.iloc[:, 0].get("Total Stockholder Equity")
            ltd = bs.iloc[:, 0].get("Long Term Debt", 0) or 0
            if oi is not None and eq is not None:
                invested_capital = float(eq) + float(ltd)
                if invested_capital > 0:
                    return round(float(oi) / invested_capital, 4)
    except Exception:
        pass

    # Fallback 4: ROE as approximation
    roe = info.get("returnOnEquity")
    if roe is not None:
        return round(roe, 4)

    return None


def _roic_is_roe(ticker_obj, info: dict) -> bool:
    """Return True if ROIC value is actually ROE (fallback 4 was used)."""
    if info.get("returnOnCapital") is not None:
        return False
    if info.get("returnOnInvestedCapital") is not None:
        return False
    # Check if financials calculation would succeed
    try:
        bs = ticker_obj.balance_sheet
        inc = ticker_obj.income_stmt
        if bs is not None and not bs.empty and inc is not None and not inc.empty:
            oi = inc.iloc[:, 0].get("Operating Income")
            eq = bs.iloc[:, 0].get("Stockholders Equity") or bs.iloc[:, 0].get("Total Stockholder Equity")
            if oi is not None and eq is not None and (float(eq) + float(bs.iloc[:, 0].get("Long Term Debt", 0) or 0)) > 0:
                return False
    except Exception:
        pass
    # If we got here, ROE was used (or None)
    return info.get("returnOnEquity") is not None


def _de_ratio(val):
    """yfinance returns D/E as percentage (e.g. 42.0 means 0.42)."""
    if val is None:
        return None
    return round(val / 100, 2)
