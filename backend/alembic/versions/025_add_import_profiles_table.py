"""add import_profiles table

Revision ID: 025
Revises: 024
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    # Check if table already exists (created by seed.py's create_all)
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'import_profiles'"))
    if result.scalar():
        return

    op.create_table(
        "import_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("delimiter", sa.String(5), server_default=",", nullable=False),
        sa.Column("encoding", sa.String(20), server_default="utf-8", nullable=False),
        sa.Column("date_format", sa.String(30), server_default="%d-%m-%Y %H:%M:%S", nullable=False),
        sa.Column("decimal_separator", sa.String(1), server_default=".", nullable=False),
        sa.Column("column_mapping", sa.JSON(), nullable=False),
        sa.Column("type_mapping", sa.JSON(), nullable=False),
        sa.Column("has_forex_pairs", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("aggregate_partial_fills", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )


def downgrade():
    op.drop_table("import_profiles")
