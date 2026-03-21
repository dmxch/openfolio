"""extend transaction types and add fees/taxes columns

Revision ID: 002
Revises: 001
Create Date: 2026-03-05
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("fees_chf", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("transactions", sa.Column("taxes_chf", sa.Numeric(14, 2), nullable=False, server_default="0"))
    # Extend enum with new types
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'tax'")
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'tax_refund'")
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'delivery_in'")
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'delivery_out'")


def downgrade() -> None:
    op.drop_column("transactions", "taxes_chf")
    op.drop_column("transactions", "fees_chf")
