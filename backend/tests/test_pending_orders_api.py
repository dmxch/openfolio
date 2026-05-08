"""Integration-Tests fuer die internen Pending-Orders-Endpoints."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from constants.limits import MAX_PENDING_ORDERS_PER_USER

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str = "po@example.com") -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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


class TestCRUD:
    async def test_create_and_list(self, client):
        jwt = await register_and_login(client, "po-crud@example.com")
        res = await client.post("/api/orders/pending", json=_payload(), headers=auth(jwt))
        assert res.status_code == 201, res.text
        order = res.json()
        assert order["ticker"] == "AAPL"
        assert order["status"] == "open"
        assert order["effective_status"] == "open"

        list_res = await client.get("/api/orders/pending", headers=auth(jwt))
        assert list_res.status_code == 200
        body = list_res.json()
        assert len(body["items"]) == 1
        assert body["counts"]["open"] == 1

    async def test_ticker_uppercased(self, client):
        jwt = await register_and_login(client, "po-upper@example.com")
        res = await client.post(
            "/api/orders/pending",
            json=_payload(ticker="msft"),
            headers=auth(jwt),
        )
        assert res.status_code == 201
        assert res.json()["ticker"] == "MSFT"

    async def test_update_limit_price(self, client):
        jwt = await register_and_login(client, "po-update@example.com")
        created = (await client.post(
            "/api/orders/pending", json=_payload(), headers=auth(jwt)
        )).json()

        res = await client.patch(
            f"/api/orders/pending/{created['id']}",
            json={"limit_price": 145.5},
            headers=auth(jwt),
        )
        assert res.status_code == 200
        assert float(res.json()["limit_price"]) == 145.5

    async def test_delete(self, client):
        jwt = await register_and_login(client, "po-del@example.com")
        created = (await client.post(
            "/api/orders/pending", json=_payload(), headers=auth(jwt)
        )).json()

        res = await client.delete(
            f"/api/orders/pending/{created['id']}", headers=auth(jwt),
        )
        assert res.status_code == 204

        list_res = await client.get("/api/orders/pending?status=all", headers=auth(jwt))
        assert len(list_res.json()["items"]) == 0


class TestCrossUserIsolation:
    async def test_user_b_cannot_see_user_a_orders(self, client):
        jwt_a = await register_and_login(client, "po-a@example.com")
        jwt_b = await register_and_login(client, "po-b@example.com")

        await client.post("/api/orders/pending", json=_payload(), headers=auth(jwt_a))

        res = await client.get("/api/orders/pending?status=all", headers=auth(jwt_b))
        assert res.status_code == 200
        assert len(res.json()["items"]) == 0
        assert res.json()["counts"]["open"] == 0

    async def test_user_b_cannot_patch_user_a_order(self, client):
        jwt_a = await register_and_login(client, "po-pa@example.com")
        jwt_b = await register_and_login(client, "po-pb@example.com")
        order_a = (await client.post(
            "/api/orders/pending", json=_payload(), headers=auth(jwt_a)
        )).json()

        res = await client.patch(
            f"/api/orders/pending/{order_a['id']}",
            json={"limit_price": 1.0},
            headers=auth(jwt_b),
        )
        assert res.status_code == 404

    async def test_user_b_cannot_delete_user_a_order(self, client):
        jwt_a = await register_and_login(client, "po-da@example.com")
        jwt_b = await register_and_login(client, "po-db@example.com")
        order_a = (await client.post(
            "/api/orders/pending", json=_payload(), headers=auth(jwt_a)
        )).json()

        res = await client.delete(
            f"/api/orders/pending/{order_a['id']}", headers=auth(jwt_b),
        )
        assert res.status_code == 404


class TestGTDValidation:
    async def test_gtd_without_date_rejected(self, client):
        jwt = await register_and_login(client, "po-gtd1@example.com")
        res = await client.post(
            "/api/orders/pending",
            json=_payload(expiry_type="gtd"),
            headers=auth(jwt),
        )
        assert res.status_code == 422

    async def test_gtc_with_date_rejected(self, client):
        jwt = await register_and_login(client, "po-gtd2@example.com")
        res = await client.post(
            "/api/orders/pending",
            json=_payload(expiry_type="gtc", expiry_date="2027-01-01"),
            headers=auth(jwt),
        )
        assert res.status_code == 422

    async def test_gtd_with_date_accepted(self, client):
        jwt = await register_and_login(client, "po-gtd3@example.com")
        future = (date.today() + timedelta(days=30)).isoformat()
        res = await client.post(
            "/api/orders/pending",
            json=_payload(expiry_type="gtd", expiry_date=future),
            headers=auth(jwt),
        )
        assert res.status_code == 201

    async def test_patch_to_gtd_requires_date_in_endresult(self, client):
        jwt = await register_and_login(client, "po-gtd4@example.com")
        order = (await client.post(
            "/api/orders/pending", json=_payload(), headers=auth(jwt),
        )).json()

        # PATCH zu gtd ohne Datum -> 422
        res = await client.patch(
            f"/api/orders/pending/{order['id']}",
            json={"expiry_type": "gtd"},
            headers=auth(jwt),
        )
        assert res.status_code == 422


class TestLimit:
    async def test_limit_blocks_create(self, client, db, monkeypatch):
        """Patch das Limit auf 2 — schneller als 100 Order erzeugen."""
        monkeypatch.setattr(
            "api.orders.MAX_PENDING_ORDERS_PER_USER", 2,
        )
        jwt = await register_and_login(client, "po-lim@example.com")
        for i in range(2):
            res = await client.post(
                "/api/orders/pending",
                json=_payload(ticker=f"T{i}"),
                headers=auth(jwt),
            )
            assert res.status_code == 201

        res = await client.post(
            "/api/orders/pending", json=_payload(ticker="ZZZ"), headers=auth(jwt),
        )
        assert res.status_code == 400


class TestEffectiveStatus:
    async def test_gtd_past_is_effectively_expired(self, client, db):
        """Direktes DB-Setup: GTD-Order mit expiry_date=gestern.

        Nicht ueber den Endpoint, weil das Schema future-Daten erzwingt
        (expiry_date als Pflichtfeld bei GTD ohne explizite Past-Verbote —
        aber die Realitaet wird normalerweise so produziert, dass eine GTC-
        Order gestern angelegt und vergessen wurde).
        """
        from datetime import date as _date, timedelta as _td
        from models.pending_order import PendingOrder
        from sqlalchemy import select
        from models.user import User

        jwt = await register_and_login(client, "po-eff@example.com")

        # Direkt in die DB injizieren mit Gestern-Datum
        user = (await db.execute(
            select(User).where(User.email == "po-eff@example.com")
        )).scalars().first()
        order = PendingOrder(
            user_id=user.id,
            ticker="LMT",
            side="buy",
            shares=1,
            limit_price=100,
            currency="USD",
            expiry_type="gtd",
            expiry_date=_date.today() - _td(days=1),
            status="open",
        )
        db.add(order)
        await db.commit()

        # status=open Filter sollte sie ausschliessen
        res = await client.get("/api/orders/pending?status=open", headers=auth(jwt))
        body = res.json()
        assert body["counts"]["open"] == 0
        assert body["counts"]["expired"] == 1
        assert all(i["effective_status"] != "expired" for i in body["items"])

        # status=closed sollte sie zeigen
        res = await client.get("/api/orders/pending?status=closed", headers=auth(jwt))
        body = res.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["effective_status"] == "expired"
        assert body["items"][0]["status"] == "open"  # DB-Wert unveraendert

        # status=all sollte sie zeigen
        res = await client.get("/api/orders/pending?status=all", headers=auth(jwt))
        assert len(res.json()["items"]) == 1


class TestFilledWriteProtection:
    """PATCH auf gefillte Orders darf nur notes mutieren."""

    async def _create_filled(self, client, db, jwt: str):
        import uuid as _uuid
        from sqlalchemy import select
        from models.pending_order import PendingOrder

        order = (await client.post(
            "/api/orders/pending", json=_payload(), headers=auth(jwt)
        )).json()
        # Manuell auf filled flippen via DB (umgeht /fill um keine Position zu brauchen)
        order_uuid = _uuid.UUID(order["id"])
        po_row = (await db.execute(
            select(PendingOrder).where(PendingOrder.id == order_uuid)
        )).scalars().first()
        po_row.status = "filled"
        await db.commit()
        return order

    async def test_patch_filled_status_via_schema_blocked(self, client, db):
        jwt = await register_and_login(client, "po-fil@example.com")
        order = await self._create_filled(client, db, jwt)
        res = await client.patch(
            f"/api/orders/pending/{order['id']}",
            json={"status": "filled"},
            headers=auth(jwt),
        )
        # Schema laesst "filled" als status-Wert nicht zu (Literal)
        assert res.status_code == 422

    async def test_patch_filled_limit_blocked(self, client, db):
        jwt = await register_and_login(client, "po-fil@example.com")
        order = await self._create_filled(client, db, jwt)
        res = await client.patch(
            f"/api/orders/pending/{order['id']}",
            json={"limit_price": 1.0},
            headers=auth(jwt),
        )
        assert res.status_code == 400
        assert "historisch" in res.json().get("detail", "")

    async def test_patch_filled_notes_allowed(self, client, db):
        jwt = await register_and_login(client, "po-fil@example.com")
        order = await self._create_filled(client, db, jwt)
        res = await client.patch(
            f"/api/orders/pending/{order['id']}",
            json={"notes": "Post-fill comment"},
            headers=auth(jwt),
        )
        assert res.status_code == 200
        assert res.json()["notes"] == "Post-fill comment"

    async def test_delete_filled_allowed(self, client, db):
        jwt = await register_and_login(client, "po-fil@example.com")
        order = await self._create_filled(client, db, jwt)
        res = await client.delete(
            f"/api/orders/pending/{order['id']}", headers=auth(jwt),
        )
        assert res.status_code == 204
