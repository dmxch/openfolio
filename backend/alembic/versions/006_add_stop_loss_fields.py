"""add stop-loss tracking fields to positions

Revision ID: 006
Revises: 005
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"


def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    if not _column_exists("positions", "stop_loss_price"):
        op.add_column("positions", sa.Column("stop_loss_price", sa.Numeric(14, 4), nullable=True))
    if not _column_exists("positions", "stop_loss_confirmed_at_broker"):
        op.add_column("positions", sa.Column("stop_loss_confirmed_at_broker", sa.Boolean(), server_default="false", nullable=False))
    if not _column_exists("positions", "stop_loss_updated_at"):
        op.add_column("positions", sa.Column("stop_loss_updated_at", sa.DateTime(), nullable=True))
    if not _column_exists("positions", "stop_loss_method"):
        op.add_column("positions", sa.Column("stop_loss_method", sa.String(30), nullable=True))


def downgrade():
    op.drop_column("positions", "stop_loss_method")
    op.drop_column("positions", "stop_loss_updated_at")
    op.drop_column("positions", "stop_loss_confirmed_at_broker")
    op.drop_column("positions", "stop_loss_price")
