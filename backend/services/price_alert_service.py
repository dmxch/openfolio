"""Price alert checking and notification service."""
import html
import logging
from datetime import timedelta

from dateutils import utcnow

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import Position
from models.price_alert import PriceAlert
from models.alert_preference import AlertPreference
from models.smtp_config import SmtpConfig
from models.user import UserSettings
from models.watchlist import WatchlistItem
from services import cache

logger = logging.getLogger(__name__)


async def check_price_alerts(db: AsyncSession) -> list[dict]:
    """Check all active alerts against current cached prices. Returns triggered alerts."""
    now = utcnow()
    query = select(PriceAlert).where(
        PriceAlert.is_active == True,
        PriceAlert.is_triggered == False,
    )
    result = await db.execute(query)
    alerts = result.scalars().all()

    # Orphan-Guard: Alerts sind an Portfolio ∪ Watchlist gebunden (gleiche
    # Semantik wie die Cascade beim Watchlist-Entfernen). Positionen koennen
    # aber auch via Verkauf auf 0, Loeschung oder Import verschwinden — dann
    # blieb der Alert bisher aktiv und feuerte weiter. Solche Waisen werden
    # hier deaktiviert statt ausgeloest.
    user_ids = {alert.user_id for alert in alerts}
    valid_tickers: set[tuple] = set()
    if user_ids:
        pos_rows = await db.execute(
            select(Position.user_id, Position.ticker).where(
                Position.user_id.in_(user_ids),
                Position.is_active == True,
                Position.shares > 0,
            )
        )
        valid_tickers.update(pos_rows.all())
        wl_rows = await db.execute(
            select(WatchlistItem.user_id, WatchlistItem.ticker).where(
                WatchlistItem.user_id.in_(user_ids)
            )
        )
        valid_tickers.update(wl_rows.all())

    orphaned = 0
    triggered = []
    for alert in alerts:
        if (alert.user_id, alert.ticker) not in valid_tickers:
            alert.is_active = False
            orphaned += 1
            logger.info(
                f"Alert deactivated (orphaned, ticker neither held nor watched): "
                f"{alert.ticker} {alert.alert_type} user={alert.user_id}"
            )
            continue

        # Get cached price
        cached = cache.get(f"price:{alert.ticker}")
        if not cached or not cached.get("price"):
            continue

        current_price = cached["price"]
        should_trigger = False

        if alert.alert_type == "price_above" and current_price > float(alert.target_value):
            should_trigger = True
        elif alert.alert_type == "price_below" and current_price < float(alert.target_value):
            should_trigger = True
        elif alert.alert_type == "pct_change_day":
            change_pct = cached.get("change_pct", 0) or 0
            if abs(change_pct) > float(alert.target_value):
                should_trigger = True

        if should_trigger:
            alert.is_triggered = True
            alert.is_active = False
            alert.triggered_at = now
            alert.trigger_price = current_price
            # Delivery-Tracking (H5): Email gilt erst nach erfolgreichem
            # SMTP-Versand als zugestellt — send_alert_emails() markiert.
            alert.notification_sent = False
            triggered.append({
                "id": str(alert.id),
                "user_id": str(alert.user_id),
                "ticker": alert.ticker,
                "alert_type": alert.alert_type,
                "target_value": float(alert.target_value),
                "currency": alert.currency,
                "trigger_price": current_price,
                "note": alert.note,
                "notify_in_app": alert.notify_in_app,
                "notify_email": alert.notify_email,
            })
            logger.info(f"Alert triggered: {alert.ticker} {alert.alert_type} target={alert.target_value} current={current_price}")

    if triggered or orphaned:
        await db.commit()

    return triggered


