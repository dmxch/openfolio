"""CHECK-Constraints reparieren und Report-Aktionen im Audit-Log zulassen.

Vollreview 2026-11-13:

- K078: Eine Neuinstallation baut das Schema per ``create_all`` und stempelt
  Alembic auf head. Zwölf CHECK-Constraints standen nur in Migrationen (058 bis
  085, 061, 063) und fehlten dort. Die Models deklarieren sie jetzt; diese
  Migration zieht sie auf bestehenden Instanzen nach. ``DROP CONSTRAINT IF
  EXISTS`` plus ``ADD``, damit sie auf beiden Schema-Herkünften läuft.
- K160: ``ck_api_write_log_action`` kennt neu die sechs Report-Vault-Aktionen.
  Der Audit-Log wird atomar mit der Mutation committet: fehlt der Wert im
  CHECK, rollt der gemeinsame Commit alles zurück. Diese Migration MUSS vor
  dem Code laufen, der die Aktionen schreibt.

Jede Constraint entsteht als NOT VALID und wird danach validiert. Verletzt
Altbestand einer nie geprüften Instanz die Regel, bleibt sie NOT VALID: sie
gilt dann für neue und geänderte Zeilen, und der Upgrade-Lauf bricht nicht ab
(``set -e`` im Entrypoint würde Backend und Worker sonst am Start hindern).
Die Migration meldet den Fall als Warnung. Nachziehen von Hand:
``ALTER TABLE <tabelle> VALIDATE CONSTRAINT <name>``.

Downgrade: stellt nur die Aktionsliste von Migration 085 wieder her. Liegen
schon report_*-Zeilen im Audit-Log, bleiben sie erhalten und die Constraint
bleibt NOT VALID. Die übrigen elf Constraints gehören auf migrierten Instanzen
schon zum Stand 099 und bleiben.

Revision ID: 102
Revises: 101
Create Date: 2026-11-13
"""

import logging
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "102"
down_revision: Union[str, None] = "101"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


# Stand nach Migration 085.
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
    "position_create",
    "position_update",
    "position_delete",
    "position_recalculate",
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
    "pe_holding_create",
    "pe_holding_update",
    "pe_holding_delete",
    "pe_valuation_create",
    "pe_valuation_update",
    "pe_valuation_delete",
    "pe_dividend_create",
    "pe_dividend_update",
    "pe_dividend_delete",
    "metal_item_create",
    "metal_item_update",
    "metal_item_delete",
    "metal_expense_create",
    "metal_expense_update",
    "metal_expense_delete",
    "dividend_confirm",
    "dividend_dismiss",
    "performance_recalculate",
    "performance_fix_total_chf",
    "performance_regen_snapshots",
    "performance_earnings_refresh",
    "screening_scan",
    "etf_sector_update",
    "etf_sector_delete",
    "eps_thresholds_update",
    "resistance_update",
    "watchlist_tag_add",
    "watchlist_tag_remove",
    "settings_update",
    "alert_pref_update",
    "onboarding_update",
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
    "import_parse",
    "import_confirm",
    "import_profile_create",
    "import_profile_delete",
)

# Report-Vault (K160).
_REPORT_ACTIONS = (
    "report_upload",
    "report_update",
    "report_delete",
    "report_prune",
    "report_archive",
    "report_unarchive",
)

_NEW_ACTIONS = _OLD_ACTIONS + _REPORT_ACTIONS


def _action_clause(actions: tuple[str, ...]) -> str:
    return "action IN (" + ",".join(f"'{a}'" for a in actions) + ")"


# (Tabelle, Name, Bedingung) — Wortlaut wie in den Migrationen 061 und 063.
_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("api_write_log", "ck_api_write_log_action", _action_clause(_NEW_ACTIONS)),
    ("pending_orders", "ck_pending_orders_side", "side IN ('buy', 'sell')"),
    (
        "pending_orders",
        "ck_pending_orders_status",
        "status IN ('open', 'filled', 'cancelled')",
    ),
    (
        "pending_orders",
        "ck_pending_orders_expiry_type",
        "expiry_type IN ('gtc', 'day', 'gtd')",
    ),
    ("pending_orders", "ck_pending_orders_shares_positive", "shares > 0"),
    ("pending_orders", "ck_pending_orders_limit_positive", "limit_price > 0"),
    (
        "pending_orders",
        "ck_pending_orders_stop_positive",
        "stop_price IS NULL OR stop_price > 0",
    ),
    (
        "pending_orders",
        "ck_pending_orders_gtd_date",
        "(expiry_type = 'gtd' AND expiry_date IS NOT NULL) "
        "OR (expiry_type <> 'gtd' AND expiry_date IS NULL)",
    ),
    ("buckets", "ck_buckets_kind", "kind IN ('user', 'system')"),
    (
        "buckets",
        "ck_buckets_system_role",
        "system_role IS NULL OR system_role IN "
        "('liquid_default', 'real_estate', 'private_equity', 'pension')",
    ),
    (
        "buckets",
        "ck_buckets_user_no_system_role",
        "kind = 'system' OR system_role IS NULL",
    ),
    (
        "position_bucket_history",
        "ck_pbh_changed_by",
        "changed_by IN ('user', 'import', 'migration', 'rule', 'migration_rollback')",
    ),
)


def _replace_check(table: str, name: str, clause: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({clause}) NOT VALID")
    bind = op.get_bind()
    try:
        # Savepoint: eine gescheiterte Validierung darf die Transaktion des
        # ganzen Upgrade-Laufs nicht mitreissen.
        with bind.begin_nested():
            bind.execute(sa.text(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}"))
    except sa.exc.IntegrityError:
        logger.warning(
            "%s: existing rows in %s violate the constraint. It stays NOT VALID and "
            "applies to new and changed rows only. Fix the rows, then run: "
            "ALTER TABLE %s VALIDATE CONSTRAINT %s",
            name, table, table, name,
        )


def upgrade() -> None:
    for table, name, clause in _CHECKS:
        _replace_check(table, name, clause)


def downgrade() -> None:
    _replace_check(
        "api_write_log", "ck_api_write_log_action", _action_clause(_OLD_ACTIONS)
    )
