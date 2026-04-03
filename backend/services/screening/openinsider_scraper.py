"""Scrapes OpenInsider for insider cluster buys and large individual purchases."""
import logging
import re
from html.parser import HTMLParser

from services.api_utils import fetch_text

logger = logging.getLogger(__name__)

CLUSTER_BUYS_URL = "https://openinsider.com/latest-cluster-buys"
LARGE_BUYS_URL = (
    "https://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd=30&fdr=&td=0&tdr="
    "&feession=&cession=&sidTicker=&tiession=&diession=&t=1&tc=&min=500&minprice=5"
    "&maxprice=&maxown=25"
)


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


def _parse_table(html: str) -> list[dict]:
    """Parse OpenInsider HTML into a list of trade dicts."""
    parser = _TableParser()
    parser.feed(html)

    if len(parser.rows) < 2:
        return []

    results = []
    for row in parser.rows[1:]:  # skip header
        if len(row) < 13:
            continue
        ticker = row[3].strip()
        if not ticker or not re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', ticker):
            continue

        results.append({
            "filing_date": row[1].strip(),
            "trade_date": row[2].strip(),
            "ticker": ticker.upper(),
            "company": row[4].strip(),
            "industry": row[5].strip() if len(row) > 5 else "",
            "insider_count": int(row[6]) if row[6].isdigit() else 1,
            "trade_type": row[7].strip() if len(row) > 7 else "",
            "price": _parse_value(row[8]) if len(row) > 8 else 0,
            "value": _parse_value(row[12]) if len(row) > 12 else 0,
        })

    return results


async def fetch_cluster_buys() -> list[dict]:
    """Fetch pre-filtered cluster buys from OpenInsider (~100 entries, 60 days)."""
    try:
        html = await fetch_text(CLUSTER_BUYS_URL, headers={"User-Agent": "Mozilla/5.0"})
        trades = _parse_table(html)
        logger.info("OpenInsider cluster buys: %d entries", len(trades))
        return trades
    except Exception:
        logger.exception("Failed to fetch OpenInsider cluster buys")
        return []


async def fetch_large_buys() -> list[dict]:
    """Fetch large insider purchases (>$500k, 30 days) from OpenInsider."""
    try:
        html = await fetch_text(LARGE_BUYS_URL, headers={"User-Agent": "Mozilla/5.0"})
        trades = _parse_table(html)
        logger.info("OpenInsider large buys: %d entries", len(trades))
        return trades
    except Exception:
        logger.exception("Failed to fetch OpenInsider large buys")
        return []
