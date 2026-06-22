"""Persistierte EPS-Zeitreihe (Quarterly Reported EPS) pro Ticker.

Jede Row = ein Quartal eines Tickers. Universe-global (kein user_id).
Quelle: Finnhub stock/metric (primaer) oder yfinance (Fallback fuer Ticker
ohne Finnhub-EPS-Serie, v.a. Finanzsektor).

Additives Feature (EPS-Scanner) — beruehrt KEINE Performance-/Renditeberechnung.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class EpsQuarterly(Base):
    """Ein Quartal Reported-EPS eines Tickers."""

    __tablename__ = "eps_quarterly"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    # period_end = Quartalsenddatum (YYYY-MM-DD), wie vom Provider geliefert.
    # Achtung: Unternehmen haben unterschiedliche Fiskalquartale.
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    eps: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # source: "finnhub" | "yfinance"
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "ticker", "period_end", name="uq_eps_quarterly_ticker_period"
        ),
        Index("ix_eps_quarterly_ticker_period", "ticker", "period_end"),
        Index("ix_eps_quarterly_fetched", "ticker", "fetched_at"),
    )
