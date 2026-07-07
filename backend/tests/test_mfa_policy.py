"""Tests for the admin-configurable MFA enforcement policy.

Deckt ab: Policy-Stufen (off/admins_only/selected/all), die harte Erzwingung in
get_current_user (403 + X-MFA-Setup-Required), die Allowlist (Enrollment/Logout
bleiben erreichbar, sonst koennte sich niemand einrichten), das Aufheben des Gates
nach erfolgtem Enrollment, sowie die Admin-Endpoints (Policy + per-User-Flag).
"""

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from models.app_setting import AppSetting
from models.user import User

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_user(client: AsyncClient, email="user@example.com", password=TEST_PASSWORD):
    return await client.post("/api/auth/register", json={"email": email, "password": password})


async def login_user(client: AsyncClient, email="user@example.com", password=TEST_PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


def auth_header(token: str):
    return {"Authorization": f"Bearer {token}"}


async def set_policy(db, value: str):
    """Insert the global mfa_policy row directly (tests run without migrations)."""
    db.add(AppSetting(key="mfa_policy", value=value))
    await db.commit()


async def _get_user(db, email: str) -> User:
    res = await db.execute(select(User).where(func.lower(User.email) == email.lower()))
    return res.scalars().first()


async def promote_admin(db, email: str):
    u = await _get_user(db, email)
    u.is_admin = True
    await db.commit()


async def flag_mfa_required(db, email: str, value: bool = True):
    u = await _get_user(db, email)
    u.mfa_required = value
    await db.commit()


async def register_and_token(client, email="user@example.com"):
    await register_user(client, email=email)
    res = await login_user(client, email=email)
    return res.json()["access_token"]


class TestPolicyDefaults:
    async def test_no_policy_row_means_off(self, client, db):
        """Ohne gesetzte Policy (Default in Tests) wird niemand gegated."""
        token = await register_and_token(client)
        res = await client.get("/api/auth/sessions", headers=auth_header(token))
        assert res.status_code == 200

    async def test_login_flags_setup_required_under_all(self, client, db):
        await set_policy(db, "all")
        await register_user(client)
        res = await login_user(client)
        assert res.status_code == 200
        assert res.json()["mfa_setup_required"] is True


class TestHardEnforcement:
    async def test_all_gates_protected_endpoint(self, client, db):
        await set_policy(db, "all")
        token = await register_and_token(client)
        res = await client.get("/api/auth/sessions", headers=auth_header(token))
        assert res.status_code == 403
        assert res.headers.get("X-MFA-Setup-Required") == "1"

    async def test_allowlist_stays_reachable(self, client, db):
        """Ein gegateter User muss /me, /mfa/setup und /logout noch erreichen."""
        await set_policy(db, "all")
        token = await register_and_token(client)

        me = await client.get("/api/auth/me", headers=auth_header(token))
        assert me.status_code == 200
        assert me.json()["mfa_setup_required"] is True

        setup = await client.post("/api/auth/mfa/setup", headers=auth_header(token))
        assert setup.status_code == 200
        assert "secret" in setup.json()

    async def test_enrolling_clears_the_gate(self, client, db):
        await set_policy(db, "all")
        token = await register_and_token(client)

        # blocked before enrollment
        assert (await client.get("/api/auth/sessions", headers=auth_header(token))).status_code == 403

        # enroll: setup -> verify with a live TOTP code
        secret = (await client.post("/api/auth/mfa/setup", headers=auth_header(token))).json()["secret"]
        code = pyotp.TOTP(secret).now()
        verify = await client.post(
            "/api/auth/mfa/verify-setup",
            json={"totp_code": code},
            headers=auth_header(token),
        )
        assert verify.status_code == 200

        # now compliant -> protected endpoint passes, no more setup nag
        assert (await client.get("/api/auth/sessions", headers=auth_header(token))).status_code == 200
        me = await client.get("/api/auth/me", headers=auth_header(token))
        assert me.json()["mfa_setup_required"] is False


class TestPolicyScoping:
    async def test_admins_only_gates_only_admins(self, client, db):
        await set_policy(db, "admins_only")
        user_token = await register_and_token(client, email="normal@example.com")
        admin_token = await register_and_token(client, email="boss@example.com")
        await promote_admin(db, "boss@example.com")

        # non-admin: not gated
        assert (await client.get("/api/auth/sessions", headers=auth_header(user_token))).status_code == 200
        # admin without MFA: gated
        assert (await client.get("/api/auth/sessions", headers=auth_header(admin_token))).status_code == 403

    async def test_selected_gates_only_flagged_users(self, client, db):
        await set_policy(db, "selected")
        flagged_token = await register_and_token(client, email="picked@example.com")
        other_token = await register_and_token(client, email="other@example.com")
        await flag_mfa_required(db, "picked@example.com", True)

        assert (await client.get("/api/auth/sessions", headers=auth_header(flagged_token))).status_code == 403
        assert (await client.get("/api/auth/sessions", headers=auth_header(other_token))).status_code == 200

    async def test_off_gates_nobody(self, client, db):
        await set_policy(db, "off")
        token = await register_and_token(client)
        await flag_mfa_required(db, "user@example.com", True)  # even a flagged user
        assert (await client.get("/api/auth/sessions", headers=auth_header(token))).status_code == 200


class TestAdminEndpoints:
    async def test_get_and_set_policy(self, client, db):
        token = await register_and_token(client, email="boss@example.com")
        await promote_admin(db, "boss@example.com")

        got = await client.get("/api/admin/settings", headers=auth_header(token))
        assert got.status_code == 200
        assert got.json()["mfa_policy"] == "off"

        # 'selected' does not gate the admin (not flagged) -> can keep using admin API
        patched = await client.patch(
            "/api/admin/settings", json={"mfa_policy": "selected"}, headers=auth_header(token)
        )
        assert patched.status_code == 200
        assert patched.json()["mfa_policy"] == "selected"

        again = await client.get("/api/admin/settings", headers=auth_header(token))
        assert again.json()["mfa_policy"] == "selected"

    async def test_invalid_policy_rejected(self, client, db):
        token = await register_and_token(client, email="boss@example.com")
        await promote_admin(db, "boss@example.com")
        res = await client.patch(
            "/api/admin/settings", json={"mfa_policy": "bogus"}, headers=auth_header(token)
        )
        assert res.status_code == 400

    async def test_set_user_mfa_required_flag(self, client, db):
        admin_token = await register_and_token(client, email="boss@example.com")
        await promote_admin(db, "boss@example.com")
        await register_user(client, email="target@example.com")
        target = await _get_user(db, "target@example.com")

        res = await client.patch(
            f"/api/admin/users/{target.id}/mfa-required",
            json={"mfa_required": True},
            headers=auth_header(admin_token),
        )
        assert res.status_code == 200
        assert res.json()["mfa_required"] is True

        listing = await client.get("/api/admin/users", headers=auth_header(admin_token))
        rows = {u["email"]: u for u in listing.json()["users"]}
        assert rows["target@example.com"]["mfa_required"] is True


class TestAllowlistFormat:
    async def test_exempt_paths_pin_api_form(self):
        """Die Lockout-Sicherheit haengt daran, dass die Allowlist exakt die vom
        Backend gesehene /api/...-Form trifft (nginx strippt kein Prefix). Form
        hier festnageln, damit ein spaeterer /api-Rewrite/root_path laut auffaellt
        statt still alle auszusperren."""
        from auth import _MFA_SETUP_EXEMPT_PATHS

        assert _MFA_SETUP_EXEMPT_PATHS
        for p in _MFA_SETUP_EXEMPT_PATHS:
            assert p.startswith("/api/auth/"), p
        # Die zum Einrichten/Abmelden zwingend noetigen Endpoints muessen exempt sein.
        for required in (
            "/api/auth/me",
            "/api/auth/mfa/setup",
            "/api/auth/mfa/verify-setup",
            "/api/auth/logout",
        ):
            assert required in _MFA_SETUP_EXEMPT_PATHS
