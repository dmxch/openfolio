"""totp_secret: String(255) -> Text (encrypted fields must use Text)

Revision ID: 035
Revises: 034
Create Date: 2026-04-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '035'
down_revision: Union[str, None] = '034'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'totp_secret',
                    existing_type=sa.String(255),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'totp_secret',
                    existing_type=sa.Text(),
                    type_=sa.String(255),
                    existing_nullable=True)
