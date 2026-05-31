"""Add reports.archived_at (Soft-Delete/Archiv).

Archivieren als reversibles Sicherheitsnetz neben dem harten DELETE:
NULL = aktiv, Timestamp = archiviert (eigene Vault-Ansicht via ?archived=true).
Der Sync-Reconciliation-Pfad (POST /reports/prune) archiviert Waisen statt
sie hart zu loeschen; ein Re-Upload derselben Quelldatei holt den Report
zurueck (archived_at -> NULL).

Revision ID: 078
Revises: 077
Create Date: 2026-05-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "078"
down_revision: Union[str, None] = "077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("archived_at", sa.DateTime(), nullable=True))
    # Partieller Index: nur archivierte Zeilen — beschleunigt die Archiv-Ansicht,
    # ohne die (haeufige) Aktiv-Liste zu belasten. SQLite ignoriert das postgres_where
    # nicht, kann aber partielle Indizes — fuer den Test-Fallback ok.
    op.create_index(
        "ix_reports_user_archived",
        "reports",
        ["user_id", "archived_at"],
        postgresql_where=sa.text("archived_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_reports_user_archived", table_name="reports")
    op.drop_column("reports", "archived_at")
