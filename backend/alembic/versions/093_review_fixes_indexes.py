"""Review-Fixes 2026-07-02: Indizes + Constraints.

- Index (user_id, order_id) auf transactions: der Import-Duplikat-Check lief
  pro Zeile über den user_id-Index statt punktgenau (Review M31).
- Indizes auf positions.ticker / positions.yfinance_ticker: der 60s-Kurs-
  Refresh matcht UPDATE ... WHERE ticker=:t OR yfinance_ticker=:t ohne Index
  (Review LOW-price-refresh-batch).
- Partial-Unique auf pending_orders.linked_transaction_id: Defense-in-Depth
  gegen Double-Fill (Review M3; Row-Lock ist der primäre Fix).
- positions.bucket_id: ondelete SET NULL widersprach nullable=False — ein
  Hard-Delete eines Buckets endete als NotNullViolation. Neu RESTRICT
  (Buckets werden ohnehin soft-deleted).

PROD-DEPLOY-VORPRÜFUNG: der Unique-Index schlägt fehl, falls Altbestand
doppelt verlinkte Transaktionen enthält (genau der M3-Race). Vorher prüfen:
  SELECT linked_transaction_id, count(*) FROM pending_orders
  WHERE linked_transaction_id IS NOT NULL
  GROUP BY 1 HAVING count(*) > 1;
Treffer manuell auflösen (jüngere Verlinkung auf NULL setzen), dann migrieren.

Revision ID: 093
Revises: 092
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "093"
down_revision: Union[str, None] = "092"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_transactions_user_order_id",
        "transactions",
        ["user_id", "order_id"],
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )
    op.create_index("idx_positions_ticker", "positions", ["ticker"])
    op.create_index("idx_positions_yf_ticker", "positions", ["yfinance_ticker"])
    op.create_index(
        "uq_pending_orders_linked_txn",
        "pending_orders",
        ["linked_transaction_id"],
        unique=True,
        postgresql_where=sa.text("linked_transaction_id IS NOT NULL"),
    )
    op.drop_constraint("positions_bucket_id_fkey", "positions", type_="foreignkey")
    op.create_foreign_key(
        "positions_bucket_id_fkey",
        "positions",
        "buckets",
        ["bucket_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("positions_bucket_id_fkey", "positions", type_="foreignkey")
    op.create_foreign_key(
        "positions_bucket_id_fkey",
        "positions",
        "buckets",
        ["bucket_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index("uq_pending_orders_linked_txn", table_name="pending_orders")
    op.drop_index("idx_positions_yf_ticker", table_name="positions")
    op.drop_index("idx_positions_ticker", table_name="positions")
    op.drop_index("idx_transactions_user_order_id", table_name="transactions")
