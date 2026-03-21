"""Add alert preferences and SMTP config tables.

Revision ID: 017
Revises: 016
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    # Alert preferences per category per user
    op.execute("""
        CREATE TABLE IF NOT EXISTS alert_preferences (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category VARCHAR(50) NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            notify_in_app BOOLEAN NOT NULL DEFAULT TRUE,
            notify_email BOOLEAN NOT NULL DEFAULT FALSE,
            UNIQUE (user_id, category)
        )
    """)

    # User SMTP config (per-user, encrypted password)
    op.execute("""
        CREATE TABLE IF NOT EXISTS smtp_config (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(30),
            host VARCHAR(255) NOT NULL,
            port INTEGER NOT NULL DEFAULT 587,
            username VARCHAR(255) NOT NULL,
            password_encrypted VARCHAR(500) NOT NULL,
            from_email VARCHAR(255),
            use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Add last_email_digest_at to user_settings for batching
    op.execute("""
        ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS last_email_digest_at TIMESTAMP
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS smtp_config")
    op.execute("DROP TABLE IF EXISTS alert_preferences")
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS last_email_digest_at")
