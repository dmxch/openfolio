"""Add sma150 + next_earnings_at to screening_results (Iteration 2.6 Schwur-Toggles).

Speichert pro Composite-Scan-Row die Daten, die fuer Schwur 1 (Trend-
Filter SMA150) und Schwur 2 (Earnings-Veto 7d) noetig sind. Beide
nullable: bestehende Rows + neue Rows ohne Coverage bleiben NULL und
werden vom Filter durchgelassen (defensive Default — Schwur-Filter ist
kein Pflicht-Drop, sondern eine Slider-Verschaerfung).

Schwur 3 (Klumpenrisiko) ist user-scoped (haengt am Portfolio des
authentifizierten Users) und braucht KEINE Persistierung — wird im
API-Layer per Request via concentration_service berechnet.

Revision ID: 079
Revises: 078
Create Date: 2026-05-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "079"
down_revision: Union[str, None] = "078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "screening_results",
        sa.Column("sma150", sa.Numeric(14, 4), nullable=True),
    )
    op.add_column(
        "screening_results",
        sa.Column("next_earnings_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("screening_results", "next_earnings_at")
    op.drop_column("screening_results", "sma150")
