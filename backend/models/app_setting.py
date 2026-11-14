import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import Boolean, Connection, DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


# Fallback, solange app_settings keinen registration_mode-Eintrag hat (Neuinstallation:
# create_all + stamp, Migration 021 laeuft dort nicht). Muss zu SECURITY.md passen.
DEFAULT_REGISTRATION_MODE = "invite_only"

# Einstellungen, die sonst nur eine Daten-Migration schreibt. Eine Neuinstallation
# baut das Schema per create_all und stempelt Alembic auf head (entrypoint.sh);
# die Migrationen laufen dort nie. Ohne die Zeile mfa_policy gilt "off", die
# README nennt aber "alle Konten" als Default (Migration 094).
FRESH_INSTALL_SETTINGS: dict[str, str] = {"mfa_policy": "all"}


def seed_fresh_install_settings(connection: Connection) -> None:
    """Insert the settings a fresh install would otherwise miss.

    Idempotent, and it never overwrites a value an admin has already set.
    """
    for key, value in FRESH_INSTALL_SETTINGS.items():
        connection.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value},
        )


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    used_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
