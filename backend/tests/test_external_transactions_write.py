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


class TestTotalChfDerivation:
    """Bug 1: POST /transactions ohne total_chf darf nicht mit 0 buchen.

    Serverseitige Brutto-Ableitung (shares*price*fx, OHNE Gebuehren) — konsistent
    mit dem /fill-Pfad und der realized-Formel (recalculate_service).
    """

    async def _total_chf_of(self, client, token, ticker):
        res = await client.get(
            f"/api/v1/external/transactions?ticker={ticker}",
            headers=api_auth(token),
        )
        assert res.status_code == 200, res.text
        return res.json()["items"]

    async def test_sell_without_total_chf_derives_brutto(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-derive-sell@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]

        # Buy mit explizitem total_chf (Cost-Basis), dann Sell OHNE total_chf.
        await _book(client, token, monkeypatch, type="buy", shares=10,
                    price_per_share=100.0, fx_rate_to_chf=0.9, total_chf=900.0)
        sell = await _book(client, token, monkeypatch, type="sell", shares=10,
                           price_per_share=120.0, fx_rate_to_chf=0.9, fees_chf=5.0,
                           total_chf=0)

        items = await self._total_chf_of(client, token, "RKLB")
        sold = next(i for i in items if i["id"] == sell["id"])
        # 10 * 120 * 0.9 = 1080.0 (brutto, OHNE die 5.0 Fees)
        assert sold["total_chf"] == pytest.approx(1080.0)

    async def test_buy_without_total_chf_derives_brutto(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-derive-buy@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]

        buy = await _book(client, token, monkeypatch, type="buy", shares=14,
                          price_per_share=99.39, fx_rate_to_chf=0.88, total_chf=0)
        items = await self._total_chf_of(client, token, "RKLB")
        booked = next(i for i in items if i["id"] == buy["id"])
        # 14 * 99.39 * 0.88 = 1224.49...
        assert booked["total_chf"] == pytest.approx(round(14 * 99.39 * 0.88, 2))

    async def test_explicit_total_chf_is_preserved(self, client, monkeypatch):
        """Ein explizit gesetzter (auch ungewoehnlicher) total_chf wird NIE
        ueberschrieben."""
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-derive-explicit@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]

        buy = await _book(client, token, monkeypatch, type="buy", shares=10,
                          price_per_share=100.0, fx_rate_to_chf=0.9, total_chf=777.0)
        items = await self._total_chf_of(client, token, "RKLB")
        booked = next(i for i in items if i["id"] == buy["id"])
        assert booked["total_chf"] == pytest.approx(777.0)

    async def test_non_trade_type_not_derived(self, client, monkeypatch):
        """Guard: Nicht-buy/sell (z.B. Dividende) mit total_chf=0 bleibt 0 —
        kein versehentliches Ableiten fuer Transfers/Splits/Dividenden."""
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-derive-div@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]

        # Position zuerst anlegen, dann Dividende mit total_chf=0.
        await _book(client, token, monkeypatch, type="buy", shares=10,
                    price_per_share=100.0, fx_rate_to_chf=0.9, total_chf=900.0)
        div = await _book(client, token, monkeypatch, type="dividend", shares=0,
                          price_per_share=0, fx_rate_to_chf=0.9, total_chf=0)
        items = await self._total_chf_of(client, token, "RKLB")
        booked = next(i for i in items if i["id"] == div["id"])
        assert booked["total_chf"] == pytest.approx(0.0)


class TestRealizedGainsAutoMaterialize:
    """Bug 2: realized-gains-View darf nach einem API-Write keinen manuellen
    'neu berechnen'-Klick brauchen — der Write-Pfad triggert den Recalc selbst."""

    async def _realized(self, client, token):
        res = await client.get(
            "/api/v1/external/performance/realized-gains",
            headers=api_auth(token),
        )
        assert res.status_code == 200, res.text
        return res.json()

    async def test_sell_appears_without_manual_recalc(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-realized-sell@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]

        await _book(client, token, monkeypatch, type="buy", shares=10,
                    price_per_share=100.0, fx_rate_to_chf=0.9, total_chf=900.0)
        await _book(client, token, monkeypatch, type="sell", shares=10,
                    price_per_share=120.0, fx_rate_to_chf=0.9, fees_chf=5.0,
                    total_chf=0)

        # KEIN /performance/recalculate dazwischen.
        data = await self._realized(client, token)
        rklb = next((p for p in data["positions"] if p["ticker"] == "RKLB"), None)
        assert rklb is not None, "geschlossene Position fehlt ohne manuellen Recalc"
        assert rklb["proceeds_chf"] == pytest.approx(1080.0)
        # realized = proceeds(1080) - cost(900) - fees(5) = 175.0
        assert rklb["realized_pnl_chf"] == pytest.approx(175.0)

    async def test_delete_buy_rematerializes_remaining_sell(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "ext-realized-del@example.com")
        token = (await create_token(client, jwt, name="w", write=True))["token"]

        await _book(client, token, monkeypatch, type="buy", shares=10,
                    price_per_share=100.0, fx_rate_to_chf=1.0, total_chf=1000.0)
        buy2 = await _book(client, token, monkeypatch, type="buy", shares=10,
                           price_per_share=200.0, fx_rate_to_chf=1.0, total_chf=2000.0)
        await _book(client, token, monkeypatch, type="sell", shares=10,
                    price_per_share=180.0, fx_rate_to_chf=1.0, total_chf=0)

        # avg-cost @ sale = (1000+2000)/20 = 150 -> realized = 1800 - 1500 = 300
        data = await self._realized(client, token)
        rklb = next(p for p in data["positions"] if p["ticker"] == "RKLB")
        assert rklb["realized_pnl_chf"] == pytest.approx(300.0)

        # Den teuren Buy loeschen -> avg-cost faellt auf 100 -> realized = 800
        res = await client.delete(
            f"/api/v1/external/transactions/{buy2['id']}",
            headers=api_auth(token),
        )
        assert res.status_code == 204

        # Wieder OHNE manuellen Recalc.
        data = await self._realized(client, token)
        rklb = next(p for p in data["positions"] if p["ticker"] == "RKLB")
        assert rklb["realized_pnl_chf"] == pytest.approx(800.0)


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
