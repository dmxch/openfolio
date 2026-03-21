"""audit fix: indexes, foreign keys, constraints, and user_id denormalization

Revision ID: 023
Revises: 022
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def _index_exists(name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"
    ), {"name": name})
    return result.scalar()


def _constraint_exists(name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = :name)"
    ), {"name": name})
    return result.scalar()


def _column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column)"
    ), {"table": table, "column": column})
    return result.scalar()


def _table_exists(name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :name)"
    ), {"name": name})
    return result.scalar()


def upgrade():
    conn = op.get_bind()

    # ============================================================
    # STEP 1: Clean up orphan data before adding FK constraints
    # ============================================================

    # Orphan transactions without valid position
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM transactions t "
        "LEFT JOIN positions p ON t.position_id = p.id "
        "WHERE p.id IS NULL"
    ))
    orphan_txns = result.scalar()
    if orphan_txns > 0:
        conn.execute(sa.text(
            "DELETE FROM transactions t "
            "WHERE NOT EXISTS (SELECT 1 FROM positions p WHERE p.id = t.position_id)"
        ))

    # Orphan rows in all user_id tables
    for table in [
        "positions", "watchlist", "fx_transactions", "price_alerts",
        "watchlist_tags", "alert_preferences", "refresh_tokens",
        "password_reset_tokens", "etf_sector_weights", "smtp_config",
        "properties", "user_settings", "portfolio_snapshots",
    ]:
        if not _table_exists(table):
            continue
        result = conn.execute(sa.text(
            f"SELECT COUNT(*) FROM {table} t "
            f"LEFT JOIN users u ON t.user_id = u.id "
            f"WHERE u.id IS NULL"
        ))
        orphan_count = result.scalar()
        if orphan_count > 0:
            conn.execute(sa.text(
                f"DELETE FROM {table} WHERE user_id NOT IN (SELECT id FROM users)"
            ))

    # ============================================================
    # STEP 2: Clean up duplicates before UNIQUE constraints
    # ============================================================

    # Duplicate positions (same user_id + ticker): keep the one with most transactions
    result = conn.execute(sa.text(
        "SELECT user_id, ticker, COUNT(*) "
        "FROM positions GROUP BY user_id, ticker HAVING COUNT(*) > 1"
    ))
    dupes = result.fetchall()
    for user_id, ticker, _ in dupes:
        # Keep position with most transactions, delete others
        conn.execute(sa.text("""
            DELETE FROM positions WHERE id IN (
                SELECT p.id FROM positions p
                LEFT JOIN (
                    SELECT position_id, COUNT(*) as cnt
                    FROM transactions GROUP BY position_id
                ) t ON t.position_id = p.id
                WHERE p.user_id = :user_id AND p.ticker = :ticker
                ORDER BY COALESCE(t.cnt, 0) DESC
                OFFSET 1
            )
        """), {"user_id": user_id, "ticker": ticker})

    # Duplicate watchlist entries (same user_id + ticker): keep newest
    result = conn.execute(sa.text(
        "SELECT user_id, ticker, COUNT(*) "
        "FROM watchlist GROUP BY user_id, ticker HAVING COUNT(*) > 1"
    ))
    dupes = result.fetchall()
    for user_id, ticker, _ in dupes:
        conn.execute(sa.text("""
            DELETE FROM watchlist WHERE id IN (
                SELECT id FROM watchlist
                WHERE user_id = :user_id AND ticker = :ticker
                ORDER BY created_at DESC
                OFFSET 1
            )
        """), {"user_id": user_id, "ticker": ticker})

    # ============================================================
    # STEP 3: Add transactions.user_id column (nullable first)
    # ============================================================
    if not _column_exists("transactions", "user_id"):
        op.add_column("transactions", sa.Column("user_id", UUID(as_uuid=True), nullable=True))

    # ============================================================
    # STEP 4: Populate transactions.user_id from positions
    # ============================================================
    conn.execute(sa.text(
        "UPDATE transactions t SET user_id = p.user_id "
        "FROM positions p WHERE t.position_id = p.id AND t.user_id IS NULL"
    ))

    # ============================================================
    # STEP 5: Set NOT NULL on transactions.user_id
    # ============================================================
    op.alter_column("transactions", "user_id", nullable=False)

    # ============================================================
    # STEP 6: Foreign Key Constraints
    # ============================================================

    FK_DEFS = [
        ("positions", "fk_positions_user", "user_id", "users", "id"),
        ("watchlist", "fk_watchlist_user", "user_id", "users", "id"),
        ("fx_transactions", "fk_fx_transactions_user", "user_id", "users", "id"),
        ("price_alerts", "fk_price_alerts_user", "user_id", "users", "id"),
        ("watchlist_tags", "fk_watchlist_tags_user", "user_id", "users", "id"),
        ("alert_preferences", "fk_alert_preferences_user", "user_id", "users", "id"),
        ("refresh_tokens", "fk_refresh_tokens_user", "user_id", "users", "id"),
        ("password_reset_tokens", "fk_password_reset_tokens_user", "user_id", "users", "id"),
        ("transactions", "fk_transactions_user", "user_id", "users", "id"),
        ("etf_sector_weights", "fk_etf_sector_weights_user", "user_id", "users", "id"),
        ("properties", "fk_properties_user", "user_id", "users", "id"),
        ("smtp_config", "fk_smtp_config_user", "user_id", "users", "id"),
        ("user_settings", "fk_user_settings_user", "user_id", "users", "id"),
    ]

    for table, fk_name, col, ref_table, ref_col in FK_DEFS:
        if not _table_exists(table):
            continue
        if _constraint_exists(fk_name):
            continue
        op.create_foreign_key(fk_name, table, ref_table, [col], [ref_col], ondelete="CASCADE")

    # Transactions → Positions: ensure ON DELETE CASCADE
    if _constraint_exists("transactions_position_id_fkey"):
        op.drop_constraint("transactions_position_id_fkey", "transactions", type_="foreignkey")
    if not _constraint_exists("fk_transactions_position"):
        op.create_foreign_key(
            "fk_transactions_position", "transactions", "positions",
            ["position_id"], ["id"], ondelete="CASCADE",
        )

    # ============================================================
    # STEP 7: UNIQUE Constraints
    # ============================================================
    if not _index_exists("idx_positions_user_ticker_unique"):
        op.execute(
            "CREATE UNIQUE INDEX idx_positions_user_ticker_unique "
            "ON positions (user_id, ticker)"
        )

    if not _index_exists("idx_watchlist_user_ticker_unique"):
        op.execute(
            "CREATE UNIQUE INDEX idx_watchlist_user_ticker_unique "
            "ON watchlist (user_id, ticker)"
        )

    # ============================================================
    # STEP 8: All Indexes
    # ============================================================

    # K-2: Transaction indexes
    INDEX_DEFS = [
        ("idx_transactions_position_id", "transactions", ["position_id"]),
        ("idx_transactions_date", "transactions", ["date"]),
        ("idx_transactions_position_date", "transactions", ["position_id", "date"]),
        ("idx_transactions_position_type", "transactions", ["position_id", "type"]),
    ]
    for idx_name, table, cols in INDEX_DEFS:
        if not _index_exists(idx_name):
            op.create_index(idx_name, table, cols)

    # H-3: Price cache indexes
    if not _index_exists("idx_price_cache_ticker_date"):
        op.execute("CREATE INDEX idx_price_cache_ticker_date ON price_cache (ticker, date DESC)")
    if not _index_exists("idx_price_cache_date_desc"):
        op.execute("CREATE INDEX idx_price_cache_date_desc ON price_cache (date DESC)")

    # H-4: Transaction user_id indexes
    if not _index_exists("idx_transactions_user_id"):
        op.create_index("idx_transactions_user_id", "transactions", ["user_id"])
    if not _index_exists("idx_transactions_user_date"):
        op.execute("CREATE INDEX idx_transactions_user_date ON transactions (user_id, date DESC)")
    if not _index_exists("idx_transactions_user_type"):
        op.create_index("idx_transactions_user_type", "transactions", ["user_id", "type"])

    # M-13: Auth table indexes
    if not _index_exists("idx_refresh_tokens_user_id"):
        op.create_index("idx_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    if not _index_exists("idx_refresh_tokens_token_hash"):
        op.create_index("idx_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    if not _index_exists("idx_password_reset_tokens_hash"):
        op.create_index("idx_password_reset_tokens_hash", "password_reset_tokens", ["token_hash"], unique=True)
    if not _index_exists("idx_password_reset_tokens_user"):
        op.create_index("idx_password_reset_tokens_user", "password_reset_tokens", ["user_id"])
    if not _index_exists("idx_price_alerts_user_id"):
        op.create_index("idx_price_alerts_user_id", "price_alerts", ["user_id"])
    if not _index_exists("idx_price_alerts_active"):
        op.execute(
            "CREATE INDEX idx_price_alerts_active ON price_alerts (is_active, is_triggered) "
            "WHERE is_active = true AND is_triggered = false"
        )
    if not _index_exists("idx_portfolio_snapshots_user_date"):
        op.execute("CREATE INDEX idx_portfolio_snapshots_user_date ON portfolio_snapshots (user_id, date DESC)")
    if not _index_exists("idx_watchlist_tags_user"):
        op.create_index("idx_watchlist_tags_user", "watchlist_tags", ["user_id"])
    if not _index_exists("idx_alert_preferences_user"):
        if _table_exists("alert_preferences"):
            op.create_index("idx_alert_preferences_user", "alert_preferences", ["user_id"])
    if not _index_exists("idx_fx_transactions_user"):
        if _table_exists("fx_transactions"):
            op.create_index("idx_fx_transactions_user", "fx_transactions", ["user_id"])

    # Additional: Positions indexes
    if not _index_exists("idx_positions_user_active"):
        op.create_index("idx_positions_user_active", "positions", ["user_id"])
    if not _index_exists("idx_positions_ticker"):
        op.create_index("idx_positions_ticker", "positions", ["ticker"])
    if not _index_exists("idx_positions_user_type"):
        op.create_index("idx_positions_user_type", "positions", ["user_id", "position_type"])


def downgrade():
    # Drop indexes (reverse order)
    indexes_to_drop = [
        "idx_positions_user_type",
        "idx_positions_ticker",
        "idx_positions_user_active",
        "idx_fx_transactions_user",
        "idx_alert_preferences_user",
        "idx_watchlist_tags_user",
        "idx_portfolio_snapshots_user_date",
        "idx_price_alerts_active",
        "idx_price_alerts_user_id",
        "idx_password_reset_tokens_user",
        "idx_password_reset_tokens_hash",
        "idx_refresh_tokens_token_hash",
        "idx_refresh_tokens_user_id",
        "idx_transactions_user_type",
        "idx_transactions_user_date",
        "idx_transactions_user_id",
        "idx_price_cache_date_desc",
        "idx_price_cache_ticker_date",
        "idx_transactions_position_type",
        "idx_transactions_position_date",
        "idx_transactions_date",
        "idx_transactions_position_id",
        "idx_watchlist_user_ticker_unique",
        "idx_positions_user_ticker_unique",
    ]
    for idx in indexes_to_drop:
        try:
            op.drop_index(idx)
        except Exception:
            pass

    # Drop FK constraints
    fk_to_drop = [
        ("transactions", "fk_transactions_position"),
        ("user_settings", "fk_user_settings_user"),
        ("smtp_config", "fk_smtp_config_user"),
        ("properties", "fk_properties_user"),
        ("etf_sector_weights", "fk_etf_sector_weights_user"),
        ("transactions", "fk_transactions_user"),
        ("password_reset_tokens", "fk_password_reset_tokens_user"),
        ("refresh_tokens", "fk_refresh_tokens_user"),
        ("alert_preferences", "fk_alert_preferences_user"),
        ("watchlist_tags", "fk_watchlist_tags_user"),
        ("price_alerts", "fk_price_alerts_user"),
        ("fx_transactions", "fk_fx_transactions_user"),
        ("watchlist", "fk_watchlist_user"),
        ("positions", "fk_positions_user"),
    ]
    for table, fk_name in fk_to_drop:
        try:
            op.drop_constraint(fk_name, table, type_="foreignkey")
        except Exception:
            pass

    # Restore original transactions FK (without CASCADE)
    try:
        op.create_foreign_key(
            "transactions_position_id_fkey", "transactions", "positions",
            ["position_id"], ["id"],
        )
    except Exception:
        pass

    # Drop transactions.user_id column
    if _column_exists("transactions", "user_id"):
        op.drop_column("transactions", "user_id")
