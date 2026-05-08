"""Add pending_dividends table + dividend-withholding-related columns.

The Dividenden-Tracker feature persists detected (yfinance Ex-Date) dividend
events as `pending_dividends` rows so the UI/Worker can prompt the user to
record the corresponding `dividend` transaction. Adds two ancillary columns:

- ``user_settings.dividend_withholding_default`` — global per-user fallback
  (default 0.35 = Schweizer Verrechnungssteuer).
- ``positions.dividend_withholding_pct`` — per-position sticky override the
  Confirm-Modal persists when the user customizes the rate.

Plan refinements R8 (UserSettings, not User) and R9 (notes plain TEXT, not
encrypted) are reflected here.

Revision ID: 057
Revises: 056
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. pending_dividends
    op.create_table(
        "pending_dividends",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id",
            UUID(as_uuid=True),
            sa.ForeignKey("positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("dividend_per_share", sa.Numeric(14, 6), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("shares_at_ex_date", sa.Numeric(20, 8), nullable=False),
        sa.Column("expected_gross_chf", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "matched_transaction_id",
            UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Plain TEXT (R9) — Dismiss-Reason ist keine sensitive Finanzdaten.
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "position_id",
            "ex_date",
            name="uq_pending_dividend_user_position_exdate",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'dismissed')",
            name="ck_pending_dividend_status",
        ),
    )
    op.create_index(
        "idx_pending_dividends_user_status",
        "pending_dividends",
        ["user_id", "status"],
    )
    op.create_index(
        "idx_pending_dividends_position",
        "pending_dividends",
        ["position_id"],
    )
    # Partial index — only rows with a matched_transaction_id, used by
    # unmatch_on_transaction_delete to find the affected pending row fast.
    op.create_index(
        "idx_pending_dividends_matched_txn",
        "pending_dividends",
        ["matched_transaction_id"],
        postgresql_where=sa.text("matched_transaction_id IS NOT NULL"),
    )

    # 2. user_settings.dividend_withholding_default (R8 — auf user_settings)
    op.add_column(
        "user_settings",
        sa.Column(
            "dividend_withholding_default",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("0.3500"),
        ),
    )

    # 3. positions.dividend_withholding_pct (R1 — Sticky-Override pro Position)
    op.add_column(
        "positions",
        sa.Column(
            "dividend_withholding_pct",
            sa.Numeric(5, 4),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("positions", "dividend_withholding_pct")
    op.drop_column("user_settings", "dividend_withholding_default")
    op.drop_index(
        "idx_pending_dividends_matched_txn",
        table_name="pending_dividends",
    )
    op.drop_index(
        "idx_pending_dividends_position",
        table_name="pending_dividends",
    )
    op.drop_index(
        "idx_pending_dividends_user_status",
        table_name="pending_dividends",
    )
    op.drop_table("pending_dividends")
