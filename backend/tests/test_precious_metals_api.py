"""Tests for precious metals API endpoints."""

import uuid

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"

GOLD_ITEM = {
    "metal_type": "gold",
    "form": "bar",
    "weight_grams": 31.1035,
    "purchase_date": "2025-01-15",
    "purchase_price_chf": 5800.00,
}


async def register_and_login(client: AsyncClient, email="metals@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestListItems:
    async def test_list_unauthorized(self, client):
        res = await client.get("/api/precious-metals")
        assert res.status_code in (401, 403)

    async def test_list_empty(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/precious-metals", headers=auth(token))
        assert res.status_code == 200
        assert res.json()["groups"] == []


class TestCreateItem:
    @patch("api.precious_metals.trigger_snapshot_regen")
    @patch("api.precious_metals.invalidate_portfolio_cache")
    async def test_create_gold_success(self, mock_cache, mock_snap, client):
        token = await register_and_login(client)
        res = await client.post("/api/precious-metals", json=GOLD_ITEM, headers=auth(token))
        assert res.status_code == 201
        data = res.json()
        assert data["metal_type"] == "gold"
        assert data["form"] == "bar"
        assert float(data["weight_grams"]) == 31.1035

    @patch("api.precious_metals.trigger_snapshot_regen")
    @patch("api.precious_metals.invalidate_portfolio_cache")
    async def test_create_invalid_metal_type(self, mock_cache, mock_snap, client):
        token = await register_and_login(client)
        item = {**GOLD_ITEM, "metal_type": "bronze"}
        res = await client.post("/api/precious-metals", json=item, headers=auth(token))
        assert res.status_code == 422

    @patch("api.precious_metals.trigger_snapshot_regen")
    @patch("api.precious_metals.invalidate_portfolio_cache")
    async def test_create_invalid_form(self, mock_cache, mock_snap, client):
        token = await register_and_login(client)
        item = {**GOLD_ITEM, "form": "ring"}
        res = await client.post("/api/precious-metals", json=item, headers=auth(token))
        assert res.status_code == 422

    async def test_create_unauthorized(self, client):
        res = await client.post("/api/precious-metals", json=GOLD_ITEM)
        assert res.status_code in (401, 403)

    async def test_create_missing_fields(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/precious-metals",
            json={"metal_type": "gold"},
            headers=auth(token),
        )
        assert res.status_code == 422


class TestUpdateItem:
    @patch("api.precious_metals.trigger_snapshot_regen")
    @patch("api.precious_metals.invalidate_portfolio_cache")
    async def test_update_success(self, mock_cache, mock_snap, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/precious-metals", json=GOLD_ITEM, headers=auth(token))
        item_id = create_res.json()["id"]
        res = await client.put(
            f"/api/precious-metals/{item_id}",
            json={"notes": "Updated note"},
            headers=auth(token),
        )
        assert res.status_code == 200

    async def test_update_not_found(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.put(
            f"/api/precious-metals/{fake_id}",
            json={"notes": "test"},
            headers=auth(token),
        )
        assert res.status_code == 404

    @patch("api.precious_metals.trigger_snapshot_regen")
    @patch("api.precious_metals.invalidate_portfolio_cache")
    async def test_update_idor(self, mock_cache, mock_snap, client):
        token_a = await register_and_login(client, "metals_a@example.com")
        token_b = await register_and_login(client, "metals_b@example.com")
        create_res = await client.post("/api/precious-metals", json=GOLD_ITEM, headers=auth(token_a))
        item_id = create_res.json()["id"]
        res = await client.put(
            f"/api/precious-metals/{item_id}",
            json={"notes": "hacked"},
            headers=auth(token_b),
        )
        assert res.status_code == 404


class TestDeleteItem:
    @patch("api.precious_metals.trigger_snapshot_regen")
    @patch("api.precious_metals.invalidate_portfolio_cache")
    async def test_delete_success(self, mock_cache, mock_snap, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/precious-metals", json=GOLD_ITEM, headers=auth(token))
        item_id = create_res.json()["id"]
        res = await client.delete(f"/api/precious-metals/{item_id}", headers=auth(token))
        assert res.status_code == 204

    @patch("api.precious_metals.trigger_snapshot_regen")
    @patch("api.precious_metals.invalidate_portfolio_cache")
    async def test_delete_idor(self, mock_cache, mock_snap, client):
        token_a = await register_and_login(client, "metals_del_a@example.com")
        token_b = await register_and_login(client, "metals_del_b@example.com")
        create_res = await client.post("/api/precious-metals", json=GOLD_ITEM, headers=auth(token_a))
        item_id = create_res.json()["id"]
        res = await client.delete(f"/api/precious-metals/{item_id}", headers=auth(token_b))
        assert res.status_code == 404
