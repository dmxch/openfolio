"""Add score_display column (0-100 normalized) to screening_results.

`score` bleibt der raw-Wert (0-10, additiv aus den Pipeline-Weights und auf
[0,10] geclampt in screening_service.py). `score_display` ist der
UI-Normalized-Score 0-100 (Phase-1: linear raw*10).

Pure-Function-Constraint: score_display wird bei jedem Scan aus score neu
berechnet (compute_display_score in screening_service.py). Ein Formel-Switch
in Iteration 2 (linear vs. log vs. percentile) erfordert dann nur einen
nightly-Recompute-Job ueber score, keine Historien-Migration.

Revision ID: 075
Revises: 074
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "075"
down_revision: Union[str, None] = "074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "screening_results",
        sa.Column(
            "score_display",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        "UPDATE screening_results "
        "SET score_display = GREATEST(0, LEAST(100, score * 10))"
    )


def downgrade() -> None:
    op.drop_column("screening_results", "score_display")
