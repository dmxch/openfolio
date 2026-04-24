"""Daily snapshots of TradingView industry-rotation performance.

Each row is one industry at one scrape time. ``UNIQUE(slug, scraped_at)``
allows multiple historical snapshots side-by-side for trend analysis and
fallback when a scrape fails (old snapshot stays available).

Source: TradingView Scanner API (symbols.query.types=["industry"]).
"""
import uuid
from datetime import datetime
from decimal import Decimal

from dateutils import utcnow
from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class MarketIndustry(Base):
    """One TradingView industry row at one scrape time."""

    __tablename__ = "market_industries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_1w: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_1m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_3m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_6m: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_ytd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_1y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_5y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    perf_10y: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(22, 2), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(22, 2), nullable=True)
    value_traded: Mapped[Decimal | None] = mapped_column(Numeric(22, 2), nullable=True)
    rvol_20d: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("slug", "scraped_at", name="uq_market_industries_slug_scraped"),
        Index("ix_market_industries_scraped_at", "scraped_at"),
    )
