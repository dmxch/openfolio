"""Add ntfy_config table and notify_push column to alert_preferences.

ntfy push notification configuration is stored per user with optional
encrypted access token. The notify_push flag in alert_preferences allows
per-category opt-in (default false to prevent flood after setup).

Revision ID: 060
Revises: 059
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ntfy_config",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("server_url", sa.String(500), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("access_token_encrypted", sa.String(500), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.add_column(
        "alert_preferences",
        sa.Column(
            "notify_push",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("alert_preferences", "notify_push")
    op.drop_table("ntfy_config")
