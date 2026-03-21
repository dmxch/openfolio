"""add admin panel, password reset, invite codes

Revision ID: 021
Revises: 020
Create Date: 2026-03-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def _table_exists(name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :name)"
    ), {"name": name})
    return result.scalar()


def _column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column)"
    ), {"table": table, "column": column})
    return result.scalar()


def upgrade():
    # Add new columns to users table (idempotent)
    if not _column_exists("users", "is_admin"):
        op.add_column("users", sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False))
    if not _column_exists("users", "force_password_change"):
        op.add_column("users", sa.Column("force_password_change", sa.Boolean(), server_default="false", nullable=False))
    if not _column_exists("users", "last_login_at"):
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))

    # Set first user (oldest created_at) as admin
    op.execute("""
        UPDATE users SET is_admin = true
        WHERE id = (SELECT id FROM users ORDER BY created_at ASC LIMIT 1)
    """)

    # Password reset tokens table
    if not _table_exists("password_reset_tokens"):
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.String(255), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"])
        op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    # App settings table
    if not _table_exists("app_settings"):
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(50), primary_key=True),
            sa.Column("value", sa.String(500), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("updated_by", UUID(as_uuid=True), nullable=True),
        )

    # Insert default registration mode (idempotent)
    op.execute("""
        INSERT INTO app_settings (key, value) VALUES ('registration_mode', 'open')
        ON CONFLICT (key) DO NOTHING
    """)

    # Invite codes table
    if not _table_exists("invite_codes"):
        op.create_table(
            "invite_codes",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("code", sa.String(20), unique=True, nullable=False),
            sa.Column("created_by", UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("used_by", UUID(as_uuid=True), nullable=True),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        )
        op.create_index("ix_invite_codes_code", "invite_codes", ["code"])


def downgrade():
    op.drop_table("invite_codes")
    op.drop_table("app_settings")
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "force_password_change")
    op.drop_column("users", "is_admin")
