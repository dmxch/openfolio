"""Add macro_cot_snapshots table for CFTC Commitments of Traders data.

Isolated macro/positioning storage — no relation to screening_scans or
screening_results. See SCOPE_SMART_MONEY_V4.md Block 1.

Revision ID: 049
Revises: 048
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "049"
down_revision: Union[str, None] = "048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "macro_cot_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument", sa.String(10), nullable=False),
        sa.Column("report_date", sa.Date, nullable=False),
        sa.Column("commercial_long", sa.BigInteger, nullable=True),
        sa.Column("commercial_short", sa.BigInteger, nullable=True),
        sa.Column("commercial_net", sa.BigInteger, nullable=True),
        sa.Column("mm_long", sa.BigInteger, nullable=True),
        sa.Column("mm_short", sa.BigInteger, nullable=True),
        sa.Column("mm_net", sa.BigInteger, nullable=True),
        sa.Column("oi_total", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("instrument", "report_date", name="uq_macro_cot_instrument_date"),
    )
    op.create_index(
        "ix_macro_cot_instrument_date",
        "macro_cot_snapshots",
        ["instrument", "report_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_macro_cot_instrument_date", table_name="macro_cot_snapshots")
    op.drop_table("macro_cot_snapshots")
