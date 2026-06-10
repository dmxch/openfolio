import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class SmtpConfig(Base):
    __tablename__ = "smtp_config"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str | None] = mapped_column(String(30))
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=587)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet bläht ~×1.4 auf — verschlüsselte Felder immer Text, nie String(N)
    # (Projektregel; Review 2026-06-10, M7 + Migration 082).
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    from_email: Mapped[str | None] = mapped_column(String(255))
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
