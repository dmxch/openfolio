"""Searches SEC EDGAR EFTS for recent 8-K filings mentioning share repurchases."""
import logging
import re
from datetime import date, timedelta

from services.api_utils import fetch_json

logger = logging.getLogger(__name__)

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_UA = "OpenFolio/1.0 screening@openfolio.dev"
LOOKBACK_DAYS = 30


def _extract_ticker(display_name: str) -> str | None:
    """Extract ticker from EDGAR display_name like 'PINTEREST, INC. (PINS)'."""
    match = re.search(r"\(([A-Z]{1,5})\)", display_name)
    if match:
        return match.group(1)
    # Try comma-separated tickers like '(Z, ZG)'
    match2 = re.search(r"\(([A-Z]{1,5}),", display_name)
    if match2:
        return match2.group(1)
    return None


def _extract_company(display_name: str) -> str:
    """Extract company name from EDGAR display_name."""
    # Remove CIK part
    name = re.sub(r"\s*\(CIK \d+\)", "", display_name)
    # Remove ticker part
    name = re.sub(r"\s*\([A-Z, -]+\)", "", name)
    return name.strip()


async def fetch_buybacks() -> list[dict]:
    """Fetch recent 8-K filings mentioning share repurchase or buyback.

    Returns list of {ticker, company, filing_date}.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)

    params = {
        "q": '"share repurchase" OR "stock buyback" OR "repurchase program"',
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": start_date.isoformat(),
        "enddt": end_date.isoformat(),
        "from": 0,
        "size": 100,
    }

    try:
        data = await fetch_json(
            EFTS_URL,
            params=params,
            headers={"User-Agent": SEC_UA},
            timeout=15,
        )
    except Exception:
        logger.exception("Failed to fetch SEC EDGAR 8-K buybacks")
        return []

    hits = data.get("hits", {}).get("hits", [])
    total = data.get("hits", {}).get("total", {}).get("value", 0)
    logger.info("SEC 8-K buybacks: %d hits (total: %d)", len(hits), total)

    seen_tickers: set[str] = set()
    results: list[dict] = []

    for hit in hits:
        src = hit.get("_source", {})
        names = src.get("display_names", [])
        period = src.get("period_ending", "")

        for name in names:
            ticker = _extract_ticker(name)
            if ticker and ticker not in seen_tickers:
                seen_tickers.add(ticker)
                results.append({
                    "ticker": ticker,
                    "company": _extract_company(name),
                    "filing_date": period,
                })
                break

    return results
