"""Regressionstests fuer die manuell gepflegten Salden (Cash/Vorsorge).

Zwei Fallen, beide aus dem Beta-Feedback vom 30.7.2026:

1. Eine Einzahlung/Entnahme auf einem Cash-Konto nullte Saldo und Stueckzahl,
   weil der Recalc-Guard nur txn-freie Positionen schuetzte. Deckt hier den
   IMPORT-Pfad ab, wo Konten mit ``pricing_mode=auto`` entstehen (der
   Unit-Test in test_recalculate_service.py deckt den manual-Fall ab).
2. ``fix_foreign_total_chf`` rewritete total_chf fuer JEDE Fremdwaehrungs-Txn
   mit shares/price — bei einer Dividende ist total_chf aber das NETTO
   (dividends_net = SUM(total_chf)), die Abzuege waeren ins Plus gedreht.
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestCashSaldoSurvivesDeposit:
    async def test_deposit_keeps_saldo_on_auto_priced_cash_position(self, client, db):
        """Import-erstellte Cash-Konten liegen auf pricing_mode=auto."""
        from models.position import PricingMode, Position

        jwt = await _register_and_login(client, "saldo-auto@example.com")

        res = await client.post(
            "/api/portfolio/positions",
            json={
                "name": "ZKB - Sparkonto - CHF",
                "ticker": "CASH_ZKB_SPAR",
                "type": "cash",
                "currency": "CHF",
                "cost_basis_chf": 12000,
                "shares": 1,
                "current_price": 12000,
            },
            headers=_auth(jwt),
        )
        assert res.status_code in (200, 201), res.text
        position_id = res.json()["id"]

        # Import-Zustand nachstellen: pricing_mode auto statt manual.
        pos = (
            await db.execute(select(Position).where(Position.id == uuid.UUID(position_id)))
        ).scalar_one()
        pos.pricing_mode = PricingMode.auto
        await db.commit()

        res = await client.post(
            "/api/transactions",
            json={
                "position_id": position_id,
                "type": "deposit",
                "date": date.today().isoformat(),
                "shares": 0,
                "price_per_share": 0,
                "currency": "CHF",
                "fx_rate_to_chf": 1,
                "total_chf": 1000,
            },
            headers=_auth(jwt),
        )
        assert res.status_code == 201, res.text

        res = await client.get(f"/api/portfolio/positions/{position_id}", headers=_auth(jwt))
        assert res.status_code == 200, res.text
        body = res.json()
        assert float(body["cost_basis_chf"]) == 12000.0
        assert float(body["shares"]) == 1.0


class TestFixForeignTotalChfSkipsDividends:
    async def test_dividend_net_untouched_trade_still_fixed(self, client):
        jwt = await _register_and_login(client, "fixfx@example.com")

        res = await client.post(
            "/api/portfolio/positions",
            json={
                "name": "Apple Inc.",
                "ticker": "AAPL",
                "type": "stock",
                "currency": "USD",
                "cost_basis_chf": 0,
                "shares": 0,
            },
            headers=_auth(jwt),
        )
        assert res.status_code in (200, 201), res.text
        position_id = res.json()["id"]

        # Dividende wie aus dem UI: total_chf = Netto (20 x 0.25 x 0.82 - 0.62)
        res = await client.post(
            "/api/transactions",
            json={
                "position_id": position_id,
                "type": "dividend",
                "date": "2026-07-30",
                "shares": 20,
                "price_per_share": 0.25,
                "currency": "USD",
                "fx_rate_to_chf": 0.82,
                "fees_chf": 0,
                "taxes_chf": 0.62,
                "total_chf": 3.48,
            },
            headers=_auth(jwt),
        )
        assert res.status_code == 201, res.text
        dividend_id = res.json()["id"]

        # Kauf mit absichtlich falschem total_chf — den DARF der Fix anfassen.
        res = await client.post(
            "/api/transactions",
            json={
                "position_id": position_id,
                "type": "buy",
                "date": "2026-05-02",
                "shares": 10,
                "price_per_share": 100,
                "currency": "USD",
                "fx_rate_to_chf": 0.82,
                "fees_chf": 5,
                "taxes_chf": 0,
                "total_chf": 1000,
            },
            headers=_auth(jwt),
        )
        assert res.status_code == 201, res.text
        buy_id = res.json()["id"]

        res = await client.post("/api/portfolio/fix-total-chf", headers=_auth(jwt))
        assert res.status_code == 200, res.text

        res = await client.get("/api/transactions", headers=_auth(jwt))
        by_id = {t["id"]: t for t in res.json()["items"]}

        # Dividende: Netto unveraendert (sonst waere dividends_net_chf falsch)
        assert float(by_id[dividend_id]["total_chf"]) == 3.48
        # Kauf: auf Brutto + Gebuehren korrigiert (10 x 100 x 0.82 + 5)
        assert float(by_id[buy_id]["total_chf"]) == 825.0
