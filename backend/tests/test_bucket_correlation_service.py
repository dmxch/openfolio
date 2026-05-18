"""Tests fuer services/bucket_correlation_service.py.

Coverage:
  - 2 perfekt korrelierte Buckets -> 1.0
  - Anti-korrelierte Buckets -> ~-1.0
  - PE/RE/Pension System-Buckets ausgeschlossen
  - Cashflow-Adjustment: gleiche Return-Serie mit + ohne Cashflow == perfekt korreliert
  - Fehler bei < 2 Buckets oder < 20 gemeinsamen Tagen
"""
from __future__ import annotations

import math
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from models.bucket import BucketSnapshot, BucketSystemRole
from models.user import User, UserSettings
from services.bucket_correlation_service import compute_bucket_correlation_matrix
from services.bucket_service import create_bucket, create_system_buckets

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


async def _add_snapshot(db, user_id, bucket_id, *, d, value, cf=0.0, peak=None):
    db.add(BucketSnapshot(
        user_id=user_id,
        bucket_id=bucket_id,
        date=d,
        total_value_chf=Decimal(str(value)),
        cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal(str(cf)),
        running_peak_chf=Decimal(str(peak if peak is not None else value)),
    ))


async def _seed_snapshots(db, user_id, bucket_id, *, start: date, values: list[float], cfs: list[float] | None = None):
    cfs = cfs or [0.0] * len(values)
    for i, v in enumerate(values):
        await _add_snapshot(db, user_id, bucket_id, d=start + timedelta(days=i), value=v, cf=cfs[i])
    await db.commit()


def _varied_returns(n: int, amplitude: float = 0.01) -> list[float]:
    """Sine-basierte tägliche Returns mit nicht-trivialer Varianz."""
    return [amplitude * math.sin(i * 0.5) + 0.001 for i in range(n)]


def _values_from_returns(start: float, daily_returns: list[float], cashflows: list[float] | None = None) -> list[float]:
    """V[t] = V[t-1] * (1 + r[t]) + cf[t]. Erster Wert = `start`, t=0 hat keinen Return."""
    cashflows = cashflows or [0.0] * len(daily_returns)
    out = [start]
    for i, r in enumerate(daily_returns):
        out.append(out[-1] * (1.0 + r) + cashflows[i])
    return out


# ---------- Happy path ------------------------------------------------------

