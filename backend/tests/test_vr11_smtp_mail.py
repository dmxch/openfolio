"""Vollreview 11/2026, Fixer smtp: SMTP-Versand und SMTP-Einstellungen.

K003/X28 (Host-Prüfung async, 400 statt Serverfehler), K092 (Verbindung zur
geprüften IP, generischer Fehlertext), Limit von PUT /settings/smtp.

Kein echtes Netz: die Namensauflösung ist ersetzt, der einzige Server läuft auf
der Loopback-Adresse dieses Prozesses.
"""

import asyncio
import logging
import socket
import threading
from email.mime.text import MIMEText
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosmtplib
import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from services import email_service, settings_service, url_guard
from services.auth_service import encrypt_value
from services.url_guard import UnsafeUrlError

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
PUBLIC_IP = "93.184.216.34"  # numerisch: braucht keine Namensauflösung


async def register_and_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _fake_dns(monkeypatch, *answers):
    """Ersetzt socket.getaddrinfo; je Aufruf eine Adressliste, die letzte gilt weiter."""
    calls: list[str] = []

    def _getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        addrs = answers[min(len(calls), len(answers)) - 1]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port or 0)) for a in addrs]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    return calls


def _msg() -> MIMEText:
    msg = MIMEText("<p>Hallo</p>", "html")
    msg["Subject"] = "Test"
    msg["From"] = "from@example.org"
    msg["To"] = "to@example.org"
    return msg


def _smtp_cfg(host: str = "smtp.example.org", port: int = 587) -> SimpleNamespace:
    return SimpleNamespace(
        host=host, port=port, username="user", password_encrypted=encrypt_value("pw"),
        from_email="from@example.org", use_tls=True,
    )


@pytest.fixture
def smtp_send(monkeypatch):
    """Ersetzt aiosmtplib.send; liefert den Mock."""
    send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(email_service.aiosmtplib, "send", send)
    return send


class TestSendSmtpMessage:
    async def test_user_server_gets_the_checked_socket(self, monkeypatch, smtp_send):
        """K092: aiosmtplib bekommt die fertige Verbindung, nicht den Namen zum Auflösen."""
        marker = object()
        opened = AsyncMock(return_value=marker)
        monkeypatch.setattr(email_service, "open_pinned_socket", opened)

        await email_service.send_smtp_message(
            _msg(), host="smtp.example.org", port=587, username="u", password="p",
            use_tls=True, user_supplied=True,
        )

        opened.assert_awaited_once_with("smtp.example.org", 587, timeout=10, allow_internal=False)
        kwargs = smtp_send.await_args.kwargs
        assert kwargs["sock"] is marker
        assert kwargs["hostname"] == "smtp.example.org"  # für die TLS-Prüfung
        assert "port" not in kwargs  # aiosmtplib lehnt sock zusammen mit port ab
        assert kwargs["start_tls"] is True and "use_tls" not in kwargs

    async def test_port_465_uses_implicit_tls(self, monkeypatch, smtp_send):
        monkeypatch.setattr(email_service, "open_pinned_socket", AsyncMock(return_value=object()))
        await email_service.send_smtp_message(
            _msg(), host="smtp.example.org", port=465, username="u", password="p",
            use_tls=False, user_supplied=True,
        )
        kwargs = smtp_send.await_args.kwargs
        assert kwargs["use_tls"] is True and "start_tls" not in kwargs

    async def test_operator_server_is_used_as_configured(self, monkeypatch, smtp_send):
        """Das globale SMTP des Betreibers darf intern liegen und bleibt ungeprüft."""
        opened = AsyncMock()
        monkeypatch.setattr(email_service, "open_pinned_socket", opened)
        await email_service.send_smtp_message(
            _msg(), host="mailrelay", port=25, username="u", password="p",
            use_tls=False, user_supplied=False,
        )
        opened.assert_not_awaited()
        kwargs = smtp_send.await_args.kwargs
        assert kwargs["hostname"] == "mailrelay" and kwargs["port"] == 25
        assert "sock" not in kwargs

    async def test_internal_user_server_is_never_contacted(self, monkeypatch, smtp_send):
        _fake_dns(monkeypatch, ["10.10.50.10"])
        with pytest.raises(UnsafeUrlError):
            await email_service.send_smtp_message(
                _msg(), host="smtp.example.org", port=587, username="u", password="p",
                use_tls=True, user_supplied=True,
            )
        smtp_send.assert_not_awaited()


