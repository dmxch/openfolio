"""widen macro_indicator_cache.status from varchar(10) to varchar(20)

Revision ID: 032
Revises: 031
Create Date: 2026-03-25

"""
from alembic import op
import sqlalchemy as sa


revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "macro_indicator_cache",
        "status",
        type_=sa.String(20),
        existing_type=sa.String(10),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "macro_indicator_cache",
        "status",
        type_=sa.String(10),
        existing_type=sa.String(20),
        existing_nullable=False,
    )
