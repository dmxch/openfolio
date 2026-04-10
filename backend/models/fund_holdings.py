"""13F-HR fund holdings snapshots for Q/Q diff analysis.

Each row represents one holding (ticker) of one fund (CIK) for one reporting
period (quarter end date). The ``UNIQUE(fund_cik, ticker, period_date)``
constraint allows storing multiple quarters side by side for diff computation.

See SCOPE_SMART_MONEY_V4.md Block 3.
"""
import uuid
from datetime import date, datetime

from dateutils import utcnow
from sqlalchemy import BigInteger, Date, DateTime, String, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FundHoldingsSnapshot(Base):
    """One 13F holding per fund per ticker per quarter."""

    __tablename__ = "fund_holdings_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fund_cik: Mapped[str] = mapped_column(String(15), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "fund_cik", "ticker", "period_date",
            name="uq_fund_holdings_cik_ticker_period",
        ),
        Index("ix_fund_holdings_ticker", "ticker"),
        Index("ix_fund_holdings_fund", "fund_cik", "filing_date"),
    )
