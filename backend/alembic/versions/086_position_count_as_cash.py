"""Fuege positions.count_as_cash hinzu — Geldmarkt-/T-Bill-ETFs als Cash zaehlen.

Eine Position mit ``count_as_cash = TRUE`` bleibt eine echte, live-bepreiste
Wertschrift (shares × price × fx, Performance unveraendert), wird aber in
Allokation (by_type → "cash"), Cash-Quote, Portfolio- und Bucket-Snapshots
(cash_chf) als Cash klassifiziert. Default FALSE — bestehende Positionen
bleiben unveraendert.

Revision ID: 086
Revises: 085
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "086"
down_revision: Union[str, None] = "085"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column(
            "count_as_cash",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("positions", "count_as_cash")
