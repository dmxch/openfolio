"""Bucket Naming-Constraint: nur fuer aktive Buckets eindeutig.

Der UniqueConstraint (user_id, name) in Migration 063 galt auch fuer
soft-deletete Buckets. Folge: nach delete_bucket() schlaegt ein erneutes
create_bucket() mit demselben Namen fehl — etwa beim Template-Switch
(FIRE → Core/Satellite → FIRE).

Fix: Constraint durch Partial Unique Index ersetzen, der nur aktive
(deleted_at IS NULL) Buckets eindeutig macht.

Revision ID: 065
Revises: 064
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "065"
down_revision: Union[str, None] = "064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_bucket_user_name", "buckets", type_="unique")
    op.create_index(
        "uq_bucket_user_name_active",
        "buckets",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_bucket_user_name_active", table_name="buckets")
    op.create_unique_constraint(
        "uq_bucket_user_name", "buckets", ["user_id", "name"]
    )
