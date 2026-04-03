"""add screening_scans and screening_results tables

Revision ID: 041
Revises: 040
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screening_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("steps", postgresql.JSONB, server_default="[]"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("result_count", sa.Integer, server_default="0"),
    )

    op.create_table(
        "screening_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("ticker", sa.String(30), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("signals", postgresql.JSONB, server_default="{}"),
        sa.Column("price_usd", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("screening_results")
    op.drop_table("screening_scans")
