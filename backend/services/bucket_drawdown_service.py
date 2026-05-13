"""Drawdown-Bremse pro Bucket.

Wird taeglich vom Worker getriggert (siehe worker._check_bucket_drawdown_brakes).
Verwendet drawdown_service.get_max_drawdown(bucket_id=...) zur Berechnung und
schreibt bei Treffer einen idempotenten Eintrag in bucket_alert_log.

Gates:
  - bucket.risk_rules.drawdown_brake_active == True
  - bucket.deleted_at IS NULL
  - bucket.kind == 'user' (System-Buckets haben keine eigene Bremse)
  - bucket_age_days >= 7 (verhindert False-Positives bei zu junger Historie)

Idempotenz:
  - 1 Alert pro (user, bucket, alert_type, alert_date) via UNIQUE constraint.
  - Vorhandener Eintrag → kein erneuter Versand.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.bucket import Bucket, BucketAlertLog, BucketKind, BucketSnapshot
from models.user import User
from services.drawdown_service import get_max_drawdown

logger = logging.getLogger(__name__)

ALERT_TYPE = "drawdown_brake_bucket"
MIN_BUCKET_AGE_DAYS = 7


async def _bucket_age_days(
    db: AsyncSession, user_id: uuid.UUID, bucket_id: uuid.UUID
) -> int:
    """Alter des Buckets in Tagen, gemessen ab erstem BucketSnapshot.

    Wenn noch keine Snapshots: 0.
    """
    q = await db.execute(
        select(BucketSnapshot.date)
        .where(
            BucketSnapshot.user_id == user_id,
            BucketSnapshot.bucket_id == bucket_id,
        )
        .order_by(BucketSnapshot.date.asc())
        .limit(1)
    )
    first = q.scalar()
    if first is None:
        return 0
    return (date.today() - first).days


async def check_bucket_drawdown_brakes(db: AsyncSession) -> dict:
    """Sweep ueber alle User+aktiven Buckets, triggere Alerts wo Drawdown-
    Schwelle ueberschritten und kein Alert fuer heute existiert."""
    today = date.today()

    user_q = await db.execute(select(User).where(User.is_active.is_(True)))
    users = list(user_q.scalars().all())

    counters = {
        "checked": 0,
        "triggered": 0,
        "skipped_young": 0,
        "skipped_idempotent": 0,
        "skipped_inactive_rules": 0,
    }

    for user in users:
        bucket_q = await db.execute(
            select(Bucket).where(
                Bucket.user_id == user.id,
                Bucket.kind == BucketKind.user,
                Bucket.deleted_at.is_(None),
            )
        )
        buckets = list(bucket_q.scalars().all())

        for bucket in buckets:
            rules = bucket.risk_rules or {}
            if not rules.get("drawdown_brake_active", False):
                counters["skipped_inactive_rules"] += 1
                continue

            threshold_pct = float(rules.get("drawdown_brake_pct", 6.0))
            counters["checked"] += 1

            # Bucket-Age-Gate (R-7.2)
            age = await _bucket_age_days(db, user.id, bucket.id)
            if age < MIN_BUCKET_AGE_DAYS:
                counters["skipped_young"] += 1
                logger.debug(
                    "Bucket %s of user %s too young (%d days), skipping drawdown-brake",
                    bucket.id, user.id, age,
                )
                continue

            # Drawdown berechnen
            try:
                dd = await get_max_drawdown(
                    db,
                    user.id,
                    period="all",
                    bucket_id=bucket.id,
                    brake_threshold_pct=threshold_pct,
                )
            except Exception:
                logger.exception("Drawdown calc failed for bucket %s", bucket.id)
                continue

            if not dd.get("drawdown_brake_active"):
                continue

            # Idempotenz-Check via UNIQUE
            inserted = await _try_insert_alert(
                db, user_id=user.id, bucket_id=bucket.id, today=today
            )
            if not inserted:
                counters["skipped_idempotent"] += 1
                continue

            counters["triggered"] += 1
            logger.info(
                "Drawdown-Bremse fuer Bucket '%s' (user=%s) erreicht: "
                "current_vs_peak=%.2f%%, threshold=%.2f%%",
                bucket.name,
                user.id,
                dd.get("current_vs_peak_pct"),
                threshold_pct,
            )
            # Email-Delivery in v2.1 noch nicht angebunden — Idempotenz-Log
            # garantiert nur dass spaeter angebundener Email-Service nicht
            # doppelt versendet. Phase 1 = Logging als Trigger-Beweis,
            # Email-Hookup als kleines Followup-PR.

    # Commit am Ende — alle inserts sind in einer Transaction
    await db.commit()
    return counters


async def _try_insert_alert(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    today: date,
) -> bool:
    """Idempotenter Insert via ON CONFLICT DO NOTHING.

    Returns True wenn neuer Eintrag erzeugt, False wenn schon existiert.
    """
    stmt = pg_insert(BucketAlertLog).values(
        user_id=user_id,
        bucket_id=bucket_id,
        alert_type=ALERT_TYPE,
        alert_date=today,
    ).on_conflict_do_nothing(
        constraint="uq_bucket_alert_log",
    )
    # PostgreSQL: cursor.rowcount sagt uns ob INSERT geschah
    result = await db.execute(stmt)
    return result.rowcount > 0
