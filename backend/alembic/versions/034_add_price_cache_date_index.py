"""add composite index on price_cache (ticker, date) and index on date

Revision ID: 034
Revises: 68c381537c96
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op


revision: str = '034'
down_revision: Union[str, None] = '033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The UniqueConstraint already covers (ticker, date), but an explicit index
    # on date alone speeds up queries that filter/sort by date without ticker.
    op.create_index('ix_price_cache_date', 'price_cache', ['date'])


def downgrade() -> None:
    op.drop_index('ix_price_cache_date', table_name='price_cache')
