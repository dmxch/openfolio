"""Sammelloeschung von Transaktionen.

Feedback 30.7.2026: Nach einem fehlgeschlagenen Import blieb nur, jede Zeile
einzeln zu loeschen — mit einer Ruecfrage pro Zeile.

Die Buchhaltung muss dabei genauso sauber bleiben wie beim Einzel-Delete:
Bestand und Cost-Basis der betroffenen Position werden neu gerechnet, fremde
Transaktionen bleiben unangetastet.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_position(client: AsyncClient, jwt: str, ticker: str = "BTC-USD") -> str:
    res = await client.post(
        "/api/portfolio/positions",
        json={
            "name": "Bitcoin",
            "ticker": ticker,
            "type": "crypto",
            "currency": "CHF",
            "cost_basis_chf": 0,
            "shares": 0,
        },
        headers=_auth(jwt),
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _buy(client: AsyncClient, jwt: str, position_id: str, day: str, shares: float, price: float) -> str:
    res = await client.post(
        "/api/transactions",
        json={
            "position_id": position_id,
            "type": "buy",
            "date": day,
            "shares": shares,
            "price_per_share": price,
            "currency": "CHF",
            "fx_rate_to_chf": 1,
            "fees_chf": 0,
            "total_chf": round(shares * price, 2),
        },
        headers=_auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


class TestBulkDelete:
    async def test_deletes_selection_and_recalculates_position(self, client):
        jwt = await _register_and_login(client, "bulk1@example.com")
        pos = await _make_position(client, jwt)
        a = await _buy(client, jwt, pos, "2026-06-01", 0.01, 60000)
        b = await _buy(client, jwt, pos, "2026-06-15", 0.005, 62000)
        keep = await _buy(client, jwt, pos, "2026-07-01", 0.002, 64000)

        res = await client.post(
            "/api/transactions/bulk-delete", json={"ids": [a, b]}, headers=_auth(jwt),
        )
        assert res.status_code == 200, res.text
        assert res.json() == {"deleted": 2, "not_found": 0}

        res = await client.get("/api/transactions", headers=_auth(jwt))
        remaining = [t["id"] for t in res.json()["items"]]
        assert remaining == [keep]

        # Position traegt nur noch den verbliebenen Kauf
        res = await client.get(f"/api/portfolio/positions/{pos}", headers=_auth(jwt))
        body = res.json()
        assert abs(float(body["shares"]) - 0.002) < 1e-9
        assert abs(float(body["cost_basis_chf"]) - 128.0) < 0.01

    async def test_foreign_transactions_are_not_touched(self, client):
        owner = await _register_and_login(client, "bulk-owner@example.com")
        other = await _register_and_login(client, "bulk-other@example.com")

        owner_pos = await _make_position(client, owner)
        owner_txn = await _buy(client, owner, owner_pos, "2026-06-01", 0.01, 60000)

        other_pos = await _make_position(client, other, ticker="ETH-USD")
        other_txn = await _buy(client, other, other_pos, "2026-06-01", 1, 3000)

        # Fremde ID mitschicken: sie darf weder geloescht noch als Fehler geworfen werden
        res = await client.post(
            "/api/transactions/bulk-delete",
            json={"ids": [owner_txn, other_txn]},
            headers=_auth(owner),
        )
        assert res.status_code == 200, res.text
        assert res.json() == {"deleted": 1, "not_found": 1}

        res = await client.get("/api/transactions", headers=_auth(other))
        assert [t["id"] for t in res.json()["items"]] == [other_txn]

    async def test_unknown_ids_only_yield_404(self, client):
        import uuid as _uuid

        jwt = await _register_and_login(client, "bulk-404@example.com")
        res = await client.post(
            "/api/transactions/bulk-delete",
            json={"ids": [str(_uuid.uuid4())]},
            headers=_auth(jwt),
        )
        assert res.status_code == 404, res.text

    async def test_selection_limit_is_enforced(self, client):
        import uuid as _uuid

        from constants.limits import MAX_BULK_DELETE_TRANSACTIONS

        jwt = await _register_and_login(client, "bulk-limit@example.com")
        too_many = [str(_uuid.uuid4()) for _ in range(MAX_BULK_DELETE_TRANSACTIONS + 1)]
        res = await client.post(
            "/api/transactions/bulk-delete", json={"ids": too_many}, headers=_auth(jwt),
        )
        assert res.status_code == 422, res.text

    async def test_duplicate_ids_are_collapsed(self, client):
        jwt = await _register_and_login(client, "bulk-dup@example.com")
        pos = await _make_position(client, jwt)
        a = await _buy(client, jwt, pos, "2026-06-01", 0.01, 60000)

        res = await client.post(
            "/api/transactions/bulk-delete", json={"ids": [a, a]}, headers=_auth(jwt),
        )
        assert res.status_code == 200, res.text
        assert res.json() == {"deleted": 1, "not_found": 0}
