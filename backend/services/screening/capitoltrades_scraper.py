"""Scrapes Capitol Trades for recent congressional stock trades."""
import logging
import re

from services.api_utils import fetch_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.capitoltrades.com/trades"
RSC_HEADERS = {
    # Voller Chrome-UA: kuerzere UA-Strings werden von manchen Anti-Bot-Layern
    # abgewiesen (siehe finra_short_service.py fuer die gleiche Lektion).
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
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


async def _fetch_page_with_buy_tickers(page: int) -> list[dict]:
    """Fetch a single page and extract tickers with their company names.

    Wichtig: Im RSC-Stream erscheint `issuerName` VOR `issuerTicker` in der
    gleichen JSON-Objekt-Sequenz. Die ersten 1-2 `issuerName`-Eintraege pro
    Seite sind Bond-/Muni-Trades ohne Ticker (z.B. "US TREASURY BILLS",
    "MINNEAPOLIS HOUSING AUTHORITY"). Ein naives `zip(tickers, names)` wuerde
    deshalb jeden Ticker um 1-2 Positionen verschieben und alle Namen falsch
    zuordnen (→ der urspruengliche Bug, wo jede Aktie als "US TREASURY BILLS"
    ausgewiesen wurde).

    Fix: adjacent-pair Regex `"issuerName":"...","issuerTicker":"..."` matcht
    nur Paare die direkt nebeneinander im Stream stehen — Bonds ohne Ticker
    fallen automatisch raus.
    """
    url = f"{BASE_URL}?per_page=96&page={page}&txType=buy&txDate=90d"
    try:
        text = await fetch_text(url, headers=RSC_HEADERS, timeout=15)
    except Exception:
        return []

    # Matche "issuerName":"...","issuerTicker":"..." direkt nacheinander.
    # Das garantiert korrekte Paare auch wenn es zwischen den Trade-Objekten
    # noch Bond-Eintraege ohne Ticker gibt.
    pairs = re.findall(
        r'"issuerName":"([^"]*)","issuerTicker":"([^"]*)"', text
    )

    # Dedupe: ein Ticker kann mehrfach auftreten (mehrere Kongress-Mitglieder
    # kaufen denselben Titel). Wir halten nur den ersten Eintrag.
    ticker_names: dict[str, str] = {}
    for name, raw_ticker in pairs:
        clean = _clean_ticker(raw_ticker)
        if clean and clean not in ticker_names:
            ticker_names[clean] = name

    return [
        {"ticker": ticker, "company": name}
        for ticker, name in ticker_names.items()
    ]


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
