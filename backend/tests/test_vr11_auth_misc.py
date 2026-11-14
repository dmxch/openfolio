"""Vollreview 11/2026, Fixer «auth»: Reset-Mail, Legacy-Schlüssel, Einladungscodes, Audit-Log.

K090 (Reset-Mail nur über das globale SMTP), K152 (Null-Schlüssel im
Entschlüsselungsring abschaltbar), K088 (Einladungscodes mit 96 Bit), K161 (Audit-Einträge
überleben die Kontolöschung).
"""

import asyncio
import base64
import json
import re
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select, update

from models.admin_audit_log import AdminAuditLog
from models.app_setting import AppSetting, InviteCode
from models.smtp_config import SmtpConfig
from models.user import User
from services import admin_service, auth_service

PW = "TestPassw0rd!2026"


def h(token):
    return {"Authorization": f"Bearer {token}"}


async def signup(client, email):
    res = await client.post("/api/auth/register", json={"email": email, "password": PW})
    assert res.status_code == 201, res.text
    res = await client.post("/api/auth/login", json={"email": email, "password": PW})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


async def get_user(db, email):
    res = await db.execute(
        select(User).where(func.lower(User.email) == email).execution_options(populate_existing=True)
    )
    return res.scalars().first()


async def make_admin(db, email):
    await db.execute(update(User).where(User.email == email).values(is_admin=True))
    await db.commit()


async def set_mode(db, mode):
    await db.execute(update(AppSetting).where(AppSetting.key == "registration_mode").values(value=mode))
    await db.commit()


class TestResetMailUsesGlobalSmtp:
    """K090: Die SMTP-Konfiguration des Kontos darf den Reset-Link nicht umleiten."""

    async def test_user_smtp_config_is_ignored(self, client, db, monkeypatch):
        from services import email_service

        await signup(client, "victim@example.com")
        user = await get_user(db, "victim@example.com")
        db.add(SmtpConfig(
            user_id=user.id,
            host="smtp.attacker.example",
            port=587,
            username="attacker",
            password_encrypted=auth_service.encrypt_value("secret"),
            from_email="attacker@attacker.example",
        ))
        await db.commit()

        sent = asyncio.Event()
        calls = []

        async def fake_send(to, subject, html, smtp_cfg=None):
            calls.append((to, smtp_cfg))
            sent.set()
            return True

        monkeypatch.setattr(email_service, "has_smtp_configured", lambda: True)
        monkeypatch.setattr(email_service, "send_email", fake_send)

        res = await client.post("/api/auth/forgot-password", json={"email": "victim@example.com"})
        assert res.status_code == 200
        await asyncio.wait_for(sent.wait(), timeout=2)
        assert calls == [("victim@example.com", None)]


def _zero_key_ciphertext(plain: str) -> str:
    """Chiffrat mit dem Schlüssel, den ein leerer LEGACY_ENCRYPTION_KEY ergab: 32 Nullen."""
    return Fernet(base64.urlsafe_b64encode(b"0" * 32)).encrypt(plain.encode()).decode()


class TestLegacyKeyRing:
    """K152: Der öffentlich bekannte Null-Schlüssel lässt sich abschalten.

    Die Fälle mit eingeschaltetem Schlüssel (Default) stehen in
    test_vr11_w3_misc_legacy_key.py.
    """

    async def test_zero_key_ciphertext_is_rejected(self, monkeypatch):
        monkeypatch.setattr(auth_service, "_LEGACY_DEFAULT_KEY", "")
        monkeypatch.setattr(auth_service.settings, "legacy_null_key_enabled", False)
        forged = _zero_key_ciphertext("JBSWY3DPEHPK3PXP")
        with pytest.raises(ValueError):
            auth_service.decrypt_value(forged)
        with pytest.raises(ValueError):
            auth_service.decrypt_totp_secret(forged)

    async def test_ring_holds_only_the_current_key_without_legacy_key(self, monkeypatch):
        monkeypatch.setattr(auth_service, "_LEGACY_DEFAULT_KEY", "")
        assert len(auth_service._get_legacy_fernets()) == 1

    async def test_configured_legacy_key_still_decrypts(self, monkeypatch):
        monkeypatch.setattr(auth_service, "_LEGACY_DEFAULT_KEY", "old-installation-key")
        legacy = auth_service._derive_legacy_fernet("old-installation-key")
        token = legacy.encrypt(b"geheim").decode()
        assert auth_service.decrypt_value(token) == "geheim"
        assert len(auth_service._get_legacy_fernets()) == 2

    async def test_current_key_roundtrip_unchanged(self):
        assert auth_service.decrypt_value(auth_service.encrypt_value("wert")) == "wert"


