"""Tests for positions API endpoints — CRUD, IDOR, validation, batch type."""

import uuid
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from models.position import Position, AssetType

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

    async def test_update_stop_loss_via_put_sets_updated_at(self, client):
        """PUT mit stop_loss_price muss stop_loss_updated_at setzen — sonst
        bleibt die Review-Uhr (stop_loss_age-Alert) stehen, obwohl der Stop
        aktualisiert wurde (Paritaet mit PATCH /stop-loss)."""
        token = await register_and_login(client, "slput@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        assert create_res.json()["stop_loss_updated_at"] is None

        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"stop_loss_price": 120.5},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["stop_loss_price"] == 120.5
        assert res.json()["stop_loss_updated_at"] is not None

    async def test_update_stop_loss_method_via_put_sets_updated_at(self, client):
        """Auch Methoden-/Broker-Bestaetigungs-Aenderungen zaehlen als Review."""
        token = await register_and_login(client, "slput2@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]

        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"stop_loss_confirmed_at_broker": True},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["stop_loss_updated_at"] is not None

    async def test_update_without_stop_fields_keeps_updated_at(self, client):
        """Updates ohne Stop-Felder duerfen die Review-Uhr NICHT anfassen."""
        token = await register_and_login(client, "slput3@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]

        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"name": "Apple ohne Stop-Update", "shares": 12},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["stop_loss_updated_at"] is None

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


