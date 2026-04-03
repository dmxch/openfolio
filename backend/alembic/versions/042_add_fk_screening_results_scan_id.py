"""add FK constraint screening_results.scan_id -> screening_scans.id

Revision ID: 042
Revises: 041
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "042"
down_revision: Union[str, None] = "041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_screening_results_scan_id",
        "screening_results",
        "screening_scans",
        ["scan_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_screening_results_scan_id", "screening_results", type_="foreignkey")
