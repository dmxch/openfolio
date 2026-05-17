"""positions.risk_rules JSONB als Position-Level Risk-Override.

Phase 2: User kann beim Bucket-Wechsel (Plan §7.7) wahlen, dass die aktuelle
Position ihre Risk-Rules behaelt — gespeichert als positions.risk_rules.
Alert-Service-Resolution: position.risk_rules > bucket.risk_rules > Default.

Revision ID: 066
Revises: 065
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("risk_rules", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("positions", "risk_rules")
