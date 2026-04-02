"""Tests for price-alerts API endpoints."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="alert@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestCreateAlert:
    async def test_create_alert_success(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/price-alerts",
            json={"ticker": "aapl", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["ticker"] == "AAPL"
        assert data["alert_type"] == "price_above"
        assert data["target_value"] == 200.0
        assert data["is_active"] is True
        assert data["is_triggered"] is False

    async def test_create_alert_invalid_type(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "invalid_type", "target_value": 200.0},
            headers=auth(token),
        )
        assert res.status_code == 400
        assert "Ungültiger Alarm-Typ" in res.json()["detail"]

    async def test_create_alert_unauthorized(self, client):
        res = await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
        )
        assert res.status_code in (401, 403)

    async def test_create_alert_missing_fields(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL"},
            headers=auth(token),
        )
        assert res.status_code == 422


class TestListAlerts:
    async def test_list_alerts_empty(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/price-alerts", headers=auth(token))
        assert res.status_code == 200
        assert res.json() == []

    async def test_list_alerts_after_create(self, client):
        token = await register_and_login(client)
        await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token),
        )
        await client.post(
            "/api/price-alerts",
            json={"ticker": "MSFT", "alert_type": "price_below", "target_value": 300.0},
            headers=auth(token),
        )
        res = await client.get("/api/price-alerts", headers=auth(token))
        assert res.status_code == 200
        assert len(res.json()) == 2

    async def test_list_alerts_filter_ticker(self, client):
        token = await register_and_login(client)
        await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token),
        )
        await client.post(
            "/api/price-alerts",
            json={"ticker": "MSFT", "alert_type": "price_below", "target_value": 300.0},
            headers=auth(token),
        )
        res = await client.get("/api/price-alerts?ticker=AAPL", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["ticker"] == "AAPL"

    async def test_list_alerts_idor_protection(self, client):
        """User A cannot see User B's alerts."""
        token_a = await register_and_login(client, "a@example.com")
        token_b = await register_and_login(client, "b@example.com")
        await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token_a),
        )
        res = await client.get("/api/price-alerts", headers=auth(token_b))
        assert res.status_code == 200
        assert len(res.json()) == 0


class TestUpdateAlert:
    async def test_update_alert_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token),
        )
        alert_id = create_res.json()["id"]
        res = await client.patch(
            f"/api/price-alerts/{alert_id}",
            json={"target_value": 250.0, "note": "Updated"},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["target_value"] == 250.0

    async def test_update_alert_not_found(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.patch(
            f"/api/price-alerts/{fake_id}",
            json={"target_value": 250.0},
            headers=auth(token),
        )
        assert res.status_code == 404

    async def test_update_alert_idor(self, client):
        """User B cannot update User A's alert."""
        token_a = await register_and_login(client, "a2@example.com")
        token_b = await register_and_login(client, "b2@example.com")
        create_res = await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token_a),
        )
        alert_id = create_res.json()["id"]
        res = await client.patch(
            f"/api/price-alerts/{alert_id}",
            json={"target_value": 250.0},
            headers=auth(token_b),
        )
        assert res.status_code == 404


class TestDeleteAlert:
    async def test_delete_alert_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token),
        )
        alert_id = create_res.json()["id"]
        res = await client.delete(f"/api/price-alerts/{alert_id}", headers=auth(token))
        assert res.status_code == 204

        # Verify deleted
        list_res = await client.get("/api/price-alerts", headers=auth(token))
        assert len(list_res.json()) == 0

    async def test_delete_alert_idor(self, client):
        """User B cannot delete User A's alert."""
        token_a = await register_and_login(client, "a3@example.com")
        token_b = await register_and_login(client, "b3@example.com")
        create_res = await client.post(
            "/api/price-alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=auth(token_a),
        )
        alert_id = create_res.json()["id"]
        res = await client.delete(f"/api/price-alerts/{alert_id}", headers=auth(token_b))
        assert res.status_code == 404
