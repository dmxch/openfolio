"""Tracks 13D/13G filings from known activist investors via SEC EDGAR Submissions API."""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from services.api_utils import fetch_json, fetch_text

logger = logging.getLogger(__name__)

SEC_UA = "OpenFolio/1.0 screening@openfolio.dev"
SEC_HEADERS = {"User-Agent": SEC_UA}

# Known activist investors / superinvestors with their SEC CIKs
TRACKED_INVESTORS: dict[str, str] = {
    "0000921669": "Carl Icahn",
    "0001336528": "Pershing Square (Ackman)",
    "0001350694": "Third Point (Dan Loeb)",
    "0001037389": "ValueAct Capital",
    "0001159159": "Starboard Value",
    "0000102909": "Berkshire Hathaway (Buffett)",
    "0001167483": "Greenlight Capital (Einhorn)",
    "0001061768": "Elliott Management",
    "0001603466": "Trian Fund Management",
    "0000885590": "Soros Fund Management",
    "0001656456": "Appaloosa Management",
    "0001067983": "Baupost Group (Klarman)",
    "0001009207": "Bridgewater Associates",
    "0001535392": "Tiger Global Management",
    "0001568820": "Coatue Management",
}

# CIK -> Ticker mapping (loaded once)
_cik_ticker_map: dict[str, str] | None = None


async def _load_cik_ticker_map() -> dict[str, str]:
    """Load SEC company_tickers.json for CIK -> ticker resolution."""
    global _cik_ticker_map
    if _cik_ticker_map is not None:
        return _cik_ticker_map

    try:
        data = await fetch_json(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=15,
        )
        _cik_ticker_map = {}
        for v in data.values():
            cik = str(v["cik_str"])
            _cik_ticker_map[cik] = v["ticker"]
        logger.info("Loaded CIK->ticker map: %d entries", len(_cik_ticker_map))
    except Exception:
        logger.exception("Failed to load SEC company_tickers.json")
        _cik_ticker_map = {}

    return _cik_ticker_map


async def _get_investor_filings(cik: str, investor_name: str) -> list[dict]:
    """Fetch recent 13D/13G filings for a single investor."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        data = await fetch_json(url, headers=SEC_HEADERS, timeout=10)
    except Exception:
        logger.warning("Failed to fetch submissions for %s", investor_name)
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    results: list[dict] = []
    for i in range(min(len(forms), len(dates), len(accessions))):
        form = forms[i]
        filing_date = dates[i]

        # Only 13D/13G from last 6 months
        cutoff = (date.today() - timedelta(days=180)).isoformat()
        if filing_date < cutoff:
            break
        if "13D" not in form and "13G" not in form:
            continue

        results.append({
            "investor": investor_name,
            "form": form,
            "filing_date": filing_date,
            "accession": accessions[i],
            "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
            "cik": cik,
        })

    return results


async def _resolve_13d_target(filing: dict) -> dict | None:
    """Try to extract the target company/ticker from a 13D/13G XML filing."""
    cik = filing["cik"].lstrip("0")
    acc = filing["accession"].replace("-", "")
    primary = filing.get("primary_doc", "")

    if not primary or not primary.endswith(".xml"):
        return None

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{primary}"
    try:
        xml_text = await fetch_text(url, headers=SEC_HEADERS, timeout=10)
    except Exception:
        return None

    try:
        root = ET.fromstring(xml_text)
        # Namespace-agnostic search
        issuer_name = None
        issuer_cik = None
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "issuerName" and elem.text:
                issuer_name = elem.text.strip()
            if tag == "issuerCIK" and elem.text:
                issuer_cik = elem.text.strip().lstrip("0")

        if issuer_cik:
            cik_map = await _load_cik_ticker_map()
            ticker = cik_map.get(issuer_cik)
            if ticker:
                return {
                    "ticker": ticker,
                    "company": issuer_name or "",
                    "investor": filing["investor"],
                    "form": filing["form"],
                    "filing_date": filing["filing_date"],
                }
    except ET.ParseError:
        pass

    return None


async def fetch_activist_positions() -> list[dict]:
    """Track 13D/13G filings from all known activists (2026).

    Returns list of {ticker, company, investor, form, filing_date}.
    """
    # Load CIK map first
    await _load_cik_ticker_map()

    # Fetch filings for all investors concurrently (with rate limiting)
    all_filings: list[dict] = []
    for cik, name in TRACKED_INVESTORS.items():
        filings = await _get_investor_filings(cik, name)
        all_filings.extend(filings)
        await asyncio.sleep(0.12)  # SEC rate limit: 10 req/sec

    logger.info("Activist tracker: %d total 13D/13G filings from %d investors",
                len(all_filings), len(TRACKED_INVESTORS))

    # Resolve target companies from XML (only for filings with XML primary docs)
    xml_filings = [f for f in all_filings if f.get("primary_doc", "").endswith(".xml")]

    results: list[dict] = []
    seen_tickers: set[str] = set()

    for filing in xml_filings[:20]:  # limit to avoid rate limiting
        target = await _resolve_13d_target(filing)
        if target and target["ticker"] not in seen_tickers:
            seen_tickers.add(target["ticker"])
            results.append(target)
        await asyncio.sleep(0.12)

    # For non-XML filings, just record the investor activity without ticker
    # (these will be shown as "Aktivist aktiv" without specific target)

    logger.info("Activist tracker: %d resolved ticker targets", len(results))
    return results
