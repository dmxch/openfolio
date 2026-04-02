"""Tests for ETF sector weights API endpoints."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="etf@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


VALID_SECTORS = [
    {"sector": "Technology", "weight_pct": 30.0},
    {"sector": "Healthcare", "weight_pct": 15.0},
    {"sector": "Financials", "weight_pct": 13.0},
    {"sector": "Consumer Cyclical", "weight_pct": 10.0},
    {"sector": "Industrials", "weight_pct": 8.0},
    {"sector": "Communication Services", "weight_pct": 7.0},
    {"sector": "Consumer Defensive", "weight_pct": 6.0},
    {"sector": "Energy", "weight_pct": 4.0},
    {"sector": "Basic Materials", "weight_pct": 3.0},
    {"sector": "Real Estate", "weight_pct": 2.0},
    {"sector": "Utilities", "weight_pct": 2.0},
]


class TestGetEtfSectors:
    async def test_get_unauthorized(self, client):
        res = await client.get("/api/etf-sectors/VOO")
        assert res.status_code in (401, 403)

    async def test_get_empty(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/etf-sectors/VOO", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["ticker"] == "VOO"
        assert data["sectors"] == []
        assert data["is_complete"] is False

    async def test_get_uppercase_ticker(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/etf-sectors/voo", headers=auth(token))
        assert res.status_code == 200
        assert res.json()["ticker"] == "VOO"


class TestPutEtfSectors:
    async def test_put_success(self, client):
        token = await register_and_login(client)
        res = await client.put(
            "/api/etf-sectors/VOO",
            json={"sectors": VALID_SECTORS},
            headers=auth(token),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_complete"] is True
        assert len(data["sectors"]) == 11

    async def test_put_invalid_sector(self, client):
        token = await register_and_login(client)
        sectors = [{"sector": "Invalid Sector", "weight_pct": 100.0}]
        res = await client.put(
            "/api/etf-sectors/VOO",
            json={"sectors": sectors},
            headers=auth(token),
        )
        assert res.status_code == 400
        assert "Ungültiger Sektor" in res.json()["detail"]

    async def test_put_sum_not_100(self, client):
        token = await register_and_login(client)
        sectors = [{"sector": "Technology", "weight_pct": 50.0}]
        res = await client.put(
            "/api/etf-sectors/VOO",
            json={"sectors": sectors},
            headers=auth(token),
        )
        assert res.status_code == 400
        assert "100%" in res.json()["detail"]

    async def test_put_unauthorized(self, client):
        res = await client.put(
            "/api/etf-sectors/VOO",
            json={"sectors": VALID_SECTORS},
        )
        assert res.status_code in (401, 403)

    async def test_put_idor_isolation(self, client):
        """User A's sectors are not visible to User B."""
        token_a = await register_and_login(client, "etf_a@example.com")
        token_b = await register_and_login(client, "etf_b@example.com")
        await client.put(
            "/api/etf-sectors/VOO",
            json={"sectors": VALID_SECTORS},
            headers=auth(token_a),
        )
        res = await client.get("/api/etf-sectors/VOO", headers=auth(token_b))
        assert res.status_code == 200
        assert res.json()["sectors"] == []


class TestDeleteEtfSectors:
    async def test_delete_success(self, client):
        token = await register_and_login(client)
        await client.put(
            "/api/etf-sectors/VOO",
            json={"sectors": VALID_SECTORS},
            headers=auth(token),
        )
        res = await client.delete("/api/etf-sectors/VOO", headers=auth(token))
        assert res.status_code == 200
        assert res.json()["status"] == "deleted"

        # Verify deleted
        get_res = await client.get("/api/etf-sectors/VOO", headers=auth(token))
        assert get_res.json()["sectors"] == []

    async def test_delete_unauthorized(self, client):
        res = await client.delete("/api/etf-sectors/VOO")
        assert res.status_code in (401, 403)
