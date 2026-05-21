"""Add form4_transactions table for SEC Form 4 insider transactions.

Speichert Insider-Trades (Form 4) pro Ticker fuer Cluster-Buy-Detection.
Lean-Probe-Scope: nur Portfolio + Watchlist (~50 Tickers), nicht SP500.
Filter im Service: transaction_code in (P, S). CEO/CFO werden bei der
Cluster-Aggregation gewichtet (Service-seitig, nicht im Schema).

Decision-Impact-Probe — Kill-Gate 2026-08-15.

Revision ID: 073
Revises: 072
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "073"
down_revision: Union[str, None] = "072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "form4_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(30), nullable=False),
        sa.Column("filing_date", sa.Date, nullable=False),
        sa.Column("transaction_date", sa.Date, nullable=False),
        sa.Column("insider_name", sa.String(200), nullable=False),
        sa.Column("insider_role", sa.String(100), nullable=True),
        sa.Column("transaction_code", sa.String(2), nullable=False),
        sa.Column("shares", sa.BigInteger, nullable=False),
        sa.Column("price", sa.Numeric(14, 4), nullable=True),
        sa.Column("value_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "ticker",
            "filing_date",
            "insider_name",
            "transaction_date",
            "transaction_code",
            name="uq_form4_ticker_filing_insider_date_code",
        ),
    )
    op.create_index(
        "ix_form4_ticker_txn_date",
        "form4_transactions",
        ["ticker", "transaction_date"],
    )
    op.create_index(
        "ix_form4_filing_date",
        "form4_transactions",
        ["filing_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_form4_filing_date", table_name="form4_transactions")
    op.drop_index("ix_form4_ticker_txn_date", table_name="form4_transactions")
    op.drop_table("form4_transactions")
