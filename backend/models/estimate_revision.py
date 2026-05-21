"""Analyst-Estimate-Snapshots fuer 30/60/90d-Revisions-Tracking.

Taegliche Konsens-Snapshots pro Ticker. Service berechnet Deltas on-demand
aus der Snapshot-Historie. Quelle: FMP /analyst-estimates (per-User Key
aus user_settings).

Decision-Impact-Probe — Kill-Gate 2026-08-15.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from dateutils import utcnow
from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class EstimateRevision(Base):
    """One snapshot of consensus EPS/Revenue estimates per ticker per day."""

    __tablename__ = "estimate_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    eps_fy1: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    eps_fy2: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    revenue_fy1: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    num_analysts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "snapshot_date",
            name="uq_estimate_revisions_ticker_snapshot",
        ),
        Index("ix_estimate_revisions_ticker_date", "ticker", "snapshot_date"),
    )
