"""Fuege etf_holdings.holding_sector hinzu — Issuer-nativer Sektor fuer Look-Through.

Die iShares-Holdings-CSV liefert eine GICS-"Sector"-Spalte. Persistiert (auf das
OpenFolio-Sektor-Vokabular gemappt) ermoeglicht sie den Sektor-Look-Through fuer
Non-US-/EM-ETFs, wo classify_tickers_bulk (ticker_industries, US-zentriert) fast
nichts kennt (EM-ETFs sonst <1 % Coverage -> Suppression). nullable — FMP-US-
Holdings = None und fallen auf classify_tickers_bulk zurueck.

Revision ID: 088
Revises: 087
Create Date: 2026-06-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "088"
down_revision: Union[str, None] = "087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("etf_holdings", sa.Column("holding_sector", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("etf_holdings", "holding_sector")
