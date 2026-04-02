"""Tests for admin API endpoints."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import update

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="admin@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


async def make_admin(db, email="admin@example.com"):
    """Promote a user to admin via direct DB update."""
    from models.user import User
    from sqlalchemy import update
    await db.execute(update(User).where(User.email == email).values(is_admin=True))
    await db.commit()


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestAdminGuard:
    async def test_non_admin_cannot_list_users(self, client):
        token = await register_and_login(client, "normal@example.com")
        res = await client.get("/api/admin/users", headers=auth(token))
        assert res.status_code == 403

    async def test_unauthenticated_cannot_access_admin(self, client):
        res = await client.get("/api/admin/users")
        assert res.status_code in (401, 403)


class TestListUsers:
    async def test_admin_can_list_users(self, client, db):
        token = await register_and_login(client)
        await make_admin(db)
        res = await client.get("/api/admin/users", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert "users" in data
        assert "total" in data
        assert data["total"] >= 1
        # Verify no sensitive data exposed (no password_hash)
        user = data["users"][0]
        assert "password_hash" not in user
        assert "email" in user


class TestUserStatus:
    async def test_admin_can_deactivate_user(self, client, db):
        admin_token = await register_and_login(client, "admin2@example.com")
        await make_admin(db, "admin2@example.com")
        # Create a second user
        await register_and_login(client, "user@example.com")
        # Get user list to find user ID
        users_res = await client.get("/api/admin/users", headers=auth(admin_token))
        users = users_res.json()["users"]
        target = next(u for u in users if u["email"] == "user@example.com")

        res = await client.patch(
            f"/api/admin/users/{target['id']}/status",
            json={"is_active": False},
            headers=auth(admin_token),
        )
        assert res.status_code == 200
        assert res.json()["is_active"] is False

    async def test_admin_cannot_deactivate_self(self, client, db):
        admin_token = await register_and_login(client, "self@example.com")
        await make_admin(db, "self@example.com")
        users_res = await client.get("/api/admin/users", headers=auth(admin_token))
        admin_user = next(u for u in users_res.json()["users"] if u["email"] == "self@example.com")

        res = await client.patch(
            f"/api/admin/users/{admin_user['id']}/status",
            json={"is_active": False},
            headers=auth(admin_token),
        )
        assert res.status_code == 400
        assert "selbst" in res.json()["detail"].lower()


class TestUserAdmin:
    async def test_admin_cannot_revoke_own_admin(self, client, db):
        admin_token = await register_and_login(client, "sole@example.com")
        await make_admin(db, "sole@example.com")
        users_res = await client.get("/api/admin/users", headers=auth(admin_token))
        admin_user = next(u for u in users_res.json()["users"] if u["email"] == "sole@example.com")

        res = await client.patch(
            f"/api/admin/users/{admin_user['id']}/admin",
            json={"is_admin": False},
            headers=auth(admin_token),
        )
        assert res.status_code == 400

    async def test_update_nonexistent_user(self, client, db):
        admin_token = await register_and_login(client, "admin3@example.com")
        await make_admin(db, "admin3@example.com")
        fake_id = str(uuid.uuid4())
        res = await client.patch(
            f"/api/admin/users/{fake_id}/status",
            json={"is_active": False},
            headers=auth(admin_token),
        )
        assert res.status_code == 404


class TestDeleteUser:
    async def test_admin_cannot_delete_self(self, client, db):
        admin_token = await register_and_login(client, "del@example.com")
        await make_admin(db, "del@example.com")
        users_res = await client.get("/api/admin/users", headers=auth(admin_token))
        admin_user = next(u for u in users_res.json()["users"] if u["email"] == "del@example.com")

        res = await client.delete(
            f"/api/admin/users/{admin_user['id']}",
            headers=auth(admin_token),
        )
        assert res.status_code == 400

    async def test_delete_nonexistent_user(self, client, db):
        admin_token = await register_and_login(client, "admin4@example.com")
        await make_admin(db, "admin4@example.com")
        fake_id = str(uuid.uuid4())
        res = await client.delete(f"/api/admin/users/{fake_id}", headers=auth(admin_token))
        assert res.status_code == 404


class TestAdminSettings:
    async def test_get_settings(self, client, db):
        admin_token = await register_and_login(client, "settings@example.com")
        await make_admin(db, "settings@example.com")
        res = await client.get("/api/admin/settings", headers=auth(admin_token))
        assert res.status_code == 200
        assert "registration_mode" in res.json()

    async def test_update_settings_valid(self, client, db):
        admin_token = await register_and_login(client, "s2@example.com")
        await make_admin(db, "s2@example.com")
        res = await client.patch(
            "/api/admin/settings",
            json={"registration_mode": "invite_only"},
            headers=auth(admin_token),
        )
        assert res.status_code == 200
        assert res.json()["registration_mode"] == "invite_only"

    async def test_update_settings_invalid_mode(self, client, db):
        admin_token = await register_and_login(client, "s3@example.com")
        await make_admin(db, "s3@example.com")
        res = await client.patch(
            "/api/admin/settings",
            json={"registration_mode": "invalid_mode"},
            headers=auth(admin_token),
        )
        assert res.status_code == 400


class TestInviteCodes:
    async def test_create_invite_code(self, client, db):
        admin_token = await register_and_login(client, "inv@example.com")
        await make_admin(db, "inv@example.com")
        res = await client.post("/api/admin/invite-codes", headers=auth(admin_token))
        assert res.status_code == 200
        data = res.json()
        assert "code" in data
        assert data["code"].startswith("OPEN-FO-")

    async def test_list_invite_codes(self, client, db):
        admin_token = await register_and_login(client, "inv2@example.com")
        await make_admin(db, "inv2@example.com")
        await client.post("/api/admin/invite-codes", headers=auth(admin_token))
        res = await client.get("/api/admin/invite-codes", headers=auth(admin_token))
        assert res.status_code == 200
        assert len(res.json()["codes"]) >= 1

    async def test_delete_invite_code(self, client, db):
        admin_token = await register_and_login(client, "inv3@example.com")
        await make_admin(db, "inv3@example.com")
        create_res = await client.post("/api/admin/invite-codes", headers=auth(admin_token))
        code_id = create_res.json()["id"]
        res = await client.delete(f"/api/admin/invite-codes/{code_id}", headers=auth(admin_token))
        assert res.status_code == 204
