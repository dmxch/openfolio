from datetime import datetime

from dateutils import utcnow
from sqlalchemy import DateTime, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class MacroIndicatorCache(Base):
    __tablename__ = "macro_indicator_cache"

    indicator: Mapped[str] = mapped_column(String(30), primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric(14, 4))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
