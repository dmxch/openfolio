"""remove alert expiry - set all expires_at to NULL

Revision ID: 020
Revises: 019
Create Date: 2026-03-11
"""
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE price_alerts SET expires_at = NULL WHERE expires_at IS NOT NULL")


def downgrade():
    pass
