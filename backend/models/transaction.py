import enum
import uuid
from datetime import date, datetime

from dateutils import utcnow
import sqlalchemy as sa
from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class TransactionType(str, enum.Enum):
    buy = "buy"
    sell = "sell"
    dividend = "dividend"
    fee = "fee"
    tax = "tax"
    tax_refund = "tax_refund"
    delivery_in = "delivery_in"
    delivery_out = "delivery_out"
    deposit = "deposit"
    withdrawal = "withdrawal"
    capital_gain = "capital_gain"
    interest = "interest"
    fx_credit = "fx_credit"
    fx_debit = "fx_debit"
    fee_correction = "fee_correction"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        sa.Index("idx_transactions_position_id", "position_id"),
        sa.Index("idx_transactions_date", "date"),
        sa.Index("idx_transactions_position_date", "position_id", "date"),
        sa.Index("idx_transactions_position_type", "position_id", "type"),
        sa.Index("idx_transactions_user_id", "user_id"),
        sa.Index("idx_transactions_user_date", "user_id", sa.text("date DESC")),
        sa.Index("idx_transactions_user_type", "user_id", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    position_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    shares: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    price_per_share: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CHF")
    fx_rate_to_chf: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=1.0)
    fees_chf: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    taxes_chf: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_chf: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(String(50))
    isin: Mapped[str | None] = mapped_column(String(20))
    import_source: Mapped[str | None] = mapped_column(String(30))
    import_batch_id: Mapped[str | None] = mapped_column(String(50))
    raw_symbol: Mapped[str | None] = mapped_column(String(50))
    gross_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(14, 2))
    realized_pnl_chf: Mapped[float | None] = mapped_column(Numeric(14, 2))
    cost_basis_at_sale: Mapped[float | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
