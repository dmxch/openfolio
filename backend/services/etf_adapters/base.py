"""Basis-Vertrag fuer ETF-Holdings-Adapter (Issuer-spezifische Look-Through-Quellen).

Ein Adapter uebersetzt den keylosen Holdings-Kanal EINES Anbieters (iShares CSV,
Xtrackers JSON, SPDR XLSX, ...) in eine Liste normalisierter Holding-Rows, die
etf_holdings_service.refresh_etf_holdings unveraendert upserted. Der Consumer
(concentration_service) ist quellen-agnostisch: er liest holding_country /
holding_sector (Issuer-nativ bevorzugt) + holding_ticker (Reverse-Overlap).

Row-Vertrag (dict) — EXAKT diese Keys, so erwartet der UPSERT sie:
    etf_ticker      str   (Position-Ticker, z.B. "SWDA.L")
    holding_ticker  str   (aufgeloester yf-Ticker ODER ISIN als stabiler Fallback-Key)
    holding_name    str|None  (<=200)
    weight_pct      float (>0)
    as_of           date|None (Quelle-Stichtag; None => UI zeigt "Stichtag unbekannt")
    holding_isin    str|None  (<=20)
    holding_country str|None  (Laender-NAME wie von der Quelle, <=64)
    holding_sector  str|None  (OpenFolio-Sektor via constants.etf_sector_map, <=40)

`updated_at` setzt der Service. Der PK ist (etf_ticker, holding_ticker) — deshalb
MUSS holding_ticker gefuellt sein; make_holding_row nimmt dafuer ISIN als Fallback.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)

# Gemeinsamer Browser-UA — mehrere Issuer-Edges (Akamai) 403en Default-UAs.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Gueltige ISIN: 2 Buchstaben Laendercode + 9 alphanumerisch + 1 Pruefziffer.
import re

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def is_valid_isin(value: str | None) -> bool:
    return bool(value) and bool(_ISIN_RE.match(value.strip().upper()))


@dataclass(frozen=True)
class EtfRef:
    """Schlanke ETF-Referenz, die ein Adapter zum Routing/Fetch braucht.

    Entkoppelt die Adapter vom SQLAlchemy-Position-Model (unit-testbar ohne DB).
    """
    ticker: str
    isin: str | None
    name: str | None

    @property
    def isin_norm(self) -> str | None:
        return self.isin.strip().upper() if self.isin else None

    @property
    def name_lc(self) -> str:
        return (self.name or "").lower()


def name_contains(ref: EtfRef, *needles: str) -> bool:
    """True wenn der Fondsname eine der Marken-Zeichenketten enthaelt (case-insensitive).

    ETF-Namen tragen fast immer die Anbieter-Marke ("iShares Core...", "Xtrackers...",
    "SPDR...", "Amundi...") — der robusteste keylose Issuer-Detektor.
    """
    n = ref.name_lc
    return any(needle.lower() in n for needle in needles)


def make_holding_row(
    *,
    etf_ticker: str,
    weight_pct: float,
    isin: str | None = None,
    yf_ticker: str | None = None,
    name: str | None = None,
    country: str | None = None,
    sector: str | None = None,
    as_of: date | None = None,
) -> dict | None:
    """Baue eine normalisierte Holding-Row oder None (unbrauchbar -> Caller skippt).

    holding_ticker = aufgeloester yf-Ticker, sonst die (validierte) ISIN als stabiler
    Key — so ueberlebt die Zeile samt Land/Sektor den Laender-/Sektor-Look-Through auch
    ohne Ticker-Aufloesung (sie matcht dann nur nicht im Overlap). Ohne beides: None.
    """
    if weight_pct is None or weight_pct <= 0:
        return None
    isin_n = isin.strip().upper() if isin else None
    if isin_n and not is_valid_isin(isin_n):
        isin_n = None
    key = (yf_ticker.strip().upper() if yf_ticker else None) or isin_n
    if not key:
        return None
    return {
        "etf_ticker": etf_ticker,
        "holding_ticker": key[:30],
        "holding_name": (name or "")[:200] or None,
        "weight_pct": float(weight_pct),
        "as_of": as_of,
        "holding_isin": isin_n[:20] if isin_n else None,
        "holding_country": (country.strip()[:64] or None) if country else None,
        "holding_sector": sector,  # bereits aufs OpenFolio-Vokabular gemappt (<=40)
    }


class EtfAdapter(ABC):
    """Ein Issuer-Holdings-Adapter. Selbst-registrierend beim Import (siehe __init__)."""

    #: Kurzlabel fuer Logs/Diagnose ("iShares", "Xtrackers", ...).
    name: str = "base"

    @abstractmethod
    def matches(self, ref: EtfRef) -> bool:
        """True, wenn dieser Adapter die Holdings des ETFs liefern kann."""

    @abstractmethod
    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        """Hole+parse die Holdings. Liste von make_holding_row-Dicts; [] = keine
        verwertbaren Zeilen; None = Fetch-Fehler (Caller loggt error, kein Delete)."""


# --- Registry -------------------------------------------------------------
REGISTRY: list[EtfAdapter] = []


def register(adapter: EtfAdapter) -> EtfAdapter:
    """Adapter global registrieren (Aufruf am Modul-Ende jedes Adapters)."""
    REGISTRY.append(adapter)
    return adapter


def get_adapter(ref: EtfRef) -> EtfAdapter | None:
    """Ersten passenden Adapter fuer diesen ETF finden (Registrierungsreihenfolge)."""
    for adapter in REGISTRY:
        try:
            if adapter.matches(ref):
                return adapter
        except Exception:
            logger.exception("etf_adapter matches() failed for %s", adapter.name)
    return None
