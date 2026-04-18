"""Add precious_metal_expenses table for storage fees, insurance etc.

Revision ID: 051
Revises: 050
Create Date: 2026-04-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "051"
down_revision: Union[str, None] = "050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum_if_not_exists(name, values):
    """Create enum type only if it doesn't already exist."""
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = :name"), {"name": name})
    if not result.scalar():
        vals = ", ".join(f"'{v}'" for v in values)
        conn.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({vals})"))


def upgrade() -> None:
    _create_enum_if_not_exists("preciousmetalexpensecategory", ["storage", "insurance", "other"])

    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'precious_metal_expenses'"))
    if result.scalar():
        return

    op.execute(
        """
        CREATE TABLE precious_metal_expenses (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            metal_type VARCHAR(20),
            date DATE NOT NULL,
            category preciousmetalexpensecategory NOT NULL,
            description VARCHAR(300),
            amount NUMERIC(12, 2) NOT NULL,
            recurring BOOLEAN NOT NULL DEFAULT FALSE,
            frequency frequency,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.create_index(
        "ix_precious_metal_expenses_user_id",
        "precious_metal_expenses",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_precious_metal_expenses_user_id",
        table_name="precious_metal_expenses",
    )
    op.drop_table("precious_metal_expenses")
    op.execute("DROP TYPE IF EXISTS preciousmetalexpensecategory")
