"""add position_type to positions

Revision ID: 009
Revises: 008
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"

def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns

def upgrade():
    if not _column_exists("positions", "position_type"):
        op.add_column("positions", sa.Column("position_type", sa.String(10), nullable=True))

def downgrade():
    if _column_exists("positions", "position_type"):
        op.drop_column("positions", "position_type")
