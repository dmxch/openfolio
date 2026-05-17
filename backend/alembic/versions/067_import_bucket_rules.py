"""import_bucket_rules: Auto-Mapping fuer neue Positionen beim CSV-Import.

Plan §2.5 + Phase 2: User definiert Regeln wie "alle Imports aus Swissquote -> Bucket X"
oder "Ticker matching ^BTC* -> Bucket Y". import_service.confirm_import wendet
Regeln in der gegebenen Reihenfolge an (erste passende gewinnt).

Revision ID: 067
Revises: 066
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "067"
down_revision: Union[str, None] = "066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_bucket_rules",
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
            "bucket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buckets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Quelle (z.B. swissquote_csv, ibkr_csv, pocket_csv) — optional
        sa.Column("source", sa.String(40), nullable=True),
        # Glob-Pattern fuer Ticker (z.B. 'BTC*', '*.SW') — optional
        sa.Column("ticker_pattern", sa.String(60), nullable=True),
        sa.Column(
            "priority",
            sa.Integer,
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source IS NOT NULL OR ticker_pattern IS NOT NULL",
            name="ck_import_bucket_rules_at_least_one_filter",
        ),
    )
    op.create_index(
        "idx_import_bucket_rules_user_priority",
        "import_bucket_rules",
        ["user_id", "priority"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_import_bucket_rules_user_priority",
        table_name="import_bucket_rules",
    )
    op.drop_table("import_bucket_rules")
