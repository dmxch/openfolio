"""External API token model — for /api/v1/external/* read-only access."""

import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


# PostgreSQL has native TEXT[]; SQLite (used in tests) has no ARRAY type and
# falls back to JSON-encoded text. The migration creates a TEXT[] column on
# Postgres, which round-trips through SQLAlchemy's ARRAY transparently.
_ScopesColumn = ARRAY(String).with_variant(JSON(), "sqlite")


class ApiToken(Base):
    """A user-generated API token for external API access.

    The plaintext token is only ever returned ONCE at creation time.
    Subsequent verification uses sha256(plaintext) lookup against `token_hash`.

    ``scopes`` controls what the token may do. Default ``["read"]`` keeps
    backwards-compatibility for tokens created before scopes existed.
    The ``write`` scope grants permission to set watchlist notes and to
    create/update/delete price alerts via the external API.
    """

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(_ScopesColumn, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