class TestInviteCodes:
    """K088: 96 Bit statt 16 Bit, kein Orakel über E-Mail und Passwort."""

    async def test_new_code_format(self, client, db):
        token = await signup(client, "boss@example.com")
        await make_admin(db, "boss@example.com")
        codes = set()
        for _ in range(3):
            res = await client.post("/api/admin/invite-codes", headers=h(token))
            assert res.status_code == 200, res.text
            codes.add(res.json()["code"])
        assert len(codes) == 3
        for code in codes:
            # 12 Zufallsbytes als 16 URL-sichere Zeichen; passt in String(20).
            assert re.fullmatch(r"OF-[A-Za-z0-9_-]{16}", code), code
            assert len(code) <= 20

    async def test_new_code_can_be_redeemed(self, client, db):
        token = await signup(client, "boss@example.com")
        await make_admin(db, "boss@example.com")
        code = (await client.post("/api/admin/invite-codes", headers=h(token))).json()["code"]
        await set_mode(db, "invite_only")
        res = await client.post(
            "/api/auth/register", json={"email": "guest@example.com", "password": PW, "invite_code": code},
        )
        assert res.status_code == 201, res.text

    async def test_pasted_code_with_whitespace_is_accepted(self, client, db):
        db.add(InviteCode(code="OF-valid-code-123456", created_by=uuid.uuid4()))
        await db.commit()
        await set_mode(db, "invite_only")
        res = await client.post(
            "/api/auth/register",
            json={"email": "guest@example.com", "password": PW, "invite_code": " OF-valid-code-123456\n"},
        )
        assert res.status_code == 201, res.text

    async def test_old_format_codes_stay_valid(self, client, db):
        db.add(InviteCode(code="OPEN-FO-2026-AB12", created_by=uuid.uuid4()))
        await db.commit()
        await set_mode(db, "invite_only")
        res = await client.post(
            "/api/auth/register",
            json={"email": "guest@example.com", "password": PW, "invite_code": "OPEN-FO-2026-AB12"},
        )
        assert res.status_code == 201, res.text

    @pytest.mark.parametrize("payload", [
        {"email": "x", "password": PW},
        {"email": "guest@example.com", "password": "weak"},
    ])
    async def test_invalid_input_does_not_reveal_a_valid_code(self, client, db, payload):
        db.add(InviteCode(code="OF-valid-code-123456", created_by=uuid.uuid4()))
        await db.commit()
        await set_mode(db, "invite_only")

        valid = await client.post("/api/auth/register", json={**payload, "invite_code": "OF-valid-code-123456"})
        guessed = await client.post("/api/auth/register", json={**payload, "invite_code": "OF-falsch"})
        assert valid.status_code == guessed.status_code == 422
        assert valid.json()["detail"] == guessed.json()["detail"]
        invite = (await db.execute(select(InviteCode).execution_options(populate_existing=True))).scalars().one()
        assert invite.is_active is True and invite.used_by is None

    async def test_collision_draws_a_new_code(self, client, db, monkeypatch):
        token = await signup(client, "boss@example.com")
        await make_admin(db, "boss@example.com")
        db.add(InviteCode(code="OF-taken", created_by=uuid.uuid4()))
        await db.commit()

        drawn = iter(["OF-taken", "OF-fresh"])
        monkeypatch.setattr(admin_service, "_generate_invite_code", lambda: next(drawn))

        res = await client.post("/api/admin/invite-codes", headers=h(token))
        assert res.status_code == 200, res.text
        assert res.json()["code"] == "OF-fresh"
        stored = (await db.execute(select(InviteCode.code))).scalars().all()
        assert sorted(stored) == ["OF-fresh", "OF-taken"]

    async def test_repeated_collision_is_a_clean_error(self, client, db, monkeypatch):
        token = await signup(client, "boss@example.com")
        await make_admin(db, "boss@example.com")
        db.add(InviteCode(code="OF-taken", created_by=uuid.uuid4()))
        await db.commit()
        monkeypatch.setattr(admin_service, "_generate_invite_code", lambda: "OF-taken")

        res = await client.post("/api/admin/invite-codes", headers=h(token))
        assert res.status_code == 503
        assert "erneut versuchen" in res.json()["detail"]
        stored = (await db.execute(select(InviteCode.code))).scalars().all()
        assert stored == ["OF-taken"]


