import uuid
from datetime import date, datetime
from decimal import Decimal

from dateutils import utcnow
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class PendingOrder(Base):
    """Manuell gepflegte Limit-Order, die beim Broker liegt aber noch nicht
    ausgefuehrt wurde.

    ``status`` haelt den Roh-Zustand (``open|filled|cancelled``). Der Business-
    Status (``expired`` fuer abgelaufene GTD-Orders) wird im Service-Layer
    via ``compute_effective_status`` berechnet — kein Worker-Job noetig.
    """

    __tablename__ = "pending_orders"
    __table_args__ = (
        Index("idx_pending_orders_user_status", "user_id", "status"),
        Index("idx_pending_orders_user_ticker", "user_id", "ticker"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    shares: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    limit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    expiry_type: Mapped[str] = mapped_column(String(10), nullable=False, default="gtc")
    expiry_date: Mapped[date | None] = mapped_column(Date)
    broker: Mapped[str | None] = mapped_column(String(50))
    bucket_id_target: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("buckets.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    linked_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    notes_last_api_write_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    notes_last_api_token_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
