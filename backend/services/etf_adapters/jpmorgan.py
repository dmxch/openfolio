"""JPMorgan-Holdings-Adapter: keyloser JSON-Download -> normalisierte Holding-Rows.

J.P. Morgan Asset Management liefert die vollen Tages-Holdings ueber einen keylosen
JSON-Endpoint (`FundsMarketingHandler/product-data`). Die ISIN wird — die Falle des
Anbieters — in einem Query-Parameter uebergeben, der literal `cusip` heisst (traegt
aber die ISIN, nicht die CUSIP). Der Feed identifiziert jede Holding nativ ueber
`securityIsin` (~100 % fuer Equity) und `country` (Voll-Name); pro Holding gibt es
KEINEN Sektor (sector/industry sind fuer alle Zeilen NULL) -> holding_sector = None.

`securityTicker` ist ein LOKALER Boersen-Code mit mehrdeutigem Suffix (z.B. "000660",
"IBE/D", "8953") — daraus laesst sich kein zuverlaessiger yfinance-Ticker bauen. Wir
uebergeben deshalb NUR die ISIN an make_holding_row; die Ticker-Aufloesung uebernimmt
die Service-Anreicherung (OpenFIGI, _resolve.py) nachgelagert. So bleibt die Zeile
samt Land fuer den Laender-Look-Through erhalten.

Browser-User-Agent zwingend: der Edge (Akamai) 403t Default-UAs (vgl.
reference_cloudflare_ua_block).

Wichtig: `fundData.dailyHoldingsAll.data[]` ist die VOLLE Liste. `fundData.dailyHoldings.data`
ist nur die Top-10 — nicht verwenden. Die fund-level `emeaSectorBreakdown` (monatlich,
gemischtes GICS/ICB-Schema je Fonds) ist bewusst NICHT im Scope.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

import httpx

from constants.etf_sector_map import map_sector
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

_PRODUCT_DATA_URL = "https://am.jpmorgan.com/FundsMarketingHandler/product-data"

# securityType-Schluesselwoerter, die eine Nicht-Equity-/Derivate-Zeile markieren.
# JPM haengt Qualifier an ("Warrant - Equity", "Futures", "Right"), darum Substring-
# statt Exact-Match. Bewusst so gewaehlt, dass sie KEINE echte Equity-Type treffen
# ("Common Stock", "Depository Receipt - American", "Fund - Real Estate Investment
# Trust" enthalten keines dieser Wortstuecke).
_NON_EQUITY_TYPE_KEYWORDS = (
    "cash",
    "future",
    "forward",
    "warrant",
    "right",
    "option",
    "swap",
    "money market",
)

# Namens-Suffix, den JPM an securityDescription haengt (Handelswaehrung), z.B.
# "SK HYNIX INC /KRW/" -> reines Display-Artefakt, fuer die UI abgeschnitten.
_CCY_SUFFIX_RE = re.compile(r"\s*/[A-Z]{2,4}/\s*$")


def _parse_iso_date(raw: str | None) -> date | None:
    """ISO-Datum ('YYYY-MM-DD') -> date, None bei fehlend/unparsbar."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except (ValueError, TypeError):
        return None


def _is_non_equity_type(security_type: str | None) -> bool:
    """True fuer Cash/Derivate/Nicht-Equity-Zeilen (Substring auf securityType)."""
    s = (security_type or "").lower()
    return any(kw in s for kw in _NON_EQUITY_TYPE_KEYWORDS)


def _clean_name(raw: str | None) -> str | None:
    """securityDescription vom angehaengten Waehrungs-Tag befreien."""
    if not raw:
        return None
    return _CCY_SUFFIX_RE.sub("", raw).strip() or None


