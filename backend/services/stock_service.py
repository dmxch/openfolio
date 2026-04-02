import logging

import yfinance as yf

from config import settings
from services import cache
from services.api_utils import fetch_json

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"


def _get_cached(key, ttl):
    return cache.get(key)


def _set_cached(key, data):
    cache.set(key, data, ttl=86400)


def get_company_profile(ticker: str) -> dict:
    cached = _get_cached(f"profile:{ticker}", 86400)
    if cached is not None:
        return cached

    info = yf.Ticker(ticker).info or {}

    result = {
        "description": info.get("longBusinessSummary"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "website": info.get("website"),
        "fullTimeEmployees": info.get("fullTimeEmployees"),
        "country": info.get("country"),
        "marketCap": info.get("marketCap"),
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "dividendYield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "quoteType": info.get("quoteType"),
    }

    _set_cached(f"profile:{ticker}", result)
    return result


async def get_fundamentals(ticker: str) -> list[dict] | None:
    if not settings.fmp_api_key:
        return None

    cached = _get_cached(f"fundamentals:{ticker}", 86400)
    if cached is not None:
        return cached

    api_key = settings.fmp_api_key
    params = {"symbol": ticker, "period": "quarter", "limit": 5, "apikey": api_key}

    async def _safe_fmp_get(url: str, params: dict) -> list:
        try:
            data = await fetch_json(url, params=params, timeout=10)
            if not isinstance(data, list):
                return []
            return data
        except Exception as e:
            logger.warning(f"FMP request/parse error for {ticker}: {e}")
            return []

    income = await _safe_fmp_get(f"{FMP_BASE}/income-statement", params)
    cashflow = await _safe_fmp_get(f"{FMP_BASE}/cash-flow-statement", params)
    balance = await _safe_fmp_get(f"{FMP_BASE}/balance-sheet-statement", params)

    if not isinstance(income, list) or not income:
        return []

    # Index cashflow and balance by date
    cf_by_date = {item["date"]: item for item in cashflow} if isinstance(cashflow, list) else {}
    bs_by_date = {item["date"]: item for item in balance} if isinstance(balance, list) else {}

    merged = []
    for inc in income:
        date = inc.get("date")
        cf = cf_by_date.get(date, {})
        bs = bs_by_date.get(date, {})

        total_debt = bs.get("totalDebt")
        total_equity = bs.get("totalStockholdersEquity")
        debt_to_equity = None
        if total_debt is not None and total_equity and total_equity != 0:
            debt_to_equity = round(total_debt / total_equity, 2)

        merged.append({
            "date": date,
            "period": inc.get("period"),
            "calendarYear": inc.get("calendarYear") or inc.get("fiscalYear"),
            "revenue": inc.get("revenue"),
            "grossProfit": inc.get("grossProfit"),
            "netIncome": inc.get("netIncome"),
            "eps": inc.get("eps"),
            "ebitda": inc.get("ebitda"),
            "operatingIncome": inc.get("operatingIncome"),
            "operatingCashFlow": cf.get("operatingCashFlow"),
            "freeCashFlow": cf.get("freeCashFlow"),
            "capitalExpenditure": cf.get("capitalExpenditure"),
            "totalDebt": total_debt,
            "totalStockholdersEquity": total_equity,
            "totalAssets": bs.get("totalAssets"),
            "cashAndCashEquivalents": bs.get("cashAndCashEquivalents"),
            "netDebt": bs.get("netDebt"),
            "debt_to_equity": debt_to_equity,
        })

    merged.sort(key=lambda x: x["date"])

    _set_cached(f"fundamentals:{ticker}", merged)
    return merged


async def get_stock_news(ticker: str) -> list[dict] | None:
    if not settings.fmp_api_key:
        return None

    cached = _get_cached(f"news:{ticker}", 3600)
    if cached is not None:
        return cached

    try:
        resp = await fetch_json(
            f"{FMP_BASE}/news/stock",
            params={"tickers": ticker, "limit": 10, "apikey": settings.fmp_api_key},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"FMP news request/parse error: {e}")
        _set_cached(f"news:{ticker}", [])
        return []

    if not isinstance(resp, list) or not resp:
        _set_cached(f"news:{ticker}", [])
        return []

    articles = []
    for item in resp:
        text = item.get("text") or ""
        articles.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "publishedDate": item.get("publishedDate"),
            "site": item.get("site"),
            "text": text[:200],
        })

    _set_cached(f"news:{ticker}", articles)
    return articles
