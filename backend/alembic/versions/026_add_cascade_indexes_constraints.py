"""add cascade on FKs, indexes on user_id, unique constraints

Revision ID: 026
Revises: 025
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def _constraint_exists(name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = :name)"
    ), {"name": name})
    return result.scalar()


def _index_exists(name):
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"
    ), {"name": name})
    return result.scalar()


def _get_fk_name(table, column):
    """Find the existing FK constraint name for a given table.column."""
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
        WHERE rel.relname = :table
          AND att.attname = :column
          AND con.contype = 'f'
        LIMIT 1
    """), {"table": table, "column": column})
    row = result.fetchone()
    return row[0] if row else None


def upgrade():
    # ============================================================
    # STEP 1: Add CASCADE to portfolio_snapshots.user_id FK
    # ============================================================
    fk_name = _get_fk_name("portfolio_snapshots", "user_id")
    if fk_name:
        op.drop_constraint(fk_name, "portfolio_snapshots", type_="foreignkey")
    op.create_foreign_key(
        "fk_portfolio_snapshots_user", "portfolio_snapshots", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )

    # ============================================================
    # STEP 2: Add CASCADE to mortgages.property_id FK
    # ============================================================
    fk_name = _get_fk_name("mortgages", "property_id")
    if fk_name:
        op.drop_constraint(fk_name, "mortgages", type_="foreignkey")
    op.create_foreign_key(
        "fk_mortgages_property", "mortgages", "properties",
        ["property_id"], ["id"], ondelete="CASCADE",
    )

    # ============================================================
    # STEP 3: Add CASCADE to property_expenses.property_id FK
    # ============================================================
    fk_name = _get_fk_name("property_expenses", "property_id")
    if fk_name:
        op.drop_constraint(fk_name, "property_expenses", type_="foreignkey")
    op.create_foreign_key(
        "fk_property_expenses_property", "property_expenses", "properties",
        ["property_id"], ["id"], ondelete="CASCADE",
    )

    # ============================================================
    # STEP 4: Add CASCADE to property_income.property_id FK
    # ============================================================
    fk_name = _get_fk_name("property_income", "property_id")
    if fk_name:
        op.drop_constraint(fk_name, "property_income", type_="foreignkey")
    op.create_foreign_key(
        "fk_property_income_property", "property_income", "properties",
        ["property_id"], ["id"], ondelete="CASCADE",
    )

    # ============================================================
    # STEP 5: Add indexes on user_id columns
    # ============================================================
    if not _index_exists("ix_portfolio_snapshots_user_id"):
        op.create_index("ix_portfolio_snapshots_user_id", "portfolio_snapshots", ["user_id"])

    if not _index_exists("ix_precious_metal_items_user_id"):
        op.create_index("ix_precious_metal_items_user_id", "precious_metal_items", ["user_id"])

    if not _index_exists("ix_import_profiles_user_id"):
        op.create_index("ix_import_profiles_user_id", "import_profiles", ["user_id"])

    # ============================================================
    # STEP 6: Add unique constraints (if not already present as indexes)
    # ============================================================
    # Migration 023 created these as unique indexes; add named constraints
    # only if neither the constraint nor the index exists yet.
    if not _constraint_exists("uq_watchlist_user_ticker") and not _index_exists("idx_watchlist_user_ticker_unique"):
        op.create_unique_constraint("uq_watchlist_user_ticker", "watchlist", ["user_id", "ticker"])

    if not _constraint_exists("uq_position_user_ticker") and not _index_exists("idx_positions_user_ticker_unique"):
        op.create_unique_constraint("uq_position_user_ticker", "positions", ["user_id", "ticker"])


def downgrade():
    # Drop unique constraints (only if we created them — the 023 indexes remain)
    if _constraint_exists("uq_position_user_ticker"):
        op.drop_constraint("uq_position_user_ticker", "positions", type_="unique")
    if _constraint_exists("uq_watchlist_user_ticker"):
        op.drop_constraint("uq_watchlist_user_ticker", "watchlist", type_="unique")

    # Drop indexes
    for idx in ["ix_import_profiles_user_id", "ix_precious_metal_items_user_id", "ix_portfolio_snapshots_user_id"]:
        if _index_exists(idx):
            op.drop_index(idx)

    # Restore FK constraints without CASCADE
    if _constraint_exists("fk_property_income_property"):
        op.drop_constraint("fk_property_income_property", "property_income", type_="foreignkey")
        op.create_foreign_key(
            "property_income_property_id_fkey", "property_income", "properties",
            ["property_id"], ["id"],
        )

    if _constraint_exists("fk_property_expenses_property"):
        op.drop_constraint("fk_property_expenses_property", "property_expenses", type_="foreignkey")
        op.create_foreign_key(
            "property_expenses_property_id_fkey", "property_expenses", "properties",
            ["property_id"], ["id"],
        )

    if _constraint_exists("fk_mortgages_property"):
        op.drop_constraint("fk_mortgages_property", "mortgages", type_="foreignkey")
        op.create_foreign_key(
            "mortgages_property_id_fkey", "mortgages", "properties",
            ["property_id"], ["id"],
        )

    if _constraint_exists("fk_portfolio_snapshots_user"):
        op.drop_constraint("fk_portfolio_snapshots_user", "portfolio_snapshots", type_="foreignkey")
        op.create_foreign_key(
            "portfolio_snapshots_user_id_fkey", "portfolio_snapshots", "users",
            ["user_id"], ["id"],
        )
