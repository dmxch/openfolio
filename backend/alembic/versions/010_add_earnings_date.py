"""add next_earnings_date to positions

Revision ID: 010
Revises: 009
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"

def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns

def upgrade():
    if not _column_exists("positions", "next_earnings_date"):
        op.add_column("positions", sa.Column("next_earnings_date", sa.DateTime, nullable=True))

def downgrade():
    if _column_exists("positions", "next_earnings_date"):
        op.drop_column("positions", "next_earnings_date")
