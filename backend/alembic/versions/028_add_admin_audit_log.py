"""add admin audit log table

Revision ID: 028_add_admin_audit_log
Revises: 027_add_app_config_table
Create Date: 2026-03-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_audit_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('admin_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('target_user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_audit_admin', 'admin_audit_log', ['admin_id'])
    op.create_index('ix_audit_created', 'admin_audit_log', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_audit_created', table_name='admin_audit_log')
    op.drop_index('ix_audit_admin', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
