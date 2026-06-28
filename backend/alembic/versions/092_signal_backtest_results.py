"""Erstelle signal_backtest_results — akkumulierte Per-Signal-Forward-Return-Historie.

Ein monatlicher Worker-Job persistiert je Einzelsignal/Fenster die univariate
present-vs-absent-Statistik. Über die Zeit entsteht die Multi-Regime-Historie,
die Invariante #3 für eine fundierte Gewichts-Entscheidung verlangt.

Revision ID: 092
Revises: 091
Create Date: 2026-06-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "092"
down_revision: Union[str, None] = "091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_backtest_results",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("signal_key", sa.String(length=32), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_present", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_absent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_present", sa.Float(), nullable=True),
        sa.Column("mean_absent", sa.Float(), nullable=True),
        sa.Column("delta", sa.Float(), nullable=True),
        sa.Column("hit_present", sa.Float(), nullable=True),
        sa.Column("n_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("earliest_scan", sa.Date(), nullable=True),
        sa.Column("latest_scan", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_date", "signal_key", "window_days", name="uq_signal_backtest_run"),
    )
    op.create_index("ix_signal_backtest_results_run_date", "signal_backtest_results", ["run_date"])


def downgrade() -> None:
    op.drop_index("ix_signal_backtest_results_run_date", table_name="signal_backtest_results")
    op.drop_table("signal_backtest_results")