def _alert_to_dict(alert: PriceAlert) -> dict:
    """Serialize a PriceAlert row into the dict shape the email builder expects."""
    return {
        "id": str(alert.id),
        "user_id": str(alert.user_id),
        "ticker": alert.ticker,
        "alert_type": alert.alert_type,
        "target_value": float(alert.target_value),
        "currency": alert.currency,
        "trigger_price": float(alert.trigger_price) if alert.trigger_price is not None else 0.0,
        "note": alert.note,
        "notify_in_app": alert.notify_in_app,
        "notify_email": alert.notify_email,
    }


async def send_alert_emails(triggered: list[dict] | None = None) -> None:
    """Send email notifications for triggered-but-undelivered alerts.

    Delivery-Tracking via PriceAlert.notification_sent (H5): selektiert pro
    User ALLE getriggerten, noch unversandten Email-Alerts — nicht nur die
    des aktuellen Laufs. Damit verzoegert der 15-Min-Digest-Throttle in
    _send_user_alerts nur noch statt zu verwerfen: der naechste Worker-Lauf
    (jede Minute) liefert nach. Erst nach erfolgreichem SMTP-Versand wird
    notification_sent=True committet.

    Retry-Fenster 24h: haelt Zustellversuche bei dauerhaft kaputter
    SMTP-Config endlich und verhindert beim ersten Deploy einen Flood aus
    historischen Alerts, deren notification_sent nie gepflegt wurde.
    Das triggered-Argument bleibt fuer Aufrufer-Kompatibilitaet erhalten,
    massgeblich ist der DB-Zustand.
    """
    from db import async_session

    now = utcnow()
    async with async_session() as db:
        rows = (await db.execute(
            select(PriceAlert).where(
                PriceAlert.is_triggered == True,
                PriceAlert.notification_sent == False,
                PriceAlert.notify_email == True,
                PriceAlert.triggered_at != None,
                PriceAlert.triggered_at >= now - timedelta(hours=24),
            )
        )).scalars().all()

        by_user: dict[str, list[PriceAlert]] = {}
        for row in rows:
            by_user.setdefault(str(row.user_id), []).append(row)

        if not by_user:
            return

        for user_id, user_rows in by_user.items():
            status = await _send_user_alerts(
                db, user_id, [_alert_to_dict(row) for row in user_rows]
            )
            if status == "retry":
                # Throttle oder transienter SMTP-Fehler: unversandt lassen,
                # der naechste Lauf versucht es erneut.
                continue
            # "sent" oder "skip" (Email-Zustellung nicht moeglich/abbestellt):
            # als erledigt markieren, damit der Backlog nicht ewig rescannt wird.
            for row in user_rows:
                row.notification_sent = True
            await db.commit()


async def send_alert_pushes(triggered: list[dict]) -> None:
    """Schedule fire-and-forget ntfy pushes for triggered alerts.

    Per User in einem eigenen Bucket gesammelt — Alerts von User A duerfen
    NIE als Push an User B gesendet werden (Multi-User-Scope).
    Filter: AlertPreference.is_enabled UND notify_push muessen true sein.
    Aggregiert ab AGGREGATION_THRESHOLD; sonst Einzel-Pushes (Dedup laeuft
    in send_push_aggregated/send_push_for_user).
    """
    from collections import defaultdict
    from uuid import UUID

    from db import async_session
    from models.ntfy_config import NtfyConfig
    from services import cache as redis_cache
    from services.ntfy_service import send_push_aggregated

    if not triggered:
        return

    # Pre-filter: only alerts whose user has a pref with notify_push enabled.
    # Sammle pro user_id, niemals User-uebergreifend mischen.
    type_labels = {
        "price_above": "Kurs ueber",
        "price_below": "Kurs unter",
        "pct_change_day": "Tagesveraenderung ueber",
    }
    buckets: dict[str, list[dict]] = defaultdict(list)

    async with async_session() as db:
        for alert in triggered:
            user_id_str = alert["user_id"]
            try:
                user_uuid = UUID(user_id_str)
            except (ValueError, TypeError):
                logger.debug(f"Skipping push for invalid user_id={user_id_str}")
                continue
            pref_result = await db.execute(
                select(AlertPreference).where(
                    AlertPreference.user_id == user_uuid,
                    AlertPreference.category == "price_alert",
                )
            )
            pref = pref_result.scalars().first()
            if not pref or not pref.is_enabled or not pref.notify_push:
                continue

            currency = alert.get("currency") or "CHF"
            ticker = alert["ticker"]
            target = alert["target_value"]
            if alert["alert_type"] == "pct_change_day":
                target_str = f"{target}%"
            else:
                target_str = f"{currency} {target:.2f}"
            type_text = type_labels.get(alert["alert_type"], alert["alert_type"])
            buckets[user_id_str].append({
                "title": f"{ticker}: {type_text} {target_str}",
                "message": (
                    f"Aktuell: {currency} {alert['trigger_price']:.2f}"
                ),
                "severity": "high",
            })

        for user_id_str, alerts in buckets.items():
            try:
                user_uuid = UUID(user_id_str)
            except (ValueError, TypeError):
                continue
            ntfy_cfg = await db.get(NtfyConfig, user_uuid)
            if not ntfy_cfg:
                continue
            send_push_aggregated(
                ntfy_cfg=ntfy_cfg,
                category="price_alert",
                alerts=alerts,
                redis_client=redis_cache,
            )


