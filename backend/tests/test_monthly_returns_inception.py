"""Test: Inception-Teiljahr wird aus den Portfolio-Monatsrenditen ausgeblendet.

Hintergrund: Das Jahres-Total nutzt XIRR mit start_value=0 fuer das Inception-
Jahr (kein Snapshot davor) und verbucht die statische Cash/Vorsorge-Baseline als
Phantom-Gewinn (Prod: 2023 zeigte +398 %). Das Inception-Teiljahr wird daher
ausgeblendet — aber nur, wenn weitere Jahre existieren (ein brandneuer User soll
sein erstes Teiljahr noch sehen).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.performance_history_service import get_monthly_returns

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


async def _seed(db, user, *, start: date, end: date):
    """Inception-Transaktion am `start` (Teiljahr, mitten im Jahr) + flache
    Monats-Snapshots bis `end` (Wert konstant → Dietz ~0 %)."""
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="STK", name="Test AG",
        type=AssetType.stock, currency="CHF",
        shares=Decimal("1"), cost_basis_chf=Decimal("100000"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    db.add(Transaction(
        user_id=user.id, position_id=pos.id, type=TransactionType.buy,
        date=start, shares=Decimal("1"), price_per_share=Decimal("100000"),
        currency="CHF", total_chf=Decimal("100000"),
    ))
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        db.add(PortfolioSnapshot(
            user_id=user.id, date=date(y, m, 15),
            total_value_chf=Decimal("100000"),
            cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
        ))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    await db.commit()


async def test_inception_partial_year_excluded_when_more_years_exist(db):
    """Start Juni 2023 (Teiljahr) + volles 2024 → 2023 ausgeblendet."""
    user = await _make_user(db)
    await _seed(db, user, start=date(2023, 6, 15), end=date(2024, 12, 15))
    res = await get_monthly_returns(db, user_id=user.id)
    months, annual = res["months"], res["annual_totals"]
    assert all(m["year"] != 2023 for m in months), "2023-Monate muessen weg sein"
    assert 2023 not in annual, "2023 darf kein Jahres-Total haben"
    assert any(m["year"] == 2024 for m in months)
    assert 2024 in annual


async def test_single_partial_inception_year_is_kept(db):
    """Nur ein Teiljahr (2023) → NICHT ausblenden, sonst saehe der neue User
    gar nichts."""
    user = await _make_user(db)
    await _seed(db, user, start=date(2023, 6, 15), end=date(2023, 12, 15))
    res = await get_monthly_returns(db, user_id=user.id)
    assert any(m["year"] == 2023 for m in res["months"])
