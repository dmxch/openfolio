"""Add estimate_revisions table for analyst EPS snapshot tracking.

Taegliche Snapshots der FMP-Konsens-Estimates pro Ticker. Service berechnet
30/60/90d-Deltas on-demand aus der Snapshot-Historie. analyst_estimates_cache
existiert nicht — eigene Tabelle noetig.

Lean-Probe-Scope: nur Portfolio + Watchlist (~50 Tickers).
Decision-Impact-Probe — Kill-Gate 2026-08-15.

Revision ID: 074
Revises: 073
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "074"
down_revision: Union[str, None] = "073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "estimate_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(30), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("eps_fy1", sa.Numeric(12, 4), nullable=True),
        sa.Column("eps_fy2", sa.Numeric(12, 4), nullable=True),
        sa.Column("revenue_fy1", sa.Numeric(20, 2), nullable=True),
        sa.Column("num_analysts", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "ticker",
            "snapshot_date",
            name="uq_estimate_revisions_ticker_snapshot",
        ),
    )
    op.create_index(
        "ix_estimate_revisions_ticker_date",
        "estimate_revisions",
        ["ticker", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_estimate_revisions_ticker_date",
        table_name="estimate_revisions",
    )
    op.drop_table("estimate_revisions")
