"""mortgage.bank + property_income.tenant: String(200) -> Text (encrypted PII)

Revision ID: 037
Revises: 036
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("mortgages", "bank",
                    existing_type=sa.String(200),
                    type_=sa.Text(),
                    existing_nullable=True)
    op.alter_column("property_income", "tenant",
                    existing_type=sa.String(200),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column("mortgages", "bank",
                    existing_type=sa.Text(),
                    type_=sa.String(200),
                    existing_nullable=True)
    op.alter_column("property_income", "tenant",
                    existing_type=sa.Text(),
                    type_=sa.String(200),
                    existing_nullable=True)
