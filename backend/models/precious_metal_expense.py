import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base
from models.property import Frequency


class PreciousMetalExpenseCategory(str, enum.Enum):
    storage = "storage"
    insurance = "insurance"
    other = "other"


class PreciousMetalExpense(Base):
    __tablename__ = "precious_metal_expenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metal_type: Mapped[str | None] = mapped_column(String(20))  # null = gilt fuer alle Metalle
    date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[PreciousMetalExpenseCategory] = mapped_column(
        Enum(PreciousMetalExpenseCategory, name="preciousmetalexpensecategory"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    frequency: Mapped[Frequency | None] = mapped_column(Enum(Frequency))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
