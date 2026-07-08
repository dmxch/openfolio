"""HSBC-Asset-Management-Adapter: keyloser legacy-.xls-Download -> Holding-Rows.

HSBC AM stellt die vollen Fund-Holdings unter einem ISIN-templatierten Endpoint
bereit (KEIN Key, KEIN Ticker im Feed — nur ISIN + CUSIP + Land). Die Datei ist
ein legacy BIFF/OLE2 .xls (Content-Type application/xls) -> read_xls (xlrd), NICHT
read_xlsx. Der Sheet "Report" hat 5 Metadaten-Zeilen (Fondsname, Datums-Serial,
Fondsgroesse), danach eine benannte Header-Zeile:
    [ISIN, CUSIP, SecurityName, NumberOfShare, MarketValue, Country,
     LocalCurrencyCode, Weighting]

Besonderheiten (am realen Feed IE00B4X9L533 / IE00B5SSQT16 verifiziert):
- Weighting ist bereits ein Prozentwert (Summe = 100), direkt uebernehmbar.
- Die Country-Spalte traegt schon die MSCI-Laenderklassifikation (Cayman-domizilierte
  KYG...-ISINs stehen als "China"/"Hong Kong" etc.) -> Land unveraendert persistieren,
  kein eigener Domizil-Override noetig.
- KEINE Sektor-Spalte -> holding_sector bleibt None (Service-Enrichment/classify
  klassifiziert dann pro Ticker).
- Cash/Margin/Receivable-Zeilen tragen KEINE ISIN (fallen ueber den fehlenden Key aus)
  und sind meist null/negativ gewichtet; ein Index-Total-Return-Future traegt aber
  eine gueltige ISIN + positives Gewicht und wird ueber den Namen ausgefiltert.
- holding_ticker: nur isin= (kein lokaler Ticker im Feed) -> make_holding_row nimmt die
  ISIN als stabilen Key; die Ticker-Aufloesung uebernimmt das OpenFIGI-Enrichment
  (CUSIP/ISIN) des Service.

Browser-User-Agent gesetzt (Konsistenz mit den uebrigen Issuer-Edges).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

from services.etf_adapters._excel import read_xls
from services.etf_adapters.base import (
    BROWSER_UA,
    EtfAdapter,
    EtfRef,
    make_holding_row,
    name_contains,
    register,
)

logger = logging.getLogger(__name__)

_DOWNLOAD_URL = (
    "https://www.assetmanagement.hsbc.co.uk/api/v1/download/document/"
    "{isin}/gb/en/holdings"
)

# Excel-1900-Datumssystem inkl. fiktivem 1900-02-29-Bug -> Epoche 1899-12-30.
_EXCEL_EPOCH = date(1899, 12, 30)

# Derivate/Index-Exposure ausfiltern: Wort-Marker AND Benchmark-Marker, damit echte
# Equities mit "Future" im Namen (z.B. "Posco Future M") NICHT faelschlich rausfallen.
_DERIV_WORDS = ("future", "forward", "swap")
_BENCHMARK_MARKERS = ("index", "msci", "ftse", "s&p", "total return")


def _parse_weight(raw: str) -> float | None:
    """Weighting-Zelle -> float (Prozent) oder None. Leere/nicht-numerische -> None."""
    s = (raw or "").strip().replace("’", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _excel_serial_to_date(raw: str) -> date | None:
    """Excel-Datums-Serial (String, z.B. "46205") -> date, sonst None.

    Rein rechnerisch (kein xlrd noetig, read_xls hat den datemode bereits verworfen).
    Plausibilitaets-Fenster ~1998..2060 schuetzt gegen Muell-Zellen.
    """
    s = (raw or "").strip()
    if not s:
        return None
    try:
        serial = int(round(float(s)))
    except (ValueError, TypeError):
        return None
    if not (20000 <= serial <= 60000):
        return None
    return _EXCEL_EPOCH + timedelta(days=serial)


def _is_derivative(name: str) -> bool:
    """True fuer Index-Futures/Forwards/Swaps (Wort-Marker UND Benchmark-Marker)."""
    low = (name or "").lower()
    if not any(w in low for w in _DERIV_WORDS):
        return False
    return any(m in low for m in _BENCHMARK_MARKERS)


def _extract_as_of(meta_rows: list[list[str]]) -> date | None:
    """Stichtag aus den Metadaten-Zeilen: Zelle "Date" -> Nachbarzelle (Serial)."""
    for row in meta_rows:
        for i, cell in enumerate(row):
            if cell.strip().lower() == "date" and i + 1 < len(row):
                return _excel_serial_to_date(row[i + 1])
    return None


def parse_hsbc_rows(
    rows: list[list[str]],
    etf_ticker: str,
    etf_isin: str | None = None,
) -> list[dict]:
    """read_xls-Zeilen -> normalisierte Holding-Rows. Reine Funktion (kein I/O).

    Header-Zeile per Namen (ISIN + Weighting) gesucht, Spalten per Name gemappt
    (Zeilenindex kann wandern). Skippt Cash/Derivate/Self-Ref/null-Gewicht; die
    ISIN dient als holding_ticker-Key (Ticker-Aufloesung via OpenFIGI im Service).
    """
    hdr_idx = next(
        (i for i, r in enumerate(rows)
         if any(c.strip() == "ISIN" for c in r)
         and any(c.strip() == "Weighting" for c in r)),
        None,
    )
    if hdr_idx is None:
        logger.warning("hsbc_adapter: Header nicht gefunden fuer %s", etf_ticker)
        return []
    header = [c.strip() for c in rows[hdr_idx]]
    idx = {name: i for i, name in enumerate(header)}

    def col(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    as_of = _extract_as_of(rows[:hdr_idx])
    own_isin = (etf_isin or "").strip().upper() or None

    out: dict[str, dict] = {}
    for row in rows[hdr_idx + 1:]:
        isin = col(row, "ISIN").upper()
        name = col(row, "SecurityName")
        # Self-Reference (Fonds haelt eigene Anteile) defensiv ueberspringen.
        if own_isin and isin == own_isin:
            continue
        # Index-Total-Return-Future o.ae. (traegt eine gueltige ISIN) rausfiltern.
        if _is_derivative(name):
            continue
        w = _parse_weight(col(row, "Weighting"))
        country = col(row, "Country") or None
        holding = make_holding_row(
            etf_ticker=etf_ticker,
            weight_pct=w,               # <=0 / None -> make_holding_row verwirft
            isin=isin or None,          # Cash-Zeilen ohne ISIN -> kein Key -> None
            yf_ticker=None,             # kein lokaler Ticker im Feed (OpenFIGI resolved)
            name=name,
            country=country,
            sector=None,                # HSBC-Feed hat keine Sektor-Spalte
            as_of=as_of,
        )
        if holding is None:
            continue
        out[holding["holding_ticker"]] = holding
    return list(out.values())


def parse_hsbc_xls(content: bytes, etf_ticker: str, etf_isin: str | None = None) -> list[dict]:
    """Rohe .xls-Bytes -> Holding-Rows (read_xls-Decode + reiner Parser)."""
    return parse_hsbc_rows(read_xls(content), etf_ticker, etf_isin)


class HsbcAdapter(EtfAdapter):
    name = "HSBC"

    def matches(self, ref: EtfRef) -> bool:
        # Marke im Namen UND ISIN vorhanden (baut den ISIN-templatierten URL).
        return name_contains(ref, "hsbc") and bool(ref.isin_norm)

    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        isin = ref.isin_norm
        if not isin:
            return None
        url = _DOWNLOAD_URL.format(isin=isin.lower())
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": BROWSER_UA})
        except Exception as e:
            logger.warning("hsbc_adapter: Fetch fehlgeschlagen fuer %s: %s", ref.ticker, e)
            return None
        if r.status_code != 200:
            logger.warning("hsbc_adapter: HTTP %s fuer %s (%s)", r.status_code, ref.ticker, isin)
            return None
        return parse_hsbc_xls(r.content, ref.ticker, isin)


register(HsbcAdapter())
