"""Tests fuer den externen POST /api/v1/external/transactions-Endpoint.

Paritaet zum internen UI-Schreibpfad (api/transactions.py): direkte Buchung
einer Transaktion ueber ein write-Token, inkl. Position-Auto-Anlage und
ApiWriteLog-Provenienz.
"""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str) -> str:
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
            self.info = {"shortName": "Rocket Lab", "currency": "USD"}

    monkeypatch.setattr(yf, "Ticker", _Fake)


def _payload(**overrides):
    base = {
        "ticker": "RKLB",
        "type": "buy",
        "date": date.today().isoformat(),
        "shares": 14,
        "price_per_share": 99.39,
        "currency": "USD",
        "fx_rate_to_chf": 0.88,
        "total_chf": 1224.0,
    }
    base.update(overrides)
    return base


class TestScope:
    async def test_read_token_forbidden(self, client):
        jwt = await register_and_login(client, "ext-txn-r@example.com")
        token = await create_token(client, jwt, name="r")
        res = await client.post(
            "/api/v1/external/transactions",
            json=_payload(),
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 403

    async def test_no_token_unauthorized(self, client):
        res = await client.post("/api/v1/external/transactions", json=_payload())
        assert res.status_code in (401, 403)


class TestWrite:
    async def test_create_auto_creates_position_and_audit_log(self, client, db, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-txn-w@example.com")
        token = await create_token(client, jwt, name="w", write=True)

        res = await client.post(
            "/api/v1/external/transactions",
            json=_payload(),
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["ticker"] == "RKLB"
        assert body["created_position"] is True
        assert body["type"] == "buy"

        # ApiWriteLog-Provenienz — atomar mit der Buchung verknuepft
        from models.api_write_log import ApiWriteLog
        rows = (await db.execute(select(ApiWriteLog))).scalars().all()
        log = next((r for r in rows if r.action == "transaction_create"), None)
        assert log is not None
        assert log.ticker == "RKLB"
        assert str(log.target_id) == body["id"]

    async def test_create_shows_in_external_list(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-txn-l@example.com")
        token = await create_token(client, jwt, name="w", write=True)

        await client.post(
            "/api/v1/external/transactions",
            json=_payload(notes="via API gebucht"),
            headers=api_auth(token["token"]),
        )
        res = await client.get(
            "/api/v1/external/transactions?ticker=RKLB",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["ticker"] == "RKLB"
        assert items[0]["notes"] == "via API gebucht"

    async def test_unknown_type_rejected(self, client):
        jwt = await register_and_login(client, "ext-txn-t@example.com")
        token = await create_token(client, jwt, name="w", write=True)
        res = await client.post(
            "/api/v1/external/transactions",
            json=_payload(type="frobnicate"),
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 422

    async def test_unknown_field_rejected(self, client):
        """Vertippter Feldname (fee_chf statt fees_chf) muss 422 geben,
        nicht still mit Default-0 buchen (extra='forbid')."""
        jwt = await register_and_login(client, "ext-txn-x@example.com")
        token = await create_token(client, jwt, name="w", write=True)
        res = await client.post(
            "/api/v1/external/transactions",
            json=_payload(fee_chf=4.0),
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 422

    async def test_missing_position_and_ticker_rejected(self, client):
        jwt = await register_and_login(client, "ext-txn-m@example.com")
        token = await create_token(client, jwt, name="w", write=True)
        payload = _payload()
        payload.pop("ticker")
        res = await client.post(
            "/api/v1/external/transactions",
            json=payload,
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 422


async def _book(client, token, monkeypatch, **overrides):
    await _patch_yfinance(monkeypatch)
    res = await client.post(
        "/api/v1/external/transactions",
        json=_payload(**overrides),
        headers=api_auth(token),
    )
    assert res.status_code == 201, res.text
    return res.json()


class TestUpdate:
    async def test_read_token_forbidden(self, client, monkeypatch):
        jwt = await register_and_login(client, "ext-upd-r@example.com")
        wtok = await create_token(client, jwt, name="w", write=True)
        booked = await _book(client, wtok["token"], monkeypatch)
        rtok = await create_token(client, jwt, name="r")
        res = await client.put(
            f"/api/v1/external/transactions/{booked['id']}",
            json={"price_per_share": 130.0},
            headers=api_auth(rtok["token"]),
        )
        assert res.status_code == 403

    async def test_update_changes_field_and_audit_log(self, client, db, monkeypatch):
        jwt = await register_and_login(client, "ext-upd-w@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]
        booked = await _book(client, token, monkeypatch)

        res = await client.put(
            f"/api/v1/external/transactions/{booked['id']}",
            json={"price_per_share": 130.0, "notes": "korrigiert"},
            headers=api_auth(token),
        )
        assert res.status_code == 200, res.text
        assert res.json()["price_per_share"] == 130.0
        assert res.json()["notes"] == "korrigiert"

        from models.api_write_log import ApiWriteLog
        rows = (await db.execute(select(ApiWriteLog))).scalars().all()
        log = next((r for r in rows if r.action == "transaction_update"), None)
        assert log is not None
        assert str(log.target_id) == booked["id"]

    async def test_update_unknown_id_404(self, client):
        jwt = await register_and_login(client, "ext-upd-x@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]
        import uuid as _uuid
        res = await client.put(
            f"/api/v1/external/transactions/{_uuid.uuid4()}",
            json={"price_per_share": 1.0},
            headers=api_auth(token),
        )
        assert res.status_code == 404

    async def test_update_unknown_field_rejected(self, client, monkeypatch):
        jwt = await register_and_login(client, "ext-upd-f@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]
        booked = await _book(client, token, monkeypatch)
        res = await client.put(
            f"/api/v1/external/transactions/{booked['id']}",
            json={"ticker": "AAPL"},  # Typ/Ticker nicht aenderbar -> extra=forbid
            headers=api_auth(token),
        )
        assert res.status_code == 422


class TestDelete:
    async def test_read_token_forbidden(self, client, monkeypatch):
        jwt = await register_and_login(client, "ext-del-r@example.com")
        wtok = await create_token(client, jwt, name="w", write=True)
        booked = await _book(client, wtok["token"], monkeypatch)
        rtok = await create_token(client, jwt, name="r")
        res = await client.delete(
            f"/api/v1/external/transactions/{booked['id']}",
            headers=api_auth(rtok["token"]),
        )
        assert res.status_code == 403

    async def test_delete_removes_and_audit_log(self, client, db, monkeypatch):
        jwt = await register_and_login(client, "ext-del-w@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]
        booked = await _book(client, token, monkeypatch)

        res = await client.delete(
            f"/api/v1/external/transactions/{booked['id']}",
            headers=api_auth(token),
        )
        assert res.status_code == 204

        # weg aus der Liste
        lst = await client.get(
            "/api/v1/external/transactions?ticker=RKLB", headers=api_auth(token),
        )
        assert lst.json()["total"] == 0

        from models.api_write_log import ApiWriteLog
        rows = (await db.execute(select(ApiWriteLog))).scalars().all()
        log = next((r for r in rows if r.action == "transaction_delete"), None)
        assert log is not None
        assert str(log.target_id) == booked["id"]
        assert log.ticker == "RKLB"

    async def test_delete_unknown_id_404(self, client):
        jwt = await register_and_login(client, "ext-del-x@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]
        import uuid as _uuid
        res = await client.delete(
            f"/api/v1/external/transactions/{_uuid.uuid4()}",
            headers=api_auth(token),
        )
        assert res.status_code == 404


class TestAtomicity:
    async def test_commit_failure_leaves_no_orphan(self, client, db, monkeypatch):
        """Regression: schlaegt der EINE Commit fehl (in Prod z.B. der
        action-CHECK-Constraint beim Audit-Log), darf KEINE Transaktion
        zurueckbleiben. Sonst sieht der Caller einen Fehler, retried, und
        erzeugt ein Duplikat — genau der Prod-Bug.

        Wir simulieren den Constraint-Fehler durch einen scheiternden Commit;
        unter SQLite (create_all) existiert der echte CHECK nicht. Gegen den
        alten Two-Commit-Code (Buchung committet VOR dem Log) wuerde dieser
        Test eine Orphan-Zeile finden.
        """
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-txn-atom@example.com")
        token = await create_token(client, jwt, name="w", write=True)

        # Erst NACH dem Setup patchen — register/login/create_token committen selbst.
        async def boom():
            raise RuntimeError("simulierter CHECK-Constraint-Fehler beim Commit")
        monkeypatch.setattr(db, "commit", boom)

        # In Prod wraps der Exception-Handler das zu 500; unter ASGITransport
        # propagiert die Exception direkt in den Test. Beides heisst: Fehler.
        with pytest.raises(RuntimeError):
            await client.post(
                "/api/v1/external/transactions",
                json=_payload(),
                headers=api_auth(token["token"]),
            )

        monkeypatch.undo()
        await db.rollback()

        from models.transaction import Transaction
        count = await db.scalar(select(func.count()).select_from(Transaction))
        assert count == 0  # keine Orphan-Buchung → Retry bleibt duplikatfrei
