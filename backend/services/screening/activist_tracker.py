"""Tracks 13D/13G filings from known activist investors via SEC EDGAR Submissions API."""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from html import unescape

from services.api_utils import fetch_json, fetch_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Purpose-of-Transaction (Item 4) tag patterns — regex-based, no LLM
# ---------------------------------------------------------------------------
PURPOSE_TAG_PATTERNS: dict[str, re.Pattern] = {
    "board_representation": re.compile(
        r"board\s+(of\s+directors|representation|seat|member)|director", re.I
    ),
    "strategic_review": re.compile(
        r"strategic\s+(review|alternative|transaction)|explore.*sale|sale\s+process", re.I
    ),
    "spinoff": re.compile(r"spin[\s\-]?off|separation|divestiture|divest|split[\s\-]?off", re.I),
    "merger": re.compile(r"merg(?:er|e|ing)|acqui(?:sition|re)", re.I),
    "governance": re.compile(r"governance|bylaws?|charter|proxy", re.I),
    "capital_return": re.compile(
        r"(?:share|stock)\s*(?:repurchas|buyback)|dividend|capital\s*return", re.I
    ),
    "management_change": re.compile(
        r"management\s+change|replace.*ceo|new.*management|leadership\s+change", re.I
    ),
    "going_private": re.compile(r"going\s+private|privatization|take.*private", re.I),
    "operational": re.compile(r"cost\s*(?:cut|reduc)|margin\s*improv|restructur", re.I),
    "valuation": re.compile(
        r"undervalue|intrinsic\s*value|discount\s*to\s*nav|sum[\s\-]of[\s\-]the[\s\-]parts", re.I
    ),
    "passive_investment": re.compile(
        r"investment\s+purposes|long[\s\-]?term|passive|no\s+current\s+plans", re.I
    ),
}

# Regex to extract Item 4 content from filing text/HTML
_ITEM4_RE = re.compile(
    r"(?:Item\s*4[.\s:\-]*(?:PURPOSE\s+OF\s+TRANSACTION)?|PURPOSE\s+OF\s+TRANSACTION)"
    r"[.\s:\-]*(.{100,2500}?)"
    r"(?:Item\s*5|INTEREST\s+IN\s+SECURITIES|Item\s*6|$)",
    re.I | re.DOTALL,
)

# Strip HTML tags
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw: str) -> str:
    """Strip HTML tags, unescape entities, normalise whitespace."""
    text = _HTML_TAG_RE.sub(" ", raw)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_item4(text: str) -> str:
    """Extract Item 4 (Purpose of Transaction) from filing text. Returns clean excerpt (max 500 chars)."""
    m = _ITEM4_RE.search(text)
    if not m:
        return ""
    excerpt = _clean_text(m.group(1))
    if len(excerpt) < 30:
        return ""
    return excerpt[:500]


def _derive_purpose_tags(excerpt: str) -> list[str]:
    """Match purpose tag patterns against excerpt text. Returns sorted tag list."""
    if not excerpt:
        return []
    tags = [tag for tag, pat in PURPOSE_TAG_PATTERNS.items() if pat.search(excerpt)]
    tags.sort()
    return tags

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

    # SEC listet in submissions.json die XSL-transformierte View-URL
    # (`xslSCHEDULE_13D_X02/primary_doc.xml`). Das ist HTML, kein XML —
    # ET.fromstring() crasht darauf. Wir strippen den xsl-Prefix und holen
    # stattdessen das rohe primary_doc.xml.
    if "xsl" in primary and "/" in primary:
        primary = primary.split("/", 1)[1]

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{primary}"
    try:
        xml_text = await fetch_text(url, headers=SEC_HEADERS, timeout=10)
    except Exception:
        return None

    # Try to extract Item 4 from the raw text (works for both XML-embedded
    # and HTML-body filings before we attempt structured XML parsing).
    letter_excerpt = _extract_item4(xml_text)
    purpose_tags = _derive_purpose_tags(letter_excerpt)

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
                    "letter_excerpt": letter_excerpt,
                    "purpose_tags": purpose_tags,
                }
    except ET.ParseError:
        pass

    return None


async def fetch_activist_positions() -> list[dict]:
    """Track 13D/13G filings from all known activists (2026).

    Returns list of {ticker, company, investor, form, filing_date,
    letter_excerpt, purpose_tags}.
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
