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

import html
import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_preference import AlertPreference
from models.bucket import Bucket, BucketAlertLog, BucketKind, BucketSnapshot
from models.ntfy_config import NtfyConfig
from models.smtp_config import SmtpConfig
from models.user import User
from services import cache
from services.drawdown_service import get_max_drawdown
from services.email_service import send_email
from services.ntfy_service import send_push_for_user

logger = logging.getLogger(__name__)

ALERT_TYPE = "drawdown_brake_bucket"
ALERT_CATEGORY = "drawdown_brake_bucket"  # AlertPreference.category
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
        "emails_sent": 0,
        "emails_skipped_no_smtp": 0,
        "emails_skipped_no_pref": 0,
        "pushes_sent": 0,
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
            # Zwei-Flag-Semantik (autoritativ):
            #   risk_rules.drawdown_brake_active  = statischer ENABLEMENT-Schalter
            #       (hat der User die Bremse fuer diesen Bucket eingeschaltet?).
            #   dd["drawdown_brake_active"]       = zur LAUFZEIT berechneter
            #       TRIGGER (ist der indexierte Drawdown aktuell <= -threshold?).
            # Der Kauf-/Risiko-Layer (Finance-Workspace, /buckets/{id}/drawdown)
            # liest IMMER den berechneten Wert; der Config-Flag schaltet nur das
            # Feature an/aus, er ist NIE selbst das Trigger-Signal.
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

            # Email-Delivery (F-5): Pref pruefen → SMTP holen → senden
            email_status = await _send_drawdown_email(db, user, bucket, dd, threshold_pct)
            if email_status == "sent":
                counters["emails_sent"] += 1
            elif email_status == "no_smtp":
                counters["emails_skipped_no_smtp"] += 1
            elif email_status == "no_pref":
                counters["emails_skipped_no_pref"] += 1

            # ntfy-Push (unabhaengig vom Email-Pfad; opt-in ueber notify_push).
            if await _send_drawdown_push(db, user, bucket, dd, threshold_pct) == "sent":
                counters["pushes_sent"] += 1

    # Commit am Ende — alle inserts sind in einer Transaction
    await db.commit()
    return counters


async def _send_drawdown_email(
    db: AsyncSession,
    user: User,
    bucket: Bucket,
    dd: dict,
    threshold_pct: float,
) -> str:
    """Sendet die Drawdown-Bremsen-Mail an den User.

    Returns: 'sent' | 'no_smtp' | 'no_pref' | 'failed'
    AlertPreference category=drawdown_brake_bucket muss is_enabled=True und
    notify_email=True haben — Default-Verhalten ist opt-in (kein automatisches
    Spam).
    """
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

    subject = f"OpenFolio: Drawdown-Bremse fuer Bucket {bucket.name} erreicht"
    body_html = _render_drawdown_email_html(bucket, dd, threshold_pct)
    try:
        ok = await send_email(user.email, subject, body_html, smtp_cfg=smtp_cfg)
        return "sent" if ok else "failed"
    except Exception:
        logger.exception("Drawdown-Mail an user=%s fehlgeschlagen", user.id)
        return "failed"


async def _send_drawdown_push(
    db: AsyncSession,
    user: User,
    bucket: Bucket,
    dd: dict,
    threshold_pct: float,
) -> str:
    """Fire-and-forget ntfy-Push. Returns 'sent' | 'no_config' | 'no_pref'.

    Opt-in ueber AlertPreference.notify_push. Neutrale Sprache (HEILIGE Regel 10):
    reine Status-Mitteilung, keine Handlungsaufforderung. Tages-Idempotenz stellt
    ``bucket_alert_log`` sicher (Aufruf nur nach erfolgreichem Insert); zusaetzlich
    greift der ntfy-interne 24h-Dedup.
    """
    pref_q = await db.execute(
        select(AlertPreference).where(
            AlertPreference.user_id == user.id,
            AlertPreference.category == ALERT_CATEGORY,
        )
    )
    pref = pref_q.scalar_one_or_none()
    if pref is None or not pref.is_enabled or not pref.notify_push:
        return "no_pref"

    ntfy_cfg = await db.get(NtfyConfig, user.id)
    if ntfy_cfg is None or not ntfy_cfg.is_enabled:
        return "no_config"

    current = dd.get("current_vs_peak_pct")
    current_str = f"{current:.1f}%" if current is not None else "n/a"
    send_push_for_user(
        ntfy_cfg=ntfy_cfg,
        category=ALERT_CATEGORY,
        title=f"Bucket {bucket.name}: Drawdown-Bremse erreicht",
        message=f"Drawdown {current_str} erreichte Schwelle {threshold_pct:.1f}%",
        severity="high",
        redis_client=cache,
    )
    return "sent"


def _render_drawdown_email_html(bucket: Bucket, dd: dict, threshold_pct: float) -> str:
    """Neutrale Sprache gemaess Plan: keine imperative Handlungsaufforderung."""
    current = dd.get("current_vs_peak_pct")
    current_str = f"{current:.2f}%" if current is not None else "n/a"
    peak_val = dd.get("running_peak_value_chf")
    peak_str = f"{peak_val:,.2f} CHF".replace(",", "'") if peak_val else "n/a"
    cur_val = dd.get("current_value_chf")
    cur_str = f"{cur_val:,.2f} CHF".replace(",", "'") if cur_val else "n/a"
    period_peak = dd.get("running_peak_date") or "n/a"

    return (
        "<html><body style=\"font-family: -apple-system, sans-serif; max-width: 600px;\">"
        f"<h2 style=\"color:#0f172a\">Drawdown-Bremse fuer Bucket "
        f"&laquo;{html.escape(bucket.name)}&raquo; erreicht</h2>"
        "<p style=\"color:#475569\">Die Drawdown-Schwelle dieses Buckets wurde "
        "ueberschritten. Dies ist eine neutrale Status-Mitteilung, keine "
        "Handlungsaufforderung.</p>"
        "<table style=\"border-collapse:collapse;margin:16px 0\">"
        "<tr><td style=\"padding:6px 12px;color:#64748b\">Drawdown aktuell</td>"
        f"<td style=\"padding:6px 12px;font-weight:600\">{current_str}</td></tr>"
        "<tr><td style=\"padding:6px 12px;color:#64748b\">Schwellwert</td>"
        f"<td style=\"padding:6px 12px\">{threshold_pct:.2f}%</td></tr>"
        "<tr><td style=\"padding:6px 12px;color:#64748b\">Peak-Wert</td>"
        f"<td style=\"padding:6px 12px\">{peak_str} (am {period_peak})</td></tr>"
        "<tr><td style=\"padding:6px 12px;color:#64748b\">Aktueller Wert</td>"
        f"<td style=\"padding:6px 12px\">{cur_str}</td></tr>"
        "</table>"
        "<p style=\"color:#64748b;font-size:13px\">"
        "Pro Bucket und Tag wird maximal eine Mail versendet (Idempotenz-Schutz). "
        "Die Schwelle und Aktivierung des Alerts kannst du unter "
        "Einstellungen &rarr; Buckets pro Bucket konfigurieren."
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
    """Idempotenter Insert.

    SELECT-then-INSERT statt ON CONFLICT (PG-spezifisch) — dialect-portabel
    fuer SQLite-Tests. Race auf demselben Tag ist akzeptabel, weil UNIQUE-
    Constraint im Schema die zweite Insert dann werfen wuerde; im
    Singleton-Worker-Pfad spielt es keine Rolle.

    Returns True wenn neuer Eintrag erzeugt, False wenn schon existiert.
    """
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
