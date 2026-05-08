"""Add pending_orders table + extend api_write_log.action whitelist.

Manuell gepflegte Liste offener Limit-Orders (beim Broker platziert, noch
nicht gefilled). Source of Truth fuer den User und die externe API; Claude
liest und schreibt via X-API-Key (Watchlist-Pattern).

Status-Enum bewusst auf ``open|filled|cancelled`` reduziert. ``expired`` ist
ein computed Wert (Service-Layer), nicht persistierter DB-Zustand — die
GTD-Expiry wird beim Read berechnet, kein Worker-Job noetig.

``linked_transaction_id`` wird durch den /fill-Endpoint gesetzt, sobald aus
einer Pending Order eine reale Transaktion entsteht (atomar mit Status-
Wechsel auf ``filled``). ``ON DELETE SET NULL`` haelt die Pending Order
auch dann erhalten, wenn die zugehoerige Transaktion spaeter geloescht wird.

Revision ID: 061
Revises: 060
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "061"
down_revision: Union[str, None] = "060"
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
)

_NEW_ACTIONS = _OLD_ACTIONS + (
    "pending_order_create",
    "pending_order_update",
    "pending_order_cancel",
    "pending_order_fill",
)


def _check_clause(actions: tuple[str, ...]) -> str:
    return "action IN (" + ",".join(f"'{a}'" for a in actions) + ")"


def upgrade() -> None:
    op.create_table(
        "pending_orders",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(30), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("shares", sa.Numeric(20, 8), nullable=False),
        sa.Column("limit_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("stop_price", sa.Numeric(14, 4), nullable=True),
        sa.Column(
            "currency",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column(
            "expiry_type",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'gtc'"),
        ),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("broker", sa.String(50), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "linked_transaction_id",
            UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "notes_last_api_write_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("notes_last_api_token_name", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "side IN ('buy', 'sell')",
            name="ck_pending_orders_side",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'filled', 'cancelled')",
            name="ck_pending_orders_status",
        ),
        sa.CheckConstraint(
            "expiry_type IN ('gtc', 'day', 'gtd')",
            name="ck_pending_orders_expiry_type",
        ),
        sa.CheckConstraint(
            "shares > 0",
            name="ck_pending_orders_shares_positive",
        ),
        sa.CheckConstraint(
            "limit_price > 0",
            name="ck_pending_orders_limit_positive",
        ),
        sa.CheckConstraint(
            "stop_price IS NULL OR stop_price > 0",
            name="ck_pending_orders_stop_positive",
        ),
        sa.CheckConstraint(
            "(expiry_type = 'gtd' AND expiry_date IS NOT NULL) "
            "OR (expiry_type <> 'gtd' AND expiry_date IS NULL)",
            name="ck_pending_orders_gtd_date",
        ),
    )
    op.create_index(
        "idx_pending_orders_user_status",
        "pending_orders",
        ["user_id", "status"],
    )
    op.create_index(
        "idx_pending_orders_user_ticker",
        "pending_orders",
        ["user_id", "ticker"],
    )

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

    op.drop_index("idx_pending_orders_user_ticker", table_name="pending_orders")
    op.drop_index("idx_pending_orders_user_status", table_name="pending_orders")
    op.drop_table("pending_orders")
