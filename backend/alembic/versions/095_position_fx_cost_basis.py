"""Position FX-vs-local cost basis: cost_basis_native + cost_basis_chf_at_fx.

Additive, display-only columns feeding the FX-vs-local return attribution. They
NEVER change cost_basis_chf (Invariante #1). Populated by the recalculate service
(_calculate_cost_basis_fx) from the transaction stream; left NULL for
manual/transaction-less positions (cash, pension, ...). Existing positions get
these filled on their next recalculate_all_positions run (kein SQL-Backfill, weil
der Weighted-Average-Sell-Reduktionspfad ordnungsabhaengig ist).

Revision ID: 095
Revises: 094
Create Date: 2026-07-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "095"
down_revision: Union[str, None] = "094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("cost_basis_native", sa.Numeric(20, 4), nullable=True),
    )
    op.add_column(
        "positions",
        sa.Column("cost_basis_chf_at_fx", sa.Numeric(14, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("positions", "cost_basis_chf_at_fx")
    op.drop_column("positions", "cost_basis_native")
