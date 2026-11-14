"""Scrapes OpenInsider for insider cluster buys and large individual purchases."""
import logging
import re
from html.parser import HTMLParser

import httpx

from services.api_utils import get_async_client, retry_external

logger = logging.getLogger(__name__)

# Hinweis: openinsider.com hat aktuell (April 2026) defektes HTTPS
# (TCP-Connect refused auf Port 443, Site liefert aber HTTP 200 auf Port 80).
# Wir nutzen deshalb http://, nicht https://. Das ist akzeptabel, weil die
# Daten (Insider-Trades) oeffentlich sind und wir keine Credentials senden.
# Siehe Connection-Probe in v0.24.x Release-Notes.
CLUSTER_BUYS_URL = "http://openinsider.com/latest-cluster-buys"
LARGE_BUYS_URL = (
    "http://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd=30&fdr=&td=0&tdr="
    "&feession=&cession=&sidTicker=&tiession=&diession=&t=1&tc=&min=500&minprice=5"
    "&maxprice=&maxown=25"
)

# Voller Browser-UA (konsistent mit FINRA-Fix): "Mozilla/5.0" allein wird
# von manchen Anti-Bot-Layern abgewiesen.
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Schutz des Abrufs (K171). Die Seite kommt ueber http://: wer den Verkehr oder
# die DNS-Antwort manipuliert, darf den Abruf nicht per Redirect auf ein anderes
# (internes) Ziel lenken und den Prozess nicht mit einer endlosen Antwort
# fuellen. Die Seiten haben wenige 100 KB.
_ALLOWED_HOSTS = frozenset({"openinsider.com", "www.openinsider.com"})
_MAX_REDIRECTS = 2
_MAX_HTML_BYTES = 5 * 1024 * 1024


@retry_external
async def _fetch_html(url: str) -> str:
    """GET mit Groessenlimit; Redirects nur auf einen Host aus _ALLOWED_HOSTS.

    httpx folgt hier bewusst nicht selbst (``follow_redirects=False``): der
    geteilte Client folgte sonst jedem Ziel.
    """
    client = get_async_client()
    for _ in range(_MAX_REDIRECTS + 1):
        async with client.stream(
            "GET", url, headers={"User-Agent": _BROWSER_UA}, timeout=15,
            follow_redirects=False,
        ) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                target = httpx.URL(url).join(resp.headers.get("location", ""))
                if target.scheme not in ("http", "https") or target.host not in _ALLOWED_HOSTS:
                    raise ValueError(f"OpenInsider: redirect to foreign host refused ({target.host!r})")
                url = str(target)
                continue
            resp.raise_for_status()
            if resp.status_code != 200:
                raise ValueError(f"OpenInsider: unexpected status {resp.status_code}")
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > _MAX_HTML_BYTES:
                    raise ValueError(f"OpenInsider: response larger than {_MAX_HTML_BYTES} bytes")
            encoding = resp.encoding or "utf-8"
        try:
            return bytes(body).decode(encoding, errors="replace")
        except LookupError:
            return bytes(body).decode("utf-8", errors="replace")
    raise ValueError("OpenInsider: too many redirects")


class _TableParser(HTMLParser):
    """Parses the OpenInsider HTML tables (class='tinytable')."""

    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []
        self.cell_text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table" and "tinytable" in attrs_dict.get("class", ""):
            self.in_table = True
        if self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        if self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.cell_text = ""

    def handle_endtag(self, tag: str) -> None:
        if self.in_cell and tag in ("td", "th"):
            self.in_cell = False
            self.current_row.append(self.cell_text.strip())
        if self.in_row and tag == "tr":
            self.in_row = False
            if self.current_row:
                self.rows.append(self.current_row)
        if tag == "table":
            self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text += data


def _parse_value(val_str: str) -> float:
    """Parse a value string like '+$9,338,467' to a float."""
    cleaned = re.sub(r"[^0-9.\-]", "", val_str)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _extract_rows(html: str) -> list[list[str]]:
    """Parse the tinytable and return raw data rows (header stripped)."""
    parser = _TableParser()
    parser.feed(html)
    if len(parser.rows) < 2:
        return []
    return parser.rows[1:]


def _valid_ticker(t: str) -> bool:
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', t))


def _parse_cluster_rows(rows: list[list[str]]) -> list[dict]:
    """Cluster-Buys Layout: X | FilingDate | TradeDate | Ticker | Company | Industry | Ins | TradeType | Price | Qty | Owned | DeltaOwn | Value."""
    results = []
    for row in rows:
        if len(row) < 13:
            continue
        ticker = row[3].strip()
        if not ticker or not _valid_ticker(ticker):
            continue
        results.append({
            "filing_date": row[1].strip(),
            "trade_date": row[2].strip(),
            "ticker": ticker.upper(),
            "company": row[4].strip(),
            "industry": row[5].strip(),
            "insider_count": int(row[6]) if row[6].isdigit() else 2,
            "trade_type": row[7].strip(),
            "price": _parse_value(row[8]),
            "value": _parse_value(row[12]),
        })
    return results


def _parse_large_buy_rows(rows: list[list[str]]) -> list[dict]:
    """Large-Buys Layout: X | FilingDate | TradeDate | Ticker | Company | InsiderName | Title | TradeType | Price | Qty | Owned | DeltaOwn | Value.

    Unterschiede zu Cluster-Buys:
    - row[5] ist Insider-Name (keine Industry-Info in dieser Tabelle verfuegbar)
    - row[6] ist Title (z.B. "Dir"), nicht Ins-Count
    - Filter: nur "P - Purchase" (Screener-URL liefert Sales mit)
    """
    results = []
    for row in rows:
        if len(row) < 13:
            continue
        ticker = row[3].strip()
        if not ticker or not _valid_ticker(ticker):
            continue
        trade_type = row[7].strip()
        if not trade_type.startswith("P"):  # Kein "S - Sale"
            continue
        results.append({
            "filing_date": row[1].strip(),
            "trade_date": row[2].strip(),
            "ticker": ticker.upper(),
            "company": row[4].strip(),
            "industry": "",  # Large-Buys-Tabelle hat keine Industry-Spalte
            "insider_count": 1,
            "trade_type": trade_type,
            "price": _parse_value(row[8]),
            "value": _parse_value(row[12]),
        })
    return results


async def fetch_cluster_buys() -> list[dict]:
    """Fetch pre-filtered cluster buys from OpenInsider (~100 entries, 60 days).

    Ein Abruffehler erreicht den Aufrufer (K148): als leere Liste erschien er
    im Scan als "done, 0".
    """
    html = await _fetch_html(CLUSTER_BUYS_URL)
    trades = _parse_cluster_rows(_extract_rows(html))
    logger.info("OpenInsider cluster buys: %d entries", len(trades))
    return trades


async def fetch_large_buys() -> list[dict]:
    """Fetch large insider purchases (>$500k, 30 days) from OpenInsider.

    Ein Abruffehler erreicht den Aufrufer (K148).
    """
    html = await _fetch_html(LARGE_BUYS_URL)
    trades = _parse_large_buy_rows(_extract_rows(html))
    logger.info("OpenInsider large buys: %d entries", len(trades))
    return trades
