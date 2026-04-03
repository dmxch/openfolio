"""Scrapes Dataroma for superinvestor activity and consensus holdings."""
import logging
import re
from html.parser import HTMLParser

from services.api_utils import fetch_text

logger = logging.getLogger(__name__)

RT_URL = "https://www.dataroma.com/m/rt.php"
PORTFOLIO_URL = "https://www.dataroma.com/m/g/portfolio_b.php"
DATAROMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html",
    "Referer": "https://www.dataroma.com/",
}


def _parse_html_table(html: str) -> list[list[str]]:
    """Extract rows from the first HTML table with <tr>/<td> tags."""
    rows: list[list[str]] = []
    raw_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    for raw in raw_rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", raw, re.DOTALL)
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if clean and any(clean):
            rows.append(clean)
    return rows


async def fetch_superinvestor_buys() -> list[dict]:
    """Fetch recent superinvestor buy transactions from Dataroma real-time feed.

    Returns list of {ticker, investor, company, value}.
    """
    try:
        html = await fetch_text(RT_URL, headers=DATAROMA_HEADERS, timeout=15)
    except Exception:
        logger.exception("Failed to fetch Dataroma real-time feed")
        return []

    rows = _parse_html_table(html)
    if not rows:
        return []

    # Expected columns: Date, Filing, Name, Activity, Security, Shares, Price, Total
    results: list[dict] = []
    for row in rows:
        if len(row) < 8:
            continue
        activity = row[3].strip().lower()
        if "buy" not in activity:
            continue

        # Extract ticker from the security name link
        ticker_match = re.search(r"/m/stock\.php\?sym=([A-Z]+)", str(row))
        # Fallback: try to find ticker in raw HTML near this row
        company = row[4].strip()
        investor = row[2].strip()
        value_str = row[7].strip()

        # Parse value
        value = 0.0
        cleaned = re.sub(r"[^0-9.]", "", value_str)
        try:
            value = float(cleaned)
        except (ValueError, TypeError):
            pass

        results.append({
            "investor": investor,
            "company": company,
            "value": value,
        })

    # Extract tickers from stock links — they appear in the same row order
    ticker_links = re.findall(r'/m/stock\.php\?sym=([A-Z]+)', html)

    # Map tickers to buy entries (ticker links appear in same order as table rows,
    # but we only kept rows with "buy" activity, so we need to re-align)
    # Re-parse all rows to find which indices are buys
    buy_indices: list[int] = []
    for idx, row in enumerate(rows):
        if len(row) < 8:
            continue
        activity = row[3].strip().lower()
        if "buy" in activity:
            buy_indices.append(idx)

    for i, result in enumerate(results):
        if i < len(buy_indices) and buy_indices[i] < len(ticker_links):
            result["ticker"] = ticker_links[buy_indices[i]]

    # Remove entries without ticker
    results = [r for r in results if r.get("ticker")]

    logger.info("Dataroma superinvestor buys: %d entries", len(results))
    return results


async def fetch_grand_portfolio() -> list[dict]:
    """Fetch Dataroma Grand Portfolio — top holdings across 82 superinvestors.

    Returns list of {ticker, company, num_investors, portfolio_weight}.
    """
    try:
        html = await fetch_text(PORTFOLIO_URL, headers=DATAROMA_HEADERS, timeout=15)
    except Exception:
        logger.exception("Failed to fetch Dataroma Grand Portfolio")
        return []

    # Extract ticker symbols from links
    tickers = re.findall(r"/m/stock\.php\?sym=([A-Z]+)", html)
    unique_tickers = list(dict.fromkeys(tickers))  # preserve order, deduplicate

    rows = _parse_html_table(html)
    if not rows:
        # Fallback: just return the tickers we found
        return [{"ticker": t, "company": "", "num_investors": 0} for t in unique_tickers]

    # Expected columns: Ticker, Company, Weight, #Investors, ...
    results: list[dict] = []
    for i, row in enumerate(rows):
        if len(row) < 4:
            continue

        ticker = row[0].strip().upper()
        if not ticker or not ticker.isalpha():
            continue

        company = row[1].strip()

        # Number of investors
        num_investors = 0
        try:
            num_investors = int(re.sub(r"[^0-9]", "", row[3]))
        except (ValueError, IndexError):
            pass

        results.append({
            "ticker": ticker,
            "company": company,
            "num_investors": num_investors,
        })

    logger.info("Dataroma Grand Portfolio: %d holdings", len(results))
    return results


async def fetch_superinvestor_data() -> tuple[list[dict], list[dict]]:
    """Fetch both real-time buys and grand portfolio.

    Returns (buys, portfolio).
    """
    import asyncio
    buys, portfolio = await asyncio.gather(
        fetch_superinvestor_buys(),
        fetch_grand_portfolio(),
        return_exceptions=True,
    )

    if isinstance(buys, Exception):
        logger.error("Dataroma buys failed: %s", buys)
        buys = []
    if isinstance(portfolio, Exception):
        logger.error("Dataroma portfolio failed: %s", portfolio)
        portfolio = []

    return buys, portfolio
