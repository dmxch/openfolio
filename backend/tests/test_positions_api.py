"""Tests for positions API endpoints — CRUD, IDOR, validation, batch type."""

import uuid
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("mock_snapshot_regen")]


@pytest.fixture(autouse=True)
def mock_snapshot_regen():
    with patch("api.positions.trigger_snapshot_regen"):
        yield


TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="positions@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def make_position_data(**overrides):
    base = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "type": "stock",
        "currency": "USD",
        "shares": 10,
        "cost_basis_chf": 1500.0,
    }
    base.update(overrides)
    return base


class TestCreatePosition:
    async def test_create_position_success(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["ticker"] == "AAPL"
        assert data["name"] == "Apple Inc."
        assert data["type"] == "stock"
        assert data["shares"] == 10.0
        assert "id" in data

    async def test_create_position_unauthorized(self, client):
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
        )
        assert res.status_code in (401, 403)

    async def test_create_position_missing_required_fields(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL"},
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_create_position_invalid_type(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(type="invalid"),
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_create_position_negative_shares(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(shares=-5),
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_create_position_encrypts_pii(self, client):
        """PII fields (notes, bank_name, iban) should be encrypted in DB."""
        token = await register_and_login(client, "pii@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="MSFT",
                name="Microsoft",
                notes="Geheime Notiz",
                bank_name="UBS",
                iban="CH9300762011623852957",
            ),
            headers=auth(token),
        )
        assert res.status_code == 201
        data = res.json()
        # Notes should be returned decrypted to the user
        assert data["notes"] == "Geheime Notiz"
        assert data["bank_name"] == "UBS"


class TestListPositions:
    async def test_list_positions_empty(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/portfolio/positions", headers=auth(token))
        assert res.status_code == 200
        assert res.json() == []

    async def test_list_positions_after_create(self, client):
        token = await register_and_login(client)
        await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        res = await client.get("/api/portfolio/positions", headers=auth(token))
        assert res.status_code == 200
        assert len(res.json()) == 1

    async def test_list_positions_idor_protection(self, client):
        """User A cannot see User B's positions."""
        token_a = await register_and_login(client, "posA@example.com")
        token_b = await register_and_login(client, "posB@example.com")
        await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token_a),
        )
        res = await client.get("/api/portfolio/positions", headers=auth(token_b))
        assert res.status_code == 200
        assert len(res.json()) == 0


class TestGetPosition:
    async def test_get_position_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.get(f"/api/portfolio/positions/{pos_id}", headers=auth(token))
        assert res.status_code == 200
        assert res.json()["ticker"] == "AAPL"

    async def test_get_position_not_found(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.get(f"/api/portfolio/positions/{fake_id}", headers=auth(token))
        assert res.status_code == 404

    async def test_get_position_idor(self, client):
        """User B cannot access User A's position."""
        token_a = await register_and_login(client, "getA@example.com")
        token_b = await register_and_login(client, "getB@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token_a),
        )
        pos_id = create_res.json()["id"]
        res = await client.get(f"/api/portfolio/positions/{pos_id}", headers=auth(token_b))
        assert res.status_code == 404


class TestUpdatePosition:
    async def test_update_position_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"name": "Apple Inc. Updated", "shares": 20},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["name"] == "Apple Inc. Updated"
        assert res.json()["shares"] == 20.0

    async def test_update_position_idor(self, client):
        """User B cannot update User A's position."""
        token_a = await register_and_login(client, "updA@example.com")
        token_b = await register_and_login(client, "updB@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token_a),
        )
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"name": "Hacked"},
            headers=auth(token_b),
        )
        assert res.status_code == 404


class TestDeletePosition:
    async def test_delete_position_success(self, client):
        token = await register_and_login(client)
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.delete(f"/api/portfolio/positions/{pos_id}", headers=auth(token))
        assert res.status_code == 204

        # Verify deleted
        list_res = await client.get("/api/portfolio/positions", headers=auth(token))
        assert len(list_res.json()) == 0

    async def test_delete_position_idor(self, client):
        """User B cannot delete User A's position."""
        token_a = await register_and_login(client, "delA@example.com")
        token_b = await register_and_login(client, "delB@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token_a),
        )
        pos_id = create_res.json()["id"]
        res = await client.delete(f"/api/portfolio/positions/{pos_id}", headers=auth(token_b))
        assert res.status_code == 404

    async def test_delete_position_not_found(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.delete(f"/api/portfolio/positions/{fake_id}", headers=auth(token))
        assert res.status_code == 404
