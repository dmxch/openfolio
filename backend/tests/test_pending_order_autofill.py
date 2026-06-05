"""Tests für die Fill-Reconciliation (pending_order_service.try_auto_fill_order).

Decision (bewusst streng): exakt gleiche Shares + Ticker + Seite + Status open,
Order-Anlage innerhalb ±35d des Transaktionsdatums. FIFO bei mehreren Treffern.
Auto-Cancel ist nicht abgedeckt (nicht aus Transaktionen ableitbar).
"""
import uuid
from datetime import date, datetime, timedelta

import pytest

from models.pending_order import PendingOrder
from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from services.pending_order_service import (
    try_auto_fill_order,
    try_auto_fill_orders_bulk,
)

pytestmark = pytest.mark.asyncio

USER = uuid.uuid4()
TXN_DATE = date(2026, 6, 5)


async def _position(db, ticker="NOVN.SW"):
    pos = Position(
        user_id=USER, bucket_id=uuid.uuid4(), ticker=ticker, name=ticker,
        type=AssetType.stock, shares=10,
    )
    db.add(pos)
    await db.flush()
    return pos


def _order(*, ticker="NOVN.SW", side="buy", shares=10, status="open",
           created=datetime(2026, 6, 5, 12, 0, 0), linked=None):
    return PendingOrder(
        user_id=USER, ticker=ticker, side=side, shares=shares,
        limit_price=100, status=status, created_at=created,
        linked_transaction_id=linked,
    )


def _txn(pos, *, type=TransactionType.buy, shares=10, d=TXN_DATE):
    return Transaction(
        user_id=USER, position_id=pos.id, type=type, date=d,
        shares=shares, price_per_share=100, total_chf=1000,
    )


async def _commit(db, *objs):
    db.add_all(objs)
    await db.commit()


async def test_exact_match_fills_and_links(db):
    pos = await _position(db)
    order, txn = _order(), None
    txn = _txn(pos)
    await _commit(db, order, txn)

    res = await try_auto_fill_order(db, txn, USER)
    assert res is not None
    await db.refresh(order)
    assert order.status == "filled"
    assert order.linked_transaction_id == txn.id


async def test_shares_mismatch_no_fill(db):
    pos = await _position(db)
    order = _order(shares=10)
    txn = _txn(pos, shares=7)
    await _commit(db, order, txn)

    assert await try_auto_fill_order(db, txn, USER) is None
    await db.refresh(order)
    assert order.status == "open"


async def test_side_mismatch_no_fill(db):
    pos = await _position(db)
    order = _order(side="sell")
    txn = _txn(pos, type=TransactionType.buy)
    await _commit(db, order, txn)
    assert await try_auto_fill_order(db, txn, USER) is None


async def test_ticker_mismatch_no_fill(db):
    pos = await _position(db, ticker="ROG.SW")
    order = _order(ticker="NOVN.SW")
    txn = _txn(pos)
    await _commit(db, order, txn)
    assert await try_auto_fill_order(db, txn, USER) is None


async def test_outside_window_no_fill(db):
    pos = await _position(db)
    order = _order(created=datetime(2026, 4, 1, 12, 0, 0))  # ~65 Tage vor Txn
    txn = _txn(pos)
    await _commit(db, order, txn)
    assert await try_auto_fill_order(db, txn, USER) is None


async def test_dividend_txn_ignored(db):
    pos = await _position(db)
    order = _order()
    txn = _txn(pos, type=TransactionType.dividend)
    await _commit(db, order, txn)
    assert await try_auto_fill_order(db, txn, USER) is None


async def test_already_filled_order_not_rematched(db):
    pos = await _position(db)
    order = _order(status="filled")
    txn = _txn(pos)
    await _commit(db, order, txn)
    assert await try_auto_fill_order(db, txn, USER) is None


async def test_txn_already_linked_skipped(db):
    # Eine Transaktion, die bereits an eine Order haengt (z.B. via /fill), darf
    # keine zweite offene Order schliessen.
    pos = await _position(db)
    txn = _txn(pos)
    db.add(txn)
    await db.flush()
    linked_order = _order(status="filled", linked=txn.id)
    open_order = _order()  # gleiche Kriterien, aber offen
    await _commit(db, linked_order, open_order)

    assert await try_auto_fill_order(db, txn, USER) is None
    await db.refresh(open_order)
    assert open_order.status == "open"


async def test_fifo_oldest_open_order_fills_first(db):
    pos = await _position(db)
    old = _order(created=datetime(2026, 6, 1, 9, 0, 0))
    new = _order(created=datetime(2026, 6, 4, 9, 0, 0))
    txn = _txn(pos)
    await _commit(db, old, new, txn)

    res = await try_auto_fill_order(db, txn, USER)
    assert res is not None
    await db.refresh(old)
    await db.refresh(new)
    assert old.status == "filled"
    assert new.status == "open"


async def test_bulk_counts_matches(db):
    pos = await _position(db)
    o1 = _order(shares=10)
    o2 = _order(shares=5)
    t1 = _txn(pos, shares=10)
    t2 = _txn(pos, shares=5)
    await _commit(db, o1, o2, t1, t2)

    n = await try_auto_fill_orders_bulk(db, [t1, t2], USER)
    assert n == 2


# --- Integration: Hook-Verdrahtung über den echten API-Pfad ---

TEST_PASSWORD = "TestPassw0rd!2026"


async def test_posting_matching_transaction_autofills_order(client, monkeypatch):
    """POST /api/transactions (buy) füllt eine passende offene Order automatisch —
    ohne manuelles /fill. Sichert den create_transaction_core-Hook ab."""
    import yfinance as yf

    class _FakeTicker:
        def __init__(self, *_a, **_k):
            self.info = {"shortName": "Apple Inc.", "currency": "USD"}

    monkeypatch.setattr(yf, "Ticker", _FakeTicker)

    await client.post("/api/auth/register", json={"email": "af@example.com", "password": TEST_PASSWORD})
    jwt = (await client.post("/api/auth/login", json={"email": "af@example.com", "password": TEST_PASSWORD})).json()["access_token"]
    h = {"Authorization": f"Bearer {jwt}"}

    pos_id = (await client.post(
        "/api/portfolio/positions",
        json={"ticker": "AAPL", "name": "Apple Inc.", "type": "stock", "currency": "USD", "shares": 0, "cost_basis_chf": 0},
        headers=h,
    )).json()["id"]

    order = (await client.post(
        "/api/orders/pending",
        json={"ticker": "AAPL", "side": "buy", "shares": 10, "limit_price": 150.0, "currency": "USD", "expiry_type": "gtc"},
        headers=h,
    )).json()

    txn_res = await client.post(
        "/api/transactions",
        json={"position_id": pos_id, "type": "buy", "date": date.today().isoformat(),
              "shares": 10, "price_per_share": 149.0, "currency": "USD",
              "fx_rate_to_chf": 0.88, "fees_chf": 5.0, "taxes_chf": 0, "total_chf": 1315.0},
        headers=h,
    )
    assert txn_res.status_code == 201, txn_res.text
    txn_id = txn_res.json().get("id") or txn_res.json().get("transaction_id")

    data = (await client.get("/api/orders/pending?status=all", headers=h)).json()
    orders = data["items"] if isinstance(data, dict) else data
    o = next(x for x in orders if x["id"] == order["id"])
    assert o["effective_status"] == "filled"
    assert o["linked_transaction_id"] == txn_id
