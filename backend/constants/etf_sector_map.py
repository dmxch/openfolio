"""Issuer-Sektorname -> OpenFolio-Sektor-Vokabular (yfinance-Stil).

Geteilt von allen ETF-Holdings-Adaptern (iShares, Xtrackers, SPDR, Amundi, ...).
Der persistierte `holding_sector` wird von concentration_service VOR
classify_tickers_bulk bevorzugt -> Sektor-Look-Through funktioniert auch fuer
EM-/Non-US-Holdings, die die US-zentrische ticker_industries-Tabelle nicht kennt.

Die meisten Issuer liefern GICS-Namen; einige (z.B. JPMorgan-Aggregat) ICB-Namen.
Beide Schemata sind hier auf dasselbe OpenFolio-Vokabular gemappt, damit ein
Portfolio mit ETFs verschiedener Anbieter EINE konsistente Sektor-Sicht ergibt.
"""
from __future__ import annotations

# Substring-freier Exact-Match auf den lowercase-getrimmten Quellnamen.
# GICS (11 Sektoren) + ICB-/Alt-Namen -> OpenFolio-Sektor (yfinance-Konvention).
SECTOR_NAME_MAP: dict[str, str] = {
    # --- Information Technology / Technology ---
    "information technology": "Technology",
    "technology": "Technology",
    "info technology": "Technology",
    # --- Financials ---
    "financials": "Financials",
    "financial services": "Financials",
    "financial": "Financials",
    "banks": "Financials",
    # --- Health Care ---
    "health care": "Healthcare",
    "healthcare": "Healthcare",
    "health": "Healthcare",
    # --- Consumer Discretionary / Cyclical ---
    "consumer discretionary": "Consumer Cyclical",
    "consumer cyclical": "Consumer Cyclical",
    "consumer discretion": "Consumer Cyclical",
    # --- Consumer Staples / Defensive ---
    "consumer staples": "Consumer Defensive",
    "consumer defensive": "Consumer Defensive",
    # --- Industrials ---
    "industrials": "Industrials",
    "industrial": "Industrials",
    "industrial goods & services": "Industrials",
    # --- Energy ---
    "energy": "Energy",
    "oil & gas": "Energy",
    # --- Materials / Basic Materials ---
    "materials": "Basic Materials",
    "basic materials": "Basic Materials",
    "basic resources": "Basic Materials",
    "chemicals": "Basic Materials",
    # --- Real Estate ---
    "real estate": "Real Estate",
    # --- Utilities ---
    "utilities": "Utilities",
    # --- Communication Services ---
    "communication": "Communication Services",
    "communication services": "Communication Services",
    "communications": "Communication Services",
    "telecommunication services": "Communication Services",
    "telecommunications": "Communication Services",
    "telecom": "Communication Services",
    "media": "Communication Services",
}


def map_sector(raw: str | None) -> str | None:
    """Issuer-Sektorname (GICS/ICB/Alt) -> OpenFolio-Sektor, None bei unbekannt.

    Unbekannt -> None (NICHT raten): concentration_service faellt dann pro Holding
    auf classify_tickers_bulk zurueck, statt einen falschen Sektor einzumischen.
    """
    if not raw:
        return None
    return SECTOR_NAME_MAP.get(raw.strip().lower())


# Rueckwaerts-kompatibler Alias (der iShares-Adapter/Test hiess das frueher so).
GICS_TO_OPENFOLIO_SECTOR = SECTOR_NAME_MAP
map_gics_sector = map_sector
