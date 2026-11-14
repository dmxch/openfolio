"""Vollreview 11/2026, Welle 3, Fixer «misc»: SMTP.

C4 (SMTP_ALLOWED_PRIVATE_HOSTS gibt interne SMTP-Hosts der Nutzer frei),
K092 (Alarm-Mails laufen über send_smtp_message und sind an die geprüfte IP
gebunden), K154 (kein Empfänger im Log der Alarm-Mails).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from decimal import Decimal
from email.mime.text import MIMEText
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from config import Settings, settings
from dateutils import utcnow
from models.price_alert import PriceAlert
from models.smtp_config import SmtpConfig
from models.user import User
from services import email_service, settings_service, url_guard
from services.auth_service import encrypt_value
from services.url_guard import UnsafeUrlError, ensure_public_url, open_pinned_socket


def _fake_dns(monkeypatch, addrs: list[str]) -> list[str]:
    """Ersetzt socket.getaddrinfo; liefert die Liste der angefragten Hostnamen."""
    calls: list[str] = []

    def _getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port or 0))
            for a in addrs
        ]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    return calls


def _msg() -> MIMEText:
    msg = MIMEText("<p>x</p>", "html")
    msg["Subject"] = "Test"
    msg["From"] = "from@example.org"
    msg["To"] = "to@example.org"
    return msg


@pytest.fixture
def smtp_send(monkeypatch):
    send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(email_service.aiosmtplib, "send", send)
    return send


# --- C4: Freigabeliste --------------------------------------------------------


class TestSmtpAllowlist:
    def test_setting_defaults_to_empty_and_reads_the_environment(self, monkeypatch):
        assert Settings.model_fields["smtp_allowed_private_hosts"].default == ""
        monkeypatch.setenv("SMTP_ALLOWED_PRIVATE_HOSTS", "mailrelay.intern, postfix")
        assert Settings().smtp_allowed_private_hosts == "mailrelay.intern, postfix"

    def test_match_is_exact_and_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(settings, "smtp_allowed_private_hosts", "MailRelay.intern, postfix ,")
        assert url_guard.is_smtp_private_host_allowed("mailrelay.intern")
        assert url_guard.is_smtp_private_host_allowed(" MAILRELAY.INTERN ")
        assert url_guard.is_smtp_private_host_allowed("postfix")
        assert not url_guard.is_smtp_private_host_allowed("relay.intern")
        assert not url_guard.is_smtp_private_host_allowed("evil-mailrelay.intern")
        assert not url_guard.is_smtp_private_host_allowed("")

    def test_empty_list_releases_nothing(self):
        assert settings.smtp_allowed_private_hosts == ""
        assert not url_guard.is_smtp_private_host_allowed("mailrelay.intern")
        assert not url_guard.is_smtp_private_host_allowed("")

    async def test_released_host_reaches_its_internal_address(self, monkeypatch):
        """Die Verbindung geht an die einmal aufgelöste Adresse, auch wenn sie intern ist."""
        peers: list = []

        async def _handle(reader, writer):
            peers.append(writer.get_extra_info("sockname"))
            writer.close()

        server = await asyncio.start_server(_handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        calls = _fake_dns(monkeypatch, ["127.0.0.1"])
        try:
            with pytest.raises(UnsafeUrlError):
                await open_pinned_socket("mailrelay.intern", port)
            sock = await open_pinned_socket("mailrelay.intern", port, allow_internal=True)
            sock.close()
            await asyncio.sleep(0.05)
        finally:
            server.close()
            await server.wait_closed()
        assert calls == ["mailrelay.intern", "mailrelay.intern"]  # je Aufruf genau eine Auflösung
        assert len(peers) == 1

    async def test_sender_passes_the_release_to_the_guard(self, monkeypatch, smtp_send):
        monkeypatch.setattr(settings, "smtp_allowed_private_hosts", "mailrelay.intern")
        opened = AsyncMock(return_value=object())
        monkeypatch.setattr(email_service, "open_pinned_socket", opened)

        await email_service.send_smtp_message(
            _msg(), host="MailRelay.intern", port=25, username="u", password="p",
            use_tls=False, user_supplied=True,
        )
        opened.assert_awaited_once_with("MailRelay.intern", 25, timeout=10, allow_internal=True)

        opened.reset_mock()
        await email_service.send_smtp_message(
            _msg(), host="other.intern", port=25, username="u", password="p",
            use_tls=False, user_supplied=True,
        )
        opened.assert_awaited_once_with("other.intern", 25, timeout=10, allow_internal=False)

    async def test_unreleased_internal_host_is_still_never_contacted(self, monkeypatch, smtp_send):
        monkeypatch.setattr(settings, "smtp_allowed_private_hosts", "mailrelay.intern")
        _fake_dns(monkeypatch, ["10.10.50.10"])
        with pytest.raises(UnsafeUrlError):
            await email_service.send_smtp_message(
                _msg(), host="other.intern", port=587, username="u", password="p",
                use_tls=True, user_supplied=True,
            )
        smtp_send.assert_not_awaited()

    async def test_storage_check_accepts_the_released_host_only(self, monkeypatch):
        monkeypatch.setattr(settings, "smtp_allowed_private_hosts", "mailrelay.internal")
        resolve = AsyncMock()
        monkeypatch.setattr(settings_service, "resolve_checked_addrs", resolve)

        await settings_service.validate_smtp_host("MailRelay.internal")
        resolve.assert_not_awaited()

        with pytest.raises(HTTPException) as exc:
            await settings_service.validate_smtp_host("other.internal")
        assert exc.value.status_code == 400

        monkeypatch.setattr(settings, "smtp_allowed_private_hosts", "")
        with pytest.raises(HTTPException):
            await settings_service.validate_smtp_host("mailrelay.internal")

    async def test_lists_for_ntfy_and_smtp_are_separate(self, monkeypatch):
        _fake_dns(monkeypatch, ["172.18.0.5"])
        monkeypatch.setattr(settings, "smtp_allowed_private_hosts", "mailrelay")
        monkeypatch.setattr(settings, "ntfy_allowed_private_hosts", "ntfy")

        # Die SMTP-Freigabe öffnet keinen ntfy-Weg ins interne Netz …
        with pytest.raises(UnsafeUrlError):
            await ensure_public_url("http://mailrelay:80")
        # … und die ntfy-Freigabe keinen SMTP-Weg.
        assert not url_guard.is_smtp_private_host_allowed("ntfy")


# --- K092 / K154: Alarm-Mails -------------------------------------------------


async def _user_with_alert(db, *, with_smtp_config: bool) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x", is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    if with_smtp_config:
        db.add(SmtpConfig(
            user_id=user.id, host="smtp.user.example", port=587, username="alerts@user.example",
            password_encrypted=encrypt_value("secret"), from_email="alerts@user.example", use_tls=True,
        ))
    db.add(PriceAlert(
        user_id=user.id, ticker="ANET", alert_type="price_above", target_value=Decimal("200"),
        currency="CHF", notify_email=True, is_active=False, is_triggered=True,
        triggered_at=utcnow(), trigger_price=Decimal("250"), notification_sent=False,
    ))
    await db.commit()
    return user


class TestAlertMails:
    async def test_user_server_is_checked_and_pinned(self, db, monkeypatch, smtp_send):
        """K092: der Versandpfad der Alarme prüfte den Host nicht und verband per Name."""
        from services.price_alert_service import send_alert_emails

        await _user_with_alert(db, with_smtp_config=True)
        marker = object()
        opened = AsyncMock(return_value=marker)
        monkeypatch.setattr(email_service, "open_pinned_socket", opened)

        await send_alert_emails([])

        opened.assert_awaited_once_with("smtp.user.example", 587, timeout=10, allow_internal=False)
        kwargs = smtp_send.await_args.kwargs
        assert kwargs["sock"] is marker
        assert kwargs["hostname"] == "smtp.user.example"  # für die TLS-Prüfung
        assert "port" not in kwargs
        assert kwargs["start_tls"] is True

    async def test_internal_user_server_gets_no_mail(self, db, monkeypatch, smtp_send):
        from services.price_alert_service import send_alert_emails

        user = await _user_with_alert(db, with_smtp_config=True)
        _fake_dns(monkeypatch, ["10.10.50.10"])

        await send_alert_emails([])

        smtp_send.assert_not_awaited()
        alert = (await db.execute(
            PriceAlert.__table__.select().where(PriceAlert.user_id == user.id)
        )).one()
        assert alert.notification_sent is False

    async def test_operator_server_is_used_as_configured(self, db, monkeypatch, smtp_send):
        from services.price_alert_service import send_alert_emails

        monkeypatch.setattr(settings, "smtp_host", "mailrelay.internal")
        monkeypatch.setattr(settings, "smtp_user", "noreply@operator.test")
        monkeypatch.setattr(settings, "smtp_password", "secret")
        user = await _user_with_alert(db, with_smtp_config=False)
        opened = AsyncMock()
        monkeypatch.setattr(email_service, "open_pinned_socket", opened)

        await send_alert_emails([])

        opened.assert_not_awaited()
        kwargs = smtp_send.await_args.kwargs
        assert kwargs["hostname"] == "mailrelay.internal" and kwargs["port"] == 587
        assert "sock" not in kwargs
        assert smtp_send.await_args.args[0]["To"] == user.email

    async def test_log_names_the_user_id_not_the_address(self, db, monkeypatch, smtp_send, caplog):
        """K154: die Empfängeradresse stand bei jedem Versand im Log."""
        from services.price_alert_service import send_alert_emails

        user = await _user_with_alert(db, with_smtp_config=True)
        monkeypatch.setattr(email_service, "open_pinned_socket", AsyncMock(return_value=object()))
        with caplog.at_level(logging.INFO, logger="services.price_alert_service"):
            await send_alert_emails([])
        assert smtp_send.await_count == 1
        assert user.email not in caplog.text
        assert str(user.id) in caplog.text
