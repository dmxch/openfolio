"""Audit-Log fuer Schreibzugriffe ueber die externe API.

Loggt **Metadaten** zu jedem Notes/Alert-Schreibvorgang via X-API-Key:
Token, User, Ticker, Action und Zeichen-Counts vor/nach (bei Notes-Aktionen).
Der Inhalt der Notiz wird **bewusst nie geloggt** — er ist verschluesselt
gespeichert, und das Audit-Log soll nicht zum Klartext-Leak werden.
"""

import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ApiWriteLog(Base):
    __tablename__ = "api_write_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    char_count_before: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
