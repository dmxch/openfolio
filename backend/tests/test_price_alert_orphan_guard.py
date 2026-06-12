"""Regression tests fuer den Orphan-Guard in check_price_alerts.

Hintergrund: Preis-Alarme sind produktseitig an Portfolio ∪ Watchlist
gebunden (siehe Cascade beim Watchlist-Entfernen). Positionen verschwinden
aber auch via Verkauf auf 0, Loeschung oder Import — der Alert blieb dann
aktiv und feuerte weiter (z.B. ANET nach Verkauf, 2026-06-12). Der Guard
deaktiviert solche Waisen statt sie auszuloesen.
"""

import uuid
from decimal import Decimal

import pytest

from models.position import AssetType, Position, PriceSource, PricingMode
from models.price_alert import PriceAlert
from models.user import User
from models.watchlist import WatchlistItem
from services.bucket_service import create_system_buckets
from services.price_alert_service import check_price_alerts

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_position(db, user, ticker="AAPL", shares="1"):
    from sqlalchemy import select

    from models.bucket import Bucket

    await create_system_buckets(db, user.id)
    await db.commit()
    bucket_id = (
        await db.execute(select(Bucket.id).where(Bucket.user_id == user.id).limit(1))
    ).scalar()
    pos = Position(
        bucket_id=bucket_id,
        user_id=user.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="CHF",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal(shares),
        cost_basis_chf=Decimal("1000"),
        current_price=Decimal("100"),
    )
    db.add(pos)
    await db.commit()
    return pos


async def _make_alert(db, user, ticker="AAPL"):
    alert = PriceAlert(
        user_id=user.id,
        ticker=ticker,
        alert_type="price_below",
        target_value=Decimal("156.00"),
        currency="CHF",
    )
    db.add(alert)
    await db.commit()
    return alert


def _fake_price(monkeypatch, price=155.94):
    from services import cache

    monkeypatch.setattr(cache, "get", lambda key: {"price": price, "change_pct": 0})


async def test_alert_on_held_position_triggers(db, monkeypatch):
    user = await _make_user(db)
    await _make_position(db, user, ticker="ANET", shares="10")
    alert = await _make_alert(db, user, ticker="ANET")
    _fake_price(monkeypatch)

    triggered = await check_price_alerts(db)

    assert len(triggered) == 1
    assert triggered[0]["ticker"] == "ANET"
    await db.refresh(alert)
    assert alert.is_triggered is True


async def test_alert_on_watchlist_only_triggers(db, monkeypatch):
    user = await _make_user(db)
    db.add(WatchlistItem(user_id=user.id, ticker="ANET", name="Arista"))
    await db.commit()
    alert = await _make_alert(db, user, ticker="ANET")
    _fake_price(monkeypatch)

    triggered = await check_price_alerts(db)

    assert len(triggered) == 1
    await db.refresh(alert)
    assert alert.is_triggered is True


async def test_orphaned_alert_is_deactivated_not_triggered(db, monkeypatch):
    user = await _make_user(db)
    alert = await _make_alert(db, user, ticker="ANET")
    _fake_price(monkeypatch)

    triggered = await check_price_alerts(db)

    assert triggered == []
    await db.refresh(alert)
    assert alert.is_active is False
    assert alert.is_triggered is False
    assert alert.triggered_at is None


async def test_alert_on_sold_to_zero_position_is_deactivated(db, monkeypatch):
    user = await _make_user(db)
    await _make_position(db, user, ticker="ANET", shares="0")
    alert = await _make_alert(db, user, ticker="ANET")
    _fake_price(monkeypatch)

    triggered = await check_price_alerts(db)

    assert triggered == []
    await db.refresh(alert)
    assert alert.is_active is False
    assert alert.is_triggered is False


async def test_guard_is_user_scoped(db, monkeypatch):
    """User A haelt ANET, User B nicht — nur Bs Alert wird deaktiviert."""
    user_a = await _make_user(db)
    user_b = await _make_user(db)
    await _make_position(db, user_a, ticker="ANET", shares="5")
    alert_a = await _make_alert(db, user_a, ticker="ANET")
    alert_b = await _make_alert(db, user_b, ticker="ANET")
    _fake_price(monkeypatch)

    triggered = await check_price_alerts(db)

    assert [t["id"] for t in triggered] == [str(alert_a.id)]
    await db.refresh(alert_b)
    assert alert_b.is_active is False