class TestLastAdminCannotDeleteItself:
    """Abnahme Fixlauf: ohne Admin wäre die Adresse aus ADMIN_EMAIL frei."""

    async def test_sole_admin_is_refused(self, client, db):
        token = await signup(client, "sole-admin@example.com")
        await make_admin(db, "sole-admin@example.com")

        res = await client.request("DELETE", "/api/auth/account", json={"password": PW}, headers=h(token))

        assert res.status_code == 409
        assert "letzte Admin-Konto" in res.json()["detail"]
        assert await get_user(db, "sole-admin@example.com") is not None

    async def test_deactivated_second_admin_does_not_count(self, client, db):
        token = await signup(client, "sole-admin@example.com")
        await make_admin(db, "sole-admin@example.com")
        await signup(client, "locked-admin@example.com")
        await make_admin(db, "locked-admin@example.com")
        await db.execute(update(User).where(User.email == "locked-admin@example.com").values(is_active=False))
        await db.commit()

        res = await client.request("DELETE", "/api/auth/account", json={"password": PW}, headers=h(token))

        assert res.status_code == 409

    async def test_admin_with_a_second_active_admin_may_leave(self, client, db):
        token = await signup(client, "first-admin@example.com")
        await make_admin(db, "first-admin@example.com")
        await signup(client, "second-admin@example.com")
        await make_admin(db, "second-admin@example.com")

        res = await client.request("DELETE", "/api/auth/account", json={"password": PW}, headers=h(token))

        assert res.status_code == 204

    async def test_regular_user_may_leave_without_any_admin(self, client, db):
        token = await signup(client, "plain@example.com")

        res = await client.request("DELETE", "/api/auth/account", json={"password": PW}, headers=h(token))

        assert res.status_code == 204


class TestAuditLogSurvivesAccountDeletion:
    """K161: Ein Admin kann seine Spuren nicht mit dem eigenen Konto löschen."""

    async def _entries(self, db):
        res = await db.execute(select(AdminAuditLog).execution_options(populate_existing=True))
        return res.scalars().all()

    async def test_self_deletion_keeps_the_entries(self, client, db):
        token = await signup(client, "rogue@example.com")
        await make_admin(db, "rogue@example.com")
        assert (await client.post("/api/admin/invite-codes", headers=h(token))).status_code == 200
        assert (await client.get("/api/admin/users", headers=h(token))).status_code == 200
        before = await self._entries(db)
        assert {e.action for e in before} == {"create_invite_code", "list_users"}
        # Ein zweiter Admin: das letzte Admin-Konto lässt sich nicht löschen.
        await signup(client, "second-admin@example.com")
        await make_admin(db, "second-admin@example.com")

        res = await client.request("DELETE", "/api/auth/account", json={"password": PW}, headers=h(token))
        assert res.status_code == 204
        assert await get_user(db, "rogue@example.com") is None

        after = await self._entries(db)
        assert {e.action for e in after} == {"create_invite_code", "list_users"}
        for entry in after:
            assert entry.admin_id is None
            assert json.loads(entry.details)["admin_email"] == "rogue@example.com"
        # Bestehende Details bleiben erhalten.
        invite_entry = next(e for e in after if e.action == "create_invite_code")
        assert json.loads(invite_entry.details)["code"].startswith("OF-")

        log = await admin_service.get_audit_log(db, 1, 50)
        assert log["total"] == 2
        for row in log["entries"]:
            assert row["admin_id"] is None
            assert row["admin_email"] == "rogue@example.com"

    async def test_admin_deleting_another_admin_keeps_that_admins_entries(self, client, db):
        rogue = await signup(client, "rogue@example.com")
        await make_admin(db, "rogue@example.com")
        boss = await signup(client, "boss@example.com")
        await make_admin(db, "boss@example.com")
        assert (await client.get("/api/admin/users", headers=h(rogue))).status_code == 200
        rogue_id = (await get_user(db, "rogue@example.com")).id

        res = await client.delete(f"/api/admin/users/{rogue_id}", headers=h(boss))
        assert res.status_code == 204, res.text

        log = await admin_service.get_audit_log(db, 1, 50)
        by_action = {row["action"]: row for row in log["entries"]}
        assert by_action["list_users"]["admin_id"] is None
        assert by_action["list_users"]["admin_email"] == "rogue@example.com"
        assert by_action["delete_user"]["admin_email"] == "boss@example.com"

    async def test_details_of_live_admins_cannot_spoof_the_email(self, db):
        admin = User(email="real@example.com", password_hash="x", is_admin=True)
        db.add(admin)
        await db.flush()
        db.add(AdminAuditLog(admin_id=admin.id, action="x", details=json.dumps({"admin_email": "fake@example.com"})))
        await db.commit()
        log = await admin_service.get_audit_log(db, 1, 50)
        assert log["entries"][0]["admin_email"] == "real@example.com"