def parse_jpmorgan_holdings(
    payload: str | bytes | dict,
    etf_ticker: str,
    fund_isin: str | None = None,
) -> list[dict]:
    """JSON-Payload -> normalisierte Holding-Rows (nur Equity, ISIN als Key).

    Reine Funktion (kein I/O) — voll unit-testbar. `payload` ist die volle Antwort
    (dict ODER str/bytes JSON). Gelesen wird ausschliesslich
    `fundData.dailyHoldingsAll.data[]` (Voll-Liste; dailyHoldings = nur Top-10).

    Uebersprungen werden: Cash/Derivate/Nicht-Equity (securityType), Zeilen ohne
    gueltige ISIN (der Feed hat keinen brauchbaren yf-Ticker -> ISIN ist der Key),
    Zeilen mit Gewicht <= 0 und die Selbst-Referenz (holding-ISIN == fund_isin).

    holding_sector bleibt None: der Feed liefert pro Holding keinen Sektor. `country`
    ist nativ (Voll-Name). `securityTicker` wird bewusst NICHT zu einem yf-Ticker
    gebaut (mehrdeutiges Boersen-Suffix); die Aufloesung laeuft nachgelagert ueber die
    Service-Anreicherung via ISIN.
    """
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            logger.warning("jpmorgan_adapter: JSON nicht parsbar fuer %s", etf_ticker)
            return []
    if not isinstance(payload, dict):
        return []

    fund_data = payload.get("fundData") or {}
    daily_all = fund_data.get("dailyHoldingsAll") or {}
    data = daily_all.get("data") or []
    if not isinstance(data, list) or not data:
        return []

    fund_isin_n = fund_isin.strip().upper() if fund_isin else None
    # Snapshot-Stichtag: Container-effectiveDate bevorzugt, sonst erster Zeilen-navDate.
    as_of = _parse_iso_date(daily_all.get("effectiveDate"))
    if as_of is None:
        as_of = _parse_iso_date(data[0].get("navDate") if isinstance(data[0], dict) else None)

    out: dict[str, dict] = {}
    for h in data:
        if not isinstance(h, dict):
            continue
        if _is_non_equity_type(h.get("securityType")):
            continue
        isin = (h.get("securityIsin") or "").strip().upper()
        if not is_valid_isin(isin):
            # Cash traegt keine ISIN, Futures nur einen Kontacode -> nicht kellbar.
            continue
        if fund_isin_n and isin == fund_isin_n:
            continue  # Selbst-Referenz
        row = make_holding_row(
            etf_ticker=etf_ticker,
            weight_pct=h.get("marketValuePercent"),  # bereits in % (Summe ~100)
            isin=isin,                               # KEIN yf_ticker: Suffix mehrdeutig
            name=_clean_name(h.get("securityDescription")),
            country=h.get("country"),                # nativer Voll-Name
            sector=map_sector(h.get("sector")),      # heute None (Feed liefert keinen)
            as_of=as_of,
        )
        if row is None:                              # Gewicht <= 0 / ungueltig
            continue
        out[row["holding_ticker"]] = row             # Dedup ueber ISIN-Key
    return list(out.values())


async def fetch_jpmorgan_holdings(ref: EtfRef) -> list[dict] | None:
    """Lade + parse JPMorgan-Holdings. None bei Fetch-Fehler (Caller -> error)."""
    isin = ref.isin_norm
    if not isin:
        return None
    params = {
        "cusip": isin,          # Anbieter-Falle: Param heisst 'cusip', traegt aber die ISIN
        "country": "ch",
        "role": "adv",
        "language": "en",
        "userLoggedIn": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(
                _PRODUCT_DATA_URL, params=params, headers={"User-Agent": BROWSER_UA}
            )
    except Exception as e:
        logger.warning("jpmorgan_adapter: Fetch fehlgeschlagen fuer %s (%s): %s",
                       ref.ticker, isin, e)
        return None
    if r.status_code != 200:
        logger.warning("jpmorgan_adapter: HTTP %s fuer %s (%s)", r.status_code, ref.ticker, isin)
        return None
    return parse_jpmorgan_holdings(r.text, ref.ticker, fund_isin=isin)


class JPMorganAdapter(EtfAdapter):
    name = "JPMorgan"

    def matches(self, ref: EtfRef) -> bool:
        # Marke im Fondsnamen UND ISIN vorhanden (die ISIN baut die URL). ISIN-Pflicht
        # verhindert Fehl-Matches auf fremde Fonds mit aehnlichem Namen.
        return bool(ref.isin_norm) and name_contains(
            ref, "jpmorgan", "jpm ", "betabuilders", "j.p. morgan"
        )

    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        return await fetch_jpmorgan_holdings(ref)


register(JPMorganAdapter())
