"""Scrapes Capitol Trades for recent congressional stock trades."""
import logging
import re

from services.api_utils import fetch_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.capitoltrades.com/trades"
RSC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "RSC": "1",
    "Next-Router-State-Tree": (
        "%5B%22%22%2C%7B%22children%22%3A%5B%22trades%22%2C%7B%22"
        "children%22%3A%5B%22__PAGE__%22%2C%7B%7D%5D%7D%5D%7D%2C"
        "null%2Cnull%2Ctrue%5D"
    ),
}


def _clean_ticker(raw: str) -> str:
    """Convert 'AAPL:US' or 'BRK/B:US' to 'AAPL' or 'BRK.B'."""
    ticker = raw.split(":")[0].strip()
    ticker = ticker.replace("/", ".")
    return ticker.upper()


def _parse_rsc(text: str) -> list[dict]:
    """Parse Next.js RSC streaming response for trade data."""
    tickers = re.findall(r'"issuerTicker":"([^"]+)"', text)
    names = re.findall(r'"issuerName":"([^"]+)"', text)
    tx_types = re.findall(r'"txType":"([^"]+)"', text)
    values = re.findall(r'"value":(\d+)', text)
    chambers = re.findall(r'"chamber":"([^"]+)"', text)
    pol_ids = re.findall(r'"_politicianId":"([^"]+)"', text)

    # Build a lookup of issuer tickers/names from the page data
    issuer_map: dict[str, str] = {}
    for t, n in zip(tickers, names):
        clean = _clean_ticker(t)
        if clean and clean not in issuer_map:
            issuer_map[clean] = n

    # Extract actual trade entries (txType matches)
    trades: list[dict] = []
    for i, tx in enumerate(tx_types):
        trade: dict = {"tx_type": tx}
        if i < len(chambers):
            trade["chamber"] = chambers[i]
        if i < len(values):
            trade["value"] = int(values[i])
        trades.append(trade)

    return trades, issuer_map


async def _fetch_page_with_buy_tickers(page: int) -> list[dict]:
    """Fetch a single page and extract tickers associated with buy transactions."""
    url = f"{BASE_URL}?per_page=96&page={page}&txType=buy&txDate=90d"
    try:
        text = await fetch_text(url, headers=RSC_HEADERS, timeout=15)
    except Exception:
        return []

    tickers = re.findall(r'"issuerTicker":"([^"]+)"', text)
    names = re.findall(r'"issuerName":"([^"]+)"', text)
    tx_types = re.findall(r'"txType":"([^"]+)"', text)

    # Build ticker -> name mapping
    ticker_names: dict[str, str] = {}
    for t, n in zip(tickers, names):
        clean = _clean_ticker(t)
        if clean:
            ticker_names[clean] = n

    results = []
    for ticker, name in ticker_names.items():
        results.append({
            "ticker": ticker,
            "company": name,
        })

    return results


async def fetch_congressional_buys() -> list[dict]:
    """Fetch congressional BUY trades only (90 days).

    Returns list of {ticker, company}.
    """
    import asyncio

    results: dict[str, dict] = {}
    for page in range(1, 4):
        entries = await _fetch_page_with_buy_tickers(page)
        if not entries:
            break
        for entry in entries:
            t = entry["ticker"]
            if t not in results:
                results[t] = entry

    logger.info("Capitol Trades congressional buys: %d tickers", len(results))
    return list(results.values())
