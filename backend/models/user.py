import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(Text)  # AES-256 encrypted
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(45))


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), default="CHF")
    broker: Mapped[str] = mapped_column(String(50), default="swissquote")
    default_stop_loss_method: Mapped[str] = mapped_column(String(20), default="trailing_pct")
    stop_loss_review_distance_pct: Mapped[float] = mapped_column(default=15.0)
    stop_loss_review_max_days: Mapped[int] = mapped_column(default=14)
    number_format: Mapped[str] = mapped_column(String(5), default="ch")
    date_format: Mapped[str] = mapped_column(String(10), default="dd.mm.yyyy")
    fred_api_key: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted

    # Alert settings
    alert_stop_missing: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_stop_unconfirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_stop_proximity: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_stop_review: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_ma_critical: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_ma_warning: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_position_limit: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_sector_limit: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_loss: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_market_climate: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_vix: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_earnings: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_allocation: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_position_type_missing: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_satellite_loss_pct: Mapped[float] = mapped_column(default=-15.0)
    alert_core_loss_pct: Mapped[float] = mapped_column(default=-25.0)
    alert_stop_proximity_pct: Mapped[float] = mapped_column(default=3.0)
    last_email_digest_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Newsletter
    newsletter_frequency: Mapped[str] = mapped_column(String(10), default="off")
    newsletter_scope: Mapped[str] = mapped_column(String(20), default="all")

    # AI Provider
    ai_provider: Mapped[str | None] = mapped_column(String(20))
    ai_model: Mapped[str | None] = mapped_column(String(50))
    ai_api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    ai_ollama_url: Mapped[str | None] = mapped_column(String(255))

    # Onboarding
    onboarding_tour_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_checklist_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_steps_json: Mapped[str | None] = mapped_column(Text)  # JSON for manual step tracking
