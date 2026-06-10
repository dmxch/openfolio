"""NtfyConfig model — per-user ntfy push notification configuration."""
import uuid
from datetime import datetime

from dateutils import utcnow_aware
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class NtfyConfig(Base):
    __tablename__ = "ntfy_config"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    server_url: Mapped[str] = mapped_column(String(500), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    # NULL = kein Auth (public ntfy.sh mit privatem Topic).
    # Fernet bläht ~×1.4 auf — verschlüsselte Felder immer Text, nie String(N)
    # (Projektregel; Review 2026-06-10, M7 + Migration 082).
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Migration 060 legte die Spalten als TIMESTAMPTZ an — das Model muss
    # timezone=True deklarieren und aware Defaults liefern, sonst mischen
    # sich naive und aware datetimes (Review 2026-06-10, ntfy-tz).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow_aware, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow_aware, onupdate=utcnow_aware, nullable=False
    )
