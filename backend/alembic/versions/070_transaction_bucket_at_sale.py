"""Add bucket_id_at_sale snapshot to transactions.

Realisierte Gewinne sollen sich pro Bucket filtern lassen, wobei der
historisch korrekte Bucket zum Verkaufszeitpunkt gilt (nicht der aktuelle
Bucket der Position). Daher: dedizierter Snapshot-Column auf der Transaction,
einmal beim Sell gesetzt, danach immutable.

Backfill fuer bestehende Sells: aktuelle position.bucket_id als best-effort.
Vor der Migration gab es keinen Snapshot, also ist das die einzige verfuegbare
Information.

FK ON DELETE SET NULL: Bucket-Loeschungen sollen historische Sells nicht
zerstoeren — sie landen dann eben in der Aggregiert-Ansicht.

Revision ID: 070
Revises: 069
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {col["name"] for col in inspector.get_columns("transactions")}
    if "bucket_id_at_sale" not in cols:
        op.add_column(
            "transactions",
            sa.Column(
                "bucket_id_at_sale",
                UUID(as_uuid=True),
                sa.ForeignKey("buckets.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
    if "idx_transactions_bucket_at_sale" not in indexes:
        op.create_index(
            "idx_transactions_bucket_at_sale",
            "transactions",
            ["bucket_id_at_sale"],
        )

    # Backfill: existing sells get the position's current bucket as best-effort.
    op.execute(
        """
        UPDATE transactions t
        SET bucket_id_at_sale = p.bucket_id
        FROM positions p
        WHERE t.position_id = p.id
          AND t.type = 'sell'
          AND t.bucket_id_at_sale IS NULL
          AND p.bucket_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = {ix["name"] for ix in inspector.get_indexes("transactions")}
    if "idx_transactions_bucket_at_sale" in indexes:
        op.drop_index("idx_transactions_bucket_at_sale", table_name="transactions")

    cols = {col["name"] for col in inspector.get_columns("transactions")}
    if "bucket_id_at_sale" in cols:
        op.drop_column("transactions", "bucket_id_at_sale")
