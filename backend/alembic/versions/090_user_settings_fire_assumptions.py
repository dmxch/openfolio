"""Fuege user_settings.fire_assumptions (JSON) hinzu — serverseitige FIRE-Annahmen.

Die FIRE-/Kapital-Projektion (Performance-Seite) hielt ihre Annahmen
(Kapitalbasis, Renditen, Sparrate, Entnahmerate, Ziel-Ausgaben) bisher nur in
localStorage — also pro Browser, nicht geraeteuebergreifend. Diese Spalte
persistiert sie pro User. NULL = Service-Defaults (kein Backfill noetig).

Revision ID: 090
Revises: 089
Create Date: 2026-06-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "090"
down_revision: Union[str, None] = "089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("fire_assumptions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_settings", "fire_assumptions")
