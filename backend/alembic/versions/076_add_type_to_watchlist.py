"""Add nullable `type` (AssetType) column to watchlist.

Schliesst die dokumentierte Universum-Luecke (Backlog Iteration 4): Watchlist-
Tickers wurden bisher nicht type-gefiltert, daher konnten Crypto-Pairs wie
ETH-USD gegen FMP-Equity-Endpoints laufen und 404en. Die neue Spalte erlaubt
explizites Tagging; resolve_equity_universe() filtert ab jetzt auf
(type IS NULL OR type='stock').

NULL = unbekannt/vermutlich Equity (Legacy-Rows + manuelle Adds ohne
Klassifikation). Der Backfill markiert nur eindeutige Crypto-Pairs — eine
ETF-/Stock-Unterscheidung braucht einen Provider-Lookup und bleibt spaeter.

Revision ID: 076
Revises: 075
Create Date: 2026-05-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "076"
down_revision: Union[str, None] = "075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Muss mit _CRYPTO_QUOTE_SUFFIXES in services/screening/universe.py uebereinstimmen.
_CRYPTO_QUOTE_SUFFIXES = ("-USD", "-EUR", "-GBP", "-USDT", "-USDC", "-BTC", "-ETH")


def upgrade() -> None:
    # Bestehenden pg-Enum referenzieren, nicht neu anlegen.
    asset_enum = postgresql.ENUM(name="assettype", create_type=False)
    op.add_column("watchlist", sa.Column("type", asset_enum, nullable=True))

    # Backfill: eindeutige Crypto-Quote-Pairs als crypto markieren.
    # B-Shares (BRK-B, BF-B) bleiben NULL, da kein Fiat-/Stablecoin-Suffix.
    where = " OR ".join(f"UPPER(ticker) LIKE '%{suf}'" for suf in _CRYPTO_QUOTE_SUFFIXES)
    op.execute(
        f"UPDATE watchlist SET type = 'crypto' WHERE type IS NULL AND ({where})"
    )


def downgrade() -> None:
    op.drop_column("watchlist", "type")
