"""Regressionstests zum Vollreview vom 13.11.2026, Fixer «txorders».

Befunde: K006 (Buchungsdatum), K023 (Ticker an Yahoo), K036 (mehrdeutiger Ticker),
K037 (doppelte Dividenden-Bestätigung), K041 (is_active nach Recalc), K108 (Regen
nach Datumsänderung), K119 (Summen der Transaktionsliste), K149 (Feldlängen),
K162 (Order-Notizen verschlüsselt).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from models.pending_dividend import (
    STATUS_CONFIRMED,
    STATUS_PENDING,
    PendingDividend,
)
from models.pending_order import PendingOrder
from models.position import Position
from models.transaction import Transaction, TransactionType
from models.user import User
from services.encryption_helpers import decrypt_field

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
TODAY = date.today().isoformat()


@pytest.fixture(autouse=True)
def no_network():
    """Kein Snapshot-Regen und kein Yahoo-Abruf. Liefert die Mocks für Asserts."""
    info = AsyncMock(return_value={"shortName": "Test AG", "currency": "USD"})
    with (
        patch("api.transactions.trigger_snapshot_regen") as txn_regen,
        patch("api.orders.trigger_snapshot_regen"),
        patch("api.dividends.trigger_snapshot_regen"),
        patch("api.transactions.get_ticker_info_cached", info),
        patch("services.ticker_info_service.get_ticker_info_cached", info),
        patch("services.import_service._auto_assign_industries", AsyncMock()),
    ):
        yield {"txn_regen": txn_regen, "ticker_info": info}


async def _login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _user_id(db, email: str) -> uuid.UUID:
    return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


def _txn(**overrides) -> dict:
    base = {
        "ticker": "NVDA",
        "type": "buy",
        "date": "2025-01-10",
        "shares": 10,
        "price_per_share": 100.0,
        "currency": "USD",
        "fx_rate_to_chf": 1.0,
        "fees_chf": 0,
        "total_chf": 1000.0,
    }
    base.update(overrides)
    return base


async def _book(client, headers, **overrides) -> dict:
    res = await client.post("/api/transactions", json=_txn(**overrides), headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _order(**overrides) -> dict:
    base = {
        "ticker": "NVDA",
        "side": "buy",
        "shares": 5,
        "limit_price": 100.0,
        "currency": "USD",
        "expiry_type": "gtc",
    }
    base.update(overrides)
    return base


async def _create_order(client, headers, **overrides) -> dict:
    res = await client.post("/api/orders/pending", json=_order(**overrides), headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _fill(**overrides) -> dict:
    base = {"price_per_share": 99.0, "fill_date": TODAY, "fx_rate_to_chf": 1.0}
    base.update(overrides)
    return base


async def _split_setup(client, headers) -> tuple[str, str, str]:
    """NVDA nach einem Teil-Wechsel in zwei Buckets: (pos_a, pos_b, bucket_b)."""
    pos_a = (await _book(client, headers))["position_id"]
    bucket = await client.post(
        "/api/portfolio/buckets", json={"name": "Satellite"}, headers=headers,
    )
    assert bucket.status_code == 201, bucket.text
    bucket_b = bucket.json()["id"]
    split = await client.post(
        f"/api/portfolio/positions/{pos_a}/split-to-bucket",
        json={"target_bucket_id": bucket_b, "split_pct": 0.5},
        headers=headers,
    )
    assert split.status_code == 200, split.text
    return pos_a, split.json()["new_position"]["id"], bucket_b


async def _txn_count(db, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.user_id == user_id)
    )


# --- K006: Buchungsdatum ----------------------------------------------------


class TestBookingDate:
    @pytest.mark.parametrize("bad_date", ["0001-01-08", "1700-01-01", "1969-12-31"])
    async def test_create_rejects_date_before_1970(self, client, bad_date):
        headers = await _login(client, "k006-create@example.com")
        res = await client.post("/api/transactions", json=_txn(date=bad_date), headers=headers)
        assert res.status_code == 422

    async def test_create_rejects_date_after_tomorrow(self, client):
        headers = await _login(client, "k006-future@example.com")
        future = (date.today() + timedelta(days=3)).isoformat()
        res = await client.post("/api/transactions", json=_txn(date=future), headers=headers)
        assert res.status_code == 422

    async def test_update_rejects_date_before_1970(self, client):
        headers = await _login(client, "k006-update@example.com")
        txn = await _book(client, headers)
        res = await client.put(
            f"/api/transactions/{txn['id']}", json={"date": "0002-01-01"}, headers=headers,
        )
        assert res.status_code == 422

    async def test_fill_rejects_date_before_1970(self, client, db):
        headers = await _login(client, "k006-fill@example.com")
        order = await _create_order(client, headers)
        res = await client.post(
            f"/api/orders/pending/{order['id']}/fill",
            json=_fill(fill_date="0002-01-01"),
            headers=headers,
        )
        assert res.status_code == 422
        assert await _txn_count(db, await _user_id(db, "k006-fill@example.com")) == 0

    async def test_dividend_confirm_rejects_date_before_1970(self, client):
        headers = await _login(client, "k006-div@example.com")
        res = await client.post(
            f"/api/dividends/{uuid.uuid4()}/confirm",
            json={"date": "1900-01-01", "total_chf": 10.0},
            headers=headers,
        )
        assert res.status_code == 422


# --- K023: Ticker, die an Yahoo gehen ----------------------------------------


class TestMarketTicker:
    @pytest.mark.parametrize("ticker", ["A,B,C", "AAPL MSFT", "A" * 31])
    async def test_auto_create_rejects_non_market_ticker(self, client, db, no_network, ticker):
        headers = await _login(client, "k023-create@example.com")
        res = await client.post("/api/transactions", json=_txn(ticker=ticker), headers=headers)
        assert res.status_code == 422
        no_network["ticker_info"].assert_not_awaited()
        assert await db.scalar(select(func.count()).select_from(Position)) == 0

    async def test_free_text_ticker_of_cash_account_stays_off_yahoo(self, client, db, no_network):
        headers = await _login(client, "k023-cash@example.com")
        res = await client.post(
            "/api/transactions",
            json=_txn(
                ticker="CASH MEIN KONTO", asset_type="cash", type="deposit",
                shares=0, price_per_share=0, currency="CHF", total_chf=100.0,
            ),
            headers=headers,
        )
        assert res.status_code == 201, res.text
        pos = (await db.execute(select(Position))).scalar_one()
        assert pos.ticker == "CASH MEIN KONTO"
        assert pos.yfinance_ticker is None
        no_network["ticker_info"].assert_not_awaited()

    async def test_free_text_ticker_of_existing_position_still_books(self, client, db):
        """Der Lookup einer bestehenden Position prüft das Muster nicht."""
        headers = await _login(client, "k023-lookup@example.com")
        first = await _book(
            client, headers, ticker="CASH MEIN KONTO", asset_type="cash", type="deposit",
            shares=0, price_per_share=0, currency="CHF", total_chf=100.0,
        )
        second = await _book(
            client, headers, ticker="cash mein konto", type="deposit",
            shares=0, price_per_share=0, currency="CHF", total_chf=50.0,
        )
        assert second["position_id"] == first["position_id"]
        assert second["created_position"] is False

    @pytest.mark.parametrize("ticker", ["AAPL,MSFT", "AAPL MSFT", " AAPL"])
    async def test_order_create_rejects_non_market_ticker(self, client, ticker):
        headers = await _login(client, "k023-order@example.com")
        res = await client.post("/api/orders/pending", json=_order(ticker=ticker), headers=headers)
        assert res.status_code == 422

    async def test_fill_of_legacy_order_with_bad_ticker_creates_no_position(
        self, client, db, no_network,
    ):
        headers = await _login(client, "k023-legacy@example.com")
        order = PendingOrder(
            user_id=await _user_id(db, "k023-legacy@example.com"),
            ticker="AAPL,MSFT,GOOG",
            side="buy",
            shares=Decimal("1"),
            limit_price=Decimal("10"),
            currency="USD",
            status="open",
        )
        db.add(order)
        await db.commit()

        res = await client.post(
            f"/api/orders/pending/{order.id}/fill", json=_fill(), headers=headers,
        )
        assert res.status_code == 422
        no_network["ticker_info"].assert_not_awaited()
        assert await db.scalar(select(func.count()).select_from(Position)) == 0


# --- K036: gleicher Ticker in mehreren Positionen ----------------------------


class TestAmbiguousTicker:
    async def test_ticker_booking_returns_409_with_hint(self, client, db):
        headers = await _login(client, "k036-409@example.com")
        await _split_setup(client, headers)
        res = await client.post("/api/transactions", json=_txn(shares=1), headers=headers)
        assert res.status_code == 409
        assert "position_id" in res.json()["detail"]
        assert await _txn_count(db, await _user_id(db, "k036-409@example.com")) == 1

    async def test_bucket_id_selects_the_position(self, client):
        headers = await _login(client, "k036-bucket@example.com")
        pos_a, pos_b, bucket_b = await _split_setup(client, headers)
        res = await client.post(
            "/api/transactions", json=_txn(shares=1, bucket_id=bucket_b), headers=headers,
        )
        assert res.status_code == 201, res.text
        assert res.json()["position_id"] == pos_b
        assert res.json()["created_position"] is False

    async def test_position_id_still_books(self, client):
        headers = await _login(client, "k036-posid@example.com")
        pos_a, _, _ = await _split_setup(client, headers)
        res = await client.post(
            "/api/transactions",
            json=_txn(ticker=None, position_id=pos_a, shares=1),
            headers=headers,
        )
        assert res.status_code == 201, res.text
        assert res.json()["position_id"] == pos_a

    async def test_active_position_wins_over_closed_one(self, client, db):
        headers = await _login(client, "k036-active@example.com")
        closed_id = (await _book(client, headers, ticker="MSFT"))["position_id"]
        await _book(
            client, headers, ticker=None, position_id=closed_id, type="sell",
            date="2025-02-10", total_chf=1200.0,
        )
        closed = await db.get(Position, uuid.UUID(closed_id))
        assert closed.is_active is False

        active = Position(
            user_id=closed.user_id, bucket_id=closed.bucket_id, ticker="MSFT",
            name="Microsoft", type=closed.type, currency="USD", shares=5,
            cost_basis_chf=500, is_active=True,
        )
        db.add(active)
        await db.commit()

        res = await client.post(
            "/api/transactions", json=_txn(ticker="MSFT", shares=1), headers=headers,
        )
        assert res.status_code == 201, res.text
        assert res.json()["position_id"] == str(active.id)

    async def test_order_fill_without_bucket_target_returns_409_and_stays_open(self, client, db):
        headers = await _login(client, "k036-fill@example.com")
        await _split_setup(client, headers)
        order = await _create_order(client, headers)

        res = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=_fill(), headers=headers,
        )
        assert res.status_code == 409
        assert "bucket_id_target" in res.json()["detail"]

        listing = await client.get("/api/orders/pending?status=open", headers=headers)
        assert [o["id"] for o in listing.json()["items"]] == [order["id"]]
        assert await _txn_count(db, await _user_id(db, "k036-fill@example.com")) == 1

    async def test_order_fill_uses_bucket_target(self, client, db):
        headers = await _login(client, "k036-fill-bucket@example.com")
        _, pos_b, bucket_b = await _split_setup(client, headers)
        order = await _create_order(client, headers, bucket_id_target=bucket_b)

        res = await client.post(
            f"/api/orders/pending/{order['id']}/fill", json=_fill(), headers=headers,
        )
        assert res.status_code == 200, res.text
        txn = await db.get(Transaction, uuid.UUID(res.json()["transaction_id"]))
        assert str(txn.position_id) == pos_b

    async def test_stop_loss_batch_sets_stop_on_every_match(self, client, db):
        # Über den Service wie die External-API: die interne Route reicht die
        # user_id als String durch, was nur der Postgres-Treiber annimmt.
        from services.stoploss_service import batch_update_stop_loss

        headers = await _login(client, "k036-stop@example.com")
        pos_a, pos_b, _ = await _split_setup(client, headers)
        result = await batch_update_stop_loss(
            db,
            await _user_id(db, "k036-stop@example.com"),
            [{"ticker": "NVDA", "stop_loss_price": 80.0, "confirmed_at_broker": True, "method": None}],
        )
        assert result == {
            "updated": [{"ticker": "NVDA", "stop_loss_price": 80.0}], "errors": [],
        }
        for pos_id in (pos_a, pos_b):
            pos = await db.get(Position, uuid.UUID(pos_id))
            await db.refresh(pos)
            assert float(pos.stop_loss_price) == 80.0
            assert pos.stop_loss_confirmed_at_broker is True
            assert pos.stop_loss_method == "manual"


# --- K041: is_active nach dem Recalc ------------------------------------------


class TestActiveStateAfterRecalc:
    async def test_corrected_sell_reactivates_position(self, client, db):
        headers = await _login(client, "k041-update@example.com")
        pos_id = (await _book(client, headers, shares=100, total_chf=1000.0))["position_id"]
        sell = await _book(
            client, headers, ticker=None, position_id=pos_id, type="sell",
            date="2025-02-10", shares=100, total_chf=1200.0,
        )
        pos = await db.get(Position, uuid.UUID(pos_id))
        assert pos.is_active is False

        res = await client.put(
            f"/api/transactions/{sell['id']}",
            json={"shares": 50, "total_chf": 600.0},
            headers=headers,
        )
        assert res.status_code == 200, res.text

        await db.refresh(pos)
        assert float(pos.shares) == 50
        assert pos.is_active is True
        listing = await client.get("/api/portfolio/positions", headers=headers)
        assert pos_id in [p["id"] for p in listing.json()]

    async def test_corrected_buy_to_zero_deactivates_position(self, client, db):
        headers = await _login(client, "k041-zero@example.com")
        buy = await _book(client, headers, stop_loss_price=80.0, stop_loss_method="structural")
        res = await client.put(
            f"/api/transactions/{buy['id']}", json={"shares": 0, "total_chf": 0}, headers=headers,
        )
        assert res.status_code == 200, res.text
        pos = await db.get(Position, uuid.UUID(buy["position_id"]))
        await db.refresh(pos)
        assert pos.is_active is False
        assert pos.stop_loss_price is None

    async def test_recalculate_all_reactivates_position_with_ledger_shares(self, client, db):
        """«Neu berechnen» läuft über _recalculate_position_with_txns."""
        from services.recalculate_service import recalculate_all_positions

        headers = await _login(client, "k041-all@example.com")
        pos_id = (await _book(client, headers, shares=100, total_chf=1000.0))["position_id"]
        sell = await _book(
            client, headers, ticker=None, position_id=pos_id, type="sell",
            date="2025-02-10", shares=100, total_chf=1200.0,
        )
        # Altbestand nachstellen: Verkauf korrigiert, Position blieb inaktiv.
        await db.execute(
            update(Transaction).where(Transaction.id == uuid.UUID(sell["id"])).values(shares=40)
        )
        await db.commit()
        pos = await db.get(Position, uuid.UUID(pos_id))
        await db.refresh(pos)
        assert pos.is_active is False

        await recalculate_all_positions(db, user_id=pos.user_id)

        await db.refresh(pos)
        assert float(pos.shares) == 60
        assert pos.is_active is True

    async def test_position_without_ledger_txns_keeps_its_status(self, client, db):
        """Ohne stückzahltragende Buchung ändert der Recalc is_active nicht."""
        headers = await _login(client, "k041-empty@example.com")
        created = await client.post(
            "/api/portfolio/positions",
            json={"ticker": "AAPL", "name": "Apple", "type": "stock", "currency": "USD",
                  "shares": 0, "cost_basis_chf": 0},
            headers=headers,
        )
        assert created.status_code in (200, 201), created.text
        pos_id = created.json()["id"]

        res = await client.post(f"/api/portfolio/positions/{pos_id}/recalculate", headers=headers)
        assert res.status_code == 200, res.text
        pos = await db.get(Position, uuid.UUID(pos_id))
        await db.refresh(pos)
        assert pos.is_active is True


# --- K108: Regen nach Datumsänderung ------------------------------------------


class TestRegenAfterDateChange:
    async def test_move_to_today_regenerates_from_old_date(self, client, db, no_network):
        headers = await _login(client, "k108@example.com")
        txn = await _book(client, headers, date="2025-01-10")
        no_network["txn_regen"].reset_mock()

        res = await client.put(
            f"/api/transactions/{txn['id']}", json={"date": TODAY}, headers=headers,
        )
        assert res.status_code == 200, res.text
        no_network["txn_regen"].assert_called_once_with(
            await _user_id(db, "k108@example.com"), date(2025, 1, 10),
        )

    async def test_move_into_past_regenerates_from_new_date(self, client, db, no_network):
        headers = await _login(client, "k108-past@example.com")
        txn = await _book(client, headers, date="2025-01-10")
        no_network["txn_regen"].reset_mock()

        res = await client.put(
            f"/api/transactions/{txn['id']}", json={"date": "2024-06-01"}, headers=headers,
        )
        assert res.status_code == 200, res.text
        no_network["txn_regen"].assert_called_once_with(
            await _user_id(db, "k108-past@example.com"), date(2024, 6, 1),
        )


# --- K037: Dividenden-Bestätigung -----------------------------------------------


async def _pending_dividend(client, db, email: str) -> tuple[dict, PendingDividend]:
    headers = await _login(client, email)
    pos_id = (await _book(client, headers, ticker="KO"))["position_id"]
    pending = PendingDividend(
        user_id=await _user_id(db, email),
        position_id=uuid.UUID(pos_id),
        ex_date=date(2025, 3, 1),
        dividend_per_share=Decimal("0.5"),
        currency="USD",
        shares_at_ex_date=Decimal("10"),
        expected_gross_chf=Decimal("5.00"),
        status=STATUS_PENDING,
    )
    db.add(pending)
    await db.commit()
    return headers, pending


async def _dividend_count(db, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user_id, Transaction.type == TransactionType.dividend,
        )
    )


async def _confirm_behind_the_back(db, pending: PendingDividend) -> None:
    """Stellt den Parallelfall nach: Die DB-Zeile ist schon bestätigt, das im
    Request geladene Objekt zeigt noch ``pending`` (Prüfung vor dem Schreiben)."""
    await db.execute(
        update(PendingDividend)
        .where(PendingDividend.id == pending.id)
        .values(status=STATUS_CONFIRMED)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    assert pending.status == STATUS_PENDING


class TestDividendConfirmRace:
    async def test_second_confirm_on_stale_read_books_nothing(self, client, db):
        headers, pending = await _pending_dividend(client, db, "k037-race@example.com")
        await _confirm_behind_the_back(db, pending)

        res = await client.post(
            f"/api/dividends/{pending.id}/confirm",
            json={"date": "2025-03-15", "total_chf": 3.25},
            headers=headers,
        )
        assert res.status_code == 409
        assert await _dividend_count(db, pending.user_id) == 0

    async def test_dismiss_on_stale_read_does_not_overwrite_confirmation(self, client, db):
        headers, pending = await _pending_dividend(client, db, "k037-dismiss@example.com")
        await _confirm_behind_the_back(db, pending)

        res = await client.post(f"/api/dividends/{pending.id}/dismiss", json={}, headers=headers)
        assert res.status_code == 409
        status = await db.scalar(
            select(PendingDividend.status).where(PendingDividend.id == pending.id)
        )
        assert status == STATUS_CONFIRMED

    async def test_confirm_books_once_and_repeat_gets_409(self, client, db):
        headers, pending = await _pending_dividend(client, db, "k037-once@example.com")
        payload = {"date": "2025-03-15", "total_chf": 3.25}

        first = await client.post(f"/api/dividends/{pending.id}/confirm", json=payload, headers=headers)
        assert first.status_code == 201, first.text
        second = await client.post(f"/api/dividends/{pending.id}/confirm", json=payload, headers=headers)
        assert second.status_code == 409

        assert await _dividend_count(db, pending.user_id) == 1
        row = (
            await db.execute(
                select(PendingDividend.status, PendingDividend.matched_transaction_id)
                .where(PendingDividend.id == pending.id)
            )
        ).one()
        assert row.status == STATUS_CONFIRMED
        assert str(row.matched_transaction_id) == first.json()["transaction_id"]

    async def test_confirm_respects_transaction_limit(self, client, db, monkeypatch):
        headers, pending = await _pending_dividend(client, db, "k037-limit@example.com")
        monkeypatch.setattr("api.dividends.MAX_TRANSACTIONS_PER_USER", 1)

        res = await client.post(
            f"/api/dividends/{pending.id}/confirm",
            json={"date": "2025-03-15", "total_chf": 3.25},
            headers=headers,
        )
        assert res.status_code == 400
        status = await db.scalar(
            select(PendingDividend.status).where(PendingDividend.id == pending.id)
        )
        assert status == STATUS_PENDING


# --- K162: Order-Notizen verschlüsselt ------------------------------------------


class TestOrderNotesEncrypted:
    async def test_create_and_patch_store_ciphertext_and_return_plaintext(self, client, db):
        headers = await _login(client, "k162@example.com")
        order = await _create_order(client, headers, notes="Tier-1 bei IBKR, Stop 80")
        assert order["notes"] == "Tier-1 bei IBKR, Stop 80"

        row = await db.get(PendingOrder, uuid.UUID(order["id"]))
        assert "Tier-1" not in row.notes
        assert decrypt_field(row.notes) == "Tier-1 bei IBKR, Stop 80"

        patched = await client.patch(
            f"/api/orders/pending/{order['id']}", json={"notes": "Neuer Plan"}, headers=headers,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["notes"] == "Neuer Plan"
        await db.refresh(row)
        assert "Neuer Plan" not in row.notes
        assert decrypt_field(row.notes) == "Neuer Plan"

        listing = await client.get("/api/orders/pending?status=open", headers=headers)
        assert listing.json()["items"][0]["notes"] == "Neuer Plan"

    async def test_legacy_plaintext_notes_stay_readable(self, client, db):
        headers = await _login(client, "k162-legacy@example.com")
        order = await _create_order(client, headers)
        await db.execute(
            update(PendingOrder)
            .where(PendingOrder.id == uuid.UUID(order["id"]))
            .values(notes="Altnotiz im Klartext")
        )
        await db.commit()

        listing = await client.get("/api/orders/pending?status=open", headers=headers)
        assert listing.json()["items"][0]["notes"] == "Altnotiz im Klartext"


# --- K149: Schema-Grenzen gegen Spaltenbreiten ----------------------------------


def _max_length(model, field: str) -> int | None:
    limits = [
        m.max_length for m in model.model_fields[field].metadata
        if getattr(m, "max_length", None) is not None
    ]
    return min(limits) if limits else None


def _column_length(model, column: str) -> int:
    return model.__table__.c[column].type.length


class TestSchemaLengths:
    def test_string_limits_fit_their_columns(self):
        from api.dividends import ConfirmDividendRequest
        from api.orders import PendingOrderCreate, PendingOrderFill, PendingOrderUpdate
        from api.stoploss import StopLossBatchItem, StopLossUpdate
        from api.transactions import TransactionCreate, TransactionUpdate

        pairs = [
            (TransactionCreate, "ticker", Position, "ticker"),
            (TransactionCreate, "stop_loss_method", Position, "stop_loss_method"),
            (TransactionCreate, "currency", Transaction, "currency"),
            (TransactionUpdate, "currency", Transaction, "currency"),
            (StopLossUpdate, "method", Position, "stop_loss_method"),
            (StopLossBatchItem, "method", Position, "stop_loss_method"),
            (StopLossBatchItem, "ticker", Position, "ticker"),
            (PendingOrderCreate, "ticker", PendingOrder, "ticker"),
            (PendingOrderCreate, "currency", PendingOrder, "currency"),
            (PendingOrderCreate, "broker", PendingOrder, "broker"),
            (PendingOrderUpdate, "currency", PendingOrder, "currency"),
            (PendingOrderUpdate, "broker", PendingOrder, "broker"),
            (PendingOrderFill, "currency", Transaction, "currency"),
            (ConfirmDividendRequest, "currency", Transaction, "currency"),
        ]
        for schema, field, model, column in pairs:
            limit = _max_length(schema, field)
            assert limit is not None, f"{schema.__name__}.{field} ohne max_length"
            assert limit <= _column_length(model, column), f"{schema.__name__}.{field}"

    async def test_stop_loss_method_longer_than_column_is_rejected(self, client):
        headers = await _login(client, "k149@example.com")
        txn = await _book(client, headers)
        too_long = "x" * 31

        single = await client.patch(
            f"/api/portfolio/positions/{txn['position_id']}/stop-loss",
            json={"stop_loss_price": 80.0, "method": too_long},
            headers=headers,
        )
        assert single.status_code == 422
        batch = await client.post(
            "/api/portfolio/stop-loss/batch",
            json={"items": [{"ticker": "NVDA", "stop_loss_price": 80.0, "method": too_long}]},
            headers=headers,
        )
        assert batch.status_code == 422
        booked = await client.post(
            "/api/transactions",
            json=_txn(stop_loss_price=80.0, stop_loss_method=too_long),
            headers=headers,
        )
        assert booked.status_code == 422


# --- K119: Summen der Transaktionsliste -----------------------------------------


class TestListSummary:
    async def _seed(self, client, headers) -> str:
        pos_id = (await _book(client, headers, fees_chf=5.0, total_chf=1000.0))["position_id"]
        await _book(
            client, headers, ticker=None, position_id=pos_id, date="2025-02-01",
            shares=5, fees_chf=2.5, total_chf=500.0,
        )
        await _book(
            client, headers, ticker=None, position_id=pos_id, type="sell", date="2025-03-01",
            shares=3, fees_chf=1.0, total_chf=300.0,
        )
        await _book(
            client, headers, ticker=None, position_id=pos_id, type="dividend",
            date="2025-04-01", shares=0, price_per_share=0, total_chf=30.0,
        )
        return pos_id

    async def test_summary_covers_all_pages(self, client):
        headers = await _login(client, "k119@example.com")
        await self._seed(client, headers)

        res = await client.get("/api/transactions?per_page=1", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body["items"]) == 1
        assert body["total"] == 4
        assert body["summary"] == {
            "total_chf_by_type": {"buy": 1500.0, "sell": 300.0, "dividend": 30.0},
            "fees_chf": 8.5,
        }

    async def test_summary_follows_the_filters(self, client):
        headers = await _login(client, "k119-filter@example.com")
        await self._seed(client, headers)

        by_type = await client.get("/api/transactions?type=buy&per_page=1", headers=headers)
        assert by_type.json()["summary"] == {
            "total_chf_by_type": {"buy": 1500.0}, "fees_chf": 7.5,
        }
        by_date = await client.get("/api/transactions?date_from=2025-02-15", headers=headers)
        assert by_date.json()["summary"] == {
            "total_chf_by_type": {"sell": 300.0, "dividend": 30.0}, "fees_chf": 1.0,
        }
        no_match = await client.get("/api/transactions?ticker=ZZZZ", headers=headers)
        assert no_match.json()["summary"] == {"total_chf_by_type": {}, "fees_chf": 0.0}
        assert no_match.json()["total"] == 0

    async def test_summary_ignores_other_users(self, client):
        other = await _login(client, "k119-other@example.com")
        await self._seed(client, other)
        headers = await _login(client, "k119-own@example.com")
        await _book(client, headers, ticker="AAPL", fees_chf=1.0, total_chf=200.0)

        res = await client.get("/api/transactions", headers=headers)
        assert res.json()["summary"] == {
            "total_chf_by_type": {"buy": 200.0}, "fees_chf": 1.0,
        }
