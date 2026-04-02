"""Tests for real estate API endpoints."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"

PROPERTY_DATA = {
    "name": "Testhaus",
    "property_type": "efh",
    "purchase_price": 850000.0,
}


async def register_and_login(client: AsyncClient, email="realestate@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestListProperties:
    async def test_list_unauthorized(self, client):
        res = await client.get("/api/properties")
        assert res.status_code in (401, 403)

    async def test_list_empty(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/properties", headers=auth(token))
        assert res.status_code == 200


class TestCreateProperty:
    async def test_create_success(self, client):
        token = await register_and_login(client)
        res = await client.post("/api/properties", json=PROPERTY_DATA, headers=auth(token))
        assert res.status_code == 201
        data = res.json()
        assert "id" in data
        assert data["name"] == "Testhaus"

    async def test_create_unauthorized(self, client):
        res = await client.post("/api/properties", json=PROPERTY_DATA)
        assert res.status_code in (401, 403)

    async def test_create_missing_fields(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/properties",
            json={"name": "Test"},
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_create_invalid_type(self, client):
        token = await register_and_login(client)
        data = {**PROPERTY_DATA, "property_type": "castle"}
        res = await client.post("/api/properties", json=data, headers=auth(token))
        assert res.status_code == 422

    async def test_create_negative_price(self, client):
        token = await register_and_login(client)
        data = {**PROPERTY_DATA, "purchase_price": -100}
        res = await client.post("/api/properties", json=data, headers=auth(token))
        assert res.status_code == 422


class TestGetProperty:
    async def test_get_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/properties", json=PROPERTY_DATA, headers=auth(token))
        prop_id = create_res.json()["id"]
        res = await client.get(f"/api/properties/{prop_id}", headers=auth(token))
        assert res.status_code == 200

    async def test_get_not_found(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.get(f"/api/properties/{fake_id}", headers=auth(token))
        assert res.status_code == 404

    async def test_get_idor(self, client):
        token_a = await register_and_login(client, "re_a@example.com")
        token_b = await register_and_login(client, "re_b@example.com")
        create_res = await client.post("/api/properties", json=PROPERTY_DATA, headers=auth(token_a))
        prop_id = create_res.json()["id"]
        res = await client.get(f"/api/properties/{prop_id}", headers=auth(token_b))
        assert res.status_code == 404


class TestDeleteProperty:
    async def test_delete_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/properties", json=PROPERTY_DATA, headers=auth(token))
        prop_id = create_res.json()["id"]
        res = await client.delete(f"/api/properties/{prop_id}", headers=auth(token))
        assert res.status_code == 204

    async def test_delete_idor(self, client):
        token_a = await register_and_login(client, "re_del_a@example.com")
        token_b = await register_and_login(client, "re_del_b@example.com")
        create_res = await client.post("/api/properties", json=PROPERTY_DATA, headers=auth(token_a))
        prop_id = create_res.json()["id"]
        res = await client.delete(f"/api/properties/{prop_id}", headers=auth(token_b))
        assert res.status_code == 404


class TestMortgages:
    async def test_create_mortgage_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/properties", json=PROPERTY_DATA, headers=auth(token))
        prop_id = create_res.json()["id"]
        mortgage_data = {
            "name": "1. Hypothek",
            "type": "fixed",
            "amount": 600000.0,
            "interest_rate": 1.5,
        }
        res = await client.post(
            f"/api/properties/{prop_id}/mortgages",
            json=mortgage_data,
            headers=auth(token),
        )
        assert res.status_code == 201
        assert res.json()["name"] == "1. Hypothek"

    async def test_create_mortgage_invalid_property(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        mortgage_data = {"name": "Test", "type": "fixed", "amount": 100000, "interest_rate": 1.0}
        res = await client.post(
            f"/api/properties/{fake_id}/mortgages",
            json=mortgage_data,
            headers=auth(token),
        )
        assert res.status_code == 404


class TestExpenses:
    async def test_create_expense_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post("/api/properties", json=PROPERTY_DATA, headers=auth(token))
        prop_id = create_res.json()["id"]
        expense_data = {
            "date": "2025-03-01",
            "category": "maintenance",
            "amount": 1500.0,
        }
        res = await client.post(
            f"/api/properties/{prop_id}/expenses",
            json=expense_data,
            headers=auth(token),
        )
        assert res.status_code == 201
        assert "id" in res.json()