async def _send_user_alerts(db: AsyncSession, user_id: str, alerts: list[dict]) -> str:
    """Send alert emails for a single user using their SMTP config.

    Returns a delivery status for das notification_sent-Tracking (H5):
      - "sent":  Email erfolgreich versandt → als zugestellt markieren
      - "skip":  Zustellung nicht moeglich/abbestellt (Pref aus, keine
                 SMTP-Config, kein Empfaenger) → als erledigt markieren
      - "retry": temporaer (15-Min-Throttle, SMTP-Fehler) → unversandt
                 lassen, naechster Worker-Lauf liefert nach
    """
    from uuid import UUID

    # Check user's alert preference for price_alert category
    pref_result = await db.execute(
        select(AlertPreference).where(
            AlertPreference.user_id == UUID(user_id),
            AlertPreference.category == "price_alert",
        )
    )
    pref = pref_result.scalars().first()
    if pref and not pref.notify_email:
        return "skip"

    # Check digest throttling (max 1 email per 15 min)
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == UUID(user_id))
    )
    user_settings = settings_result.scalars().first()
    now = utcnow()
    if user_settings and user_settings.last_email_digest_at:
        if (now - user_settings.last_email_digest_at) < timedelta(minutes=15):
            logger.info(f"Email digest throttled for user {user_id} — retry next run")
            return "retry"

    # Get user's SMTP config
    smtp_cfg = await db.get(SmtpConfig, UUID(user_id))
    if not smtp_cfg:
        # Fall back to global SMTP from config
        from config import settings as app_settings
        if not all([app_settings.smtp_host, app_settings.smtp_user, app_settings.smtp_password]):
            return "skip"
        smtp_host = app_settings.smtp_host
        smtp_port = app_settings.smtp_port
        smtp_user = app_settings.smtp_user
        smtp_password = app_settings.smtp_password
        from_email = app_settings.smtp_user
        use_tls = True
        email_to = app_settings.alert_email_to
        if not email_to:
            return "skip"
    else:
        from services.auth_service import decrypt_value
        smtp_host = smtp_cfg.host
        smtp_port = smtp_cfg.port
        smtp_user = smtp_cfg.username
        smtp_password = decrypt_value(smtp_cfg.password_encrypted)
        from_email = smtp_cfg.from_email or smtp_cfg.username
        use_tls = smtp_cfg.use_tls
        # Send to user's own email
        from models.user import User
        user_result = await db.execute(select(User.email).where(User.id == UUID(user_id)))
        email_to = user_result.scalar()
        if not email_to:
            return "skip"

    # Build digest email if multiple alerts
    type_labels = {
        "price_above": "Kurs über",
        "price_below": "Kurs unter",
        "pct_change_day": "Tagesveränderung über",
    }

    if len(alerts) == 1:
        alert = alerts[0]
        currency = alert.get("currency") or "CHF"
        ticker = alert["ticker"]
        type_text = type_labels.get(alert["alert_type"], alert["alert_type"])
        if alert["alert_type"] == "pct_change_day":
            target_str = f"{alert['target_value']}%"
        else:
            target_str = f"{currency} {alert['target_value']:.2f}"
        subject = f"OpenFolio Alarm: {ticker} — {type_text} {target_str}"
    else:
        tickers = ", ".join(set(a["ticker"] for a in alerts))
        subject = f"OpenFolio: {len(alerts)} Alarme ausgelöst ({tickers})"

    now_str = now.strftime("%d.%m.%Y, %H:%M UTC")
    rows_html = ""
    for alert in alerts:
        currency = alert.get("currency") or "CHF"
        type_text = type_labels.get(alert["alert_type"], alert["alert_type"])
        if alert["alert_type"] == "pct_change_day":
            target_str = f"{alert['target_value']}%"
            current_str = f"{currency} {alert['trigger_price']:.2f}"
        else:
            target_str = f"{currency} {alert['target_value']:.2f}"
            current_str = f"{currency} {alert['trigger_price']:.2f}"
        note = html.escape(alert.get("note") or "")
        ticker_safe = html.escape(alert.get("ticker") or "")
        rows_html += f"""
        <tr>
            <td style="padding:8px;color:#fff;font-weight:bold;">{ticker_safe}</td>
            <td style="padding:8px;color:#fff;">{type_text} {target_str}</td>
            <td style="padding:8px;color:#10b981;font-weight:bold;">{current_str}</td>
            <td style="padding:8px;color:#9ca3af;">{note}</td>
        </tr>"""

    body_html = f"""
    <div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;max-width:600px;margin:0 auto;border-radius:12px;">
        <h2 style="color:#f59e0b;margin-top:0;">{"Preis-Alarm ausgelöst" if len(alerts) == 1 else f"{len(alerts)} Preis-Alarme ausgelöst"}</h2>
        <p style="color:#9ca3af;font-size:14px;">{now_str}</p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">
            <tr style="border-bottom:1px solid #333;">
                <th style="padding:8px;text-align:left;color:#9ca3af;font-weight:normal;">Ticker</th>
                <th style="padding:8px;text-align:left;color:#9ca3af;font-weight:normal;">Alarm</th>
                <th style="padding:8px;text-align:left;color:#9ca3af;font-weight:normal;">Aktuell</th>
                <th style="padding:8px;text-align:left;color:#9ca3af;font-weight:normal;">Notiz</th>
            </tr>
            {rows_html}
        </table>
    </div>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = email_to
        msg.attach(MIMEText(body_html, "html"))

        if smtp_port == 465:
            await aiosmtplib.send(
                msg,
                hostname=smtp_host,
                port=smtp_port,
                username=smtp_user,
                password=smtp_password,
                use_tls=True,
                timeout=10,
            )
        else:
            await aiosmtplib.send(
                msg,
                hostname=smtp_host,
                port=smtp_port,
                username=smtp_user,
                password=smtp_password,
                start_tls=use_tls,
                timeout=10,
            )

        # Update digest timestamp
        if user_settings:
            user_settings.last_email_digest_at = now
            await db.commit()

        logger.info(f"Alert email sent to {email_to} ({len(alerts)} alerts)")
        return "sent"
    except Exception as e:
        logger.error(f"Alert email failed for user {user_id}: {e} — retry next run")
        # Session bereinigen: der Fehler kann vom commit() stammen — ohne
        # rollback wirft der naechste User PendingRollbackError (M9-Muster).
        try:
            await db.rollback()
        except Exception:
            logger.exception(f"Alert email rollback failed for user {user_id}")
        return "retry"
