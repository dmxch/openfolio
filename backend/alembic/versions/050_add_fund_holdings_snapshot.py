"""Add fund_holdings_snapshot table for SEC 13F Q/Q diff analysis.

Stores per-fund, per-ticker, per-quarter holdings from 13F-HR filings.
Unique constraint on (fund_cik, ticker, period_date) allows side-by-side
quarter comparison. See SCOPE_SMART_MONEY_V4.md Block 3.

Revision ID: 050
Revises: 049
Create Date: 2026-04-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fund_holdings_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fund_cik", sa.String(15), nullable=False),
        sa.Column("fund_name", sa.String(200), nullable=False),
        sa.Column("ticker", sa.String(30), nullable=False),
        sa.Column("shares", sa.BigInteger, nullable=False),
        sa.Column("value_usd", sa.BigInteger, nullable=True),
        sa.Column("filing_date", sa.Date, nullable=False),
        sa.Column("period_date", sa.Date, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "fund_cik", "ticker", "period_date",
            name="uq_fund_holdings_cik_ticker_period",
        ),
    )
    op.create_index(
        "ix_fund_holdings_ticker",
        "fund_holdings_snapshot",
        ["ticker"],
    )
    op.create_index(
        "ix_fund_holdings_fund",
        "fund_holdings_snapshot",
        ["fund_cik", "filing_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_fund_holdings_fund", table_name="fund_holdings_snapshot")
    op.drop_index("ix_fund_holdings_ticker", table_name="fund_holdings_snapshot")
    op.drop_table("fund_holdings_snapshot")
