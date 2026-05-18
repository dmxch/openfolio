"""Cross-Bucket-Constraint-Alert: max_total_pct pro Bucket.

Sweep-Pattern analog ``bucket_drawdown_service`` — täglich aus dem Worker
getriggert. Loest Alert wenn ``bucket_value / liquid_total * 100 > max_total_pct``.

Gates:
  - bucket.kind == 'user' (System-Buckets haben keinen Constraint)
  - bucket.deleted_at IS NULL
  - bucket.risk_rules.max_total_pct gesetzt (None oder 0 -> skip)

Idempotenz: 1 Alert pro (user, bucket, alert_type, alert_date) via
``bucket_alert_log``-UNIQUE-Constraint.

Neutrale Sprache: "Bucket X übersteigt Soll-Anteil" — keine
Handlungsaufforderung (HEILIGE Regel 10).
"""
from __future__ import annotations

import html
import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_preference import AlertPreference
from models.bucket import Bucket, BucketAlertLog, BucketKind
from models.smtp_config import SmtpConfig
from models.user import User
from services.bucket_performance_service import get_allocations_by_bucket
from services.email_service import send_email

logger = logging.getLogger(__name__)

ALERT_TYPE = "bucket_total_drift"
ALERT_CATEGORY = "bucket_total_drift"


async def check_bucket_total_drift(db: AsyncSession) -> dict:
    """Sweep ueber alle User+aktiven User-Buckets mit max_total_pct gesetzt."""
    today = date.today()

    user_q = await db.execute(select(User).where(User.is_active.is_(True)))
    users = list(user_q.scalars().all())

    counters = {
        "checked": 0,
        "triggered": 0,
        "emails_sent": 0,
        "emails_skipped_no_smtp": 0,
        "emails_skipped_no_pref": 0,
        "skipped_no_rule": 0,
        "skipped_idempotent": 0,
        "skipped_no_allocation": 0,
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
        relevant = [
            b for b in buckets
            if (b.risk_rules or {}).get("max_total_pct")
        ]
        if not relevant:
            counters["skipped_no_rule"] += len(buckets)
            continue

        try:
            allocations = await get_allocations_by_bucket(db, user.id)
        except Exception:
            logger.exception("Allokation fuer user=%s konnte nicht geladen werden", user.id)
            continue
        alloc_by_id = {a["bucket_id"]: a for a in allocations}

        for bucket in relevant:
            counters["checked"] += 1
            threshold = float(bucket.risk_rules["max_total_pct"])
            alloc = alloc_by_id.get(str(bucket.id))
            if alloc is None:
                counters["skipped_no_allocation"] += 1
                continue
            current_pct = float(alloc.get("pct") or 0.0)
            if current_pct <= threshold:
                continue

            inserted = await _try_insert_alert(
                db, user_id=user.id, bucket_id=bucket.id, today=today
            )
            if not inserted:
                counters["skipped_idempotent"] += 1
                continue

            counters["triggered"] += 1
            logger.info(
                "Bucket-Drift fuer '%s' (user=%s): current=%.2f%% > threshold=%.2f%%",
                bucket.name,
                user.id,
                current_pct,
                threshold,
            )

            email_status = await _send_drift_email(
                db, user, bucket, current_pct=current_pct, threshold_pct=threshold,
                value_chf=float(alloc.get("value_chf") or 0.0),
            )
            if email_status == "sent":
                counters["emails_sent"] += 1
            elif email_status == "no_smtp":
                counters["emails_skipped_no_smtp"] += 1
            elif email_status == "no_pref":
                counters["emails_skipped_no_pref"] += 1

    await db.commit()
    return counters


async def _send_drift_email(
    db: AsyncSession,
    user: User,
    bucket: Bucket,
    *,
    current_pct: float,
    threshold_pct: float,
    value_chf: float,
) -> str:
    """Returns 'sent' | 'no_smtp' | 'no_pref' | 'failed'."""
    pref_q = await db.execute(
        select(AlertPreference).where(
            AlertPreference.user_id == user.id,
            AlertPreference.category == ALERT_CATEGORY,
        )
    )
    pref = pref_q.scalar_one_or_none()
    if pref is None or not pref.is_enabled or not pref.notify_email:
        return "no_pref"

    smtp_cfg = await db.get(SmtpConfig, user.id)
    if smtp_cfg is None:
        return "no_smtp"

    subject = f"OpenFolio: Bucket {bucket.name} uebersteigt Soll-Anteil"
    body_html = _render_drift_email_html(
        bucket, current_pct=current_pct, threshold_pct=threshold_pct, value_chf=value_chf
    )
    try:
        ok = await send_email(user.email, subject, body_html, smtp_cfg=smtp_cfg)
        return "sent" if ok else "failed"
    except Exception:
        logger.exception("Drift-Mail an user=%s fehlgeschlagen", user.id)
        return "failed"


def _render_drift_email_html(
    bucket: Bucket,
    *,
    current_pct: float,
    threshold_pct: float,
    value_chf: float,
) -> str:
    value_str = f"{value_chf:,.2f} CHF".replace(",", "'")
    return (
        "<html><body style=\"font-family: -apple-system, sans-serif; max-width: 600px;\">"
        f"<h2 style=\"color:#0f172a\">Bucket &laquo;{html.escape(bucket.name)}&raquo; "
        "uebersteigt Soll-Anteil</h2>"
        "<p style=\"color:#475569\">Der Anteil dieses Buckets am liquiden "
        "Gesamtportfolio liegt aktuell ueber dem konfigurierten Soll-Limit. "
        "Dies ist eine neutrale Status-Mitteilung, keine Handlungsaufforderung.</p>"
        "<table style=\"border-collapse:collapse;margin:16px 0\">"
        "<tr><td style=\"padding:6px 12px;color:#64748b\">Aktueller Anteil</td>"
        f"<td style=\"padding:6px 12px;font-weight:600\">{current_pct:.2f}%</td></tr>"
        "<tr><td style=\"padding:6px 12px;color:#64748b\">Soll-Maximum</td>"
        f"<td style=\"padding:6px 12px\">{threshold_pct:.2f}%</td></tr>"
        "<tr><td style=\"padding:6px 12px;color:#64748b\">Bucket-Wert</td>"
        f"<td style=\"padding:6px 12px\">{value_str}</td></tr>"
        "</table>"
        "<p style=\"color:#64748b;font-size:13px\">"
        "Pro Bucket und Tag wird maximal eine Mail versendet. Das Soll-Maximum "
        "kannst du unter Einstellungen &rarr; Buckets pro Bucket konfigurieren."
        "</p>"
        "</body></html>"
    )


async def _try_insert_alert(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    today: date,
) -> bool:
    existing = await db.execute(
        select(BucketAlertLog).where(
            BucketAlertLog.user_id == user_id,
            BucketAlertLog.bucket_id == bucket_id,
            BucketAlertLog.alert_type == ALERT_TYPE,
            BucketAlertLog.alert_date == today,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False
    db.add(BucketAlertLog(
        user_id=user_id,
        bucket_id=bucket_id,
        alert_type=ALERT_TYPE,
        alert_date=today,
    ))
    await db.flush()
    return True
