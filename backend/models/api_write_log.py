"""Audit-Log fuer Schreibzugriffe ueber die externe API.

Loggt **Metadaten** zu jedem Notes/Alert-Schreibvorgang via X-API-Key:
Token, User, Ticker, Action und Zeichen-Counts vor/nach (bei Notes-Aktionen).
Der Inhalt der Notiz wird **bewusst nie geloggt** — er ist verschluesselt
gespeichert, und das Audit-Log soll nicht zum Klartext-Leak werden.
"""

import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


# Erlaubte Werte von ``action``. Der Audit-Log wird atomar mit der Mutation
# committet: ein Wert, der hier fehlt, rollt den ganzen Schreibvorgang zurück.
# Neue Aktion = hier eintragen UND per Migration in ck_api_write_log_action
# aufnehmen (zuletzt Migration 102); tests/test_vr11_schema.py vergleicht beide.
API_WRITE_LOG_ACTIONS: tuple[str, ...] = (
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
    # Report-Vault (historisch: Funktion entfernt, die Aktionen bleiben fuer
    # bestehende Log-Zeilen und den CHECK-Constraint aus Migration 102 gueltig)
    "report_upload",
    "report_update",
    "report_delete",
    "report_prune",
    "report_archive",
    "report_unarchive",
)


class ApiWriteLog(Base):
    __tablename__ = "api_write_log"
    __table_args__ = (
        # Existiert in der DB (Migrations-Stand) — hier nachdeklariert,
        # damit Model und DB-Schema übereinstimmen (alembic check).
        Index("ix_api_write_log_created_at", "created_at"),
        CheckConstraint(
            "action IN (" + ",".join(f"'{a}'" for a in API_WRITE_LOG_ACTIONS) + ")",
            name="ck_api_write_log_action",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    char_count_before: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
