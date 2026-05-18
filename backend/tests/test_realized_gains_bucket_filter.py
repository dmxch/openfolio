"""Tests fuer get_realized_gains mit bucket_id-Filter.

Verifiziert die Snapshot-Semantik: realisierte Gewinne werden anhand des
Buckets zum Verkaufszeitpunkt (Transaction.bucket_id_at_sale) gefiltert,
nicht anhand des aktuellen Position.bucket_id.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from models.position import AssetType, Position, PricingMode, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.total_return_service import get_realized_gains

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


def _make_position(user_id, bucket_id, ticker="AAPL") -> Position:
    return Position(
        user_id=user_id,
        bucket_id=bucket_id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="USD",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=0,
        cost_basis_chf=0,
    )


def _make_sell(user_id, pos_id, bucket_id_at_sale, *, sell_date, pnl) -> Transaction:
    return Transaction(
        user_id=user_id,
        position_id=pos_id,
        type=TransactionType.sell,
        date=sell_date,
        shares=Decimal("1"),
        price_per_share=Decimal("100"),
        currency="USD",
        fx_rate_to_chf=Decimal("1"),
        fees_chf=Decimal("0"),
        taxes_chf=Decimal("0"),
        total_chf=Decimal("100"),
        cost_basis_at_sale=Decimal("80"),
        realized_pnl_chf=Decimal(str(pnl)),
        realized_pnl=Decimal(str(pnl)),
        bucket_id_at_sale=bucket_id_at_sale,
    )


async def test_no_filter_returns_all_sells(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket_a = await create_bucket(db, user.id, name="Core")
    bucket_b = await create_bucket(db, user.id, name="Satellite")
    await db.commit()

    pos = _make_position(user.id, bucket_a.id, ticker="AAPL")
    db.add(pos)
    await db.commit()

    db.add(_make_sell(user.id, pos.id, bucket_a.id, sell_date=date(2025, 1, 10), pnl=20))
    db.add(_make_sell(user.id, pos.id, bucket_b.id, sell_date=date(2025, 2, 10), pnl=30))
    await db.commit()

    res = await get_realized_gains(db, user_id=user.id)
    assert len(res["positions"]) == 2
    assert res["total_realized_pnl_chf"] == 50.0


async def test_filter_by_bucket_only_returns_matching_sells(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket_a = await create_bucket(db, user.id, name="Core")
    bucket_b = await create_bucket(db, user.id, name="Satellite")
    await db.commit()

    pos = _make_position(user.id, bucket_a.id, ticker="AAPL")
    db.add(pos)
    await db.commit()

    db.add(_make_sell(user.id, pos.id, bucket_a.id, sell_date=date(2025, 1, 10), pnl=20))
    db.add(_make_sell(user.id, pos.id, bucket_b.id, sell_date=date(2025, 2, 10), pnl=30))
    await db.commit()

    res_a = await get_realized_gains(db, user_id=user.id, bucket_id=bucket_a.id)
    assert len(res_a["positions"]) == 1
    assert res_a["total_realized_pnl_chf"] == 20.0

    res_b = await get_realized_gains(db, user_id=user.id, bucket_id=bucket_b.id)
    assert len(res_b["positions"]) == 1
    assert res_b["total_realized_pnl_chf"] == 30.0


async def test_snapshot_survives_position_bucket_change(db):
    """Wenn die Position spaeter in einen anderen Bucket wandert, bleibt der
    historische Sell weiterhin im urspruenglichen Bucket gelistet."""
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket_a = await create_bucket(db, user.id, name="Core")
    bucket_b = await create_bucket(db, user.id, name="Satellite")
    await db.commit()

    pos = _make_position(user.id, bucket_a.id, ticker="AAPL")
    db.add(pos)
    await db.commit()

    db.add(_make_sell(user.id, pos.id, bucket_a.id, sell_date=date(2025, 1, 10), pnl=20))
    await db.commit()

    # Position spaeter in Bucket B umhaengen
    pos.bucket_id = bucket_b.id
    await db.commit()

    # Sell muss weiterhin in Bucket A erscheinen, nicht in B
    res_a = await get_realized_gains(db, user_id=user.id, bucket_id=bucket_a.id)
    assert len(res_a["positions"]) == 1

    res_b = await get_realized_gains(db, user_id=user.id, bucket_id=bucket_b.id)
    assert len(res_b["positions"]) == 0


async def test_filter_isolated_per_user(db):
    """Bucket-Filter darf keine Sells anderer User zurueckgeben."""
    user1 = await _make_user(db)
    user2 = await _make_user(db)
    await create_system_buckets(db, user1.id)
    await create_system_buckets(db, user2.id)
    await db.commit()
    b1 = await create_bucket(db, user1.id, name="Core")
    b2 = await create_bucket(db, user2.id, name="Core")
    await db.commit()

    p1 = _make_position(user1.id, b1.id, ticker="AAPL")
    p2 = _make_position(user2.id, b2.id, ticker="MSFT")
    db.add_all([p1, p2])
    await db.commit()

    db.add(_make_sell(user1.id, p1.id, b1.id, sell_date=date(2025, 1, 10), pnl=20))
    db.add(_make_sell(user2.id, p2.id, b2.id, sell_date=date(2025, 1, 10), pnl=99))
    await db.commit()

    # User1 filtert auf seinen eigenen Bucket — sollte b2 NICHT sehen,
    # selbst wenn er per Zufall b2.id raten wuerde (user_id-Scope greift).
    res = await get_realized_gains(db, user_id=user1.id, bucket_id=b2.id)
    assert len(res["positions"]) == 0
