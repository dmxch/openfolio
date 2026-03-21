"""Add industry field to positions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("positions")]
    if "industry" not in columns:
        op.add_column("positions", sa.Column("industry", sa.String(80), nullable=True))
    else:
        # Widen from VARCHAR(60) to VARCHAR(80) if needed
        op.alter_column("positions", "industry", type_=sa.String(80), existing_type=sa.String(60))


def downgrade():
    op.drop_column("positions", "industry")
