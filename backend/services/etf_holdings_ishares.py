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
import math
import re
from datetime import date, datetime

from constants.etf_holdings_sources import ISHARES_HOLDINGS_URLS
from constants.exchange_suffix import exchange_to_yf_ticker
# Geteilter Sektor-Map (frueher hier lokal definiert). Re-Export unter den alten
# Namen, damit bestehende Importe (Tests, concentration_service) stabil bleiben.
from constants.etf_sector_map import (  # noqa: F401
    GICS_TO_OPENFOLIO_SECTOR,
    map_gics_sector,
    map_sector,
)

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# iShares "Fund Holdings as of"-Datum: mehrere Formate je Domain/Locale moeglich.
_AS_OF_FORMATS = ("%b %d, %Y", "%d-%b-%Y", "%d/%b/%Y", "%Y-%m-%d", "%d %b %Y")

# Die Ticker-Spalte heisst je nach Domain und Fondstyp "Ticker" oder "Issuer Ticker".
_TICKER_HEADERS = ("ticker", "issuer ticker")


def _find_header(rows: list[list[str]]) -> tuple[int, str] | None:
    """(Zeilenindex, Name der Ticker-Spalte in Kleinschreibung) oder None."""
    for i, row in enumerate(rows):
        cells = [c.strip().lower() for c in row]
        ticker_col = next((h for h in _TICKER_HEADERS if h in cells), None)
        if ticker_col and any("weight" in c for c in cells):
            return i, ticker_col
    return None


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


def parse_ishares_csv(
    text: str, etf_ticker: str, *, response_info: str | None = None,
) -> list[dict]:
    """CSV-Text -> normalisierte Holding-Rows (nur Equity, aufgeloeste yf-Ticker).

    Reine Funktion (kein I/O) — voll unit-testbar. holding_ticker = aufgeloester
    yfinance-Ticker; faellt die Boersen-Aufloesung aus, bleibt der lokale Ticker
    als Fallback-Key, damit die Zeile (und ihr Land) fuer den Laender-Look-Through
    erhalten bleibt (sie klassifiziert dann nur nicht im Sektor-Pfad).

    `response_info` (Status, Content-Type) erscheint nur in der Warnung, wenn die
    Kopfzeile fehlt.
    """
    # Ein BOM vor dem ersten Anfuehrungszeichen hebelt das CSV-Quoting der ersten
    # Zelle aus: steht die Kopfzeile ganz oben, findet der Vergleich sie nicht mehr.
    text = text.lstrip("\ufeff")
    rows = list(csv.reader(io.StringIO(text)))
    found = _find_header(rows)
    if found is None:
        # Ohne Status, Content-Type und Anfang der Antwort bleibt offen, ob der
        # Anbieter das Format geaendert hat oder eine HTML-Seite liefert.
        logger.warning(
            "ishares_adapter: header not found for %s (%s, first 200 chars: %r)",
            etf_ticker, response_info or "no response info", text[:200],
        )
        return []
    hdr_idx, ticker_col = found
    idx = {name.strip().lower(): i for i, name in enumerate(rows[hdr_idx])}

    def col(row: list[str], name: str) -> str:
        i = idx.get(name.lower())
        return row[i].strip() if (i is not None and i < len(row)) else ""

    as_of = _extract_as_of(rows[:hdr_idx])
    etf_base = etf_ticker.split(".")[0].upper()  # CSV-Self-Ref traegt kein Suffix

    out: dict[tuple[str, str], dict] = {}
    for row in rows[hdr_idx + 1:]:
        if col(row, "Asset Class").lower() != "equity":
            continue
        w = _parse_weight(col(row, "Weight (%)"))
        # Nicht-endliche/<=0 verwerfen (symmetrisch zu make_holding_row / FMP-Pfad):
        # ein NaN/Inf-Gewicht passierte den `== 0`-Guard, wuerde persistiert und
        # korrumpierte die Laender-/Sektor-Durchsicht (/country-lookthrough 500).
        if w is None or not math.isfinite(w) or w <= 0:
            continue
        local = col(row, ticker_col)
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


def _decode_body(content: bytes, content_type: str | None) -> str:
    """Bytes -> Text mit dem Charset aus dem Content-Type, sonst UTF-8 (BOM faellt weg)."""
    match = re.search(r"charset=([\w-]+)", content_type or "", re.IGNORECASE)
    charset = match.group(1) if match else "utf-8"
    if charset.lower().replace("-", "") == "utf8":
        charset = "utf-8-sig"
    try:
        return content.decode(charset, errors="replace")
    except LookupError:
        return content.decode("utf-8-sig", errors="replace")


async def fetch_ishares_holdings(etf_ticker: str) -> list[dict] | None:
    """Lade + parse iShares-Holdings. None bei Fetch-Fehler (Caller -> error)."""
    url = ISHARES_HOLDINGS_URLS.get(etf_ticker)
    if not url:
        return None
    # Import erst hier: services.etf_adapters laedt beim Import dieses Modul.
    from services.etf_adapters._http import capped_get

    # capped_get setzt den Browser-UA, streamt und bricht bei der Byte-Grenze ab;
    # Netzwerkfehler und HTTP != 200 loggt es selbst und liefert None.
    meta: dict = {}
    content = await capped_get(
        url, adapter="ishares_adapter", ticker=etf_ticker,
        headers={"User-Agent": _BROWSER_UA}, meta=meta,
    )
    if content is None:
        return None
    return parse_ishares_csv(
        _decode_body(content, meta.get("content_type")),
        etf_ticker,
        response_info=f"status={meta.get('status')}, content-type={meta.get('content_type')}",
    )
