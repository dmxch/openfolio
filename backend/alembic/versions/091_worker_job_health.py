"""Erstelle worker_job_health — Heartbeat/Liveness-Tabelle fuer Worker-Jobs.

Ein APScheduler-Listener schreibt nach jedem Lauf eine Zeile pro job_id
(last_run/status/runtime/error + max_age_s). Backend liest sie (Admin-Endpoint)
und der Worker prueft stuendlich auf stale/failing Jobs (ERROR-Log = Alert).

Revision ID: 091
Revises: 090
Create Date: 2026-06-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "091"
down_revision: Union[str, None] = "090"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_job_health",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_runtime_ms", sa.Integer(), nullable=True),
        sa.Column("max_age_s", sa.Integer(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )


def downgrade() -> None:
    op.drop_table("worker_job_health")
