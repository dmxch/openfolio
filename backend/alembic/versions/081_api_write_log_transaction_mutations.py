"""Erweitere api_write_log.action-Whitelist um Transaktions-Mutationen.

Mit dem externen ``PUT`` und ``DELETE /api/v1/external/transactions/{id}``
(volle Schreib-Paritaet zum UI) braucht die ``action``-Spalte zwei weitere
Werte: ``transaction_update`` und ``transaction_delete``.

Wie 080: der Audit-Log wird atomar mit der Mutation committet — fehlt der Wert
im CHECK-Constraint, rollt der gemeinsame Commit alles zurueck und der Endpoint
ist unbenutzbar.

Revision ID: 081
Revises: 080
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op


revision: str = "081"
down_revision: Union[str, None] = "080"
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
    "transaction_create",
)

_NEW_ACTIONS = _OLD_ACTIONS + (
    "transaction_update",
    "transaction_delete",
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
