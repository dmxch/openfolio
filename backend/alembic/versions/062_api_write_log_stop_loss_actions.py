"""Erweitere api_write_log.action-Whitelist um Stop-Loss-Aktionen.

Mit der externen ``PATCH /positions/by-id/{id}/stop-loss`` und
``POST /portfolio/stop-loss/batch`` API brauchen wir zwei neue Werte fuer
die ``action``-Spalte: ``stop_loss_update`` und ``stop_loss_batch``.

Hintergrund: Seit v0.38.0 wird der Audit-Log VOR dem Service-Commit
geflusht (Finding #3 — Atomic-Commit mit dem Service). Dadurch wird ein
fehlender Constraint-Eintrag sofort zum 500er fuer den User, statt wie
vorher nur den Audit-Log still zu verlieren. Diese Migration schliesst
genau diese Luecke.

Revision ID: 062
Revises: 061
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = "062"
down_revision: Union[str, None] = "061"
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
)

_NEW_ACTIONS = _OLD_ACTIONS + (
    "stop_loss_update",
    "stop_loss_batch",
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
