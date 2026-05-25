import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base
from models.position import AssetType


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Asset-Klasse — nullable, weil Legacy-Rows + manuell hinzugefuegte Tickers
    # ohne Klassifikation existieren. NULL = "unbekannt, vermutlich Equity".
    # Wird beim Anlegen via classify_ticker_format() gesetzt (heute nur Crypto-
    # Pairs erkannt; ETF-Detection braucht Netzwerk → spaeter).
    type: Mapped[AssetType | None] = mapped_column(Enum(AssetType), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100))
    manual_resistance: Mapped[float | None] = mapped_column(Numeric(12, 4))
    notes: Mapped[str | None] = mapped_column(Text)
    notes_last_api_write_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes_last_api_token_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
