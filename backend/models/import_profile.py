import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ImportProfile(Base):
    __tablename__ = "import_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    delimiter: Mapped[str] = mapped_column(String(5), default=",")
    encoding: Mapped[str] = mapped_column(String(20), default="utf-8")
    date_format: Mapped[str] = mapped_column(String(30), default="%d-%m-%Y %H:%M:%S")
    decimal_separator: Mapped[str] = mapped_column(String(1), default=".")
    column_mapping: Mapped[dict] = mapped_column(JSON, nullable=False)
    type_mapping: Mapped[dict] = mapped_column(JSON, nullable=False)
    has_forex_pairs: Mapped[bool] = mapped_column(Boolean, default=False)
    aggregate_partial_fills: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
