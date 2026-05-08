"""Pending-Dividend-Model.

Represents a yfinance-detected dividend Ex-Date for a user position that has
not yet been recorded as a `dividend` Transaction. The Worker creates one row
per (user_id, position_id, ex_date) tuple; the user confirms (creates a
matching Transaction) or dismisses each row via the Dashboard widget.

Status (`String(20)`, not Postgres-Enum — R-A1 of plan, less Alembic friction):
    - ``pending``    — still needs user action (default, shown in widget)
    - ``confirmed``  — Transaction created, ``matched_transaction_id`` is set
    - ``dismissed``  — user explicitly ignored, Worker no longer recreates it
"""

import uuid
from datetime import date as _date_type, datetime

from dateutils import utcnow
import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


# Application-side status constants. The DB has a CHECK constraint enforcing
# the same values; using a String column avoids Alembic enum migration pain.
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_DISMISSED = "dismissed"
ALLOWED_STATUSES = (STATUS_PENDING, STATUS_CONFIRMED, STATUS_DISMISSED)


class PendingDividend(Base):
    __tablename__ = "pending_dividends"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "position_id",
            "ex_date",
            name="uq_pending_dividend_user_position_exdate",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'dismissed')",
            name="ck_pending_dividend_status",
        ),
        Index("idx_pending_dividends_user_status", "user_id", "status"),
        Index("idx_pending_dividends_position", "position_id"),
        Index(
            "idx_pending_dividends_matched_txn",
            "matched_transaction_id",
            postgresql_where=sa.text("matched_transaction_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    ex_date: Mapped[_date_type] = mapped_column(Date, nullable=False)
    dividend_per_share: Mapped[float] = mapped_column(Numeric(14, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    shares_at_ex_date: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    expected_gross_chf: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
    )
    matched_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Plain TEXT (Dismiss-Reason). Not encrypted — it is non-sensitive metadata.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
