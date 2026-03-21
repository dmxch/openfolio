"""add price_source and isin columns to positions

Revision ID: 001
Revises:
Create Date: 2026-03-05
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE pricesource AS ENUM ('yahoo', 'coingecko', 'gold_org', 'manual')")
    op.add_column("positions", sa.Column("isin", sa.String(20), nullable=True))
    op.add_column(
        "positions",
        sa.Column(
            "price_source",
            sa.Enum("yahoo", "coingecko", "gold_org", "manual", name="pricesource"),
            nullable=False,
            server_default="yahoo",
        ),
    )


def downgrade() -> None:
    op.drop_column("positions", "price_source")
    op.drop_column("positions", "isin")
    op.execute("DROP TYPE pricesource")
