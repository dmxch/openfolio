"""widen positions.iban to text for Fernet encryption

Revision ID: 031
Revises: 030
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa


revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "positions",
        "iban",
        type_=sa.Text(),
        existing_type=sa.String(34),
    )


def downgrade() -> None:
    op.alter_column(
        "positions",
        "iban",
        type_=sa.String(34),
        existing_type=sa.Text(),
    )
