"""Scrapes Dataroma for superinvestor activity and consensus holdings.

Dataroma-Struktur (Stand 2026-04-09):
- Grand Portfolio: `/m/g/portfolio.php` (NICHT `portfolio_b.php` — das ist
  ein Filter-Sub-View mit nur ~12 Eintraegen). Liefert die Top-100 Holdings
  aggregiert ueber ~82 Superinvestoren, Spalten:
  Symbol | Stock | % | Ownership count | Hold Price | Max % | Current | 52W Low
- Real-Time Buys: `/m/rt.php`. KEINE Ticker-Links mehr (nur Plaintext-
  Company-Namen) — die Zeile enthaelt aber einen SEC-Archives-Link mit der
  CIK-Nummer, die wir via CIK→Ticker-Map (aus activist_tracker) aufloesen.
- Homepage-Warmup ist noetig: direkter Zugriff auf `/m/...` ohne vorheriges
  GET auf `/` liefert sporadisch 302 → 0 bytes.
"""
import asyncio
import logging
import re

from services.api_utils import fetch_text, get_async_client

logger = logging.getLogger(__name__)

HOME_URL = "https://www.dataroma.com/"
RT_URL = "https://www.dataroma.com/m/rt.php"
PORTFOLIO_URL = "https://www.dataroma.com/m/g/portfolio.php"
DATAROMA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",  # kein gzip, um Parser-Probleme zu vermeiden
    "Referer": "https://www.dataroma.com/",
    "Connection": "keep-alive",
}

_homepage_warmed: bool = False


async def _warm_homepage() -> None:
    """Einmaliger GET auf die Homepage — Dataroma verlangt sporadisch einen
    Warmup-Request, sonst liefern direkte /m/-Aufrufe 302 → leeren Body.
    """
    global _homepage_warmed
    if _homepage_warmed:
        return
    try:
        await fetch_text(HOME_URL, headers=DATAROMA_HEADERS, timeout=15)
        _homepage_warmed = True
    except Exception as e:
        logger.debug(f"Dataroma warmup failed: {e}")


# Obergrenze fuer das HTML, das der Parser liest (K157). Die Seiten haben
# wenige 100 KB.
_MAX_HTML_CHARS = 2_000_000


def _tag_blocks(html: str, tag: str) -> list[str]:
    """Inhalte aller ``<tag ...>…</tag>``-Bloecke, in einem Durchlauf.

    Liefert dasselbe wie ``re.findall(r"<tag[^>]*>(.*?)</tag>", html, re.DOTALL)``
    (Gross- und Kleinschreibung egal). Der Regex suchte bei fehlendem
    Schluss-Tag von JEDEM Start-Tag aus bis zum Textende: bei kaputtem HTML mit
    vielen offenen ``<tr>`` lief das quadratisch und blockierte den Event-Loop
    (K157). Fehlt ein ``>`` oder das Schluss-Tag, kann auch kein spaeterer
    Block mehr passen — die Suche endet dort.
    """
    open_re = re.compile(f"<{tag}", re.IGNORECASE)
    close_re = re.compile(f"</{tag}>", re.IGNORECASE)
    blocks: list[str] = []
    pos = 0
    while True:
        start = open_re.search(html, pos)
        if start is None:
            break
        tag_end = html.find(">", start.end())
        if tag_end == -1:
            break
        close = close_re.search(html, tag_end + 1)
        if close is None:
            break
        blocks.append(html[tag_end + 1:close.start()])
        pos = close.end()
    return blocks


def _strip_tags(text: str) -> str:
    """Entfernt ``<…>``-Tags in einem Durchlauf; gleiches Ergebnis wie
    ``re.sub(r"<[^>]+>", "", text)``, ohne dessen quadratische Laufzeit bei
    vielen ``<`` ohne ``>``."""
    out: list[str] = []
    pos = 0
    while True:
        lt = text.find("<", pos)
        if lt == -1:
            break
        gt = text.find(">", lt + 1)
        if gt == -1:
            break
        if gt == lt + 1:
            # "<>" ist kein Tag: stehen lassen und dahinter weitersuchen.
            out.append(text[pos:gt])
            pos = gt
            continue
        out.append(text[pos:lt])
        pos = gt + 1
    out.append(text[pos:])
    return "".join(out)


def _parse_html_table(html: str) -> list[tuple[list[str], str]]:
    """Extract rows from HTML tables.

    Returns list of (cells, raw_row_html) tuples. Der raw_row_html wird
    gebraucht um Ticker-Links und SEC-Archives-CIKs aus der Zeile zu extrahieren
    (nicht nur den plain text content).
    """
    if len(html) > _MAX_HTML_CHARS:
        logger.warning(
            "Dataroma: HTML has %d chars, parsing only the first %d", len(html), _MAX_HTML_CHARS,
        )
        html = html[:_MAX_HTML_CHARS]
    rows: list[tuple[list[str], str]] = []
    for raw in _tag_blocks(html, "tr"):
        clean = [_strip_tags(c).strip() for c in _tag_blocks(raw, "td")]
        if clean and any(clean):
            rows.append((clean, raw))
    return rows


