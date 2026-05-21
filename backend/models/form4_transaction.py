"""SEC Form 4 insider transactions for cluster-buy detection.

Lean-Probe-Scope: Universum = Portfolio + Watchlist (~50 Tickers). Filter
auf transaction_code ∈ {P, S} passiert im Service, nicht im Schema. CEO/CFO
Gewichtung erfolgt bei der Cluster-Aggregation (Service-seitig).

Decision-Impact-Probe — Kill-Gate 2026-08-15. Bei <3 Trade-Kippungen wird
das Feature entfernt und diese Tabelle wieder gedroppt.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from dateutils import utcnow
from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Form4Transaction(Base):
    """One row per insider transaction reported on SEC Form 4."""

    __tablename__ = "form4_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    insider_name: Mapped[str] = mapped_column(String(200), nullable=False)
    insider_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_code: Mapped[str] = mapped_column(String(2), nullable=False)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "filing_date",
            "insider_name",
            "transaction_date",
            "transaction_code",
            name="uq_form4_ticker_filing_insider_date_code",
        ),
        Index("ix_form4_ticker_txn_date", "ticker", "transaction_date"),
        Index("ix_form4_filing_date", "filing_date"),
    )
