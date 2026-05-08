"""External-API Schreib-Scope, Watchlist-Notes-Metadaten und Audit-Log.

Ermoeglicht externen Clients (Claude Code via X-API-Key) das Schreiben von
Watchlist-Notizen und Preis-Alarmen. Vier DB-Aenderungen in einer Migration:

1. ``api_tokens.scopes`` (TEXT[]) — Default ``{read}``. Bestehende Tokens
   bleiben damit read-only; nur neu erstellte Tokens koennen den ``write``
   Scope erhalten.
2. ``watchlist.notes_last_api_write_at`` — Zeitstempel des letzten API-
   Notizen-Schreibvorgangs (NULL = manuell oder nie via API gesetzt).
3. ``watchlist.notes_last_api_token_name`` — Snapshot des Token-Namens (kein
   FK; Token kann widerrufen werden, der Anzeige-Name bleibt eingefroren).
4. Neue Tabelle ``api_write_log`` — Audit-Trail fuer externe Schreibzugriffe.
   ``content`` der Notiz wird **bewusst nie geloggt** (verschluesselt + DSGVO).

Revision ID: 058
Revises: 057
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID


revision: str = "058"
down_revision: Union[str, None] = "057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. api_tokens.scopes
    op.add_column(
        "api_tokens",
        sa.Column(
            "scopes",
            ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY['read']::text[]"),
        ),
    )

    # 2./3. watchlist Notiz-Metadaten
    op.add_column(
        "watchlist",
        sa.Column("notes_last_api_write_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "watchlist",
        sa.Column("notes_last_api_token_name", sa.String(100), nullable=True),
    )

    # 4. api_write_log
    op.create_table(
        "api_write_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "token_id",
            UUID(as_uuid=True),
            sa.ForeignKey("api_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(30), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("char_count_before", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("char_count_after", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("target_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('notes_replace','notes_append','notes_clear',"
            "'alert_create','alert_update','alert_delete')",
            name="ck_api_write_log_action",
        ),
    )
    op.create_index("ix_api_write_log_user_id", "api_write_log", ["user_id"])
    op.create_index("ix_api_write_log_created_at", "api_write_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_api_write_log_created_at", table_name="api_write_log")
    op.drop_index("ix_api_write_log_user_id", table_name="api_write_log")
    op.drop_table("api_write_log")

    op.drop_column("watchlist", "notes_last_api_token_name")
    op.drop_column("watchlist", "notes_last_api_write_at")

    op.drop_column("api_tokens", "scopes")
