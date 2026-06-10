"""Erzwinge NOT NULL auf Spalten, die das Model bereits als NOT NULL deklariert.

Drift zwischen Models und Migrations-Stand (Review 2026-06-10, M6): die
Models deklarieren reports.tags/created_at/updated_at,
screening_results.signals/created_at sowie
screening_scans.started_at/steps/result_count als NOT NULL, die
Migrationen 041/077 hatten die Spalten aber nullable angelegt. Die
Model-Intention ist hier richtig — vor dem SET NOT NULL werden allfällige
NULL-Zeilen mit den sinnvollen Defaults befüllt (entsprechend den
server_defaults aus 041 bzw. den Python-Defaults der Models).

Revision ID: 083
Revises: 082
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "083"
down_revision: Union[str, None] = "082"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (Tabelle, Spalte, Backfill-SQL-Ausdruck, Spaltentyp für alter_column)
_COLUMNS: list[tuple[str, str, str, sa.types.TypeEngine]] = [
    ("reports", "tags", "'[]'::jsonb", postgresql.JSONB(astext_type=sa.Text())),
    ("reports", "created_at", "now()", sa.DateTime()),
    ("reports", "updated_at", "now()", sa.DateTime()),
    ("screening_results", "signals", "'{}'::jsonb", postgresql.JSONB(astext_type=sa.Text())),
    ("screening_results", "created_at", "now()", sa.DateTime()),
    ("screening_scans", "started_at", "now()", sa.DateTime()),
    ("screening_scans", "steps", "'[]'::jsonb", postgresql.JSONB(astext_type=sa.Text())),
    ("screening_scans", "result_count", "0", sa.Integer()),
]


def upgrade() -> None:
    for table, column, default_expr, col_type in _COLUMNS:
        # Erst NULL-Zeilen mit dem sinnvollen Default befüllen, sonst
        # schlägt das SET NOT NULL auf Bestandsdaten fehl.
        op.execute(
            f"UPDATE {table} SET {column} = {default_expr} WHERE {column} IS NULL"
        )
        op.alter_column(
            table,
            column,
            existing_type=col_type,
            nullable=False,
        )


def downgrade() -> None:
    for table, column, _default_expr, col_type in reversed(_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=col_type,
            nullable=True,
        )