class TestSendEmail:
    async def test_user_config_is_checked_at_send_time(self, monkeypatch, smtp_send):
        """K092: der Versandpfad prüfte den Host gar nicht. Zeigt der Name beim Senden
        nach innen, geht keine Mail raus."""
        _fake_dns(monkeypatch, ["172.18.0.5"])
        sent = await email_service.send_email("to@example.org", "S", "<p>x</p>", smtp_cfg=_smtp_cfg())
        assert sent is False
        smtp_send.assert_not_awaited()

    async def test_user_config_is_pinned(self, monkeypatch, smtp_send):
        marker = object()
        monkeypatch.setattr(email_service, "open_pinned_socket", AsyncMock(return_value=marker))
        sent = await email_service.send_email("to@example.org", "S", "<p>x</p>", smtp_cfg=_smtp_cfg())
        assert sent is True
        assert smtp_send.await_args.kwargs["sock"] is marker

    async def test_global_config_stays_unpinned(self, monkeypatch, smtp_send):
        monkeypatch.setattr(email_service.settings, "smtp_host", "mailrelay.internal")
        monkeypatch.setattr(email_service.settings, "smtp_user", "ops")
        monkeypatch.setattr(email_service.settings, "smtp_password", "pw")
        opened = AsyncMock()
        monkeypatch.setattr(email_service, "open_pinned_socket", opened)
        sent = await email_service.send_email("to@example.org", "S", "<p>x</p>")
        assert sent is True
        opened.assert_not_awaited()
        assert smtp_send.await_args.kwargs["hostname"] == "mailrelay.internal"


class TestEmailLogs:
    """K154: Empfängeradressen standen bei jedem Versand im Log."""

    async def test_success_and_failure_log_a_masked_address(self, monkeypatch, smtp_send, caplog):
        monkeypatch.setattr(email_service, "open_pinned_socket", AsyncMock(return_value=object()))
        with caplog.at_level(logging.INFO, logger="services.email_service"):
            assert await email_service.send_email("harry.muster@example.org", "S", "<p>x</p>", smtp_cfg=_smtp_cfg())
            smtp_send.side_effect = ConnectionRefusedError(111, "Connection refused")
            assert not await email_service.send_email("harry.muster@example.org", "S", "<p>x</p>", smtp_cfg=_smtp_cfg())
        assert len(caplog.records) == 2
        assert "harry.muster" not in caplog.text
        assert caplog.text.count("h***@example.org") == 2
        assert "ConnectionRefusedError" in caplog.text

    def test_mask_handles_odd_input(self):
        assert email_service._mask_address("a@b.ch") == "a***@b.ch"
        assert email_service._mask_address("kein-at") == "***"
        assert email_service._mask_address("") == "***"


class _FakeSmtpServer:
    """Spricht gerade genug SMTP für eine Mail ohne TLS und ohne Login."""

    def __init__(self):
        self.data: list[bytes] = []
        self.server: asyncio.base_events.Server | None = None
        self.port = 0

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader, writer):
        writer.write(b"220 test ESMTP\r\n")
        await writer.drain()
        in_data = False
        while line := await reader.readline():
            if in_data:
                if line != b".\r\n":
                    self.data.append(line)
                    continue
                in_data = False
                writer.write(b"250 OK\r\n")
            elif line[:4].upper() == b"EHLO":
                writer.write(b"250-test\r\n250 SIZE 1000000\r\n")
            elif line[:4].upper() == b"DATA":
                in_data = True
                writer.write(b"354 go ahead\r\n")
            elif line[:4].upper() == b"QUIT":
                writer.write(b"221 bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"250 OK\r\n")
            await writer.drain()
        writer.close()


class TestRebindingWithRealClient:
    async def test_mail_reaches_the_checked_address(self, monkeypatch):
        """K092 mit dem echten aiosmtplib: erste DNS-Antwort (geprüft) 127.0.0.1, jede
        weitere 127.0.0.2. Ohne Bindung löste aiosmtplib selbst noch einmal auf und
        landete bei der zweiten Adresse."""
        monkeypatch.setattr(url_guard, "_is_unsafe_ip", lambda ip: False)
        async with _FakeSmtpServer() as server:
            calls = _fake_dns(monkeypatch, ["127.0.0.1"], ["127.0.0.2"])
            await email_service.send_smtp_message(
                _msg(), host="smtp.example.org", port=server.port, username=None, password=None,
                use_tls=False, user_supplied=True, timeout=5,
            )
        assert calls == ["smtp.example.org"]
        assert any(b"Subject: Test" in line for line in server.data)


class TestValidateSmtpHost:
    async def test_cgnat_address_is_rejected(self):
        """K092: 100.64.0.0/10 galt als öffentlich."""
        with pytest.raises(HTTPException) as exc:
            await settings_service.validate_smtp_host("100.64.0.1")
        assert exc.value.status_code == 400
        assert "interne" in exc.value.detail

    @pytest.mark.parametrize("host", ["a..b", "x" * 64 + ".example.org"])
    async def test_invalid_hostname_is_a_400(self, host):
        """X28: der IDNA-Codec wirft UnicodeError; das war ein Serverfehler."""
        with pytest.raises(HTTPException) as exc:
            await settings_service.validate_smtp_host(host)
        assert exc.value.status_code == 400
        assert exc.value.detail == "SMTP-Host konnte nicht aufgelöst werden"

    async def test_resolver_timeout_is_a_400(self, monkeypatch):
        async def _timeout(host, port, **kw):
            raise url_guard.UnresolvableHostError("cannot resolve host: TimeoutError")

        monkeypatch.setattr(settings_service, "resolve_checked_addrs", _timeout)
        with pytest.raises(HTTPException) as exc:
            await settings_service.validate_smtp_host("dead.example.org")
        assert exc.value.status_code == 400

    async def test_resolution_leaves_the_event_loop(self, monkeypatch):
        """K003: getaddrinfo lief im Loop-Thread und hielt den ganzen Worker an."""
        threads: list[int] = []

        def _getaddrinfo(host, port, *args, **kwargs):
            threads.append(threading.get_ident())
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, 0))]

        monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
        await settings_service.validate_smtp_host("smtp.example.org")
        assert threads and threads[0] != threading.get_ident()

    async def test_public_address_passes(self):
        await settings_service.validate_smtp_host(PUBLIC_IP)


