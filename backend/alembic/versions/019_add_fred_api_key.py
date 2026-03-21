"""add fred_api_key to user_settings

Revision ID: 019
Revises: 018
Create Date: 2026-03-11
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("user_settings")]
    if "fred_api_key" not in columns:
        op.add_column("user_settings", sa.Column("fred_api_key", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("user_settings", "fred_api_key")
