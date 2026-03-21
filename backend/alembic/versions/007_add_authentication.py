"""add authentication: users, refresh_tokens, user_settings tables + user_id to all data tables

Revision ID: 007
Revises: 006
Create Date: 2026-03-08
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "007"
down_revision = "006"


def _table_exists(table):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    return table in inspector.get_table_names()


def _column_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade():
    # 1. Create users table
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column("email", sa.String(255), unique=True, nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("totp_secret", sa.String(255), nullable=True),
            sa.Column("mfa_enabled", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )

    # 2. Create refresh_tokens table
    if not _table_exists("refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column("user_id", UUID(as_uuid=True), nullable=False),
            sa.Column("token_hash", sa.String(255), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("revoked", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("user_agent", sa.String(500), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
        )
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
        op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    # 3. Create user_settings table
    if not _table_exists("user_settings"):
        op.create_table(
            "user_settings",
            sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
            sa.Column("base_currency", sa.String(3), server_default="CHF"),
            sa.Column("broker", sa.String(50), server_default="swissquote"),
            sa.Column("default_stop_loss_method", sa.String(20), server_default="trailing_pct"),
            sa.Column("stop_loss_review_distance_pct", sa.Numeric(), server_default="15.0"),
            sa.Column("stop_loss_review_max_days", sa.Integer(), server_default="14"),
            sa.Column("number_format", sa.String(5), server_default="ch"),
            sa.Column("date_format", sa.String(10), server_default="dd.mm.yyyy"),
        )

    # 4. Create initial admin user
    import bcrypt
    admin_id = uuid.uuid4()
    pw_hash = bcrypt.hashpw("OpenFolio2026!".encode(), bcrypt.gensalt(rounds=12)).decode()

    conn = op.get_bind()
    # Check if any user already exists
    existing = conn.execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
    if existing == 0:
        conn.execute(
            sa.text(
                "INSERT INTO users (id, email, password_hash, mfa_enabled, is_active, created_at, updated_at) "
                "VALUES (:id, :email, :pw, false, true, NOW(), NOW())"
            ),
            {"id": admin_id, "email": "admin@openfolio.local", "pw": pw_hash},
        )
        # Create default settings
        conn.execute(
            sa.text(
                "INSERT INTO user_settings (user_id, base_currency, broker, default_stop_loss_method, "
                "stop_loss_review_distance_pct, stop_loss_review_max_days, number_format, date_format) "
                "VALUES (:uid, 'CHF', 'swissquote', 'trailing_pct', 15.0, 14, 'ch', 'dd.mm.yyyy')"
            ),
            {"uid": admin_id},
        )
    else:
        # Get existing first user
        row = conn.execute(sa.text("SELECT id FROM users LIMIT 1")).fetchone()
        admin_id = row[0]

    # 5. Add user_id to positions
    if not _column_exists("positions", "user_id"):
        op.add_column("positions", sa.Column("user_id", UUID(as_uuid=True), nullable=True))
        conn.execute(sa.text("UPDATE positions SET user_id = :uid WHERE user_id IS NULL"), {"uid": admin_id})
        op.alter_column("positions", "user_id", nullable=False)
        op.create_index("ix_positions_user_id", "positions", ["user_id"])

    # 6. Add user_id to watchlist
    if not _column_exists("watchlist", "user_id"):
        op.add_column("watchlist", sa.Column("user_id", UUID(as_uuid=True), nullable=True))
        conn.execute(sa.text("UPDATE watchlist SET user_id = :uid WHERE user_id IS NULL"), {"uid": admin_id})
        op.alter_column("watchlist", "user_id", nullable=False)
        op.create_index("ix_watchlist_user_id", "watchlist", ["user_id"])

    # 7. Add user_id to properties
    if not _column_exists("properties", "user_id"):
        op.add_column("properties", sa.Column("user_id", UUID(as_uuid=True), nullable=True))
        conn.execute(sa.text("UPDATE properties SET user_id = :uid WHERE user_id IS NULL"), {"uid": admin_id})
        op.alter_column("properties", "user_id", nullable=False)
        op.create_index("ix_properties_user_id", "properties", ["user_id"])


def downgrade():
    op.drop_index("ix_properties_user_id", "properties")
    op.drop_column("properties", "user_id")
    op.drop_index("ix_watchlist_user_id", "watchlist")
    op.drop_column("watchlist", "user_id")
    op.drop_index("ix_positions_user_id", "positions")
    op.drop_column("positions", "user_id")
    op.drop_table("user_settings")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
