"""ETF-Holdings-Mapping aus FMP — globale Tabelle (nicht user-spezifisch).

Ein ETF-Holding ist eine universelle Tatsache (NVDA in OEF mit 7% Gewicht
gilt für jeden User), daher pro (etf_ticker, holding_ticker) ein Eintrag,
unabhängig vom User. UPSERT-Semantik: wöchentlich refreshen, alte Holdings
werden überschrieben.

Phase 1 enthält nur US-ETFs (FMP-Coverage). Non-US (`.SW`, `.L`, `.TO`)
werden vom Refresh-Service mit Log-Info geskipped.

Composite-PK auf (etf_ticker, holding_ticker) statt UUID, weil das Mapping
inhärent ein Komposit ist und Lookups beide Felder brauchen. Index auf
`holding_ticker` für Reverse-Lookup ("welche ETFs enthalten NVDA?") —
genau der Pfad den der Core-Overlap-Banner pro StockDetail-Aufruf macht.
"""
from datetime import date, datetime

from dateutils import utcnow
from sqlalchemy import Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class EtfHolding(Base):
    """Eine Holding-Position eines ETFs zu einem bestimmten Stichtag."""

    __tablename__ = "etf_holdings"

    etf_ticker: Mapped[str] = mapped_column(String(30), primary_key=True)
    holding_ticker: Mapped[str] = mapped_column(String(30), primary_key=True)

    holding_name: Mapped[str | None] = mapped_column(String(200))
    weight_pct: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)

    # Quelle-native ISIN/Land (Issuer-CSV liefert sie mit; FMP-US-Holdings = None).
    # holding_country = Laender-NAME wie von der Quelle geliefert (iShares "Location",
    # z.B. "Taiwan") — traegt den Laender-Look-Through unabhaengig von der
    # Ticker-Resolution. holding_isin = stabiler Identitaets-Anker wo vorhanden.
    holding_isin: Mapped[str | None] = mapped_column(String(20))
    holding_country: Mapped[str | None] = mapped_column(String(64))
    # Issuer-nativer Sektor, gemappt aufs OpenFolio-Vokabular (iShares "Sector"/GICS).
    # Wird von concentration_service vor classify_tickers_bulk bevorzugt; None bei
    # FMP-US-Holdings (fallen auf classify zurueck).
    holding_sector: Mapped[str | None] = mapped_column(String(40))

    # Stichtag laut FMP. None wenn FMP keinen liefert — UI zeigt dann
    # "Stichtag unbekannt", NICHT updated_at (das wäre Falsch-Sicherheit).
    as_of: Mapped[date | None] = mapped_column(Date)

    # Pull-Zeitpunkt — Internal-Diagnose, NICHT user-facing.
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        # Reverse-Lookup: für einen Aktien-Ticker alle ETFs finden, die ihn halten
        Index("ix_etf_holdings_holding_ticker", "holding_ticker"),
    )