async def test_two_buckets_perfectly_correlated_returns_one(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()

    start = date.today() - timedelta(days=30)
    rets = _varied_returns(30)
    vals = _values_from_returns(1000.0, rets)
    # 31 values, 30 returns. Snapshots starten an `start`, gehen 31 Tage.
    await _seed_snapshots(db, user.id, a.id, start=start, values=vals)
    await _seed_snapshots(db, user.id, b.id, start=start, values=vals)

    result = await compute_bucket_correlation_matrix(db, user.id, period="90d")

    names = {b["name"] for b in result["buckets"]}
    assert {"A", "B"} <= names
    assert result["observations"] >= 20
    assert result["matrix"][0][0] == pytest.approx(1.0)
    # Off-diagonale fuer A/B == 1
    idx_a = next(i for i, b in enumerate(result["buckets"]) if b["name"] == "A")
    idx_b = next(i for i, b in enumerate(result["buckets"]) if b["name"] == "B")
    assert result["matrix"][idx_a][idx_b] == pytest.approx(1.0, abs=1e-6)
    # Mindestens ein high_correlations-Eintrag fuer A/B
    assert any(
        {p["bucket_a_name"], p["bucket_b_name"]} == {"A", "B"}
        for p in result["high_correlations"]
    )


async def test_anti_correlated_buckets_return_negative_one(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="Up")
    b = await create_bucket(db, user.id, name="Down")
    await db.commit()

    start = date.today() - timedelta(days=30)
    rets_a = _varied_returns(30)
    rets_b = [-r for r in rets_a]
    vals_a = _values_from_returns(1000.0, rets_a)
    vals_b = _values_from_returns(1000.0, rets_b)
    await _seed_snapshots(db, user.id, a.id, start=start, values=vals_a)
    await _seed_snapshots(db, user.id, b.id, start=start, values=vals_b)

    result = await compute_bucket_correlation_matrix(db, user.id, period="90d")
    idx_a = next(i for i, b in enumerate(result["buckets"]) if b["name"] == "Up")
    idx_b = next(i for i, b in enumerate(result["buckets"]) if b["name"] == "Down")
    assert result["matrix"][idx_a][idx_b] == pytest.approx(-1.0, abs=1e-3)
    assert any(p["correlation"] < -0.7 for p in result["high_correlations"])


# ---------- Excludes --------------------------------------------------------

async def test_system_buckets_pe_re_pension_excluded(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()

    start = date.today() - timedelta(days=30)
    rets = _varied_returns(30)
    vals = _values_from_returns(1000.0, rets)
    await _seed_snapshots(db, user.id, a.id, start=start, values=vals)
    await _seed_snapshots(db, user.id, b.id, start=start, values=vals)

    # PE/RE/Pension bekommen Snapshots — duerfen nicht in der Matrix erscheinen
    from sqlalchemy import select
    from models.bucket import Bucket
    sys_q = await db.execute(
        select(Bucket).where(
            Bucket.user_id == user.id,
            Bucket.system_role.in_([
                BucketSystemRole.real_estate,
                BucketSystemRole.private_equity,
                BucketSystemRole.pension,
            ]),
        )
    )
    for sys_b in sys_q.scalars().all():
        await _seed_snapshots(db, user.id, sys_b.id, start=start, values=vals)

    result = await compute_bucket_correlation_matrix(db, user.id, period="90d")
    names = {b["name"] for b in result["buckets"]}
    assert "Immobilien" not in names
    assert "Private Equity" not in names
    assert "Vorsorge" not in names
    # liquid_default hat keine Snapshots -> faellt raus. Nur A + B uebrig.
    assert names == {"A", "B"}


# ---------- Cashflow-Adjustment ---------------------------------------------

async def test_cashflow_neutralizes_value_jump(db):
    """Bucket A und B haben identische Returns. B bekommt zusätzlich an Tag 10
    einen Cashflow von +500. TWR-bereinigt sind beide perfekt korreliert.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()

    start = date.today() - timedelta(days=30)
    rets = _varied_returns(30)
    cfs = [0.0] * 30
    cfs[10] = 500.0
    vals_a = _values_from_returns(1000.0, rets)
    vals_b = _values_from_returns(1000.0, rets, cashflows=cfs)
    cf_snaps_b = [0.0] + cfs  # ein Eintrag mehr als rets

    await _seed_snapshots(db, user.id, a.id, start=start, values=vals_a)
    await _seed_snapshots(db, user.id, b.id, start=start, values=vals_b, cfs=cf_snaps_b)

    result = await compute_bucket_correlation_matrix(db, user.id, period="90d")
    idx_a = next(i for i, b in enumerate(result["buckets"]) if b["name"] == "A")
    idx_b = next(i for i, b in enumerate(result["buckets"]) if b["name"] == "B")
    assert result["matrix"][idx_a][idx_b] == pytest.approx(1.0, abs=1e-6)


# ---------- Error paths -----------------------------------------------------

async def test_less_than_two_buckets_raises(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)  # nur System-Buckets — PE/RE/Pension out, liquid_default = 1
    await db.commit()

    with pytest.raises(ValueError, match="Mindestens 2"):
        await compute_bucket_correlation_matrix(db, user.id, period="30d")


async def test_insufficient_history_raises(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    a = await create_bucket(db, user.id, name="A")
    b = await create_bucket(db, user.id, name="B")
    await db.commit()

    # Nur 5 Tage — < 20 Mindestbeobachtungen
    start = date.today() - timedelta(days=5)
    short_rets = _varied_returns(5)
    short_vals = _values_from_returns(1000.0, short_rets)
    await _seed_snapshots(db, user.id, a.id, start=start, values=short_vals)
    await _seed_snapshots(db, user.id, b.id, start=start, values=short_vals)

    with pytest.raises(ValueError, match="Unzureichende"):
        await compute_bucket_correlation_matrix(db, user.id, period="30d")


async def test_unknown_period_raises(db):
    user = await _make_user(db)
    with pytest.raises(ValueError, match="Unbekannter Zeitraum"):
        await compute_bucket_correlation_matrix(db, user.id, period="quartal")
