"""add manual_resistance to positions and watchlist

Revision ID: 005
Revises: 004
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"


def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    if not _column_exists("positions", "manual_resistance"):
        op.add_column("positions", sa.Column("manual_resistance", sa.Numeric(12, 4), nullable=True))
    if not _column_exists("watchlist", "manual_resistance"):
        op.add_column("watchlist", sa.Column("manual_resistance", sa.Numeric(12, 4), nullable=True))


def downgrade():
    op.drop_column("positions", "manual_resistance")
    op.drop_column("watchlist", "manual_resistance")
