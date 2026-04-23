"""Add market_industries table for daily TradingView industry-rotation snapshots.

Stores aggregated performance metrics (change, 1W, 1M, 3M, 6M, YTD, 1Y, 5Y, 10Y)
per US-industry per scrape timestamp. Unique constraint on (slug, scraped_at)
enables historical comparison and fallback when a scrape fails.

Revision ID: 052
Revises: 051
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_industries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("scraped_at", sa.DateTime, nullable=False),
        sa.Column("change_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_1w", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_1m", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_3m", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_6m", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_ytd", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_1y", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_5y", sa.Numeric(12, 4), nullable=True),
        sa.Column("perf_10y", sa.Numeric(12, 4), nullable=True),
        sa.Column("market_cap", sa.Numeric(22, 2), nullable=True),
        sa.Column("volume", sa.Numeric(22, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "slug", "scraped_at",
            name="uq_market_industries_slug_scraped",
        ),
    )
    op.create_index(
        "ix_market_industries_scraped_at",
        "market_industries",
        ["scraped_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_industries_scraped_at",
        table_name="market_industries",
    )
    op.drop_table("market_industries")
