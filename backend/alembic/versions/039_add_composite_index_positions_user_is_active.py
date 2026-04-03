"""add composite index on positions (user_id, is_active)

Revision ID: 039
Revises: 037
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = '039'
down_revision: Union[str, None] = '037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_positions_user_active",
        "positions",
        ["user_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_positions_user_active", table_name="positions")
