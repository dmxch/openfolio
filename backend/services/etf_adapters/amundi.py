"""Amundi-ETF-Holdings-Adapter (inkl. ex-Lyxor) — keyloser JSON-POST -> Rows.

Amundi liefert die Zusammensetzung ueber einen keylosen Produkt-Endpoint, den man
per POST mit der Fonds-ISIN im Body anspricht. Die Antwort traegt pro Holding
Issuer-native GICS-Sektoren, `countryOfRisk` (voller Laendername) und einen
Bloomberg-Ticker `bbg` ("SYMBOL CC") — bei PHYSISCHEN Fonds die echte Index-Sicht.

*** KRITISCHE FALLE (Vertrauen in die Zahlen) ***
SWAP-basierte (synthetische) Amundi-Fonds geben als "composition" einen
SUBSTITUT-KORB zurueck (Trager-Portfolio des Swaps), NICHT das echte Index-Exposure
— z.B. liefert der "Amundi MSCI World SWAP" Siemens Energy / ASML / Airbus / Bayer
statt Apple / Nvidia / Microsoft. Diesen Korb als Holdings zu persistieren waere
grob irrefuehrend. Wir erkennen Swap-Replikation an den Fonds-Characteristics
(REPLICATION_IS_SWAP_BASED bzw. FUND_REPLICATION_METHODOLOGY enthaelt "Swap"/
"Synthetic"/"Indirect") und geben fuer solche Fonds bewusst [] zurueck (ehrliches
"kein Per-Holding-Look-Through") statt den Korb einzumischen. PHYSISCH/Direct
parst normal.

Browser-User-Agent gesetzt (mehrere Issuer-Edges 403en Default-UAs).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

import httpx

from constants.etf_sector_map import map_sector
from constants.exchange_suffix import bloomberg_composite_to_yf
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

_API_URL = "https://www.amundietf.ch/mapi/ProductAPI/getProductsData"

# Amundi-Composition-Datum ist ISO ("2026-07-06"); defensiv weitere Formate.
_AS_OF_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y")

# Non-Equity-/Derivat-Typen: ausgeschlossen. WICHTIG: FUTURE-Zeilen tragen eine
# GUELTIGE Futures-ISIN (z.B. DE000C71QQS6) — ein reiner ISIN-Presence-Filter
# wuerde sie NICHT fangen, deshalb zwingend zusaetzlich der Typ-Filter.
_NON_EQUITY_TOKENS = frozenset({
    "CASH", "FUTURE", "FUTURES", "FORWARD", "FORWARDS", "SWAP", "SWAPS",
    "OPTION", "OPTIONS", "WARRANT", "WARRANTS", "RIGHT", "RIGHTS",
    "BOND", "BONDS", "REPO", "DEPOSIT", "DEPOSITS", "MONEY", "FX",
    "DERIV", "DERIVATIVE", "DERIVATIVES",
})
_TYPE_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")


def _build_body(isin: str) -> dict:
    """POST-Body fuer getProductsData (getrimmt auf die genutzten Felder)."""
    return {
        "productIds": [isin],
        "characteristics": [
            "ISIN",
            "FUND_REPLICATION_METHODOLOGY",
            "REPLICATION_IS_SWAP_BASED",
        ],
        "composition": {
            "compositionFields": [
                "date", "type", "bbg", "isin", "name", "weight",
                "quantity", "currency", "sector", "country", "countryOfRisk",
            ]
        },
        "productType": "PRODUCT",
    }


def _is_swap_based(characteristics: dict) -> bool:
    """True, wenn der Fonds synthetisch (Swap) repliziert -> Composition ist ein
    Substitut-Korb und darf NICHT als Holdings persistiert werden."""
    flag = characteristics.get("REPLICATION_IS_SWAP_BASED")
    if isinstance(flag, bool) and flag:
        return True
    if isinstance(flag, str) and flag.strip().lower() in ("true", "1", "yes", "y"):
        return True
    method = str(characteristics.get("FUND_REPLICATION_METHODOLOGY") or "").lower()
    return any(k in method for k in ("swap", "synthetic", "indirect"))


def _is_non_equity_type(row_type: str) -> bool:
    """Non-Equity/Derivat-Typ? Token-basiert (Ganzwort), damit z.B.
    'DEPOSITORY_RECEIPT' NICHT faelschlich ueber das Cash-Token 'DEPOSIT' gefiltert
    wird — Depository Receipts (ADR/GDR/NVDR) sind echte Aktien-Exposures."""
    tokens = set(_TYPE_TOKEN_SPLIT.split((row_type or "").upper()))
    return bool(tokens & _NON_EQUITY_TOKENS)


def _parse_as_of(raw: str | None) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in _AS_OF_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def parse_amundi_composition(payload: dict | str | bytes, etf_ticker: str) -> list[dict]:
    """Amundi-Produkt-JSON -> normalisierte Holding-Rows (rein, kein I/O).

    - Swap-Fonds: [] (Substitut-Korb, kein echtes Look-Through — siehe Modul-Docstring).
    - Sonst: pro Equity-Holding eine Row via make_holding_row. holding_ticker =
      aus `bbg` aufgeloester yf-Ticker, sonst faellt make_holding_row auf die ISIN
      als stabilen Key zurueck (Land/Sektor ueberleben so den Look-Through auch
      ohne Ticker-Aufloesung).

    `weight` kommt als Bruch (0..1) ODER Prozent (0..100). Skala wird EINMAL pro
    Payload aus der Summe der behaltenen Gewichte erkannt (Vollbestand-Summe ~1.0
    => Bruch, ~100 => Prozent) und auf PROZENT normalisiert.
    """
    data = payload
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "replace")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            logger.warning("amundi_adapter: JSON-Decode fehlgeschlagen fuer %s", etf_ticker)
            return []
    if not isinstance(data, dict):
        return []

    products = data.get("products")
    if isinstance(products, list) and products:
        product = products[0]
    elif "composition" in data:  # Payload ist bereits das Produkt-Objekt
        product = data
    else:
        return []
    if not isinstance(product, dict):
        return []

    characteristics = product.get("characteristics") or {}
    if _is_swap_based(characteristics):
        logger.info("amundi_adapter: %s ist Swap-basiert -> kein Per-Holding-Look-Through", etf_ticker)
        return []

    fund_isin = str(characteristics.get("ISIN") or product.get("productId") or "").strip().upper()

    composition = product.get("composition") or {}
    comp_rows = composition.get("compositionData")
    if not isinstance(comp_rows, list):
        return []

    # 1. Filtern (Non-Equity/Derivate, Cash, Self-Ref, ungueltige ISIN, Nullgewicht).
    kept: list[tuple[dict, str, float]] = []
    for r in comp_rows:
        cc = r.get("compositionCharacteristics") if isinstance(r, dict) else None
        if not isinstance(cc, dict):
            cc = r if isinstance(r, dict) else None
        if not isinstance(cc, dict):
            continue
        if _is_non_equity_type(cc.get("type")):
            continue
        isin = str(cc.get("isin") or "").strip().upper()
        if not is_valid_isin(isin):
            continue
        if fund_isin and isin == fund_isin:  # Self-Reference (Fonds haelt sich selbst)
            continue
        w = cc.get("weight")
        if not isinstance(w, (int, float)) or w <= 0:
            continue
        kept.append((cc, isin, float(w)))

    if not kept:
        return []

    # 2. Skala erkennen: Bruch (Summe ~1) vs. Prozent (Summe ~100).
    total = sum(w for _, _, w in kept)
    fraction_scale = total <= 1.5

    # 3. Rows bauen (Dedupe auf holding_ticker; PK = etf_ticker + holding_ticker).
    out: dict[str, dict] = {}
    for cc, isin, w in kept:
        weight_pct = w * 100.0 if fraction_scale else w
        yf = bloomberg_composite_to_yf(cc.get("bbg"))
        country = cc.get("countryOfRisk") or cc.get("country") or None
        row = make_holding_row(
            etf_ticker=etf_ticker,
            weight_pct=weight_pct,
            isin=isin,
            yf_ticker=yf,
            name=cc.get("name"),
            country=country,
            sector=map_sector(cc.get("sector")),
            as_of=_parse_as_of(cc.get("date")),
        )
        if row:
            out[row["holding_ticker"]] = row
    return list(out.values())


async def fetch_amundi_holdings(etf_ticker: str, isin: str) -> list[dict] | None:
    """POST an Amundi + parse. None bei Fetch-Fehler/Non-200 (Caller -> error)."""
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.post(
                _API_URL,
                json=_build_body(isin),
                headers={
                    "User-Agent": BROWSER_UA,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
    except Exception as e:
        logger.warning("amundi_adapter: Fetch fehlgeschlagen fuer %s (%s): %s", etf_ticker, isin, e)
        return None
    if r.status_code != 200:
        logger.warning("amundi_adapter: HTTP %s fuer %s (%s)", r.status_code, etf_ticker, isin)
        return None
    try:
        payload = r.json()
    except Exception as e:
        logger.warning("amundi_adapter: JSON-Antwort ungueltig fuer %s: %s", etf_ticker, e)
        return None
    return parse_amundi_composition(payload, etf_ticker)


class AmundiAdapter(EtfAdapter):
    name = "Amundi"

    def matches(self, ref: EtfRef) -> bool:
        # Marke (Amundi oder ex-Lyxor) im Namen UND ISIN vorhanden (fuer den Body).
        return name_contains(ref, "amundi", "lyxor") and bool(ref.isin_norm)

    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        isin = ref.isin_norm
        if not isin:
            return None
        return await fetch_amundi_holdings(ref.ticker, isin)


register(AmundiAdapter())
