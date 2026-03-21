"""Tests for API auth endpoints — register, login, MFA, backup codes."""

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def register_user(client: AsyncClient, email="test@example.com", password="TestPass1"):
    return await client.post("/api/auth/register", json={"email": email, "password": password})


async def login_user(client: AsyncClient, email="test@example.com", password="TestPass1", totp_code=None):
    body = {"email": email, "password": password}
    if totp_code:
        body["totp_code"] = totp_code
    return await client.post("/api/auth/login", json=body)


def auth_header(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestRegistration:
    async def test_register_success(self, client):
        res = await register_user(client)
        assert res.status_code == 201
        data = res.json()
        assert data["email"] == "test@example.com"
        assert "user_id" in data

    async def test_register_duplicate(self, client):
        await register_user(client)
        res = await register_user(client)
        assert res.status_code == 409

    async def test_register_weak_password(self, client):
        res = await register_user(client, password="weak")
        assert res.status_code == 422

    async def test_register_invalid_email(self, client):
        res = await register_user(client, email="not-an-email")
        assert res.status_code == 422


class TestLogin:
    async def test_login_success(self, client):
        await register_user(client)
        res = await login_user(client)
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "test@example.com"

    async def test_login_wrong_password(self, client):
        await register_user(client)
        res = await login_user(client, password="WrongPass1")
        assert res.status_code == 401

    async def test_login_unknown_email(self, client):
        res = await login_user(client, email="nobody@example.com")
        assert res.status_code == 401


class TestTokenRefresh:
    async def test_refresh_success(self, client):
        await register_user(client)
        login_res = await login_user(client)
        refresh_token = login_res.json()["refresh_token"]

        res = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_invalid_token(self, client):
        res = await client.post("/api/auth/refresh", json={"refresh_token": "invalid"})
        assert res.status_code == 401


class TestMe:
    async def test_get_me(self, client):
        await register_user(client)
        login_res = await login_user(client)
        token = login_res.json()["access_token"]

        res = await client.get("/api/auth/me", headers=auth_header(token))
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "test@example.com"
        assert "backup_codes_remaining" in data

    async def test_get_me_unauthorized(self, client):
        res = await client.get("/api/auth/me")
        assert res.status_code in (401, 403)


class TestChangePassword:
    async def test_change_password(self, client):
        await register_user(client)
        login_res = await login_user(client)
        token = login_res.json()["access_token"]

        res = await client.post(
            "/api/auth/change-password",
            json={"current_password": "TestPass1", "new_password": "NewPass1!"},
            headers=auth_header(token),
        )
        assert res.status_code == 200

    async def test_change_password_wrong_current(self, client):
        await register_user(client)
        login_res = await login_user(client)
        token = login_res.json()["access_token"]

        res = await client.post(
            "/api/auth/change-password",
            json={"current_password": "WrongPass1", "new_password": "NewPass1!"},
            headers=auth_header(token),
        )
        assert res.status_code == 401


class TestHealth:
    async def test_health_endpoint(self, client):
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
