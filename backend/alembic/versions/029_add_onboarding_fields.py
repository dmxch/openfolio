"""add onboarding fields to user_settings

Revision ID: 029
Revises: 028
Create Date: 2026-03-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_settings', sa.Column('onboarding_tour_completed', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('user_settings', sa.Column('onboarding_checklist_hidden', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('user_settings', sa.Column('onboarding_steps_json', sa.Text(), nullable=True))

    # Existing users already know the app — mark onboarding as completed
    op.execute("UPDATE user_settings SET onboarding_tour_completed = true, onboarding_checklist_hidden = true")


def downgrade() -> None:
    op.drop_column('user_settings', 'onboarding_steps_json')
    op.drop_column('user_settings', 'onboarding_checklist_hidden')
    op.drop_column('user_settings', 'onboarding_tour_completed')
