"""Price alert checking and notification service."""
import logging
from datetime import datetime, timedelta

from dateutils import utcnow

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.price_alert import PriceAlert
from models.alert_preference import AlertPreference
from models.smtp_config import SmtpConfig
from models.user import UserSettings
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

    triggered = []
    for alert in alerts:
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

    if triggered:
        await db.commit()

    return triggered


async def send_alert_emails(triggered: list[dict]) -> None:
    """Send email notifications for triggered alerts using per-user SMTP config."""
    from db import async_session

    # Group alerts by user
    by_user = {}
    for alert in triggered:
        if alert.get("notify_email"):
            by_user.setdefault(alert["user_id"], []).append(alert)

    if not by_user:
        return

    async with async_session() as db:
        for user_id, user_alerts in by_user.items():
            await _send_user_alerts(db, user_id, user_alerts)


async def _send_user_alerts(db: AsyncSession, user_id: str, alerts: list[dict]):
    """Send alert emails for a single user using their SMTP config."""
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
        return

    # Check digest throttling (max 1 email per 15 min)
    settings_result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == UUID(user_id))
    )
    user_settings = settings_result.scalars().first()
    now = utcnow()
    if user_settings and user_settings.last_email_digest_at:
        if (now - user_settings.last_email_digest_at) < timedelta(minutes=15):
            logger.info(f"Email digest throttled for user {user_id}")
            return

    # Get user's SMTP config
    smtp_cfg = await db.get(SmtpConfig, UUID(user_id))
    if not smtp_cfg:
        # Fall back to global SMTP from config
        from config import settings as app_settings
        if not all([app_settings.smtp_host, app_settings.smtp_user, app_settings.smtp_password]):
            return
        smtp_host = app_settings.smtp_host
        smtp_port = app_settings.smtp_port
        smtp_user = app_settings.smtp_user
        smtp_password = app_settings.smtp_password
        from_email = app_settings.smtp_user
        use_tls = True
        email_to = app_settings.alert_email_to
        if not email_to:
            return
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
            return

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
        note = alert.get("note") or ""
        rows_html += f"""
        <tr>
            <td style="padding:8px;color:#fff;font-weight:bold;">{alert['ticker']}</td>
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
    except Exception as e:
        logger.error(f"Alert email failed for user {user_id}: {e}")
