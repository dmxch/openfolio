"""Add etf_sector_weights table and is_etf column on positions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "etf_sector_weights" not in existing_tables:
        op.create_table(
            "etf_sector_weights",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("ticker", sa.String(20), nullable=False, index=True),
            sa.Column("sector", sa.String(50), nullable=False),
            sa.Column("weight_pct", sa.Numeric(5, 2), nullable=False),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
            sa.UniqueConstraint("ticker", "sector", name="uq_etf_sector_ticker_sector"),
        )

    columns = [c["name"] for c in inspector.get_columns("positions")]
    if "is_etf" not in columns:
        op.add_column("positions", sa.Column("is_etf", sa.Boolean, server_default=sa.false()))

        # Heuristic: set is_etf = true for positions with type='etf' or ISIN starting with IE/LU
        op.execute("""
            UPDATE positions SET is_etf = true
            WHERE type = 'etf'
               OR (isin IS NOT NULL AND (isin LIKE 'IE%' OR isin LIKE 'LU%'))
        """)


def downgrade():
    op.drop_column("positions", "is_etf")
    op.drop_table("etf_sector_weights")
