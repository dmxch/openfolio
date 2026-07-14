"""Assetklasse 'bond' (Anleihen) im AssetType-Enum ergänzen.

Börsengehandelte Bond-ETFs/-Fonds bekommen eine eigene Assetklasse — bisher lagen
sie als type='etf' im Bestand und sind doch weder Cash noch Aktien. Der PG-Enum
'assettype' wird von positions.type UND watchlist.type geteilt
(models/watchlist.py:27), ein einziges ALTER TYPE deckt daher beide Tabellen ab.

Bewusst reines DDL, kein UPDATE bestehender Zeilen auf 'bond':
  - alembic/env.py umschliesst den gesamten upgrade-Lauf mit EINER Transaktion.
    PostgreSQL verbietet die Verwendung eines frisch per ADD VALUE angelegten
    Enum-Werts in derselben Transaktion ("unsafe use of new value of enum type").
    Ein UPDATE im selben Lauf würde die Migration und damit — wegen `set -e` in
    entrypoint.sh — den Start von Backend und Worker hart brechen.
  - Es gibt ohnehin kein sicheres Auswahlkriterium: count_as_cash ist kein
    Bond-Marker, das Flag tragen im Multi-User-Betrieb auch echte
    CHF-Geldmarktfonds, die ETF bleiben sollen.
Die Umstellung der betroffenen Positionen (IB01.L) erfolgt deshalb bewusst
manuell durch den Nutzer über die UI.

Revision ID: 097
Revises: 096
Create Date: 2026-07-14
"""

from typing import Union

from alembic import op

revision: str = "097"
down_revision: Union[str, None] = "096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS hält die Migration idempotent: je nach Bootstrap-Pfad legt
    # Base.metadata.create_all() den Enum direkt aus dem Model an (entrypoint.sh
    # bei frischer DB, tests/conftest.py) — dort bringt AssetType den Wert schon
    # mit, während die Migration gegen gewachsene DBs noch laufen muss. Ohne
    # Guard würde "label already exists" den Deploy abbrechen.
    op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'bond'")


def downgrade() -> None:
    # No-op: PostgreSQL kann einen Enum-Wert nicht entfernen (kein DROP VALUE).
    # Ein echter Rückbau hiesse Typ neu anlegen, alle Spalten umhängen, alten
    # Typ droppen — unverhältnismässig für einen rein additiven Wert.
    # Achtung: Nach einem Code-Rollback auf eine Version ohne AssetType.bond
    # wirft jede verbliebene Zeile mit type='bond' beim Laden einen LookupError
    # (auch in watchlist.type). Solche Zeilen vor einem Rollback manuell auf
    # 'etf' zurücksetzen.
    pass
