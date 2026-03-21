"""Watchlist: notes, price alerts, tags

Revision ID: 016
Revises: 015
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add notes to watchlist
    conn.execute(sa.text(
        "ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS notes TEXT"
    ))

    # 2. Price alerts table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS price_alerts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            ticker VARCHAR(20) NOT NULL,
            alert_type VARCHAR(20) NOT NULL,
            target_value NUMERIC(14,4) NOT NULL,
            currency VARCHAR(3),
            is_active BOOLEAN NOT NULL DEFAULT true,
            is_triggered BOOLEAN NOT NULL DEFAULT false,
            triggered_at TIMESTAMP,
            trigger_price NUMERIC(14,4),
            notification_sent BOOLEAN NOT NULL DEFAULT false,
            notify_in_app BOOLEAN NOT NULL DEFAULT true,
            notify_email BOOLEAN NOT NULL DEFAULT false,
            note VARCHAR(200),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP
        )
    """))

    # 3. Watchlist tags table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS watchlist_tags (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            name VARCHAR(30) NOT NULL,
            color VARCHAR(7),
            CONSTRAINT uq_tag_user_name UNIQUE (user_id, name)
        )
    """))

    # 4. Watchlist item-tag association
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS watchlist_item_tags (
            watchlist_item_id UUID NOT NULL REFERENCES watchlist(id) ON DELETE CASCADE,
            tag_id UUID NOT NULL REFERENCES watchlist_tags(id) ON DELETE CASCADE,
            PRIMARY KEY (watchlist_item_id, tag_id)
        )
    """))


def downgrade() -> None:
    op.drop_table("watchlist_item_tags")
    op.drop_table("watchlist_tags")
    op.drop_table("price_alerts")
    op.execute("ALTER TABLE watchlist DROP COLUMN IF EXISTS notes")
