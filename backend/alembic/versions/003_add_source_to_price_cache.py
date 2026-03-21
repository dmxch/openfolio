"""add source to price_cache

Revision ID: 003
Revises: 002
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='price_cache' AND column_name='source'"
    ))
    if not result.fetchone():
        op.add_column("price_cache", sa.Column("source", sa.String(20), nullable=False, server_default="yahoo"))


def downgrade() -> None:
    op.drop_column("price_cache", "source")
