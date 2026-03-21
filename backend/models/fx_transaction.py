import uuid
from datetime import date, datetime

from dateutils import utcnow
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class FxTransaction(Base):
    __tablename__ = "fx_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(20))
    currency_from: Mapped[str] = mapped_column(String(10), nullable=False)
    currency_to: Mapped[str] = mapped_column(String(10), nullable=False)
    amount_from: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    amount_to: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    derived_rate: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    import_batch_id: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
