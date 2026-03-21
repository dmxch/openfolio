"""Add Swissquote import fields: new transaction types, columns, fx_transactions table."""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def _col_exists(table, column):
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)
    return column in [c["name"] for c in insp.get_columns(table)]


def _table_exists(table):
    from sqlalchemy import inspect
    bind = op.get_bind()
    insp = inspect(bind)
    return table in insp.get_table_names()


def upgrade():
    # 1. Add new enum values to transactiontype
    # Must run outside transaction for PostgreSQL enums
    for val in ("capital_gain", "interest", "fx_credit", "fx_debit", "fee_correction"):
        op.execute(f"ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS '{val}'")

    # 2. Add new columns to transactions table
    new_cols = [
        ("order_id", sa.String(20)),
        ("isin", sa.String(20)),
        ("import_source", sa.String(30)),
        ("import_batch_id", sa.String(50)),
        ("raw_symbol", sa.String(50)),
        ("gross_amount", sa.Numeric(14, 2)),
        ("tax_amount", sa.Numeric(14, 2)),
    ]
    for col_name, col_type in new_cols:
        if not _col_exists("transactions", col_name):
            op.add_column("transactions", sa.Column(col_name, col_type, nullable=True))

    # 3. Create fx_transactions table
    if not _table_exists("fx_transactions"):
        op.create_table(
            "fx_transactions",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("order_id", sa.String(20)),
            sa.Column("currency_from", sa.String(10), nullable=False),
            sa.Column("currency_to", sa.String(10), nullable=False),
            sa.Column("amount_from", sa.Numeric(14, 2), nullable=False),
            sa.Column("amount_to", sa.Numeric(14, 2), nullable=False),
            sa.Column("derived_rate", sa.Numeric(10, 6), nullable=False),
            sa.Column("import_batch_id", sa.String(50)),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade():
    if _table_exists("fx_transactions"):
        op.drop_table("fx_transactions")

    cols = ["order_id", "isin", "import_source", "import_batch_id", "raw_symbol", "gross_amount", "tax_amount"]
    for col in cols:
        if _col_exists("transactions", col):
            op.drop_column("transactions", col)

    # Note: PostgreSQL enum values cannot be removed in a downgrade
