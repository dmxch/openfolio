"""Erweitere api_write_log.action-Whitelist um Watchlist-Add/Remove.

Mit der externen ``POST /watchlist`` und ``DELETE /watchlist/{ticker}`` API
brauchen wir zwei neue Werte fuer die ``action``-Spalte: ``watchlist_add``
und ``watchlist_remove``. SQLite unterstuetzt kein direktes Anpassen von
CHECK-Constraints, deshalb verwenden wir batch_alter_table — auf Postgres
fuehrt das zu einem normalen DROP/ADD CONSTRAINT.

Revision ID: 059
Revises: 058
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "059"
down_revision: Union[str, None] = "058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_ACTIONS = (
    "notes_replace",
    "notes_append",
    "notes_clear",
    "alert_create",
    "alert_update",
    "alert_delete",
    "watchlist_add",
    "watchlist_remove",
)

_OLD_ACTIONS = (
    "notes_replace",
    "notes_append",
    "notes_clear",
    "alert_create",
    "alert_update",
    "alert_delete",
)


def _check_clause(actions: tuple[str, ...]) -> str:
    return "action IN (" + ",".join(f"'{a}'" for a in actions) + ")"


def upgrade() -> None:
    with op.batch_alter_table("api_write_log") as batch:
        batch.drop_constraint("ck_api_write_log_action", type_="check")
        batch.create_check_constraint(
            "ck_api_write_log_action",
            _check_clause(_NEW_ACTIONS),
        )


def downgrade() -> None:
    with op.batch_alter_table("api_write_log") as batch:
        batch.drop_constraint("ck_api_write_log_action", type_="check")
        batch.create_check_constraint(
            "ck_api_write_log_action",
            _check_clause(_OLD_ACTIONS),
        )
