"""Tests for private equity API endpoints."""

import uuid

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"

HOLDING_DATA = {
    "company_name": "Test AG",
    "num_shares": 100,
    "nominal_value": 1000.0,
    "purchase_price_per_share": 50.0,
    "currency": "CHF",
}


async def register_and_login(client: AsyncClient, email="pe@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestListHoldings:
    async def test_list_unauthorized(self, client):
        res = await client.get("/api/private-equity")
        assert res.status_code in (401, 403)

    async def test_list_empty(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/private-equity", headers=auth(token))
        assert res.status_code == 200


class TestCreateHolding:
    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_create_success(self, mock_cache, client):
        token = await register_and_login(client)
        res = await client.post("/api/private-equity", json=HOLDING_DATA, headers=auth(token))
        assert res.status_code == 201
        data = res.json()
        assert data["company_name"] == "Test AG"
        assert data["num_shares"] == 100

    async def test_create_unauthorized(self, client):
        res = await client.post("/api/private-equity", json=HOLDING_DATA)
        assert res.status_code in (401, 403)

    async def test_create_missing_fields(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/private-equity",
            json={"company_name": "Test"},
            headers=auth(token),
        )
        assert res.status_code == 422

    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_create_invalid_shares(self, mock_cache, client):
        token = await register_and_login(client)
        data = {**HOLDING_DATA, "num_shares": 0}
        res = await client.post("/api/private-equity", json=data, headers=auth(token))
        assert res.status_code == 422


class TestGetHolding:
    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_get_success(self, mock_cache, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/private-equity", json=HOLDING_DATA, headers=auth(token))
        holding_id = create_res.json()["id"]
        res = await client.get(f"/api/private-equity/{holding_id}", headers=auth(token))
        assert res.status_code == 200
        assert res.json()["company_name"] == "Test AG"

    async def test_get_not_found(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.get(f"/api/private-equity/{fake_id}", headers=auth(token))
        assert res.status_code == 404

    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_get_idor(self, mock_cache, client):
        token_a = await register_and_login(client, "pe_a@example.com")
        token_b = await register_and_login(client, "pe_b@example.com")
        create_res = await client.post("/api/private-equity", json=HOLDING_DATA, headers=auth(token_a))
        holding_id = create_res.json()["id"]
        res = await client.get(f"/api/private-equity/{holding_id}", headers=auth(token_b))
        assert res.status_code == 404


class TestDeleteHolding:
    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_delete_success(self, mock_cache, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/private-equity", json=HOLDING_DATA, headers=auth(token))
        holding_id = create_res.json()["id"]
        res = await client.delete(f"/api/private-equity/{holding_id}", headers=auth(token))
        assert res.status_code == 204

    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_delete_idor(self, mock_cache, client):
        token_a = await register_and_login(client, "pe_del_a@example.com")
        token_b = await register_and_login(client, "pe_del_b@example.com")
        create_res = await client.post("/api/private-equity", json=HOLDING_DATA, headers=auth(token_a))
        holding_id = create_res.json()["id"]
        res = await client.delete(f"/api/private-equity/{holding_id}", headers=auth(token_b))
        assert res.status_code == 404


class TestValuations:
    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_create_valuation_success(self, mock_cache, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/private-equity", json=HOLDING_DATA, headers=auth(token))
        holding_id = create_res.json()["id"]
        val_data = {
            "valuation_date": "2025-12-31",
            "gross_value_per_share": 75.0,
            "discount_pct": 30.0,
        }
        res = await client.post(
            f"/api/private-equity/{holding_id}/valuations",
            json=val_data,
            headers=auth(token),
        )
        assert res.status_code == 201

    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_create_valuation_invalid_holding(self, mock_cache, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        val_data = {"valuation_date": "2025-12-31", "gross_value_per_share": 75.0}
        res = await client.post(
            f"/api/private-equity/{fake_id}/valuations",
            json=val_data,
            headers=auth(token),
        )
        assert res.status_code == 404


class TestDividends:
    @patch("api.private_equity.invalidate_portfolio_cache")
    async def test_create_dividend_success(self, mock_cache, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/private-equity", json=HOLDING_DATA, headers=auth(token))
        holding_id = create_res.json()["id"]
        div_data = {
            "payment_date": "2025-06-15",
            "dividend_per_share": 2.50,
            "withholding_tax_pct": 35.0,
            "fiscal_year": 2024,
        }
        res = await client.post(
            f"/api/private-equity/{holding_id}/dividends",
            json=div_data,
            headers=auth(token),
        )
        assert res.status_code == 201
