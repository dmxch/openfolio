"""Tests for transactions API endpoints — CRUD, IDOR, validation, auto-create position."""

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("mock_snapshot_regen")]


@pytest.fixture(autouse=True)
def mock_snapshot_regen():
    with patch("api.transactions.trigger_snapshot_regen"):
        yield

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="txn@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


async def create_position(client: AsyncClient, token: str, ticker="AAPL", name="Apple Inc."):
    res = await client.post(
        "/api/portfolio/positions",
        json={
            "ticker": ticker,
            "name": name,
            "type": "stock",
            "currency": "USD",
            "shares": 0,
            "cost_basis_chf": 0,
        },
        headers=auth(token),
    )
    return res.json()["id"]


def make_txn_data(position_id, **overrides):
    base = {
        "position_id": position_id,
        "type": "buy",
        "date": "2025-01-15",
        "shares": 10,
        "price_per_share": 150.0,
        "currency": "USD",
        "fx_rate_to_chf": 0.88,
        "fees_chf": 5.0,
        "taxes_chf": 0,
        "total_chf": 1325.0,
    }
    base.update(overrides)
    return base


class TestCreateTransaction:
    async def test_create_transaction_success(self, client):
        token = await register_and_login(client)
        pos_id = await create_position(client, token)
        res = await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["type"] == "buy"
        assert data["shares"] == 10.0
        assert data["position_id"] == pos_id

    async def test_create_transaction_unauthorized(self, client):
        res = await client.post(
            "/api/transactions",
            json=make_txn_data(str(uuid.uuid4())),
        )
        assert res.status_code in (401, 403)

    async def test_create_transaction_position_not_found(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.post(
            "/api/transactions",
            json=make_txn_data(fake_id),
            headers=auth(token),
        )
        assert res.status_code == 404

    async def test_create_transaction_idor(self, client):
        """User B cannot create transaction on User A's position."""
        token_a = await register_and_login(client, "txnA@example.com")
        token_b = await register_and_login(client, "txnB@example.com")
        pos_id = await create_position(client, token_a)
        res = await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token_b),
        )
        assert res.status_code == 404

    async def test_create_transaction_missing_position_and_ticker(self, client):
        token = await register_and_login(client, "txnval@example.com")
        res = await client.post(
            "/api/transactions",
            json={
                "type": "buy",
                "date": "2025-01-15",
                "shares": 10,
                "price_per_share": 150.0,
                "total_chf": 1500.0,
            },
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_create_transaction_negative_shares(self, client):
        token = await register_and_login(client, "txnneg@example.com")
        pos_id = await create_position(client, token, ticker="MSFT", name="Microsoft")
        res = await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id, shares=-5),
            headers=auth(token),
        )
        assert res.status_code == 422


class TestListTransactions:
    async def test_list_transactions_empty(self, client):
        token = await register_and_login(client, "txnlist@example.com")
        res = await client.get("/api/transactions", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_transactions_after_create(self, client):
        token = await register_and_login(client, "txnlist2@example.com")
        pos_id = await create_position(client, token)
        await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token),
        )
        res = await client.get("/api/transactions", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    async def test_list_transactions_idor(self, client):
        """User B cannot see User A's transactions."""
        token_a = await register_and_login(client, "txnidorA@example.com")
        token_b = await register_and_login(client, "txnidorB@example.com")
        pos_id = await create_position(client, token_a)
        await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token_a),
        )
        res = await client.get("/api/transactions", headers=auth(token_b))
        assert res.status_code == 200
        assert res.json()["total"] == 0


class TestUpdateTransaction:
    async def test_update_transaction_success(self, client):
        token = await register_and_login(client, "txnupd@example.com")
        pos_id = await create_position(client, token)
        create_res = await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token),
        )
        txn_id = create_res.json()["id"]
        res = await client.put(
            f"/api/transactions/{txn_id}",
            json={"shares": 20, "total_chf": 2650.0},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["shares"] == 20.0

    async def test_update_transaction_not_found(self, client):
        token = await register_and_login(client, "txnupd404@example.com")
        fake_id = str(uuid.uuid4())
        res = await client.put(
            f"/api/transactions/{fake_id}",
            json={"shares": 20},
            headers=auth(token),
        )
        assert res.status_code == 404

    async def test_update_transaction_idor(self, client):
        """User B cannot update User A's transaction."""
        token_a = await register_and_login(client, "txnupdA@example.com")
        token_b = await register_and_login(client, "txnupdB@example.com")
        pos_id = await create_position(client, token_a)
        create_res = await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token_a),
        )
        txn_id = create_res.json()["id"]
        res = await client.put(
            f"/api/transactions/{txn_id}",
            json={"shares": 999},
            headers=auth(token_b),
        )
        assert res.status_code == 404


class TestDeleteTransaction:
    async def test_delete_transaction_success(self, client):
        token = await register_and_login(client, "txndel@example.com")
        pos_id = await create_position(client, token)
        create_res = await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token),
        )
        txn_id = create_res.json()["id"]
        res = await client.delete(f"/api/transactions/{txn_id}", headers=auth(token))
        assert res.status_code == 204

        # Verify deleted
        list_res = await client.get("/api/transactions", headers=auth(token))
        assert list_res.json()["total"] == 0

    async def test_delete_transaction_idor(self, client):
        """User B cannot delete User A's transaction."""
        token_a = await register_and_login(client, "txndelA@example.com")
        token_b = await register_and_login(client, "txndelB@example.com")
        pos_id = await create_position(client, token_a)
        create_res = await client.post(
            "/api/transactions",
            json=make_txn_data(pos_id),
            headers=auth(token_a),
        )
        txn_id = create_res.json()["id"]
        res = await client.delete(f"/api/transactions/{txn_id}", headers=auth(token_b))
        assert res.status_code == 404
