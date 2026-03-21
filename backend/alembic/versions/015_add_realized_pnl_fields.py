"""add realized P&L fields to transactions and portfolio_snapshots table

Revision ID: 015
Revises: 014
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Realized P&L fields on sell transactions (idempotent)
    for col_name, col_type in [
        ("realized_pnl", "NUMERIC(14,2)"),
        ("realized_pnl_chf", "NUMERIC(14,2)"),
        ("cost_basis_at_sale", "NUMERIC(14,2)"),
    ]:
        conn.execute(sa.text(
            f"ALTER TABLE transactions ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
        ))

    # Portfolio snapshots for TTWROR (idempotent)
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            date DATE NOT NULL,
            total_value_chf NUMERIC(14,2) NOT NULL DEFAULT 0,
            cash_chf NUMERIC(14,2) NOT NULL DEFAULT 0,
            net_cash_flow_chf NUMERIC(14,2) NOT NULL DEFAULT 0,
            CONSTRAINT uq_snapshot_user_date UNIQUE (user_id, date)
        )
    """))


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_column("transactions", "cost_basis_at_sale")
    op.drop_column("transactions", "realized_pnl_chf")
    op.drop_column("transactions", "realized_pnl")
