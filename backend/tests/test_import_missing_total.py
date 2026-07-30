"""Import mit fehlender Betragsspalte — Menge und Kurs da, Betrag leer.

Feedback 30.7.2026: Bitcoin-Kaeufe kamen ohne Betrag herein. Solche Zeilen
landeten mit total_chf=0 in der Datenbank (Cost-Basis 0, Position mit -100%),
und weil es keine Sammelloeschung gibt, muss jede Zeile einzeln weg.

Ursache ist nicht ein einzelnes Broker-Format, sondern die Luecke im
Confirm-Pfad: nur Fremdwaehrungs-Zeilen wurden nachgerechnet. Jeder Broker,
der seine Betragsspalte umbenennt, faellt in dieselbe Falle.
"""

import uuid
from datetime import date

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


class TestConfirmDerivesMissingTotal:
    async def test_buy_without_total_gets_amount_from_shares_and_price(self, client):
        jwt = await _register_and_login(client, "import-total@example.com")

        res = await client.post(
            "/api/portfolio/positions",
            json={
                "name": "Bitcoin",
                "ticker": "BTC-USD",
                "type": "crypto",
                "currency": "CHF",
                "cost_basis_chf": 0,
                "shares": 0,
            },
            headers=_auth(jwt),
        )
        assert res.status_code in (200, 201), res.text
        position_id = res.json()["id"]

        # Zwei Kaeufe wie aus einem Export ohne Betragsspalte
        res = await client.post(
            "/api/import/confirm",
            json={
                "transactions": [
                    {
                        "position_id": position_id,
                        "type": "buy",
                        "date": "2026-06-01",
                        "shares": 0.01,
                        "price_per_share": 60000,
                        "currency": "CHF",
                        "fx_rate_to_chf": 1.0,
                        "fees_chf": 0,
                        "total_chf": 0,
                    },
                    {
                        "position_id": position_id,
                        "type": "buy",
                        "date": "2026-06-15",
                        "shares": 0.005,
                        "price_per_share": 62000,
                        "currency": "CHF",
                        "fx_rate_to_chf": 1.0,
                        "fees_chf": 0,
                        "total_chf": 0,
                    },
                ],
                "new_positions": [],
            },
            headers=_auth(jwt),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["created_transactions"] == 2
        assert body.get("derived_totals") == 2

        res = await client.get("/api/transactions", headers=_auth(jwt))
        totals = sorted(float(t["total_chf"]) for t in res.json()["items"])
        assert totals == [310.0, 600.0]  # 0.005 x 62000, 0.01 x 60000

    async def test_existing_total_is_never_overwritten(self, client):
        """Der Broker-Betrag hat Vorrang — abgeleitet wird nur, wenn er fehlt."""
        jwt = await _register_and_login(client, "import-total2@example.com")

        res = await client.post(
            "/api/portfolio/positions",
            json={
                "name": "Bitcoin",
                "ticker": "BTC-USD",
                "type": "crypto",
                "currency": "CHF",
                "cost_basis_chf": 0,
                "shares": 0,
            },
            headers=_auth(jwt),
        )
        position_id = res.json()["id"]

        # Betrag inkl. Gebuehren, wie ihn der Pocket-Parser liefert (cost + fee)
        res = await client.post(
            "/api/import/confirm",
            json={
                "transactions": [{
                    "position_id": position_id,
                    "type": "buy",
                    "date": "2026-06-01",
                    "shares": 0.01,
                    "price_per_share": 60000,
                    "currency": "CHF",
                    "fx_rate_to_chf": 1.0,
                    "fees_chf": 9.5,
                    "total_chf": 609.5,
                }],
                "new_positions": [],
            },
            headers=_auth(jwt),
        )
        assert res.status_code == 201, res.text
        assert res.json().get("derived_totals") == 0

        res = await client.get("/api/transactions", headers=_auth(jwt))
        assert float(res.json()["items"][0]["total_chf"]) == 609.5


class TestPreviewWarnsAboutMissingTotal:
    def test_warning_listed_for_rows_without_total(self):
        from services.import_service import (
            ImportPreview,
            ParsedTransaction,
            flag_rows_without_total,
        )

        preview = ImportPreview(
            source_type="csv",
            filename="btc.csv",
            total_rows=3,
            transactions=[
                ParsedTransaction(type="buy", date="2026-06-01", shares=0.01, price_per_share=60000, total_chf=0),
                ParsedTransaction(type="buy", date="2026-06-02", shares=0.02, price_per_share=61000, total_chf=0),
                ParsedTransaction(type="buy", date="2026-06-03", shares=0.03, price_per_share=62000, total_chf=1860),
            ],
        )

        flag_rows_without_total(preview)

        assert preview.warnings, "fehlende Betraege muessen in der Vorschau auffallen"
        assert preview.warnings[0].startswith("2 Zeile(n) ohne Betrag")

    def test_no_warning_when_all_rows_carry_an_amount(self):
        from services.import_service import (
            ImportPreview,
            ParsedTransaction,
            flag_rows_without_total,
        )

        preview = ImportPreview(
            source_type="csv",
            filename="btc.csv",
            total_rows=1,
            transactions=[
                ParsedTransaction(type="buy", date="2026-06-01", shares=0.01, price_per_share=60000, total_chf=600),
                # Einzahlung ohne Menge/Kurs ist legitim ohne abgeleiteten Betrag
                ParsedTransaction(type="deposit", date="2026-06-02", shares=0, price_per_share=0, total_chf=0),
            ],
        )

        flag_rows_without_total(preview)

        assert preview.warnings == []
