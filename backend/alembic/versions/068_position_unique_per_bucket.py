"""positions UNIQUE constraint von (user_id, ticker) auf
(user_id, ticker, bucket_id) lockern — fuer F-17 Teil-Wechsel.

Phase 2 (Plan §5.7 R-5.1): User soll eine Position teilweise in einen
anderen Bucket verschieben koennen. Voraussetzung: zwei Positionen mit
demselben Ticker in unterschiedlichen Buckets sind erlaubt.

Constraint-Aenderung:
  ALT: UNIQUE (user_id, ticker)                  als Constraint
  NEU: UNIQUE (user_id, ticker, bucket_id) WHERE is_active=true
       als Partial Index

import_service behandelt Same-Ticker-Match weiter wie zuvor wenn nur eine
einzige Position mit dem Ticker existiert (Backward-Compat).

Revision ID: 068
Revises: 067
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_position_user_ticker", "positions", type_="unique")
    op.create_index(
        "uq_position_user_ticker_bucket_active",
        "positions",
        ["user_id", "ticker", "bucket_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
        sqlite_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_position_user_ticker_bucket_active",
        table_name="positions",
    )
    op.create_unique_constraint(
        "uq_position_user_ticker", "positions", ["user_id", "ticker"]
    )
