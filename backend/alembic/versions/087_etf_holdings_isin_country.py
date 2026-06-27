"""Fuege etf_holdings.holding_isin + holding_country hinzu — fuer UCITS-Look-Through.

Issuer-Holdings-Quellen (iShares-CSV etc.) liefern Land (und teils ISIN) nativ mit.
holding_country (ISO-2) traegt den Laender-Look-Through UNABHAENGIG von der
Ticker-Resolution; holding_isin ist ein stabiler Identitaets-Anker, wo die Quelle
ihn liefert. Beide nullable — bestehende FMP-US-Holdings bleiben unveraendert.

Revision ID: 087
Revises: 086
Create Date: 2026-06-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "087"
down_revision: Union[str, None] = "086"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("etf_holdings", sa.Column("holding_isin", sa.String(length=20), nullable=True))
    op.add_column("etf_holdings", sa.Column("holding_country", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("etf_holdings", "holding_country")
    op.drop_column("etf_holdings", "holding_isin")
