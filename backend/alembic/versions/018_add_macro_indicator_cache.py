"""add macro_indicator_cache table

Revision ID: 018
Revises: 017
Create Date: 2026-03-11
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    if "macro_indicator_cache" not in inspector.get_table_names():
        op.create_table(
            "macro_indicator_cache",
            sa.Column("indicator", sa.String(30), primary_key=True),
            sa.Column("value", sa.Numeric(14, 4), nullable=True),
            sa.Column("status", sa.String(10), nullable=False, server_default="unknown"),
            sa.Column("raw_data", sa.JSON, nullable=True),
            sa.Column("fetched_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("macro_indicator_cache")
