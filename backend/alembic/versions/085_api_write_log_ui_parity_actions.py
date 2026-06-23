"""Erweitere api_write_log.action-Whitelist um alle UI-Paritaets-Aktionen (v0.45).

Mit der vollen Schreib-Paritaet der externen API (api/external_v1.py) zum UI —
Positionen, Immobilien, Private Equity, Edelmetalle, Dividenden, Buckets,
Performance-Aktionen, Screening, ETF-Sektoren, EPS-Schwellen, Analyse,
Settings/Onboarding und Import — braucht die ``action``-Spalte zahlreiche neue
Werte.

Wie 080/081: der Audit-Log wird atomar mit der Mutation committet — fehlt der
Wert im CHECK-Constraint, rollt der gemeinsame Commit alles zurueck und der
Endpoint ist unbenutzbar (Prod-500). Daher MUSS diese Migration vor dem Deploy
laufen.

Revision ID: 085
Revises: 084
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op


revision: str = "085"
down_revision: Union[str, None] = "084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Stand nach Migration 081 (transaction_update/_delete inklusive).
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
    "transaction_update",
    "transaction_delete",
)

# Neue UI-Paritaets-Aktionen (v0.45).
_NEW_PARITY_ACTIONS = (
    # Positionen
    "position_create",
    "position_update",
    "position_delete",
    "position_recalculate",
    # Immobilien
    "property_create",
    "property_update",
    "property_delete",
    "mortgage_create",
    "mortgage_update",
    "mortgage_delete",
    "property_expense_create",
    "property_expense_update",
    "property_expense_delete",
    "property_income_create",
    "property_income_update",
    "property_income_delete",
    # Private Equity
    "pe_holding_create",
    "pe_holding_update",
    "pe_holding_delete",
    "pe_valuation_create",
    "pe_valuation_update",
    "pe_valuation_delete",
    "pe_dividend_create",
    "pe_dividend_update",
    "pe_dividend_delete",
    # Edelmetalle
    "metal_item_create",
    "metal_item_update",
    "metal_item_delete",
    "metal_expense_create",
    "metal_expense_update",
    "metal_expense_delete",
    # Dividenden (Pending)
    "dividend_confirm",
    "dividend_dismiss",
    # Performance-Aktionen
    "performance_recalculate",
    "performance_fix_total_chf",
    "performance_regen_snapshots",
    "performance_earnings_refresh",
    # Screening
    "screening_scan",
    # ETF-Sektoren
    "etf_sector_update",
    "etf_sector_delete",
    # EPS-Scanner
    "eps_thresholds_update",
    # Analyse
    "resistance_update",
    "watchlist_tag_add",
    "watchlist_tag_remove",
    # Settings / Onboarding
    "settings_update",
    "alert_pref_update",
    "onboarding_update",
    # Buckets
    "bucket_create",
    "bucket_update",
    "bucket_delete",
    "bucket_from_template",
    "bucket_migration_rollback",
    "bucket_split_position",
    "bucket_move_position",
    "bucket_import_rule_create",
    "bucket_import_rule_del",
    "bucket_backfill_snapshots",
    "bucket_onboarding_dismiss",
    # Import
    "import_parse",
    "import_confirm",
    "import_profile_create",
    "import_profile_delete",
)

_NEW_ACTIONS = _OLD_ACTIONS + _NEW_PARITY_ACTIONS


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
