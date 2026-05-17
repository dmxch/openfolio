"""Tests fuer F-16 Bucket-Snapshot-Backfill."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from models.bucket import BucketSnapshot
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position, PricingMode, PriceSource
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.bucket_snapshot_backfill_service import (
    _current_bucket_shares,
    backfill_bucket_snapshots,
)

pytestmark = pytest.mark.asyncio


async def _make_user(db):
    u = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(u)
    await db.commit()
    db.add(UserSettings(user_id=u.id, noticed_buckets_migration=True))
    await db.commit()
    return u


async def _add_position(db, user, bucket_id, cb=1000):
    pos = Position(
        user_id=user.id,
        bucket_id=bucket_id,
        ticker=f"T{uuid.uuid4().hex[:6]}",
        name="T",
        type=AssetType.stock,
        currency="CHF",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("10"),
        cost_basis_chf=Decimal(str(cb)),
        current_price=Decimal("100"),
    )
    db.add(pos)
    await db.commit()
    return pos


async def test_current_bucket_shares(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()
    await _add_position(db, user, a.id, cb=3000)
    await _add_position(db, user, b.id, cb=1000)
    shares = await _current_bucket_shares(db, user.id)
    assert pytest.approx(shares[a.id], rel=1e-3) == 0.75
    assert pytest.approx(shares[b.id], rel=1e-3) == 0.25


async def test_backfill_fills_historical_snapshots(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()
    await _add_position(db, user, a.id, cb=6000)
    await _add_position(db, user, b.id, cb=2000)
    # Drei portfolio_snapshots der Vergangenheit
    today = date.today()
    for i in range(3):
        db.add(PortfolioSnapshot(
            user_id=user.id,
            date=today - timedelta(days=i + 1),
            total_value_chf=Decimal("8000"),
            cash_chf=Decimal("0"),
            net_cash_flow_chf=Decimal("0"),
        ))
    await db.commit()

    result = await backfill_bucket_snapshots(db, user.id)
    await db.commit()
    assert result["days_filled"] == 6  # 3 Tage x 2 Buckets
    assert result["buckets_touched"] == 2

    # Bucket A bekommt 75%, Bucket B 25%
    from sqlalchemy import select
    snaps = (await db.execute(
        select(BucketSnapshot).where(BucketSnapshot.user_id == user.id)
        .order_by(BucketSnapshot.bucket_id, BucketSnapshot.date)
    )).scalars().all()
    by_bucket: dict = {}
    for s in snaps:
        by_bucket.setdefault(s.bucket_id, []).append(float(s.total_value_chf))
    assert all(v == 6000 for v in by_bucket[a.id])
    assert all(v == 2000 for v in by_bucket[b.id])


async def test_backfill_skips_existing(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    await db.commit()
    await _add_position(db, user, a.id, cb=1000)

    today = date.today()
    yesterday = today - timedelta(days=1)
    db.add(PortfolioSnapshot(
        user_id=user.id, date=yesterday,
        total_value_chf=Decimal("1000"),
        cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal("0"),
    ))
    # bucket_snapshot existiert schon fuer yesterday
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=a.id, date=yesterday,
        total_value_chf=Decimal("999"),  # absichtlich abweichender Wert
        cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
        running_peak_chf=Decimal("999"),
    ))
    await db.commit()

    result = await backfill_bucket_snapshots(db, user.id)
    await db.commit()
    assert result["skipped_existing"] >= 1

    # Vorhandener Wert nicht ueberschrieben
    from sqlalchemy import select
    s = (await db.execute(
        select(BucketSnapshot).where(
            BucketSnapshot.user_id == user.id,
            BucketSnapshot.bucket_id == a.id,
            BucketSnapshot.date == yesterday,
        )
    )).scalar_one()
    assert float(s.total_value_chf) == 999.0


async def test_backfill_running_peak_monoton(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    await db.commit()
    await _add_position(db, user, a.id, cb=1000)

    today = date.today()
    # Wertverlauf: 1000, 1500, 800
    for i, v in enumerate([1000, 1500, 800], start=1):
        db.add(PortfolioSnapshot(
            user_id=user.id,
            date=today - timedelta(days=4 - i),
            total_value_chf=Decimal(str(v)),
            cash_chf=Decimal("0"),
            net_cash_flow_chf=Decimal("0"),
        ))
    await db.commit()
    await backfill_bucket_snapshots(db, user.id)
    await db.commit()

    from sqlalchemy import select
    snaps = (await db.execute(
        select(BucketSnapshot).where(
            BucketSnapshot.user_id == user.id,
            BucketSnapshot.bucket_id == a.id,
        ).order_by(BucketSnapshot.date)
    )).scalars().all()
    peaks = [float(s.running_peak_chf) for s in snaps]
    # peaks muss monoton sein
    assert peaks == sorted(peaks)
    # peak nach Tag mit value=1500 muss >= 1500 bleiben
    assert peaks[-1] >= 1500.0
