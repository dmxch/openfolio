"""Add etf_holdings table for Core-Overlap-Flag (Phase B).

Globale Tabelle (nicht user-spezifisch) — ein ETF-Holding ist eine
universelle Tatsache (NVDA in OEF mit 7% Gewicht gilt für alle User).
Composite-PK auf (etf_ticker, holding_ticker) für UPSERT-Semantik beim
wöchentlichen FMP-Refresh. Index auf holding_ticker für Reverse-Lookup
("welche ETFs enthalten NVDA?") — der Hauptpfad des Core-Overlap-Banners.

``as_of`` ist der Stichtag laut FMP; ``updated_at`` ist der Pull-Zeitpunkt
(Internal-Diagnose, nicht user-facing — UI nutzt as_of oder kommuniziert
"Stichtag unbekannt", verhindert Falsch-Sicherheit).

Revision ID: 056
Revises: 055
Create Date: 2026-04-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "056"
down_revision: Union[str, None] = "055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "etf_holdings",
        sa.Column("etf_ticker", sa.String(30), primary_key=True),
        sa.Column("holding_ticker", sa.String(30), primary_key=True),
        sa.Column("holding_name", sa.String(200), nullable=True),
        sa.Column("weight_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("as_of", sa.Date, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_etf_holdings_holding_ticker",
        "etf_holdings",
        ["holding_ticker"],
    )


def downgrade() -> None:
    op.drop_index("ix_etf_holdings_holding_ticker", table_name="etf_holdings")
    op.drop_table("etf_holdings")
