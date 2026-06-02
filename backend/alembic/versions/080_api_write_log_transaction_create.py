"""Erweitere api_write_log.action-Whitelist um ``transaction_create``.

Mit dem externen ``POST /api/v1/external/transactions`` (Schreib-Paritaet zum
UI) braucht die ``action``-Spalte einen neuen Wert: ``transaction_create``.

Hintergrund (vgl. 062): Der Audit-Log wird atomar mit der Buchung committet.
Fehlt der Wert im CHECK-Constraint, schlaegt der gemeinsame Commit fehl und
rollt die Transaktion mit zurueck — ohne diesen Eintrag ist der Endpoint
unbenutzbar. Diese Migration schliesst die Luecke.

Revision ID: 080
Revises: 079
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op


revision: str = "080"
down_revision: Union[str, None] = "079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_ACTIONS = (
    "notes_replace",
    "notes_append",
    "notes_clear",
    "alert_create",
    "alert_update",
    "alert_delete",
    "watchlist_add",
    "watchlist_remove",
    "pending_order_create",
    "pending_order_update",
    "pending_order_cancel",
    "pending_order_fill",
    "stop_loss_update",
    "stop_loss_batch",
)

_NEW_ACTIONS = _OLD_ACTIONS + ("transaction_create",)


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