class TestSmtpRoutes:
    async def _save(self, client, token, host=PUBLIC_IP):
        return await client.put(
            "/api/settings/smtp",
            json={"host": host, "port": 587, "username": "u@example.org", "password": "pw"},
            headers=auth(token),
        )

    async def test_save_rejects_invalid_and_internal_hosts(self, client):
        token = await register_and_login(client, "smtp-save@test.local")
        for host in ("a..b", "100.64.0.1", "10.0.0.1"):
            res = await self._save(client, token, host)
            assert res.status_code == 400, host
        assert (await self._save(client, token)).status_code == 200

    async def test_save_is_limited_to_five_per_minute(self):
        import main  # noqa: F401 — registriert die Routen am Limiter
        from api.auth import limiter

        route_limits = limiter._route_limits["api.settings.save_smtp_config"]
        assert [str(l.limit) for l in route_limits] == ["5 per 1 minute"]

    async def test_test_mail_goes_through_the_pinned_sender(self, client, monkeypatch):
        token = await register_and_login(client, "smtp-test@test.local")
        await self._save(client, token)
        sender = AsyncMock()
        monkeypatch.setattr(settings_service, "send_smtp_message", sender)

        res = await client.post("/api/settings/smtp/test", headers=auth(token))

        assert res.status_code == 200
        kwargs = sender.await_args.kwargs
        assert kwargs["host"] == PUBLIC_IP and kwargs["port"] == 587
        assert kwargs["user_supplied"] is True

    async def test_error_text_carries_no_banner(self, client, monkeypatch):
        """K092: «Malformed SMTP response line: <Banner>» ging an den Client und
        machte den Test zum Portscanner."""
        token = await register_and_login(client, "smtp-banner@test.local")
        await self._save(client, token)
        monkeypatch.setattr(
            settings_service, "send_smtp_message",
            AsyncMock(side_effect=aiosmtplib.SMTPConnectError(
                "Error connecting to 93.184.216.34 on port 587: "
                "Malformed SMTP response line: SSH-2.0-OpenSSH_9.6"
            )),
        )

        res = await client.post("/api/settings/smtp/test", headers=auth(token))

        assert res.status_code == 400
        detail = res.json()["detail"]
        assert detail == "SMTP-Verbindung fehlgeschlagen. Bitte Host, Port und Verschlüsselung prüfen."
        assert "SSH" not in detail and "93.184" not in detail

    async def test_refused_and_timeout_look_the_same(self, client, monkeypatch):
        token = await register_and_login(client, "smtp-oracle@test.local")
        await self._save(client, token)
        details = []
        for error in (ConnectionRefusedError(111, "Connection refused"),
                      aiosmtplib.SMTPConnectTimeoutError("Timed out connecting")):
            monkeypatch.setattr(settings_service, "send_smtp_message", AsyncMock(side_effect=error))
            res = await client.post("/api/settings/smtp/test", headers=auth(token))
            assert res.status_code == 400
            details.append(res.json()["detail"])
        assert details[0] == details[1]

    async def test_host_turned_internal_is_reported_as_such(self, client, monkeypatch):
        token = await register_and_login(client, "smtp-rebind@test.local")
        await self._save(client, token)
        monkeypatch.setattr(
            settings_service, "send_smtp_message",
            AsyncMock(side_effect=UnsafeUrlError("host resolves to an internal address")),
        )
        res = await client.post("/api/settings/smtp/test", headers=auth(token))
        assert res.status_code == 400
        assert "interne" in res.json()["detail"]

    async def test_auth_error_stays_a_401(self, client, monkeypatch):
        token = await register_and_login(client, "smtp-auth@test.local")
        await self._save(client, token)
        monkeypatch.setattr(
            settings_service, "send_smtp_message",
            AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError(535, "bad credentials")),
        )
        res = await client.post("/api/settings/smtp/test", headers=auth(token))
        assert res.status_code == 401
        assert res.json()["detail"] == "SMTP-Authentifizierung fehlgeschlagen"
