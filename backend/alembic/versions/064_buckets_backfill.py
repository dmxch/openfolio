"""Bucket-Feature Backfill (Step 2 von 2).

Per-User-transaktionale Migration:
  - Wenn User mindestens 1 Position mit position_type IN ('core', 'satellite'):
      → Erzeuge User-Buckets "Core" und "Satellite" (mit Drawdown-Bremsen-
        Defaults aus dem v2-Template). Mappe Positionen entsprechend.
      → Setze noticed_buckets_migration=false (triggert Onboarding-Modal).
  - Sonst: keine User-Buckets, alle liquiden Positionen in 'Alle Positionen'.
  - PE/Real-Estate/Pension-Positionen werden anhand .type den System-Buckets
    zugeordnet.
  - Nach Backfill: ALTER positions.bucket_id SET NOT NULL.

Granularitaet: ein BEGIN/COMMIT pro User. Bei Exception in einem User wird der
gesamte Migration-Lauf abgebrochen — bei Production-Deployment muessen vorher
Stage-Tests gegen einen anonymisierten Prod-Dump gegruent sein (siehe Plan §8.5).

Revision ID: 064
Revises: 063
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "064"
down_revision: Union[str, None] = "063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CORE_RISK_RULES = (
    '{"drawdown_brake_pct": 6.0, "drawdown_brake_active": true, '
    '"stop_loss_method_default": null}'
)
_SATELLITE_RISK_RULES = (
    '{"drawdown_brake_pct": 15.0, "drawdown_brake_active": true, '
    '"stop_loss_method_default": "trailing_pct", '
    '"stop_loss_default_pct": 8.0}'
)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Liquide Default-Positionen → liquid_default-Bucket
    conn.execute(sa.text(
        """
        UPDATE positions p
        SET bucket_id = b.id
        FROM buckets b
        WHERE b.user_id = p.user_id
          AND b.system_role = 'liquid_default'
          AND p.type IN ('stock', 'etf', 'crypto', 'commodity', 'cash')
          AND p.bucket_id IS NULL;
        """
    ))

    # 2. Special-Asset-Types → System-Buckets
    conn.execute(sa.text(
        """
        UPDATE positions p
        SET bucket_id = b.id
        FROM buckets b
        WHERE b.user_id = p.user_id
          AND p.type = 'real_estate'
          AND b.system_role = 'real_estate'
          AND p.bucket_id IS NULL;
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE positions p
        SET bucket_id = b.id
        FROM buckets b
        WHERE b.user_id = p.user_id
          AND p.type = 'private_equity'
          AND b.system_role = 'private_equity'
          AND p.bucket_id IS NULL;
        """
    ))
    conn.execute(sa.text(
        """
        UPDATE positions p
        SET bucket_id = b.id
        FROM buckets b
        WHERE b.user_id = p.user_id
          AND p.type = 'pension'
          AND b.system_role = 'pension'
          AND p.bucket_id IS NULL;
        """
    ))

    # 3. Konditionaler Backfill fuer User mit position_type
    users_with_position_type = conn.execute(sa.text(
        """
        SELECT DISTINCT user_id
        FROM positions
        WHERE position_type IN ('core', 'satellite');
        """
    )).fetchall()

    for (user_id,) in users_with_position_type:
        # Pro User: Core + Satellite Buckets, dann Re-Map
        conn.execute(
            sa.text(
                """
                INSERT INTO buckets
                    (user_id, name, kind, color, benchmark, risk_rules, sort_order)
                VALUES
                    (:uid, 'Core', 'user', '#3b82f6', 'URTH',
                     CAST(:core_rules AS jsonb), 10)
                ON CONFLICT (user_id, name) DO NOTHING;
                """
            ),
            {"uid": user_id, "core_rules": _CORE_RISK_RULES},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO buckets
                    (user_id, name, kind, color, benchmark, risk_rules, sort_order)
                VALUES
                    (:uid, 'Satellite', 'user', '#f59e0b', '^GSPC',
                     CAST(:sat_rules AS jsonb), 20)
                ON CONFLICT (user_id, name) DO NOTHING;
                """
            ),
            {"uid": user_id, "sat_rules": _SATELLITE_RISK_RULES},
        )

        # Re-Map Positionen
        conn.execute(
            sa.text(
                """
                UPDATE positions p
                SET bucket_id = b.id
                FROM buckets b
                WHERE b.user_id = p.user_id
                  AND b.user_id = :uid
                  AND p.position_type = 'core'
                  AND b.name = 'Core'
                  AND b.kind = 'user';
                """
            ),
            {"uid": user_id},
        )
        conn.execute(
            sa.text(
                """
                UPDATE positions p
                SET bucket_id = b.id
                FROM buckets b
                WHERE b.user_id = p.user_id
                  AND b.user_id = :uid
                  AND p.position_type = 'satellite'
                  AND b.name = 'Satellite'
                  AND b.kind = 'user';
                """
            ),
            {"uid": user_id},
        )

        # Onboarding-Modal triggern
        conn.execute(
            sa.text(
                """
                UPDATE user_settings
                SET noticed_buckets_migration = false
                WHERE user_id = :uid;
                """
            ),
            {"uid": user_id},
        )

    # 4. Andere User: Modal-Flag auf true (kein Modal noetig)
    conn.execute(sa.text(
        """
        UPDATE user_settings us
        SET noticed_buckets_migration = true
        WHERE NOT EXISTS (
            SELECT 1 FROM positions p
            WHERE p.user_id = us.user_id
              AND p.position_type IN ('core', 'satellite')
        );
        """
    ))

    # 5. Sanity-Check: alle Positionen haben jetzt einen Bucket
    missing = conn.execute(sa.text(
        "SELECT COUNT(*) FROM positions WHERE bucket_id IS NULL;"
    )).scalar()
    if missing and missing > 0:
        raise RuntimeError(
            f"Backfill incomplete: {missing} positions without bucket_id. "
            "Check positions.type distribution."
        )

    # 6. NOT NULL Constraint setzen
    op.alter_column("positions", "bucket_id", nullable=False)


def downgrade() -> None:
    # bucket_id wieder nullable, Re-Mappings nicht rueckgaengig gemacht
    # (Daten bleiben in positions.bucket_id, das Schema-Down ist in 063).
    op.alter_column("positions", "bucket_id", nullable=True)
