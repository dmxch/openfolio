"""SPDR-Adapter (State Street) — keyloser .xlsx-Download -> Holding-Rows.

SPDR/SSGA veroeffentlicht taegliche EMEA-Holdings als offenes .xlsx (kein Key,
kein Login). Die Datei traegt STARKE Issuer-native Referenzdaten: native ISIN pro
Holding, GICS "Sector Classification" und "Trade Country Name" — genau das, was der
Laender-/Sektor-Look-Through (concentration_service) bevorzugt.

Pitfall: Die Download-URL ist NICHT ueber die (bekanntere) LSE-Boersen-Kennung
erreichbar, sondern nur ueber den lowercase Bloomberg-XETRA-Ticker ("GY"). Deshalb
gibt es keine ableitbare URL aus Ticker/ISIN — wir pflegen eine kleine, gegen
ssga.com verifizierte Registry SPDR_ISIN_TO_GY (ISIN -> GY-Kuerzel) und matchen nur
darauf. Nicht gelistete SPDR-ETFs matchen schlicht nicht (ehrlicher Skip, kein Fehler).

Browser-User-Agent zwingend (Akamai-Edge 403t Default-UAs, vgl. iShares-Adapter).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from constants.etf_sector_map import map_sector
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

# ISIN -> lowercase Bloomberg-XETRA-Ticker ("GY"), der die .xlsx-URL bildet.
# Jedes Paar ist gegen ssga.com verifiziert (Fund-Data-Datei liefert HTTP 200 und
# nennt ISIN/Ticker im Preamble). Nur breit gehaltene SPDR-UCITS-EQUITY-ETFs —
# Bond-/Wandelanleihen-Fonds bewusst raus (deren "Sector"-Spalte traegt kein GICS).
# Erweiterbar: neuen ETF erst nach 200-Check + Preamble-Abgleich aufnehmen.
SPDR_ISIN_TO_GY: dict[str, str] = {
    "IE00BFY0GT14": "sppw",  # SPDR MSCI World UCITS ETF (Acc)  [LSE: SWRD]
    "IE00B6YX5C33": "spy5",  # SPDR S&P 500 UCITS ETF (Dist)
    "IE000XZSV718": "spyl",  # SPDR S&P 500 UCITS ETF (Acc)
    "IE00B469F816": "spym",  # SPDR MSCI Emerging Markets UCITS ETF (Acc)
    "IE00B4YBJ215": "spy4",  # SPDR S&P 400 U.S. Mid Cap UCITS ETF (Acc)
    "IE00B5M1WJ87": "spyw",  # SPDR S&P Euro Dividend Aristocrats UCITS ETF (Dist)
    "IE00B6YX5D40": "spyd",  # SPDR S&P U.S. Dividend Aristocrats UCITS ETF (Dist)
    "IE00BCBJG560": "zprs",  # SPDR MSCI World Small Cap UCITS ETF (Acc)
    "IE00BSPLC413": "zprv",  # SPDR MSCI USA Small Cap Value Weighted UCITS ETF
    "IE00B9KNR336": "zpra",  # SPDR S&P Pan Asia Dividend Aristocrats UCITS ETF (Dist)
    "IE00B3YLTY66": "spyi",  # SPDR MSCI ACWI IMI UCITS ETF (Acc)
    "IE00B6S2Z822": "spyg",  # SPDR S&P UK Dividend Aristocrats UCITS ETF (Dist)
}

_URL_TEMPLATE = (
    "https://www.ssga.com/library-content/products/fund-data/etfs/emea/"
    "holdings-daily-emea-en-{gy}-gy.xlsx"
)

# Preamble-Zelle "Holdings As Of:" traegt das Stichtagsdatum (z.B. "07-Jul-2026").
_AS_OF_FORMATS = ("%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%Y-%m-%d")

# Feldnamen exakt wie im Header der SSGA-Datei (Row mit "ISIN" + "Percent of Fund").
_COL_ISIN = "ISIN"
_COL_NAME = "Security Name"
_COL_WEIGHT = "Percent of Fund"
_COL_COUNTRY = "Trade Country Name"
_COL_SECTOR = "Sector Classification"


def spdr_url(gy_ticker: str) -> str:
    """Bilde die Holdings-URL aus dem lowercase GY-Kuerzel."""
    return _URL_TEMPLATE.format(gy=gy_ticker.strip().lower())


def _parse_weight(raw: str) -> float | None:
    # Prozentwerte stehen als schlichter Float ("5.114354"); Cash-Zeilen tragen "-".
    s = (raw or "").strip().replace("’", "").replace(",", "")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_as_of(pre_header_rows: list[list[str]]) -> date | None:
    for row in pre_header_rows:
        for i, cell in enumerate(row):
            if "holdings as of" in cell.strip().lower():
                # Datum steht in der Nachbarzelle ("Holdings As Of:" | "07-Jul-2026").
                cand = row[i + 1].strip() if i + 1 < len(row) else ""
                for fmt in _AS_OF_FORMATS:
                    try:
                        return datetime.strptime(cand, fmt).date()
                    except (ValueError, TypeError):
                        continue
    return None


def parse_spdr_holdings(
    rows: list[list[str]], etf_ticker: str, etf_isin: str | None = None
) -> list[dict]:
    """SSGA-.xlsx-Zeilen (read_xlsx-Output) -> normalisierte Holding-Rows.

    Reine Funktion (kein I/O) — voll unit-testbar. Der Header wird ueber die Zeile
    gefunden, die "ISIN" UND "Percent of Fund" enthaelt; Spalten werden per Name
    gemappt (Reihenfolge-robust). Ge-skippt werden — via ISIN-Regex — die
    "Unassigned"-Cash/Derivate-Zeilen, die leere Trennzeile und die abschliessende
    "Marketing Communication."-Disclaimer-Zeile; zusaetzlich die Fonds-Selbstreferenz
    (ISIN == etf_isin) und (durch make_holding_row) Null-Gewicht-Zeilen.

    holding_ticker bleibt die ISIN (SPDR-Feed traegt keinen brauchbaren lokalen
    Ticker) — Land/Sektor sind Issuer-nativ und ueberleben so den Look-Through auch
    ohne Boersen-Aufloesung.
    """
    hdr_idx = next(
        (i for i, r in enumerate(rows)
         if any(c.strip() == _COL_ISIN for c in r)
         and any(c.strip() == _COL_WEIGHT for c in r)),
        None,
    )
    if hdr_idx is None:
        logger.warning("spdr_adapter: Header nicht gefunden fuer %s", etf_ticker)
        return []
    header = [c.strip() for c in rows[hdr_idx]]
    idx = {name: i for i, name in enumerate(header)}

    def col(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    as_of = _extract_as_of(rows[:hdr_idx])
    self_isin = etf_isin.strip().upper() if etf_isin else None

    out: dict[tuple[str, str], dict] = {}
    for row in rows[hdr_idx + 1:]:
        isin = col(row, _COL_ISIN).upper()
        # ISIN-Regex-Filter: entfernt Cash ("Unassigned"), Trenn- und Disclaimer-Zeile.
        if not is_valid_isin(isin):
            continue
        if self_isin and isin == self_isin:          # Fonds-Selbstreferenz
            continue
        w = _parse_weight(col(row, _COL_WEIGHT))
        country = col(row, _COL_COUNTRY) or None
        holding = make_holding_row(
            etf_ticker=etf_ticker,
            weight_pct=w,                              # None/0 -> make_holding_row skippt
            isin=isin,                                 # holding_ticker faellt auf ISIN
            name=col(row, _COL_NAME) or None,
            country=country,                           # native "Trade Country Name" (Venue)
            sector=map_sector(col(row, _COL_SECTOR)),  # native GICS -> OpenFolio-Sektor
            as_of=as_of,
        )
        if holding is None:
            continue
        out[(etf_ticker, holding["holding_ticker"])] = holding
    return list(out.values())


class SpdrAdapter(EtfAdapter):
    name = "SPDR"

    def matches(self, ref: EtfRef) -> bool:
        # Marke (loose, faengt Broker-Kuerzungen) UND ISIN in der verifizierten
        # Registry (baut die URL). ISINs sind global eindeutig -> keine Fehl-Matches.
        return (
            ref.isin_norm in SPDR_ISIN_TO_GY
            and name_contains(ref, "spdr", "ssga", "state street")
        )

    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        gy = SPDR_ISIN_TO_GY.get(ref.isin_norm or "")
        if not gy:
            return None
        url = spdr_url(gy)
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": BROWSER_UA})
        except Exception as e:
            logger.warning("spdr_adapter: Fetch fehlgeschlagen fuer %s: %s", ref.ticker, e)
            return None
        if r.status_code != 200:
            logger.warning("spdr_adapter: HTTP %s fuer %s", r.status_code, ref.ticker)
            return None
        rows = read_xlsx(r.content)
        if not rows:
            logger.warning("spdr_adapter: leeres/ungueltiges .xlsx fuer %s", ref.ticker)
            return None
        return parse_spdr_holdings(rows, ref.ticker, ref.isin_norm)


register(SpdrAdapter())
