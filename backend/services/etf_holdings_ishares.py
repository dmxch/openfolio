"""iShares-Holdings-Adapter: keyloser CSV-Download -> normalisierte Holding-Rows.

iShares-CSVs identifizieren Holdings nur ueber lokalen Boersen-Ticker + Exchange
(KEINE ISIN). Wir mappen Exchange -> yfinance-Suffix (constants/exchange_suffix.py),
damit holding_ticker fuer classify_tickers_bulk (Sektor-Look-Through) passt, und
persistieren holding_country (iShares "Location") fuer den Laender-Look-Through.

Browser-User-Agent zwingend: der .ajax-CSV-Endpoint ist keyless, gibt aber mit
Default-UA HTTP 403 (Akamai-Edge, vgl. reference_cloudflare_ua_block) zurueck.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime

import httpx

from constants.etf_holdings_sources import ISHARES_HOLDINGS_URLS
from constants.exchange_suffix import exchange_to_yf_ticker

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# iShares "Fund Holdings as of"-Datum: mehrere Formate je Domain/Locale moeglich.
_AS_OF_FORMATS = ("%b %d, %Y", "%d-%b-%Y", "%d/%b/%Y", "%Y-%m-%d", "%d %b %Y")

# iShares "Sector" (GICS-Namen) -> OpenFolio-Sektor-Vokabular (yfinance-Stil).
# Persistierter Sektor wird von concentration_service vor classify_tickers_bulk
# bevorzugt -> Sektor-Look-Through funktioniert auch fuer EM-Holdings.
GICS_TO_OPENFOLIO_SECTOR = {
    "information technology": "Technology",
    "technology": "Technology",
    "financials": "Financials",
    "financial services": "Financials",
    "health care": "Healthcare",
    "healthcare": "Healthcare",
    "consumer discretionary": "Consumer Cyclical",
    "consumer cyclical": "Consumer Cyclical",
    "consumer staples": "Consumer Defensive",
    "consumer defensive": "Consumer Defensive",
    "industrials": "Industrials",
    "energy": "Energy",
    "materials": "Basic Materials",
    "basic materials": "Basic Materials",
    "real estate": "Real Estate",
    "utilities": "Utilities",
    "communication": "Communication Services",
    "communication services": "Communication Services",
    "telecommunication services": "Communication Services",
    "telecommunications": "Communication Services",
}


def map_gics_sector(raw: str | None) -> str | None:
    """GICS-/Issuer-Sektorname -> OpenFolio-Sektor, oder None bei unbekannt."""
    if not raw:
        return None
    return GICS_TO_OPENFOLIO_SECTOR.get(raw.strip().lower())


def is_ishares_etf(etf_ticker: str) -> bool:
    return etf_ticker in ISHARES_HOLDINGS_URLS


def _parse_weight(raw: str) -> float | None:
    # Dezimaltrenner ist immer '.'; CH nutzt U+2019-, UK/Global Komma-Tausender.
    s = (raw or "").strip().replace("’", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_as_of(pre_header_rows: list[list[str]]) -> date | None:
    for row in pre_header_rows:
        for i, cell in enumerate(row):
            if "as of" in cell.strip().lower():
                cand = cell.split("as of")[-1].strip().strip('"')
                if not cand and i + 1 < len(row):
                    cand = row[i + 1].strip()
                for fmt in _AS_OF_FORMATS:
                    try:
                        return datetime.strptime(cand, fmt).date()
                    except (ValueError, TypeError):
                        continue
    return None


def parse_ishares_csv(text: str, etf_ticker: str) -> list[dict]:
    """CSV-Text -> normalisierte Holding-Rows (nur Equity, aufgeloeste yf-Ticker).

    Reine Funktion (kein I/O) — voll unit-testbar. holding_ticker = aufgeloester
    yfinance-Ticker; faellt die Boersen-Aufloesung aus, bleibt der lokale Ticker
    als Fallback-Key, damit die Zeile (und ihr Land) fuer den Laender-Look-Through
    erhalten bleibt (sie klassifiziert dann nur nicht im Sektor-Pfad).
    """
    rows = list(csv.reader(io.StringIO(text)))
    hdr_idx = next(
        (i for i, r in enumerate(rows)
         if any(c.strip() == "Ticker" for c in r) and any("Weight" in c for c in r)),
        None,
    )
    if hdr_idx is None:
        logger.warning("ishares_adapter: Header nicht gefunden fuer %s", etf_ticker)
        return []
    header = [c.strip() for c in rows[hdr_idx]]
    idx = {name: i for i, name in enumerate(header)}

    def col(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    as_of = _extract_as_of(rows[:hdr_idx])
    etf_base = etf_ticker.split(".")[0].upper()  # CSV-Self-Ref traegt kein Suffix

    out: dict[tuple[str, str], dict] = {}
    for row in rows[hdr_idx + 1:]:
        if col(row, "Asset Class").lower() != "equity":
            continue
        w = _parse_weight(col(row, "Weight (%)"))
        if w is None or w == 0:
            continue
        local = col(row, "Ticker")
        # Self-Reference (Fund/Cash-Bucket): lokaler Ticker == ETF-Basis-Ticker
        if local.upper() in (etf_base, etf_ticker.upper()):
            continue
        yf = exchange_to_yf_ticker(local, col(row, "Exchange"))
        holding_ticker = yf or (local.upper() if local else None)
        if not holding_ticker:
            continue
        country = col(row, "Location") or None
        out[(etf_ticker, holding_ticker)] = {
            "etf_ticker": etf_ticker,
            "holding_ticker": holding_ticker,
            "holding_name": (col(row, "Name") or "")[:200],
            "weight_pct": w,
            "as_of": as_of,
            "holding_isin": None,                       # iShares-CSV liefert keine ISIN
            "holding_country": country[:64] if country else None,
            "holding_sector": map_gics_sector(col(row, "Sector")),
        }
    return list(out.values())


async def fetch_ishares_holdings(etf_ticker: str) -> list[dict] | None:
    """Lade + parse iShares-Holdings. None bei Fetch-Fehler (Caller -> error)."""
    url = ISHARES_HOLDINGS_URLS.get(etf_ticker)
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": _BROWSER_UA})
    except Exception as e:
        logger.warning("ishares_adapter: Fetch fehlgeschlagen fuer %s: %s", etf_ticker, e)
        return None
    if r.status_code != 200:
        logger.warning("ishares_adapter: HTTP %s fuer %s", r.status_code, etf_ticker)
        return None
    return parse_ishares_csv(r.text, etf_ticker)
