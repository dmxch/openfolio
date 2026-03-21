"""add user_id to etf_sector_weights for multi-user isolation

Revision ID: 022
Revises: 021
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def _column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column)"
    ), {"table": table, "column": column})
    return result.scalar()


def upgrade():
    if not _column_exists("etf_sector_weights", "user_id"):
        op.add_column("etf_sector_weights", sa.Column("user_id", UUID(as_uuid=True), nullable=True))

        # Assign existing rows to the first (oldest) user so data isn't orphaned
        op.execute("""
            UPDATE etf_sector_weights
            SET user_id = (SELECT id FROM users ORDER BY created_at ASC LIMIT 1)
            WHERE user_id IS NULL
        """)

        op.alter_column("etf_sector_weights", "user_id", nullable=False)
        op.create_index("ix_etf_sector_weights_user_id", "etf_sector_weights", ["user_id"])

        # Drop the old unique constraint and create a new one including user_id
        op.drop_constraint("uq_etf_sector_ticker_sector", "etf_sector_weights", type_="unique")
        op.create_unique_constraint(
            "uq_etf_sector_user_ticker_sector",
            "etf_sector_weights",
            ["user_id", "ticker", "sector"],
        )


def downgrade():
    op.drop_constraint("uq_etf_sector_user_ticker_sector", "etf_sector_weights", type_="unique")
    op.drop_index("ix_etf_sector_weights_user_id", "etf_sector_weights")
    op.drop_column("etf_sector_weights", "user_id")
    op.create_unique_constraint(
        "uq_etf_sector_ticker_sector",
        "etf_sector_weights",
        ["ticker", "sector"],
    )
