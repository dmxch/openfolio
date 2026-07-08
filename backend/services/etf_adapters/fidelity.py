"""Fidelity-International-Adapter: keyloser .xlsx-Download -> Holding-Rows.

Fidelity International (fidelity.lu) liefert je Fonds ein ISIN-getemplatetes
.xlsx (OOXML) mit der SCHWAECHSTEN Feldabdeckung aller Anbieter: pro Holding nur
`ISIN | Name | Weight (%)` — KEIN natives Land, KEIN nativer Sektor. Deshalb
bleiben holding_country/holding_sector hier None; die Ticker-/Sektor-Anreicherung
(US-Overlap-Reverse-Lookup + classify_tickers_bulk) uebernimmt der Service ueber
die persistierte ISIN.

Sheet-Layout (ein Worksheet, benannt nach der Fonds-ISIN):
    Zeile 1: Fondsname (Spalte A)
    Zeile 2: 'Date:' | 'YYYY-MM-DD'
    Zeile 3: Header ['ISIN','Name','Weight (%)']
    Zeile 4+: Holdings
Derivate/Cash (Index-Futures, FX) tragen eine LEERE ISIN-Spalte und fallen so
ueber die ISIN-Validierung heraus — es gibt keine Asset-Class-Spalte zum Filtern.

Browser-User-Agent zwingend: der Download-Endpoint sitzt hinter Akamai und
antwortet Default-UAs mit 403 (vgl. reference_cloudflare_ua_block). Content-Type
ist application/octet-stream; der Body ist echtes OOXML (beginnt mit 'PK').
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from services.etf_adapters._excel import read_xlsx
from services.etf_adapters.base import (
    BROWSER_UA,
    EtfAdapter,
    EtfRef,
    is_valid_isin,
    make_holding_row,
    name_contains,
    register,
)

logger = logging.getLogger(__name__)

_DOWNLOAD_URL = (
    "https://www.fidelity.lu/xapi/fund/portfolio/download/fundFullHolding"
    "?id={isin}&country=lu&language=en"
)

# 'Date:'-Zeile: Fidelity liefert ISO (YYYY-MM-DD); die uebrigen Formate sind
# defensive Fallbacks, falls read_xlsx eine echte Datetime-Zelle stringifiziert
# ('2026-07-07 00:00:00') oder eine Locale-Variante auftaucht.
_AS_OF_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y")


def _parse_weight(raw: str) -> float | None:
    # Dezimaltrenner ist '.'; evtl. '%'-Suffix und Tausender-Trenner entfernen.
    s = (raw or "").strip().rstrip("%").replace("’", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_as_of(pre_header_rows: list[list[str]]) -> date | None:
    """Stichtag aus der 'Date:'-Zeile ueber dem Header ziehen (None wenn keiner)."""
    for row in pre_header_rows:
        for i, cell in enumerate(row):
            c = (cell or "").strip()
            if not c.lower().startswith("date"):
                continue
            # Wert steht nach dem Doppelpunkt in derselben Zelle ODER in der naechsten.
            cand = c.split(":", 1)[1].strip() if ":" in c else ""
            if not cand and i + 1 < len(row):
                cand = (row[i + 1] or "").strip()
            for probe in (cand, cand[:10]):  # [:10] kappt ' 00:00:00'
                for fmt in _AS_OF_FORMATS:
                    try:
                        return datetime.strptime(probe, fmt).date()
                    except (ValueError, TypeError):
                        continue
    return None


def parse_fidelity_holdings(
    rows: list[list[str]],
    etf_ticker: str,
    fund_isin: str | None = None,
) -> list[dict]:
    """Dekodierte Sheet-Zeilen -> normalisierte Holding-Rows (reine Funktion, kein I/O).

    `rows` = Ausgabe von _excel.read_xlsx (list[list[str]]). Skippt Derivate/Cash
    (leere/ungueltige ISIN), Self-Reference (Holding-ISIN == Fonds-ISIN) und
    Null-Gewichte. holding_ticker faellt auf die ISIN zurueck (kein lokaler Ticker
    im Feed) — der Service loest US-Holdings spaeter ueber die ISIN auf.
    """
    hdr_idx = next(
        (
            i
            for i, r in enumerate(rows)
            if any(c.strip().upper() == "ISIN" for c in r)
            and any("weight" in c.lower() for c in r)
        ),
        None,
    )
    if hdr_idx is None:
        logger.warning("fidelity_adapter: Header nicht gefunden fuer %s", etf_ticker)
        return []

    header = [c.strip() for c in rows[hdr_idx]]
    isin_i = next((i for i, c in enumerate(header) if c.upper() == "ISIN"), None)
    name_i = next((i for i, c in enumerate(header) if c.lower() == "name"), None)
    weight_i = next((i for i, c in enumerate(header) if "weight" in c.lower()), None)
    if isin_i is None or weight_i is None:
        logger.warning("fidelity_adapter: ISIN/Weight-Spalte fehlt fuer %s", etf_ticker)
        return []

    as_of = _extract_as_of(rows[:hdr_idx])
    fund_isin_n = fund_isin.strip().upper() if fund_isin else None

    def col(row: list[str], i: int | None) -> str:
        return row[i].strip() if (i is not None and i < len(row)) else ""

    out: dict[str, dict] = {}
    for row in rows[hdr_idx + 1:]:
        isin = col(row, isin_i).upper()
        # Derivate/Cash (Index-Futures, FX) tragen keine gueltige ISIN -> raus.
        if not is_valid_isin(isin):
            continue
        # Self-Reference (Fund-of-Fund haelt sich selbst): Holding-ISIN == Fonds-ISIN.
        if fund_isin_n and isin == fund_isin_n:
            continue
        holding = make_holding_row(
            etf_ticker=etf_ticker,
            weight_pct=_parse_weight(col(row, weight_i)),  # None/0 -> Row wird None
            isin=isin,
            name=col(row, name_i) or None,
            country=None,   # Fidelity per-Holding: kein natives Land
            sector=None,    # Fidelity per-Holding: kein nativer Sektor
            as_of=as_of,
        )
        if holding:
            out.setdefault(holding["holding_ticker"], holding)  # PK-Dedup (erste gewinnt)
    return list(out.values())


class FidelityAdapter(EtfAdapter):
    name = "Fidelity"

    def matches(self, ref: EtfRef) -> bool:
        # Marke im Namen + ISIN vorhanden (die URL ist ISIN-getemplatet).
        return name_contains(ref, "fidelity") and bool(ref.isin_norm)

    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        isin = ref.isin_norm
        if not isin:
            return None
        url = _DOWNLOAD_URL.format(isin=isin)
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": BROWSER_UA})
        except Exception as e:
            logger.warning("fidelity_adapter: Fetch fehlgeschlagen fuer %s: %s", isin, e)
            return None
        if r.status_code != 200:
            logger.warning("fidelity_adapter: HTTP %s fuer %s", r.status_code, isin)
            return None
        # Soft-200 mit HTML-Fehlerseite abfangen: echtes OOXML beginnt mit 'PK'.
        if not r.content or not r.content.startswith(b"PK"):
            logger.warning("fidelity_adapter: kein OOXML-Body fuer %s", isin)
            return None
        rows = read_xlsx(r.content)
        return parse_fidelity_holdings(rows, ref.ticker, isin)


register(FidelityAdapter())
