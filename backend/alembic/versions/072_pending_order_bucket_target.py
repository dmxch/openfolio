"""Add bucket_id_target to pending_orders.

Beim Anlegen einer Pending Order kann der User schon entscheiden, in welchem
Bucket die Position landen soll, falls beim Fill eine neue Position
auto-erstellt wird. Ohne dieses Feld faellt der Fill-Pfad auf den
liquid_default-Bucket zurueck.

Bestaehende Orders: NULL (Fallback greift weiterhin).

Revision ID: 072
Revises: 071
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "072"
down_revision: Union[str, None] = "071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = {col["name"] for col in inspector.get_columns("pending_orders")}
    if "bucket_id_target" not in cols:
        op.add_column(
            "pending_orders",
            sa.Column(
                "bucket_id_target",
                UUID(as_uuid=True),
                sa.ForeignKey("buckets.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("pending_orders")}
    if "bucket_id_target" in cols:
        op.drop_column("pending_orders", "bucket_id_target")
