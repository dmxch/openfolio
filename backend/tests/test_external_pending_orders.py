"""Tests fuer die externen /api/v1/external/pending-orders-Endpoints."""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str = "ex-po@example.com") -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def jwt_auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def api_auth(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def create_token(client, jwt, name="t", write=False):
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": name, "write_access": write},
        headers=jwt_auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _patch_yfinance(monkeypatch):
    import yfinance as yf

    class _Fake:
        def __init__(self, *_a, **_kw):
            self.info = {"shortName": "Foo Co", "currency": "USD"}

    monkeypatch.setattr(yf, "Ticker", _Fake)


def _payload(**overrides):
    base = {
        "ticker": "AAPL",
        "side": "buy",
        "shares": 10,
        "limit_price": 150.0,
        "currency": "USD",
        "expiry_type": "gtc",
        "broker": "IBKR",
    }
    base.update(overrides)
    return base


class TestExternalRead:
    async def test_get_works_with_read_token_includes_notes(self, client):
        """v0.38+: read-Token sieht Notes UND die API-Marker (Provenienz).

        Marker-Felder sind nötig damit der Skill manuell-vs-via-API
        unterscheiden kann; ohne sie wird der Sync-Status falsch.
        """
        jwt = await register_and_login(client, "ex-r@example.com")
        await client.post(
            "/api/orders/pending",
            json=_payload(notes="manuell gesetzt"),
            headers=jwt_auth(jwt),
        )

        token = await create_token(client, jwt, name="r")
        res = await client.get(
            "/api/v1/external/pending-orders", headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0].get("notes") == "manuell gesetzt"
        # Marker-Schlüssel müssen vorhanden sein, auch wenn null (manuell gesetzt)
        assert "notes_last_api_write_at" in items[0]
        assert "notes_last_api_token_name" in items[0]

    async def test_get_write_token_includes_notes(self, client):
        jwt = await register_and_login(client, "ex-w@example.com")
        await client.post(
            "/api/orders/pending",
            json=_payload(notes="Pre-fill thoughts"),
            headers=jwt_auth(jwt),
        )

        token = await create_token(client, jwt, name="w", write=True)
        res = await client.get(
            "/api/v1/external/pending-orders", headers=api_auth(token["token"]),
        )
        items = res.json()["items"]
        assert items[0].get("notes") == "Pre-fill thoughts"


class TestExternalScopeGating:
    async def test_read_token_cannot_create(self, client):
        jwt = await register_and_login(client, "ex-rc@example.com")
        token = await create_token(client, jwt, name="r")
        res = await client.post(
            "/api/v1/external/pending-orders",
            json=_payload(),
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 403

    async def test_read_token_cannot_fill(self, client):
        jwt = await register_and_login(client, "ex-rf@example.com")
        order = (await client.post(
            "/api/orders/pending", json=_payload(), headers=jwt_auth(jwt),
        )).json()

        token = await create_token(client, jwt, name="r")
        res = await client.post(
            f"/api/v1/external/pending-orders/{order['id']}/fill",
            json={
                "price_per_share": 150.0,
                "fill_date": date.today().isoformat(),
                "fx_rate_to_chf": 0.88,
            },
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 403


class TestExternalWrite:
    async def test_write_token_create_and_audit_log(self, client, db):
        jwt = await register_and_login(client, "ex-cw@example.com")
        token = await create_token(client, jwt, name="w", write=True)
        res = await client.post(
            "/api/v1/external/pending-orders",
            json=_payload(),
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 201
        order = res.json()
        assert order["ticker"] == "AAPL"

        # ApiWriteLog Eintrag pruefen
        from models.api_write_log import ApiWriteLog
        rows = (await db.execute(select(ApiWriteLog))).scalars().all()
        assert any(r.action == "pending_order_create" for r in rows)

    async def test_write_token_update(self, client):
        jwt = await register_and_login(client, "ex-up@example.com")
        order = (await client.post(
            "/api/orders/pending", json=_payload(), headers=jwt_auth(jwt),
        )).json()

        token = await create_token(client, jwt, name="w", write=True)
        res = await client.patch(
            f"/api/v1/external/pending-orders/{order['id']}",
            json={"limit_price": 145.0, "notes": "API update"},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        assert float(res.json()["limit_price"]) == 145.0

    async def test_write_token_delete(self, client):
        jwt = await register_and_login(client, "ex-del@example.com")
        order = (await client.post(
            "/api/orders/pending", json=_payload(), headers=jwt_auth(jwt),
        )).json()

        token = await create_token(client, jwt, name="w", write=True)
        res = await client.delete(
            f"/api/v1/external/pending-orders/{order['id']}",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 204

    async def test_write_token_fill(self, client, monkeypatch, db):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ex-fil@example.com")
        order = (await client.post(
            "/api/orders/pending", json=_payload(), headers=jwt_auth(jwt),
        )).json()

        token = await create_token(client, jwt, name="w", write=True)
        res = await client.post(
            f"/api/v1/external/pending-orders/{order['id']}/fill",
            json={
                "price_per_share": 149.85,
                "fill_date": date.today().isoformat(),
                "fees_chf": 5.0,
                "fx_rate_to_chf": 0.88,
            },
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["transaction_id"]
        assert body["order"]["status"] == "filled"

        from models.api_write_log import ApiWriteLog
        rows = (await db.execute(select(ApiWriteLog))).scalars().all()
        assert any(r.action == "pending_order_fill" for r in rows)
