"""Email sending service using per-user or global SMTP config."""
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

import aiosmtplib

from config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body_html: str, smtp_cfg: Any = None) -> bool:
    """Send an email using provided SMTP config or global settings (async)."""
    if smtp_cfg:
        from services.auth_service import decrypt_value
        host = smtp_cfg.host
        port = smtp_cfg.port
        user = smtp_cfg.username
        password = decrypt_value(smtp_cfg.password_encrypted)
        from_email = smtp_cfg.from_email or smtp_cfg.username
        use_tls = smtp_cfg.use_tls
    else:
        if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password]):
            return False
        host = settings.smtp_host
        port = settings.smtp_port
        user = settings.smtp_user
        password = settings.smtp_password
        from_email = settings.smtp_user
        use_tls = True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to
        msg.attach(MIMEText(body_html, "html"))

        if port == 465:
            await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user,
                password=password,
                use_tls=True,
                timeout=10,
            )
        else:
            await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user,
                password=password,
                start_tls=use_tls,
                timeout=10,
            )

        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email send failed to {to}: {e}")
        return False


def has_smtp_configured() -> bool:
    """Check if global SMTP is configured."""
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def build_reset_email_html(reset_url: str) -> str:
    return f"""
    <div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;max-width:600px;margin:0 auto;border-radius:12px;">
        <h2 style="color:#3B82F6;margin-top:0;">Passwort zurücksetzen</h2>
        <p style="color:#e0e0e0;line-height:1.6;">
            Du hast angefordert, dein Passwort zurückzusetzen.<br>
            Klicke auf den folgenden Link (gültig für 30 Minuten):
        </p>
        <div style="margin:24px 0;">
            <a href="{reset_url}"
               style="display:inline-block;background:#3B82F6;color:#ffffff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">
                Passwort zurücksetzen &rarr;
            </a>
        </div>
        <p style="color:#9ca3af;font-size:13px;line-height:1.5;">
            Falls du diese Anfrage nicht gestellt hast,
            ignoriere diese E-Mail. Dein Passwort bleibt unverändert.
        </p>
        <hr style="border:none;border-top:1px solid #333;margin:24px 0;">
        <p style="color:#6b7280;font-size:12px;">OpenFolio — Portfolio & Marktanalyse</p>
    </div>
    """


def build_temp_password_email_html(temp_password: str) -> str:
    return f"""
    <div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;max-width:600px;margin:0 auto;border-radius:12px;">
        <h2 style="color:#F59E0B;margin-top:0;">Temporäres Passwort</h2>
        <p style="color:#e0e0e0;line-height:1.6;">
            Ein Administrator hat dir ein temporäres Passwort gesetzt.<br>
            Bitte ändere es beim nächsten Login.
        </p>
        <div style="margin:24px 0;background:#0f0f23;border:1px solid #333;border-radius:8px;padding:16px;text-align:center;">
            <code style="color:#10b981;font-size:18px;letter-spacing:2px;">{temp_password}</code>
        </div>
        <hr style="border:none;border-top:1px solid #333;margin:24px 0;">
        <p style="color:#6b7280;font-size:12px;">OpenFolio — Portfolio & Marktanalyse</p>
    </div>
    """