async def fetch_superinvestor_buys() -> list[dict]:
    """Fetch recent superinvestor buy transactions from Dataroma real-time feed.

    Dataroma hat die Ticker-Links aus `rt.php` entfernt — die Security-Spalte
    ist jetzt reiner Plaintext. Wir loesen deshalb ueber die in jeder Zeile
    enthaltene SEC-Archives-URL auf (enthaelt die CIK-Nummer), und mappen die
    CIK via activist_tracker's company_tickers.json-Map auf den Ticker.

    Returns list of {ticker, investor, company, value}.
    """
    await _warm_homepage()
    # Ein Abruffehler erreicht den Aufrufer (K148).
    html = await fetch_text(RT_URL, headers=DATAROMA_HEADERS, timeout=15)

    rows = _parse_html_table(html)
    if not rows:
        return []

    # CIK->Ticker Map (teilen wir mit activist_tracker)
    from services.screening.activist_tracker import _load_cik_ticker_map
    try:
        cik_map = await _load_cik_ticker_map()
    except Exception as e:
        logger.warning(f"Dataroma: CIK map load failed: {e}")
        cik_map = {}

    # Spalten in rt.php (Stand 2026-04-09):
    # Transaction Date | Filing | Reporting Name | Activity | Security | Shares | Price | Total
    results: list[dict] = []
    for cells, raw_row in rows:
        if len(cells) < 8:
            continue
        activity = cells[3].strip().lower()
        if "buy" not in activity:
            continue

        investor = cells[2].strip()
        company = cells[4].strip()
        value_str = cells[7].strip()

        # Parse value ($12,311,558 → 12311558)
        cleaned = re.sub(r"[^0-9.]", "", value_str)
        try:
            value = float(cleaned)
        except (ValueError, TypeError):
            value = 0.0

        # CIK aus der SEC-Archives-URL in der Zeile extrahieren
        cik_match = re.search(r"/data/(\d+)/", raw_row)
        if not cik_match:
            continue
        cik = cik_match.group(1).lstrip("0")  # SEC map hat un-padded CIKs
        ticker = cik_map.get(cik)
        if not ticker:
            continue

        results.append({
            "investor": investor,
            "company": company,
            "value": value,
            "ticker": ticker,
        })

    logger.info("Dataroma superinvestor buys: %d entries", len(results))
    return results


async def fetch_grand_portfolio() -> list[dict]:
    """Fetch Dataroma Grand Portfolio — Top-100 Holdings aggregiert ueber ~82
    Superinvestoren.

    URL ist `/m/g/portfolio.php` (OHNE `_b`). Die alte URL `portfolio_b.php`
    ist ein gefiltertes Sub-View und liefert nur ~12 Eintraege.

    Spaltenstruktur (Stand 2026-04-09):
    Symbol | Stock | % | Ownership count | Hold Price* | Max % | Current | 52W Low

    Returns list of {ticker, company, num_investors, portfolio_weight}.
    """
    await _warm_homepage()
    # Ein Abruffehler erreicht den Aufrufer (K148).
    html = await fetch_text(PORTFOLIO_URL, headers=DATAROMA_HEADERS, timeout=15)

    rows = _parse_html_table(html)
    if not rows:
        return []

    results: list[dict] = []
    for cells, _raw in rows:
        if len(cells) < 4:
            continue

        ticker = cells[0].strip().upper()
        # Filter: Ticker ist alphanumerisch, darf Punkt enthalten (BRK.B, BRK.A).
        # Header-Zeile ("Symbol" in col 0, "Stock" in col 1) explizit skippen.
        if not ticker or not re.match(r"^[A-Z][A-Z0-9.]{0,6}$", ticker):
            continue
        if ticker == "SYMBOL" or cells[1].strip().lower() == "stock":
            continue
        # Klassen-Trenner auf Bindestrich normalisieren (System-Konvention, gleich
        # wie sec_13f_service + capitoltrades_scraper): yfinance + Consensus-Aggregation
        # nutzen 'BRK-B', nicht 'BRK.B'. Sonst splittet derselbe Titel in zwei
        # ticker_signals-Eintraege und der Smart-Money-Consensus-Score zerfaellt.
        ticker = ticker.replace(".", "-")

        company = cells[1].strip()

        # Weight% (col 2)
        try:
            weight = float(re.sub(r"[^0-9.]", "", cells[2]))
        except (ValueError, IndexError):
            weight = 0.0

        # Ownership count (col 3) — Anzahl Superinvestoren die die Aktie halten
        try:
            num_investors = int(re.sub(r"[^0-9]", "", cells[3]))
        except (ValueError, IndexError):
            num_investors = 0

        results.append({
            "ticker": ticker,
            "company": company,
            "portfolio_weight": weight,
            "num_investors": num_investors,
        })

    logger.info("Dataroma Grand Portfolio: %d holdings", len(results))
    return results


async def fetch_superinvestor_data() -> tuple[list[dict], list[dict]]:
    """Fetch both real-time buys and grand portfolio.

    Returns (buys, portfolio).

    Scheitert der Abruf des Grand Portfolio oder ist es leer, wirft die Funktion
    (K148): das Grand Portfolio hat im Normalbetrieb rund 100 Zeilen, und als
    leere Liste erschien ein Ausfall im Scan als "done".

    Scheitert nur der Echtzeit-Feed, bleibt das geladene Grand Portfolio
    erhalten: es trägt fast alle Signale dieser Quelle. Der Fehler steht im Log,
    ``buys`` ist dann leer.
    """
    import asyncio
    buys, portfolio = await asyncio.gather(
        fetch_superinvestor_buys(),
        fetch_grand_portfolio(),
        return_exceptions=True,
    )

    if isinstance(portfolio, BaseException):
        logger.error("Dataroma portfolio failed: %r", portfolio)
        raise portfolio
    if not portfolio:
        raise RuntimeError("Dataroma Grand Portfolio returned no holdings")
    if isinstance(buys, BaseException):
        if not isinstance(buys, Exception):
            raise buys  # Abbruch (CancelledError) nicht schlucken
        logger.error("Dataroma buys failed, continuing with the grand portfolio: %r", buys)
        buys = []

    return buys, portfolio
