"""fred_api_key: String(500) -> Text (encrypted fields must use Text)

Revision ID: 036
Revises: 035
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("user_settings", "fred_api_key",
                    existing_type=sa.String(500),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column("user_settings", "fred_api_key",
                    existing_type=sa.Text(),
                    type_=sa.String(500),
                    existing_nullable=True)
