import uuid
from datetime import date, datetime

from dateutils import utcnow
from sqlalchemy import Date, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

# JSONB auf Postgres, generisches JSON als SQLite-Fallback (Test-Env).
_JsonType = JSONB().with_variant(JSON(), "sqlite")


class Report(Base):
    """Ein gerenderter Markdown-Brief im Report-Vault.

    Quelle ist der Claude-Finance-Workspace, der die `.md`-Briefe via
    `POST /api/v1/reports` (Token, write-Scope) hochlaedt. User-scoped
    (Multi-User). `source_path` ist der natuerliche Upsert-Key (ein Eintrag
    pro Quelldatei und User); `content_hash` kurzschliesst unveraenderte
    Re-Pushes. `tags` ist user-editierbar aus dem UI.
    """
    __tablename__ = "reports"
    __table_args__ = (
        # Ein Report pro Quelldatei und User — Upsert-Ziel des Sync-Skripts.
        # NULL source_path (Ad-hoc-Push) ist erlaubt; NULLs gelten als distinct.
        UniqueConstraint("user_id", "source_path", name="uq_report_user_source_path"),
        Index("ix_reports_user_date", "user_id", "report_date"),
        Index("ix_reports_user_category", "user_id", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    report_date: Mapped[date | None] = mapped_column(Date)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(_JsonType, default=list)
    source: Mapped[str | None] = mapped_column(String(100))
    source_path: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # Soft-Delete/Archiv: NULL = aktiv, gesetzt = archiviert (eigene Vault-Ansicht).
    # Reversibel (unarchive setzt zurueck auf NULL); hartes DELETE bleibt daneben.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
