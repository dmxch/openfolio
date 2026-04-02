"""Tests for settings API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="settings@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestGetSettings:
    async def test_get_settings_unauthorized(self, client):
        res = await client.get("/api/settings")
        assert res.status_code in (401, 403)

    async def test_get_settings_success(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/settings", headers=auth(token))
        assert res.status_code == 200


class TestUpdateSettings:
    async def test_update_settings_unauthorized(self, client):
        res = await client.patch("/api/settings", json={"number_format": "de"})
        assert res.status_code in (401, 403)

    async def test_update_settings_success(self, client):
        token = await register_and_login(client)
        res = await client.patch(
            "/api/settings",
            json={"number_format": "de"},
            headers=auth(token),
        )
        assert res.status_code == 200


class TestFredApiKey:
    async def test_save_fred_key_unauthorized(self, client):
        res = await client.put("/api/settings/fred-api-key", json={"api_key": "test123"})
        assert res.status_code in (401, 403)

    async def test_save_fred_key_success(self, client):
        token = await register_and_login(client)
        res = await client.put(
            "/api/settings/fred-api-key",
            json={"api_key": "test-fred-key-12345"},
            headers=auth(token),
        )
        assert res.status_code == 200

    async def test_save_fred_key_empty(self, client):
        token = await register_and_login(client)
        res = await client.put(
            "/api/settings/fred-api-key",
            json={"api_key": ""},
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_delete_fred_key_unauthorized(self, client):
        res = await client.delete("/api/settings/fred-api-key")
        assert res.status_code in (401, 403)

    async def test_delete_fred_key_success(self, client):
        token = await register_and_login(client)
        res = await client.delete("/api/settings/fred-api-key", headers=auth(token))
        assert res.status_code == 204


class TestOnboarding:
    async def test_onboarding_status_unauthorized(self, client):
        res = await client.get("/api/settings/onboarding/status")
        assert res.status_code in (401, 403)

    async def test_onboarding_status_success(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/settings/onboarding/status", headers=auth(token))
        assert res.status_code == 200

    async def test_mark_tour_complete(self, client):
        token = await register_and_login(client)
        res = await client.post("/api/settings/onboarding/tour-complete", headers=auth(token))
        assert res.status_code == 200


class TestExport:
    async def test_export_portfolio_unauthorized(self, client):
        res = await client.get("/api/export/portfolio")
        assert res.status_code in (401, 403)

    async def test_export_portfolio_success(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/export/portfolio", headers=auth(token))
        assert res.status_code == 200
        assert "text/csv" in res.headers.get("content-type", "")

    async def test_export_transactions_success(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/export/transactions", headers=auth(token))
        assert res.status_code == 200
        assert "text/csv" in res.headers.get("content-type", "")
