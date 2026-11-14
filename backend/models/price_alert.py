import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    __table_args__ = (
        # Der Minutenjob check_price_alerts liest nur offene Alarme. Ausgelöste
        # Zeilen bleiben liegen; der partielle Index hält sie aus dem Scan heraus.
        # Postgres nutzt ihn für «== True» / «== False», nicht für «.is_(True)»
        # (IS TRUE): daraus leitet der Planer das Indexprädikat nicht ab.
        Index(
            "ix_price_alerts_open",
            "ticker",
            postgresql_where=text("is_active AND NOT is_triggered"),
            sqlite_where=text("is_active AND NOT is_triggered"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)  # price_above, price_below, pct_change_day
    target_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime)
    trigger_price: Mapped[float | None] = mapped_column(Numeric(14, 4))
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
