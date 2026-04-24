"""Add concentration columns to market_industries.

Per-industry aggregates computed from the stock-level scan:
  - top1_ticker:   symbol of the largest MCap member
  - top1_weight:   that member's share of industry MCap (0..1)
  - effective_n:   1 / HHI, the effective number of equally-weighted members

Lets the UI flag single-stock industries (e.g. Media Conglomerates where
SPHR is ~65% of MCap) so flow signals there aren't mistaken for
diversified sector rotation.

Revision ID: 054
Revises: 053
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "054"
down_revision: Union[str, None] = "053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "market_industries",
        sa.Column("top1_ticker", sa.String(20), nullable=True),
    )
    op.add_column(
        "market_industries",
        sa.Column("top1_weight", sa.Numeric(5, 4), nullable=True),
    )
    op.add_column(
        "market_industries",
        sa.Column("effective_n", sa.Numeric(6, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_industries", "effective_n")
    op.drop_column("market_industries", "top1_weight")
    op.drop_column("market_industries", "top1_ticker")
