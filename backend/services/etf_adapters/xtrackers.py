"""Xtrackers-(DWS-)Holdings-Adapter: keyloser JSON-Download -> Holding-Rows.

Xtrackers liefert die Bestandteile ISIN-getemplatet und keylos als JSON:
    GET https://etf.dws.com/api/pdp/en-lu/etf/{ISIN}/holdings
(der Name-Slug nach der ISIN ist optional/egal — die ISIN allein genuegt).

Der Feed ist Look-Through-STARK: er traegt native ISIN + vollen Landesnamen +
GICS-Industry pro Holding, d.h. Land UND Sektor kommen direkt vom Anbieter
(kein Reverse-Ticker-Lookup noetig). Da der Feed KEINEN Boersen-Ticker fuehrt,
laeuft holding_ticker ueber die ISIN als stabilen Fallback-Key (make_holding_row).

Struktur (am realen Payload von IE00BJ0KDQ92 / IE00BTJRMP35 verifiziert):
  payload["tables"][0] traegt die Holdings-Tabelle.
    .columns  = Liste von {key, value}; `value` = Header-Name ("ISIN", "Name",
                "% Weight", "Country", "Industry", "Asset class"), `key` = interner
                Spalten-Key ("header", "column_0", ...). Wir mappen NAME -> key,
                nie ueber die Position (Spalten koennen sich verschieben).
    .values   = VOLLE Zeilenliste (rowsPerPage ist nur ein Anzeige-Hinweis). Jede
                Zeile ist ein Dict, keyed nach Spalten-key; jede Zelle ist ein Dict
                {value, sortValue, type} (PITFALL: kein Skalar!).
    .disclaimers[0].text = "<p>Source: DWS 06.07.2026</p>" -> Stichtag (DD.MM.YYYY);
                das top-level `asOfDate` ist in der Praxis leer.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from constants.etf_sector_map import map_sector
from services.etf_adapters._http import capped_get
from services.etf_adapters.base import (
    EtfAdapter,
    EtfRef,
    make_holding_row,
    name_contains,
    register,
)

logger = logging.getLogger(__name__)

_HOLDINGS_URL = "https://etf.dws.com/api/pdp/en-lu/etf/{isin}/holdings"

# Equity-artige Bestandteile behalten, Cash/Right/Future/Warrants/Bond raus.
# WICHTIG: nicht nur "Equities" — auch "Depository Receipts" (Thai-NVDRs, GDRs/ADRs)
# und "Preferred Stock" sind echte Aktien-Exposures mit nativem Land+Sektor (z.B.
# haelt ein Thailand-/Brasilien-Sleeve fast nur NVDRs bzw. Vorzugsaktien). Inklusiv
# per Keyword (lieber ein echtes Holding behalten als eins faelschlich droppen).
_EQUITY_ASSET_KEYWORDS = ("equit", "depositary", "depository", "receipt", "preferred")


def _is_equity_asset_class(raw: str) -> bool:
    s = (raw or "").lower()
    return any(k in s for k in _EQUITY_ASSET_KEYWORDS)

# Country-Platzhalter des Feeds -> None (statt "--" o.ae. zu persistieren).
_COUNTRY_PLACEHOLDERS = {"", "-", "--", "n/a", "unknown"}

# Stichtag: "Source: DWS 06.07.2026" (DD.MM.YYYY).
_AS_OF_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def _text(cell: object) -> str:
    """Anzeige-String einer Zelle (Dict {value, ...} ODER Skalar) — getrimmt."""
    if isinstance(cell, dict):
        v = cell.get("value")
        return str(v).strip() if v is not None else ""
    return str(cell).strip() if cell is not None else ""


def _weight(cell: object) -> float | None:
    """Gewicht in Prozent aus einer Zelle. Bevorzugt den numerischen sortValue
    (z.B. 5.0741409), sonst wird der Anzeige-String ("5.074%") geparst."""
    raw: object
    if isinstance(cell, dict):
        sv = cell.get("sortValue")
        if isinstance(sv, (int, float)) and not isinstance(sv, bool):
            return float(sv)
        raw = cell.get("value")
    else:
        raw = cell
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if raw is None:
        return None
    s = str(raw).strip().replace("%", "").replace("’", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_as_of(table: dict, payload: dict) -> date | None:
    """Stichtag aus dem Disclaimer ("Source: DWS DD.MM.YYYY"), sonst top-level
    asOfDate (ISO), sonst None."""
    for disc in table.get("disclaimers") or []:
        m = _AS_OF_RE.search((disc or {}).get("text") or "")
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
    iso = (payload.get("asOfDate") or "").strip()
    if iso:
        try:
            return datetime.strptime(iso[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def parse_xtrackers_holdings(
    payload: dict | str | bytes,
    etf_ticker: str,
    etf_isin: str | None = None,
) -> list[dict]:
    """JSON-Payload -> normalisierte Holding-Rows (nur Equity, ISIN als Key).

    Reine Funktion (kein I/O) — voll unit-testbar. Mappt Spalten ueber ihren
    Header-NAMEN (nicht die Position), normalisiert die {value, sortValue}-Zellen,
    filtert Cash/Derivate + die Fonds-Selbstreferenz + Null-/Negativ-Gewichte.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            logger.warning("xtrackers_adapter: JSON-Parse fehlgeschlagen fuer %s", etf_ticker)
            return []
    if not isinstance(payload, dict):
        return []

    tables = payload.get("tables") or []
    if not tables or not isinstance(tables[0], dict):
        logger.warning("xtrackers_adapter: tables[0] fehlt fuer %s", etf_ticker)
        return []
    table = tables[0]

    # Header-NAME -> interner Spalten-Key (robust gegen Spalten-Umsortierung).
    name2key: dict[str, str] = {}
    for col in table.get("columns") or []:
        if isinstance(col, dict) and col.get("key") and col.get("value"):
            name2key[str(col["value"]).strip()] = str(col["key"])

    k_isin = name2key.get("ISIN")
    k_name = name2key.get("Name")
    k_weight = name2key.get("% Weight")
    k_country = name2key.get("Country")
    k_industry = name2key.get("Industry")
    k_asset = name2key.get("Asset class")
    if not (k_isin and k_weight and k_asset):
        logger.warning(
            "xtrackers_adapter: Pflichtspalten fehlen fuer %s (cols=%s)",
            etf_ticker, list(name2key),
        )
        return []

    as_of = _extract_as_of(table, payload)
    fund_isin = (etf_isin or "").strip().upper()

    out: dict[str, dict] = {}
    for row in table.get("values") or []:
        if not isinstance(row, dict):
            continue
        if not _is_equity_asset_class(_text(row.get(k_asset))):
            continue  # Cash / Right / Future / Warrants (Equity/DR/Preferred bleiben)
        isin = _text(row.get(k_isin)).upper()
        if not isin or (fund_isin and isin == fund_isin):
            continue  # leere ISIN oder Fonds-Selbstreferenz
        w = _weight(row.get(k_weight))
        if w is None or w <= 0:
            continue
        country = _text(row.get(k_country)) if k_country else ""
        if country.lower() in _COUNTRY_PLACEHOLDERS:
            country = ""
        industry = _text(row.get(k_industry)) if k_industry else ""
        holding = make_holding_row(
            etf_ticker=etf_ticker,
            weight_pct=w,
            isin=isin,                          # kein Ticker im Feed -> ISIN = Key
            name=_text(row.get(k_name)) if k_name else None,
            country=country or None,
            sector=map_sector(industry),        # native GICS-Industry -> OpenFolio
            as_of=as_of,
        )
        if holding:                             # None = ungueltige ISIN / Gewicht
            out[holding["holding_ticker"]] = holding
    return list(out.values())


class XtrackersAdapter(EtfAdapter):
    name = "Xtrackers"

    def matches(self, ref: EtfRef) -> bool:
        # Marke im Fondsnamen (auch broker-verkuerzt robust) UND gueltige ISIN, da
        # die Holdings-URL ISIN-getemplatet ist — Muell-ISIN faellt auf no_source durch.
        return name_contains(ref, "xtrackers") and bool(ref.isin_valid)

    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        isin = ref.isin_valid
        if not isin:
            return None
        url = _HOLDINGS_URL.format(isin=isin)
        content = await capped_get(url, adapter="xtrackers_adapter", ticker=ref.ticker)
        if content is None:
            return None
        # parse_xtrackers_holdings dekodiert bytes selbst (json.loads); ungueltiges
        # JSON -> [] (der Stale-Delete-Guard im Service verhindert ein Leerraeumen).
        return parse_xtrackers_holdings(content, ref.ticker, etf_isin=isin)


register(XtrackersAdapter())
