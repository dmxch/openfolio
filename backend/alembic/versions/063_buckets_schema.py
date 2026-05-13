"""Bucket-Feature Schema (Step 1 von 2).

Idempotente Schema-Migration:
  - buckets-Tabelle
  - position_bucket_history (Audit-Trail)
  - bucket_snapshots (parallel zu portfolio_snapshots)
  - bucket_alert_log (Idempotenz-Schutz fuer Drawdown-Bremsen-Alerts)
  - positions.bucket_id (FK, NULL erlaubt — NOT NULL erst in 064 nach Backfill)
  - user_settings.noticed_buckets_migration (Onboarding-Flag)
  - System-Buckets pro User: Alle Positionen, Immobilien, Private Equity, Vorsorge

Diese Migration ist idempotent: Bei Fehler kann sie neu gestartet werden.
Es werden keine Position.bucket_id-Werte gesetzt (das macht 064).

Revision ID: 063
Revises: 062
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "063"
down_revision: Union[str, None] = "062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. buckets-Tabelle
    # ------------------------------------------------------------------
    op.create_table(
        "buckets",
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
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column(
            "kind",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
        sa.Column("system_role", sa.String(20), nullable=True),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("benchmark", sa.String(20), nullable=True),
        sa.Column("target_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("target_chf", sa.Numeric(14, 2), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "sort_order",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("risk_rules", JSONB, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_bucket_user_name"),
        sa.CheckConstraint(
            "kind IN ('user', 'system')",
            name="ck_buckets_kind",
        ),
        sa.CheckConstraint(
            "system_role IS NULL OR system_role IN "
            "('liquid_default', 'real_estate', 'private_equity', 'pension')",
            name="ck_buckets_system_role",
        ),
        sa.CheckConstraint(
            "(target_pct IS NULL) OR (target_chf IS NULL)",
            name="ck_buckets_target_xor",
        ),
        sa.CheckConstraint(
            "kind = 'system' OR system_role IS NULL",
            name="ck_buckets_user_no_system_role",
        ),
    )
    op.create_index("idx_buckets_user_id", "buckets", ["user_id"])
    op.create_index("idx_buckets_user_kind", "buckets", ["user_id", "kind"])
    op.create_index(
        "idx_buckets_user_system_role",
        "buckets",
        ["user_id", "system_role"],
        unique=True,
        postgresql_where=sa.text("system_role IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 2. positions.bucket_id (NULL erlaubt — Backfill in 064)
    # ------------------------------------------------------------------
    op.add_column(
        "positions",
        sa.Column(
            "bucket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buckets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_positions_bucket_id", "positions", ["bucket_id"])

    # ------------------------------------------------------------------
    # 3. position_bucket_history (Audit-Trail)
    # ------------------------------------------------------------------
    op.create_table(
        "position_bucket_history",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "position_id",
            UUID(as_uuid=True),
            sa.ForeignKey("positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_bucket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buckets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_bucket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buckets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "changed_by",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
        sa.Column("note", sa.Text, nullable=True),
        sa.CheckConstraint(
            "changed_by IN ('user', 'import', 'migration', 'rule', 'migration_rollback')",
            name="ck_pbh_changed_by",
        ),
    )
    op.create_index(
        "idx_pbh_position",
        "position_bucket_history",
        ["position_id", "changed_at"],
    )

    # ------------------------------------------------------------------
    # 4. bucket_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "bucket_snapshots",
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
        sa.Column(
            "bucket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buckets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column(
            "total_value_chf",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cash_chf",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "net_cash_flow_chf",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "running_peak_chf",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.UniqueConstraint(
            "user_id", "bucket_id", "date", name="uq_bucket_snapshot"
        ),
    )
    op.create_index(
        "idx_bucket_snapshot_user_date",
        "bucket_snapshots",
        ["user_id", "date"],
    )
    op.create_index(
        "idx_bucket_snapshot_bucket_date",
        "bucket_snapshots",
        ["bucket_id", "date"],
    )

    # ------------------------------------------------------------------
    # 5. bucket_alert_log (Idempotenz fuer Drawdown-Bremsen-Alerts)
    # ------------------------------------------------------------------
    op.create_table(
        "bucket_alert_log",
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
        sa.Column(
            "bucket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buckets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alert_type", sa.String(40), nullable=False),
        sa.Column("alert_date", sa.Date, nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "bucket_id", "alert_type", "alert_date",
            name="uq_bucket_alert_log",
        ),
    )
    op.create_index(
        "idx_bucket_alert_user_date",
        "bucket_alert_log",
        ["user_id", "alert_date"],
    )

    # ------------------------------------------------------------------
    # 6. user_settings.noticed_buckets_migration
    # ------------------------------------------------------------------
    op.add_column(
        "user_settings",
        sa.Column(
            "noticed_buckets_migration",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ------------------------------------------------------------------
    # 7. System-Buckets pro existierendem User erstellen
    # ------------------------------------------------------------------
    # Wird per Raw-SQL via INSERT ... SELECT gemacht: idempotent durch
    # ON CONFLICT (user_id, name) DO NOTHING.
    op.execute(
        """
        INSERT INTO buckets (user_id, name, kind, system_role, sort_order, color)
        SELECT
            u.id,
            CASE r.system_role
                WHEN 'liquid_default' THEN 'Alle Positionen'
                WHEN 'real_estate' THEN 'Immobilien'
                WHEN 'private_equity' THEN 'Private Equity'
                WHEN 'pension' THEN 'Vorsorge'
            END AS name,
            'system' AS kind,
            r.system_role,
            r.sort_order,
            r.color
        FROM users u
        CROSS JOIN (
            VALUES
                ('liquid_default', 0, '#64748b'),
                ('real_estate', 90, '#a3a3a3'),
                ('private_equity', 91, '#a3a3a3'),
                ('pension', 92, '#a3a3a3')
        ) AS r(system_role, sort_order, color)
        ON CONFLICT (user_id, name) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_column("user_settings", "noticed_buckets_migration")
    op.drop_index("idx_bucket_alert_user_date", table_name="bucket_alert_log")
    op.drop_table("bucket_alert_log")
    op.drop_index("idx_bucket_snapshot_bucket_date", table_name="bucket_snapshots")
    op.drop_index("idx_bucket_snapshot_user_date", table_name="bucket_snapshots")
    op.drop_table("bucket_snapshots")
    op.drop_index("idx_pbh_position", table_name="position_bucket_history")
    op.drop_table("position_bucket_history")
    op.drop_index("idx_positions_bucket_id", table_name="positions")
    op.drop_column("positions", "bucket_id")
    op.drop_index("idx_buckets_user_system_role", table_name="buckets")
    op.drop_index("idx_buckets_user_kind", table_name="buckets")
    op.drop_index("idx_buckets_user_id", table_name="buckets")
    op.drop_table("buckets")
