"""drop risk_class column from positions

Revision ID: 040
Revises: 039
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '040'
down_revision: Union[str, None] = '039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('positions', 'risk_class')


def downgrade() -> None:
    op.add_column('positions', sa.Column('risk_class', sa.Integer(), nullable=False, server_default='3'))
