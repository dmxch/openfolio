"""Add value_traded and rvol_20d columns to market_industries.

Value.Traded is aggregated from stock-level TradingView queries (not
available on industry-aggregate rows). RVOL is computed at scrape time
from the last 20 daily value_traded snapshots (excluding today).

Revision ID: 053
Revises: 052
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "market_industries",
        sa.Column("value_traded", sa.Numeric(22, 2), nullable=True),
    )
    op.add_column(
        "market_industries",
        sa.Column("rvol_20d", sa.Numeric(6, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_industries", "rvol_20d")
    op.drop_column("market_industries", "value_traded")
