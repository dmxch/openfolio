"""Unit-Tests fuer services/bucket_service.py.

Coverage:
  - System-Buckets idempotent erstellen
  - User-Bucket-CRUD + Limit-Check
  - Position-Wechsel mit History-Eintrag
  - Migration-Rollback
  - Risk-Rules-Diff fuer Wechsel-Modal
  - System-Bucket-Protection (Name nicht editierbar, kein Delete)
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from models.bucket import Bucket, BucketKind, BucketSystemRole, PositionBucketHistory
from models.position import AssetType, Position, PricingMode, PriceSource
from models.user import User, UserSettings
from services.bucket_service import (
    BucketError,
    MAX_BUCKETS_PER_USER,
    count_active_user_buckets,
    create_bucket,
    create_system_buckets,
    delete_bucket,
    diff_risk_rules,
    get_bucket,
    get_liquid_default_bucket,
    list_buckets,
    migration_rollback,
    move_position_to_bucket,
    update_bucket,
)

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    return user


async def _make_position(db, user, *, bucket_id=None, ticker="AAPL"):
    pos = Position(
        user_id=user.id,
        bucket_id=bucket_id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="USD",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("10"),
        cost_basis_chf=Decimal("1000"),
        current_price=Decimal("100"),
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


async def test_create_system_buckets_idempotent(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    buckets = await list_buckets(db, user.id)
    names = {b.name for b in buckets}
    assert "Alle Positionen" in names
    assert "Immobilien" in names
    assert "Private Equity" in names
    assert "Vorsorge" in names

    # zweimal aufrufen — idempotent, nicht 8 Buckets
    await create_system_buckets(db, user.id)
    await db.commit()
    buckets2 = await list_buckets(db, user.id)
    assert len(buckets2) == 4


async def test_get_liquid_default_lazy_creates(db):
    user = await _make_user(db)
    # noch keine System-Buckets
    bucket = await get_liquid_default_bucket(db, user.id)
    await db.commit()
    assert bucket.system_role == BucketSystemRole.liquid_default


async def test_create_user_bucket(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()

    bucket = await create_bucket(
        db, user.id,
        name="Core",
        color="#3b82f6",
        benchmark="URTH",
        risk_rules={"drawdown_brake_pct": 6.0, "drawdown_brake_active": True},
    )
    await db.commit()
    assert bucket.kind == BucketKind.user
    assert bucket.name == "Core"
    assert await count_active_user_buckets(db, user.id) == 1


async def test_create_bucket_duplicate_name_rejected(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()

    await create_bucket(db, user.id, name="Trading")
    await db.commit()

    with pytest.raises(BucketError):
        await create_bucket(db, user.id, name="Trading")


async def test_create_bucket_limit_enforced(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()

    for i in range(MAX_BUCKETS_PER_USER):
        await create_bucket(db, user.id, name=f"B{i}")
        await db.commit()

    with pytest.raises(BucketError):
        await create_bucket(db, user.id, name="One Too Many")


async def test_create_bucket_target_xor(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    with pytest.raises(BucketError):
        await create_bucket(db, user.id, name="X", target_pct=50.0, target_chf=10000)


async def test_update_system_bucket_name_rejected(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    liquid = await get_liquid_default_bucket(db, user.id)
    with pytest.raises(BucketError):
        await update_bucket(db, user.id, liquid.id, name="Renamed")


async def test_update_system_bucket_color_allowed(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    liquid = await get_liquid_default_bucket(db, user.id)
    await update_bucket(db, user.id, liquid.id, color="#ff0000", benchmark="^GSPC")
    await db.commit()
    refreshed = await get_bucket(db, user.id, liquid.id)
    assert refreshed.color == "#ff0000"
    assert refreshed.benchmark == "^GSPC"


async def test_delete_user_bucket_reassigns_positions(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    custom = await create_bucket(db, user.id, name="Trading")
    await db.commit()
    pos = await _make_position(db, user, bucket_id=custom.id, ticker="XYZ")
    moved = await delete_bucket(db, user.id, custom.id)
    await db.commit()
    assert moved == 1

    await db.refresh(pos)
    liquid = await get_liquid_default_bucket(db, user.id)
    assert pos.bucket_id == liquid.id
    refreshed = await get_bucket(db, user.id, custom.id)
    assert refreshed.deleted_at is not None


async def test_delete_system_bucket_rejected(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    liquid = await get_liquid_default_bucket(db, user.id)
    with pytest.raises(BucketError):
        await delete_bucket(db, user.id, liquid.id)


async def test_move_position_to_bucket_records_history(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="Core")
    b = await create_bucket(db, user.id, name="Satellite")
    await db.commit()
    pos = await _make_position(db, user, bucket_id=a.id)

    await move_position_to_bucket(db, user.id, pos.id, b.id, note="rebalance")
    await db.commit()

    await db.refresh(pos)
    assert pos.bucket_id == b.id

    from sqlalchemy import select
    hist_q = await db.execute(
        select(PositionBucketHistory).where(PositionBucketHistory.position_id == pos.id)
    )
    entries = list(hist_q.scalars().all())
    assert len(entries) == 1
    assert entries[0].from_bucket_id == a.id
    assert entries[0].to_bucket_id == b.id
    assert entries[0].changed_by == "user"


async def test_move_to_same_bucket_is_noop(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    await db.commit()
    pos = await _make_position(db, user, bucket_id=a.id)
    await move_position_to_bucket(db, user.id, pos.id, a.id)
    await db.commit()
    from sqlalchemy import select
    hist_q = await db.execute(
        select(PositionBucketHistory).where(PositionBucketHistory.position_id == pos.id)
    )
    assert len(list(hist_q.scalars().all())) == 0


async def test_migration_rollback_deletes_user_buckets_and_remaps(db):
    user = await _make_user(db)
    # Onboarding-Modal-Flag mock-aus: muss durch Rollback auf True kommen
    from sqlalchemy import select
    settings_q = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    )
    settings = settings_q.scalar_one()
    settings.noticed_buckets_migration = False
    await db.commit()

    await create_system_buckets(db, user.id)
    await db.commit()
    core = await create_bucket(db, user.id, name="Core")
    sat = await create_bucket(db, user.id, name="Satellite")
    await db.commit()
    p1 = await _make_position(db, user, bucket_id=core.id, ticker="AAA")
    p2 = await _make_position(db, user, bucket_id=sat.id, ticker="BBB")

    result = await migration_rollback(db, user.id)
    await db.commit()

    assert result["buckets_deleted"] == 2
    assert result["positions_moved"] == 2

    await db.refresh(p1); await db.refresh(p2)
    liquid = await get_liquid_default_bucket(db, user.id)
    assert p1.bucket_id == liquid.id
    assert p2.bucket_id == liquid.id

    await db.refresh(settings)
    assert settings.noticed_buckets_migration is True


async def test_split_position_basic_50_50(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="Core")
    b = await create_bucket(db, user.id, name="Spielgeld")
    await db.commit()
    pos = await _make_position(db, user, bucket_id=a.id, ticker="AAPL")
    pos.shares = Decimal("10")
    pos.cost_basis_chf = Decimal("1000")
    await db.commit()

    from services.bucket_service import split_position_to_bucket
    original, new_pos = await split_position_to_bucket(
        db, user.id, pos.id, b.id, split_pct=0.5,
    )
    await db.commit()

    assert float(original.shares) == 5.0
    assert float(original.cost_basis_chf) == 500.0
    assert float(new_pos.shares) == 5.0
    assert float(new_pos.cost_basis_chf) == 500.0
    assert new_pos.bucket_id == b.id
    assert original.bucket_id == a.id
    assert new_pos.id != original.id
    assert new_pos.ticker == original.ticker


async def test_split_position_rejects_existing_target(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()
    # Position AAPL in beiden Buckets
    p1 = await _make_position(db, user, bucket_id=a.id, ticker="AAPL")
    p2 = await _make_position(db, user, bucket_id=b.id, ticker="AAPL")

    from services.bucket_service import split_position_to_bucket
    with pytest.raises(BucketError, match="bereits eine aktive Position"):
        await split_position_to_bucket(
            db, user.id, p1.id, b.id, split_pct=0.5,
        )


async def test_split_position_invalid_pct(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()
    pos = await _make_position(db, user, bucket_id=a.id, ticker="X")

    from services.bucket_service import split_position_to_bucket
    with pytest.raises(BucketError):
        await split_position_to_bucket(db, user.id, pos.id, b.id, split_pct=0)
    with pytest.raises(BucketError):
        await split_position_to_bucket(db, user.id, pos.id, b.id, split_pct=1)
    with pytest.raises(BucketError):
        await split_position_to_bucket(db, user.id, pos.id, b.id, split_pct=1.5)


async def test_split_position_same_bucket_rejected(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    await db.commit()
    pos = await _make_position(db, user, bucket_id=a.id, ticker="X")

    from services.bucket_service import split_position_to_bucket
    with pytest.raises(BucketError):
        await split_position_to_bucket(db, user.id, pos.id, a.id, split_pct=0.5)


async def test_diff_risk_rules_marks_changes():
    from models.bucket import Bucket
    a = Bucket(user_id=uuid.uuid4(), name="A", kind=BucketKind.user,
               benchmark="URTH",
               risk_rules={"drawdown_brake_pct": 6.0, "drawdown_brake_active": True})
    b = Bucket(user_id=uuid.uuid4(), name="B", kind=BucketKind.user,
               benchmark="^GSPC",
               risk_rules={"drawdown_brake_pct": 15.0,
                           "drawdown_brake_active": True,
                           "stop_loss_method_default": "trailing_pct"})
    diff = diff_risk_rules(a, b)
    by_key = {row["key"]: row for row in diff}
    assert by_key["drawdown_brake_pct"]["changed"] is True
    assert by_key["drawdown_brake_pct"]["old"] == 6.0
    assert by_key["drawdown_brake_pct"]["new"] == 15.0
    assert by_key["benchmark"]["changed"] is True
    assert by_key["benchmark"]["old"] == "URTH"
    assert by_key["benchmark"]["new"] == "^GSPC"
    assert by_key["drawdown_brake_active"]["changed"] is False
