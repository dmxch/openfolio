"""Tests fuer services/bucket_consistency_service.py.

Toleranz max(±1 CHF absolut, ±0.05% relativ) — strenger waere False-Positives
durch FX-Rundung produzieren.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from models.bucket import BucketSnapshot
from models.portfolio_snapshot import PortfolioSnapshot
from models.user import User, UserSettings
from services.bucket_consistency_service import (
    ABSOLUTE_TOLERANCE_CHF,
    RELATIVE_TOLERANCE_PCT,
    _within_tolerance,
    check_user_consistency,
)
from services.bucket_service import create_bucket, create_system_buckets

pytestmark = pytest.mark.asyncio


def test_within_tolerance_absolute_boundary():
    # diff 1.00 darf nicht ausserhalb sein
    assert _within_tolerance(1000.0, 1001.0) is True
    assert _within_tolerance(1000.0, 999.0) is True
    assert _within_tolerance(1000.0, 1001.5) is False  # 1.50 > 1 absolute, 0.15% > 0.05%


def test_within_tolerance_relative_kicks_in_at_high_values():
    # Bei grossen Werten zaehlt die relative Toleranz
    assert _within_tolerance(100_000.0, 100_049.0) is True   # 0.049% < 0.05%
    assert _within_tolerance(100_000.0, 100_100.0) is False  # 0.1% > 0.05%


def test_within_tolerance_zero_portfolio():
    # Bei 0 Portfolio: absolute Toleranz reicht (verhindert div-by-zero)
    assert _within_tolerance(0.0, 0.5) is True
    assert _within_tolerance(0.0, 1.5) is False


async def _make_user(db):
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    return user


async def test_consistency_passes_when_sums_match(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    b1 = await create_bucket(db, user.id, name="A")
    b2 = await create_bucket(db, user.id, name="B")
    await db.commit()

    today = date.today()
    db.add(PortfolioSnapshot(
        user_id=user.id, date=today, total_value_chf=Decimal("1000.00"),
        cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
    ))
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=b1.id, date=today,
        total_value_chf=Decimal("600.00"), cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal("0"), running_peak_chf=Decimal("600"),
    ))
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=b2.id, date=today,
        total_value_chf=Decimal("400.00"), cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal("0"), running_peak_chf=Decimal("400"),
    ))
    await db.commit()

    mismatches = await check_user_consistency(db, user.id, days=7)
    assert mismatches == []


async def test_consistency_flags_diff_above_tolerance(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    b1 = await create_bucket(db, user.id, name="A")
    await db.commit()

    today = date.today()
    db.add(PortfolioSnapshot(
        user_id=user.id, date=today, total_value_chf=Decimal("1000.00"),
        cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
    ))
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=b1.id, date=today,
        total_value_chf=Decimal("900.00"), cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal("0"), running_peak_chf=Decimal("900"),
    ))
    await db.commit()

    mismatches = await check_user_consistency(db, user.id, days=7)
    assert len(mismatches) == 1
    assert mismatches[0]["diff_chf"] == 100.0


async def test_consistency_tolerates_fx_rounding(db):
    """Rundungsdifferenzen ±0.50 CHF werden NICHT als Mismatch gemeldet."""
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    b1 = await create_bucket(db, user.id, name="A")
    await db.commit()

    today = date.today()
    db.add(PortfolioSnapshot(
        user_id=user.id, date=today, total_value_chf=Decimal("12345.67"),
        cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
    ))
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=b1.id, date=today,
        total_value_chf=Decimal("12345.17"),  # 0.50 CHF Differenz
        cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
        running_peak_chf=Decimal("12345.17"),
    ))
    await db.commit()
    mismatches = await check_user_consistency(db, user.id, days=7)
    assert mismatches == []
