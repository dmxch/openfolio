import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


GRAMS_PER_TROY_OZ = 31.1035


class PreciousMetalItem(Base):
    __tablename__ = "precious_metal_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="SET NULL"))

    metal_type: Mapped[str] = mapped_column(String(20), nullable=False)  # gold, silver, platinum, palladium
    form: Mapped[str] = mapped_column(String(20), nullable=False)  # bar, coin, other
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    weight_grams: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(Text)
    fineness: Mapped[str | None] = mapped_column(String(10))  # 999.9, 995, 900

    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    purchase_price_chf: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    storage_location: Mapped[str | None] = mapped_column(Text)

    is_sold: Mapped[bool] = mapped_column(Boolean, default=False)
    sold_date: Mapped[date | None] = mapped_column(Date)
    sold_price_chf: Mapped[float | None] = mapped_column(Numeric(14, 2))

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    @property
    def weight_oz(self) -> float:
        return float(self.weight_grams) / GRAMS_PER_TROY_OZ
