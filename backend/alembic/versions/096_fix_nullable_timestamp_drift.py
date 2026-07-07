"""Fix Model<->DB nullable drift on two timestamp columns.

Die Models deklarieren ``Mapped[datetime]`` (= NOT NULL), aber die Spalten
wurden in Migr. 091 (worker_job_health.updated_at) und 092
(signal_backtest_results.created_at) nullable angelegt. `alembic check` meldete
das dauerhaft als offene modify_nullable-Diffs. Hier auf NOT NULL ziehen
(Model-Intent). Defensiver NULL-Backfill vorab, damit SET NOT NULL nie an einer
verirrten NULL-Zeile scheitert (beide Spalten haben Python-Defaults, also sind
NULLs praktisch ausgeschlossen — Guertel + Hosentraeger).

Revision ID: 096
Revises: 095
Create Date: 2026-07-07
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "096"
down_revision: Union[str, None] = "095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE worker_job_health SET updated_at = now() WHERE updated_at IS NULL")
    op.alter_column(
        "worker_job_health", "updated_at",
        existing_type=sa.DateTime(), nullable=False,
    )
    op.execute("UPDATE signal_backtest_results SET created_at = now() WHERE created_at IS NULL")
    op.alter_column(
        "signal_backtest_results", "created_at",
        existing_type=sa.DateTime(), nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "signal_backtest_results", "created_at",
        existing_type=sa.DateTime(), nullable=True,
    )
    op.alter_column(
        "worker_job_health", "updated_at",
        existing_type=sa.DateTime(), nullable=True,
    )
