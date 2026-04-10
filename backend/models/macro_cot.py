"""CFTC Commitments of Traders snapshots (weekly).

Isolated macro/positioning data — NOT used in the equity screening score.
See SCOPE_SMART_MONEY_V4.md Block 1 for the full specification.
"""
import uuid
from datetime import datetime, date

from dateutils import utcnow
from sqlalchemy import BigInteger, Date, DateTime, String, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class MacroCotSnapshot(Base):
    """One weekly CFTC COT snapshot per instrument.

    Signed ``commercial_net`` / ``mm_net`` values are computed in Python on
    write (rather than via a PostgreSQL ``GENERATED ALWAYS AS`` column) so the
    same schema works under SQLite in the test environment.
    """
    __tablename__ = "macro_cot_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument: Mapped[str] = mapped_column(String(10), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)

    commercial_long: Mapped[int | None] = mapped_column(BigInteger)
    commercial_short: Mapped[int | None] = mapped_column(BigInteger)
    commercial_net: Mapped[int | None] = mapped_column(BigInteger)

    mm_long: Mapped[int | None] = mapped_column(BigInteger)
    mm_short: Mapped[int | None] = mapped_column(BigInteger)
    mm_net: Mapped[int | None] = mapped_column(BigInteger)

    oi_total: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("instrument", "report_date", name="uq_macro_cot_instrument_date"),
        Index("ix_macro_cot_instrument_date", "instrument", "report_date"),
    )
