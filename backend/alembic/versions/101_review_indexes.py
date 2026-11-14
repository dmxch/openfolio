"""Vollreview 2026-11-13: fehlende Indizes anlegen, doppelten Index entfernen.

- K127: ``reports.linked_transaction_id`` hat einen FK mit ON DELETE SET NULL,
  aber keinen Index. Je gelöschter Transaktion lief ein Seq-Scan über die
  Reports aller Nutzer. Partieller Index, weil die meisten Reports keinen Link
  haben. Dazu ``property_id`` der drei Immobilien-Kindtabellen (FK mit CASCADE).
- K132: der Minutenjob ``check_price_alerts`` liest nur offene Alarme
  (``is_active AND NOT is_triggered``). Ausgelöste Zeilen bleiben liegen; der
  partielle Index hält sie aus dem Scan heraus.
- GS12: ``ix_eps_quarterly_ticker_period`` deckt exakt die Spalten von
  ``uq_eps_quarterly_ticker_period``. Jeder EPS-Upsert pflegte beide.

Idempotent (IF NOT EXISTS / IF EXISTS). Die Indizes entstehen ohne
CONCURRENTLY, weil der ganze Upgrade-Lauf eine Transaktion ist; die Tabellen
sind klein.

Revision ID: 101
Revises: 100
Create Date: 2026-11-13
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "101"
down_revision: Union[str, None] = "100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_reports_linked_transaction",
        "reports",
        ["linked_transaction_id"],
        postgresql_where=sa.text("linked_transaction_id IS NOT NULL"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_mortgages_property_id", "mortgages", ["property_id"], if_not_exists=True
    )
    op.create_index(
        "ix_property_expenses_property_id",
        "property_expenses",
        ["property_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_property_income_property_id",
        "property_income",
        ["property_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_price_alerts_open",
        "price_alerts",
        ["ticker"],
        postgresql_where=sa.text("is_active AND NOT is_triggered"),
        if_not_exists=True,
    )
    op.drop_index(
        "ix_eps_quarterly_ticker_period", table_name="eps_quarterly", if_exists=True
    )


def downgrade() -> None:
    op.create_index(
        "ix_eps_quarterly_ticker_period",
        "eps_quarterly",
        ["ticker", "period_end"],
        if_not_exists=True,
    )
    op.drop_index("ix_price_alerts_open", table_name="price_alerts", if_exists=True)
    op.drop_index(
        "ix_property_income_property_id", table_name="property_income", if_exists=True
    )
    op.drop_index(
        "ix_property_expenses_property_id",
        table_name="property_expenses",
        if_exists=True,
    )
    op.drop_index("ix_mortgages_property_id", table_name="mortgages", if_exists=True)
    op.drop_index("ix_reports_linked_transaction", table_name="reports", if_exists=True)
