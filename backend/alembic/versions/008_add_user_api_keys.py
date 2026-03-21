"""add anthropic_api_key to user_settings

Revision ID: 008
Revises: 007
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"


def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    if not _column_exists("user_settings", "anthropic_api_key"):
        op.add_column("user_settings", sa.Column("anthropic_api_key", sa.String(500), nullable=True))


def downgrade():
    if _column_exists("user_settings", "anthropic_api_key"):
        op.drop_column("user_settings", "anthropic_api_key")
