"""Trade-Journal: Plan(Vault-Report)->Ist(Txn)-Join + Status, und der
Ownership-Schutz des Plan->Ist-Links (Multi-User)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from api.external_v1 import _resolve_linked_txn_id
from models.position import AssetType, Position, PriceSource
from models.report import Report
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket
from services.trade_journal_service import get_trade_journal

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await create_system_buckets(db, user.id)
    await get_liquid_default_bucket(db, user.id)
    await db.commit()
    return user


async def _make_txn(db, user, *, ticker="AAPL", typ=TransactionType.buy) -> Transaction:
    liquid = await get_liquid_default_bucket(db, user.id)
    pos = Position(
        user_id=user.id, bucket_id=liquid.id, ticker=ticker, name=f"{ticker} Inc",
        type=AssetType.stock, currency="USD", price_source=PriceSource.yahoo,
        shares=Decimal("10"), cost_basis_chf=Decimal("1500"),
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    txn = Transaction(
        position_id=pos.id, user_id=user.id, type=typ, date=date(2026, 6, 18),
        shares=Decimal("10"), price_per_share=Decimal("150"), currency="USD",
        fx_rate_to_chf=Decimal("0.9"), total_chf=Decimal("1350"),
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


def _report(user, **over) -> Report:
    base = dict(
        user_id=user.id, category="trade", title="Trade-Plan AAPL",
        report_date=date(2026, 6, 17), body="...", content_hash=uuid.uuid4().hex,
        ticker="AAPL", side="buy",
    )
    base.update(over)
    return Report(**base)


# --- Journal-Join + Status ----------------------------------------------

async def test_journal_links_plan_to_executed_and_open(db):
    user = await _make_user(db)
    txn = await _make_txn(db, user, ticker="AAPL")

    db.add(_report(user, title="Trade-Plan AAPL", ticker="AAPL", side="buy",
                   linked_transaction_id=txn.id, content_hash="h1"))                 # executed
    db.add(_report(user, title="Sell-Check NUE", ticker="NUE", side="sell",
                   linked_transaction_id=None, content_hash="h2"))                    # open
    db.add(_report(user, category="macro", title="Macro-Brief", ticker=None,
                   content_hash="h3"))                                                # nicht 'trade'
    db.add(_report(user, title="Alt-Plan", ticker="XOM",
                   archived_at=date(2026, 6, 1), content_hash="h4"))                  # archiviert
    await db.commit()

    res = await get_trade_journal(db, user.id)
    assert res["summary"] == {"total": 2, "executed": 1, "open": 1}   # macro + archiviert raus

    by_ticker = {e["ticker"]: e for e in res["entries"]}
    assert by_ticker["AAPL"]["status"] == "executed"
    assert by_ticker["AAPL"]["ist"]["transaction_id"] == str(txn.id)
    assert by_ticker["AAPL"]["ist"]["price_per_share"] == 150.0
    assert by_ticker["NUE"]["status"] == "open"
    assert by_ticker["NUE"]["ist"] is None


async def test_journal_is_user_scoped(db):
    """Fremde Reports/Txns tauchen nie im Journal eines anderen Users auf."""
    a = await _make_user(db)
    b = await _make_user(db)
    txn_a = await _make_txn(db, a, ticker="AAPL")
    db.add(_report(a, linked_transaction_id=txn_a.id, content_hash="ha"))
    await db.commit()

    res_b = await get_trade_journal(db, b.id)
    assert res_b["summary"]["total"] == 0
    assert res_b["entries"] == []


# --- Ownership-Schutz des Links -----------------------------------------

async def test_link_resolver_accepts_own_txn(db):
    user = await _make_user(db)
    txn = await _make_txn(db, user)
    out = await _resolve_linked_txn_id(db, user, str(txn.id))
    assert out == txn.id


async def test_link_resolver_rejects_foreign_txn(db):
    owner = await _make_user(db)
    txn = await _make_txn(db, owner)
    attacker = await _make_user(db)
    with pytest.raises(HTTPException) as ei:
        await _resolve_linked_txn_id(db, attacker, str(txn.id))
    assert ei.value.status_code == 404


async def test_link_resolver_rejects_malformed(db):
    user = await _make_user(db)
    with pytest.raises(HTTPException) as ei:
        await _resolve_linked_txn_id(db, user, "not-a-uuid")
    assert ei.value.status_code == 422


async def test_link_resolver_empty_is_none(db):
    user = await _make_user(db)
    assert await _resolve_linked_txn_id(db, user, None) is None
    assert await _resolve_linked_txn_id(db, user, "") is None
    assert await _resolve_linked_txn_id(db, user, "  ") is None
