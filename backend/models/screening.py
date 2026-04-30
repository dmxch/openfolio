import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

# Use JSONB on PostgreSQL, fall back to generic JSON for SQLite (test env)
_JsonType = JSONB().with_variant(JSON(), "sqlite")


class ScreeningScan(Base):
    """Tracks a single screening scan run (progress + metadata)."""
    __tablename__ = "screening_scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    steps: Mapped[dict] = mapped_column(_JsonType, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, default=0)


class ScreeningResult(Base):
    """A single ticker result from a screening scan."""
    __tablename__ = "screening_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("screening_scans.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sector: Mapped[str | None] = mapped_column(String(100))
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals: Mapped[dict] = mapped_column(_JsonType, default=dict)
    price_usd: Mapped[float | None] = mapped_column(Float)
    industry_name: Mapped[str | None] = mapped_column(String(200))
    sector_momentum: Mapped[str | None] = mapped_column(String(20))
    sector_bonus: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