class TestCashTradableGuard:
    """Guard: ein handelbares Wertpapier darf nicht als type=cash/pension laufen.

    Hintergrund: type=cash faellt durch _NON_YAHOO_TYPES (wird nie bepreist) und
    der cash-Bewertungszweig rechnet cost_basis_chf * fx — bei echtem CHF-Einstand
    ein Phantom-Verlust (IB01.L "-19% an einem Tag").

    Der Guard selbst ist unveraendert gueltig; nur der empfohlene Ausweg hat sich
    geaendert. Es gibt jetzt ZWEI sanktionierte Wege, und sie meinen Verschiedenes:

      - Anleihen-/T-Bill-ETF (IB01.L)  -> type="bond". Eigene Assetklasse: liquide,
        aber weder Cash noch Aktie. count_as_cash bleibt dabei IMMER False.
      - Geldmarktfonds, den man bewusst als Cash fuehren will -> type="etf" +
        count_as_cash=true. Weiterhin erlaubt, aber nicht mehr die Empfehlung fuer
        einen Anleihen-ETF.

    Beide bewerten korrekt ueber shares*price*fx — der Phantom-Bug ist auf beiden
    Wegen geschlossen.
    """

    async def test_create_cash_with_market_ticker_rejected(self, client):
        token = await register_and_login(client, "guard1@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(ticker="IB01.L", name="T-Bill Park", type="cash"),
            headers=auth(token),
        )
        assert res.status_code == 422
        # Die Fehlermeldung muss auf den neuen empfohlenen Weg zeigen (Anleihen),
        # nicht mehr nur auf den ETF+count_as_cash-Umweg.
        assert "Anleihen" in res.json()["detail"]

    async def test_create_cash_with_yfinance_ticker_rejected(self, client):
        token = await register_and_login(client, "guard2@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CASH_PARK", name="Park", type="cash", yfinance_ticker="IB01.L"
            ),
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_create_cash_placeholder_ok_and_forced_manual(self, client):
        """Echtes Cash-Konto (Platzhalter-Ticker) wird angelegt und auf
        pricing_mode=manual gezogen (schliesst die auto-Default-Falle)."""
        token = await register_and_login(client, "guard3@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CASH_RAIFFEISEN", name="Lohnkonto", type="cash",
                currency="CHF", pricing_mode="auto",
            ),
            headers=auth(token),
        )
        assert res.status_code == 201
        assert res.json()["pricing_mode"] == "manual"

    async def test_create_cash_currency_code_label_ok(self, client):
        """Ein 3-Buchstaben-Waehrungscode als Cash-Label ist kein Markt-Symbol."""
        token = await register_and_login(client, "guard4@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(ticker="USD", name="USD Cash", type="cash"),
            headers=auth(token),
        )
        assert res.status_code == 201

    async def test_create_cash_hyphen_placeholder_ok(self, client):
        """Konvention CASH-CHF/CASH-USD (Bindestrich) ist ein Konto-Label, kein
        Symbol — darf NICHT geblockt werden."""
        token = await register_and_login(client, "guard4b@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CASH-CHF", name="CHF Konto", type="cash", currency="CHF"
            ),
            headers=auth(token),
        )
        assert res.status_code == 201

    async def test_create_bond_etf_ok(self, client):
        """Der sanktionierte Weg fuer einen Anleihen-/T-Bill-ETF: type="bond".

        Kein Cash ("es ist eigentlich kein Cash"), keine Aktie — eigene Klasse.
        """
        token = await register_and_login(client, "guard5@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="IB01.L", name="iShares $ Treasury Bond 0-1yr", type="bond"
            ),
            headers=auth(token),
        )
        assert res.status_code == 201
        assert res.json()["type"] == "bond"
        assert res.json()["count_as_cash"] is False

    async def test_create_bond_with_count_as_cash_is_clamped(self, client):
        """count_as_cash ist ETF-exklusiv — eine Anleihe bekommt es NIE (E1).

        Der Request wird nicht abgelehnt, aber das Flag wird hart auf False
        geklemmt: eine Anleihe darf nicht in die Cash-Quote rutschen.
        """
        token = await register_and_login(client, "guard5b@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="IB01.L", name="T-Bill ETF", type="bond", count_as_cash=True
            ),
            headers=auth(token),
        )
        assert res.status_code == 201
        assert res.json()["type"] == "bond"
        assert res.json()["count_as_cash"] is False

    async def test_create_etf_count_as_cash_still_ok(self, client):
        """Weiterhin erlaubt: ein Geldmarktfonds, den der Nutzer bewusst als Cash
        fuehrt (etf + count_as_cash). Nur nicht mehr die Empfehlung fuer IB01."""
        token = await register_and_login(client, "guard5c@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CSBGC0.SW", name="CHF Geldmarktfonds", type="etf",
                count_as_cash=True,
            ),
            headers=auth(token),
        )
        assert res.status_code == 201
        assert res.json()["type"] == "etf"
        assert res.json()["count_as_cash"] is True

    async def test_update_etf_count_as_cash_to_bond_clears_flag(self, client):
        """Der Umstellungs-Pfad, den der Nutzer selbst per UI geht (keine
        Datenmigration): IB01 von etf+count_as_cash auf bond. Das Cash-Flag muss
        dabei fallen — sonst zaehlte die Anleihe weiter zur Cash-Quote."""
        token = await register_and_login(client, "guard5d@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="IB01.L", name="T-Bill ETF", type="etf", count_as_cash=True
            ),
            headers=auth(token),
        )
        assert create_res.json()["count_as_cash"] is True
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"type": "bond"},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["type"] == "bond"
        assert res.json()["count_as_cash"] is False

    async def test_update_type_to_cash_with_ticker_rejected(self, client):
        token = await register_and_login(client, "guard6@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(ticker="AAPL", type="stock"),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"type": "cash"},
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_update_add_ticker_to_cash_rejected(self, client):
        token = await register_and_login(client, "guard7@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CASH_X", name="Konto", type="cash", currency="CHF"
            ),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"yfinance_ticker": "IB01.L"},
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_update_unrelated_field_on_cash_ok(self, client):
        """Unbeteiligter Edit (notes) an einer Cash-Pos darf NICHT blockiert
        werden — Guard greift nur bei Typwechsel/Handels-Signal."""
        token = await register_and_login(client, "guard8@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CASH_Y", name="Konto", type="cash", currency="CHF"
            ),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"notes": "neue Notiz"},
            headers=auth(token),
        )
        assert res.status_code == 200

    async def test_update_cash_full_form_unchanged_ticker_ok(self, client):
        """Das EditModal sendet bei jedem Save das GANZE Formular inkl.
        unveraendertem ticker — ein reiner Praesenz-Check wuerde das blocken.
        Mit unveraendertem ticker muss der Save durchgehen."""
        token = await register_and_login(client, "guard9@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CASH_Z", name="Konto", type="cash", currency="CHF"
            ),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={  # voller Modal-Payload, ticker unveraendert
                "ticker": "CASH_Z", "name": "Konto neu", "type": "cash",
                "currency": "CHF", "shares": 1, "cost_basis_chf": 7777.0,
                "notes": "Saldo aktualisiert",
            },
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["cost_basis_chf"] == 7777.0

    async def test_update_change_ticker_to_market_symbol_rejected(self, client):
        """Den ticker einer Cash-Pos AUF ein Markt-Symbol aendern -> 422."""
        token = await register_and_login(client, "guard10@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(
                ticker="CASH_W", name="Konto", type="cash", currency="CHF"
            ),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"ticker": "IB01.L"},
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_legacy_cash_market_ticker_stays_editable(self, client, db):
        """Alt-Daten (Cash-Pos mit Markt-Ticker, vor dem Guard entstanden) muessen
        editierbar bleiben — sonst kann der Nutzer nicht mal den Saldo korrigieren.
        Wir erzeugen den Alt-Zustand per DB (umgeht den Create-Guard)."""
        token = await register_and_login(client, "guard11@example.com")
        create_res = await client.post(
            "/api/portfolio/positions",
            json=make_position_data(ticker="IB01.L", name="T-Bill", type="bond"),
            headers=auth(token),
        )
        pos_id = create_res.json()["id"]
        # Alt-Zustand simulieren: Typ direkt auf cash kippen (kein API-Guard).
        pos = await db.get(Position, uuid.UUID(pos_id))
        pos.type = AssetType.cash
        await db.commit()
        # Unbeteiligter Edit (Saldo) muss durchgehen, ticker bleibt unveraendert.
        res = await client.put(
            f"/api/portfolio/positions/{pos_id}",
            json={"cost_basis_chf": 12345.0, "notes": "Saldo fix"},
            headers=auth(token),
        )
        assert res.status_code == 200
        assert res.json()["cost_basis_chf"] == 12345.0


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
