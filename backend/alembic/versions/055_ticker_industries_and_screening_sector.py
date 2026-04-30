"""Add ticker_industries table and sector-rotation columns to screening_results.

Two changes that ship together (must be atomic):

1. New ``ticker_industries`` table — UPSERT-target for the daily TradingView
   stock-level scan. PK is ``ticker``, single row per ticker, no history.
   Lets the Smart-Money screener look up TradingView industry names for
   any US-ticker without an extra API call.

2. New columns on ``screening_results``:
   - ``industry_name``: TradingView industry display name (matches
     ``MarketIndustry.name``).
   - ``sector_momentum``: One of tailwind/headwind/neutral/concentrated/unknown.
   - ``sector_bonus``: Score delta applied for the branche-rotation layer
     (default 0). Persisted so the UI can show a transparent score
     breakdown even if the config constants are tuned later.

The legacy ``sector`` column stays untouched.

Revision ID: 055
Revises: 054
Create Date: 2026-04-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticker_industries",
        sa.Column("ticker", sa.String(30), primary_key=True),
        sa.Column("industry_name", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_ticker_industries_industry_name",
        "ticker_industries",
        ["industry_name"],
    )

    op.add_column(
        "screening_results",
        sa.Column("industry_name", sa.String(200), nullable=True),
    )
    op.add_column(
        "screening_results",
        sa.Column("sector_momentum", sa.String(20), nullable=True),
    )
    op.add_column(
        "screening_results",
        sa.Column(
            "sector_bonus",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("screening_results", "sector_bonus")
    op.drop_column("screening_results", "sector_momentum")
    op.drop_column("screening_results", "industry_name")

    op.drop_index(
        "ix_ticker_industries_industry_name",
        table_name="ticker_industries",
    )
    op.drop_table("ticker_industries")
