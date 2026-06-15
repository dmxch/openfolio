"""Tests fuer den /fill-Endpoint: Atomic Transaction + Status."""

from datetime import date

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str = "fil@example.com") -> str:
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


async def _create_order(client, jwt, **overrides):
    res = await client.post(
        "/api/orders/pending", json=_payload(**overrides), headers=auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _patch_yfinance(monkeypatch):
    """Vermeidet Live-yfinance-Anfragen aus _resolve_or_create_position."""
    import yfinance as yf

    class _FakeTicker:
        def __init__(self, *_a, **_kw):
            self.info = {"shortName": "Apple Inc.", "currency": "USD"}

    monkeypatch.setattr(yf, "Ticker", _FakeTicker)


class TestFill:
    async def test_fill_creates_transaction_and_links(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "fil-create@example.com")
        order = await _create_order(client, jwt)

        res = await client.post(
            f"/api/orders/pending/{order['id']}/fill",
            json={
                "price_per_share": 149.85,
                "fill_date": date.today().isoformat(),
                "fees_chf": 5.0,
                "fx_rate_to_chf": 0.88,
                "notes": "Tier-1 Fill",
            },
            headers=auth(jwt),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["transaction_id"]
        assert body["order"]["status"] == "filled"
        assert body["order"]["linked_transaction_id"] == body["transaction_id"]

        # Transaktion ist via /transactions sichtbar
        tx_res = await client.get("/api/transactions", headers=auth(jwt))
        assert tx_res.status_code == 200
        items = tx_res.json()["items"]
        assert any(t["ticker"] == "AAPL" and t["type"] == "buy" for t in items)

    async def test_fill_sell_materializes_realized_gains(self, client, monkeypatch):
        """Bug 2 (Fill-Pfad): ein gefuellter Sell muss sofort in der
        realized-gains-View erscheinen — ohne manuellen 'neu berechnen'-Klick.
        _do_fill triggert den Position-Recalc selbst."""
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "fil-realized@example.com")

        # Bestand aufbauen: Buy 10 @ 100 USD fx 0.9 -> Cost-Basis 900 CHF.
        buy = await client.post(
            "/api/transactions",
            json={
                "ticker": "AAPL", "type": "buy", "date": date.today().isoformat(),
                "shares": 10, "price_per_share": 100.0, "currency": "USD",
                "fx_rate_to_chf": 0.9, "total_chf": 900.0,
            },
            headers=auth(jwt),
        )
        assert buy.status_code == 201, buy.text

        # Pending Sell-Order und Fill @ 120 USD fx 0.9 -> Proceeds 1080.
        order = await _create_order(client, jwt, side="sell")
        fill = await client.post(
            f"/api/orders/pending/{order['id']}/fill",
            json={
                "price_per_share": 120.0,
                "fill_date": date.today().isoformat(),
                "fees_chf": 5.0,
                "fx_rate_to_chf": 0.9,
            },
            headers=auth(jwt),
        )
        assert fill.status_code == 200, fill.text

        # KEIN /performance/recalculate dazwischen.
        rg = await client.get("/api/portfolio/realized-gains", headers=auth(jwt))
        assert rg.status_code == 200, rg.text
        aapl = next((p for p in rg.json()["positions"] if p["ticker"] == "AAPL"), None)
        assert aapl is not None, "gefuellter Sell fehlt in realized-gains ohne Recalc"
        # _do_fill nutzt die total_chf-Konvention brutto+fees+taxes (10*120*0.9+5
        # = 1085) — bewusst NICHT angefasst (separate, nicht freigegebene
        # Konvention-Inkonsistenz). Dieser Test prueft Bug 2 (Materialisierung),
        # nicht Bug 1. realized = 1085 - cost(900) - fees(5) = 180.
        assert aapl["proceeds_chf"] == pytest.approx(1085.0)
        assert aapl["realized_pnl_chf"] == pytest.approx(180.0)

    async def test_fill_on_already_filled_returns_409(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "fil-409@example.com")
        order = await _create_order(client, jwt)
        body = {
            "price_per_share": 150.0,
            "fill_date": date.today().isoformat(),
            "fx_rate_to_chf": 0.88,
        }
        res1 = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=body, headers=auth(jwt),
        )
        assert res1.status_code == 200

        res2 = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=body, headers=auth(jwt),
        )
        assert res2.status_code == 409

    async def test_fill_on_cancelled_returns_409(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt = await register_and_login(client, "fil-cancel@example.com")
        order = await _create_order(client, jwt)

        res = await client.patch(
            f"/api/orders/pending/{order['id']}",
            json={"status": "cancelled"},
            headers=auth(jwt),
        )
        assert res.status_code == 200

        body = {
            "price_per_share": 150.0,
            "fill_date": date.today().isoformat(),
            "fx_rate_to_chf": 0.88,
        }
        res = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=body, headers=auth(jwt),
        )
        assert res.status_code == 409

    async def test_fill_user_b_cannot_fill_user_a_order(self, client, monkeypatch):
        await _patch_yfinance(monkeypatch)
        jwt_a = await register_and_login(client, "fil-a@example.com")
        jwt_b = await register_and_login(client, "fil-b@example.com")
        order = await _create_order(client, jwt_a)

        body = {
            "price_per_share": 150.0,
            "fill_date": date.today().isoformat(),
            "fx_rate_to_chf": 0.88,
        }
        res = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=body, headers=auth(jwt_b),
        )
        assert res.status_code == 404
