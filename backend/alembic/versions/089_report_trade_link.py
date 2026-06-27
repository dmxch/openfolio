"""Fuege reports.ticker / side / linked_transaction_id hinzu — Trade-Journal Plan->Ist-Link.

Ein 'trade'-Report (Trade-Plan / Sell-Check aus dem claude-finance-Vault) ist die
PLAN-Seite eines Trades. ``linked_transaction_id`` verknuepft ihn exakt mit der
spaeter ausgefuehrten Transaktion (Ist-Seite); ``ticker``/``side`` machen den Plan
strukturiert auswertbar. Alle drei nullable, von claude-finance beim Buchen gesetzt
(Schreibzeit-Tag) — bestehende Reports bleiben unveraendert (NULL).

FK ON DELETE SET NULL: wird die Transaktion geloescht, bleibt der Plan-Report
erhalten, nur der Link verfaellt (analog pending_orders.linked_transaction_id).

Revision ID: 089
Revises: 088
Create Date: 2026-06-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "089"
down_revision: Union[str, None] = "088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("ticker", sa.String(length=30), nullable=True))
    op.add_column("reports", sa.Column("side", sa.String(length=8), nullable=True))
    op.add_column(
        "reports",
        sa.Column("linked_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_reports_linked_transaction",
        "reports",
        "transactions",
        ["linked_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_reports_linked_transaction", "reports", type_="foreignkey")
    op.drop_column("reports", "linked_transaction_id")
    op.drop_column("reports", "side")
    op.drop_column("reports", "ticker")
