"""Tests fuer services/bucket_performance_service.py.

Coverage:
  - get_bucket_summary: total_value/cost_basis aus Snapshots + Positionen
  - get_bucket_history: Period-Filter + Reihenfolge
  - get_bucket_monthly_returns: cashflow-bereinigte Monatsrendite + Annual
  - compare_to_benchmark: TWR-Formel (V_end - cf_sum)/V_start - 1,
    Benchmark-Allowlist (Defense-in-Depth fuer Audit H-1)
  - get_bucket_cashflows: INFLOW/OUTFLOW-Aggregat ueber Position->Bucket
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from models.bucket import BucketSnapshot
from models.position import AssetType, Position, PricingMode, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_performance_service import (
    compare_to_benchmark,
    get_bucket_cashflows,
    get_bucket_history,
    get_bucket_monthly_returns,
    get_bucket_summary,
)
from services.bucket_service import create_bucket, create_system_buckets

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(
        email=f"u{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
    )
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


async def _make_position(db, user, *, bucket_id, ticker="AAPL", shares=10, cb=1000, price=100):
    pos = Position(
        user_id=user.id,
        bucket_id=bucket_id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="CHF",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal(str(shares)),
        cost_basis_chf=Decimal(str(cb)),
        current_price=Decimal(str(price)),
    )
    db.add(pos)
    await db.commit()
    return pos


async def _add_snapshot(db, user, bucket_id, *, d: date, value: float, peak: float, cf: float = 0.0):
    db.add(BucketSnapshot(
        user_id=user.id,
        bucket_id=bucket_id,
        date=d,
        total_value_chf=Decimal(str(value)),
        cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal(str(cf)),
        running_peak_chf=Decimal(str(peak)),
    ))
    await db.commit()


# ---------- get_bucket_summary ----------------------------------------------

async def test_summary_uses_snapshot_value_when_available(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    await _make_position(db, user, bucket_id=bucket.id, cb=1000, shares=10, price=100)
    # Snapshot ueberschreibt position-basierten Wert
    await _add_snapshot(db, user, bucket.id, d=date.today(), value=1500, peak=1500)

    summary = await get_bucket_summary(db, user.id, bucket.id)
    assert summary["total_value_chf"] == 1500.0
    assert summary["cost_basis_chf"] == 1000.0
    assert summary["unrealized_pnl_chf"] == 500.0
    assert summary["unrealized_pnl_pct"] == 50.0
    assert summary["position_count"] == 1
    assert summary["running_peak_chf"] == 1500.0


async def test_summary_returns_empty_for_unknown_bucket(db):
    user = await _make_user(db)
    res = await get_bucket_summary(db, user.id, uuid.uuid4())
    assert res == {}


# ---------- get_bucket_history ----------------------------------------------

async def test_history_filters_period_ytd(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Hist")
    await db.commit()
    today = date.today()
    last_year_dec = date(today.year - 1, 12, 15)
    this_year_jan = date(today.year, 1, 15)
    await _add_snapshot(db, user, bucket.id, d=last_year_dec, value=900, peak=900)
    await _add_snapshot(db, user, bucket.id, d=this_year_jan, value=1100, peak=1100)
    rows = await get_bucket_history(db, user.id, bucket.id, period="ytd")
    # YTD-Filter schneidet 2024-12 ab
    assert len(rows) == 1
    assert rows[0]["date"] == this_year_jan.isoformat()


async def test_history_unknown_period_raises(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="X")
    await db.commit()
    with pytest.raises(ValueError):
        await get_bucket_history(db, user.id, bucket.id, period="quartal")


# ---------- get_bucket_monthly_returns --------------------------------------

async def test_monthly_returns_cashflow_adjusted(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="M")
    await db.commit()
    # Monat 1: End-Wert 1000, kein Cashflow
    # Monat 2: End-Wert 1200, Cashflow Mitte Monat +100 → echte Rendite = (1200-100)/1000-1 = 10%
    await _add_snapshot(db, user, bucket.id, d=date(2025, 1, 31), value=1000, peak=1000, cf=0)
    # Cashflow-Snapshot in der Mitte Monat 2:
    await _add_snapshot(db, user, bucket.id, d=date(2025, 2, 15), value=1100, peak=1100, cf=100)
    await _add_snapshot(db, user, bucket.id, d=date(2025, 2, 28), value=1200, peak=1200, cf=0)
    result = await get_bucket_monthly_returns(db, user.id, bucket.id)
    months = result["months"]
    assert len(months) == 1
    feb = months[0]
    assert feb["year"] == 2025
    assert feb["month"] == 2
    # cf_sum = 100 → (1200-100)/1000-1 = 0.10 = 10.0%
    assert feb["return_pct"] == 10.0
    assert result["annual_totals"][2025] == 10.0


async def test_monthly_returns_empty_when_no_snapshots(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Empty")
    await db.commit()
    res = await get_bucket_monthly_returns(db, user.id, bucket.id)
    assert res == {"months": [], "annual_totals": {}}


# ---------- compare_to_benchmark --------------------------------------------

async def test_compare_to_benchmark_twr_formula(db):
    """Verifiziert die TWR-Formel: (V_end - cf_sum) / V_start - 1.

    Snapshots:
      Tag 1: V=1000, cf=0      (V_start)
      Tag 2: V=1100, cf=+50    (zwischendurch, cf wird in cf_sum gezaehlt)
      Tag 3: V=1200, cf=0      (V_end)
    Erwartete TWR-Rendite: (1200 - 50) / 1000 - 1 = 0.15 = 15.0%
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="TWR", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=3), value=1000, peak=1000, cf=0)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=2), value=1100, peak=1100, cf=50)
    await _add_snapshot(db, user, bucket.id, d=today, value=1200, peak=1200, cf=0)
    # benchmark_service.get_benchmark_monthly_returns wird via
    # asyncio.to_thread aufgerufen. Wir mocken die Source-Funktion → bleibt
    # synchron und to_thread liefert das Mock-Result zurueck.
    with patch(
        "services.benchmark_service.get_benchmark_monthly_returns",
        return_value={
            "months": [],
            "annual_totals": {},
            "ticker": "^GSPC",
            "name": "S&P 500",
        },
    ):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    assert result["bucket_return_pct"] == 15.0
    assert result["benchmark_ticker"] == "^GSPC"
    assert result["benchmark_name"] == "S&P 500"


async def test_compare_to_benchmark_disallowed_ticker_returns_no_benchmark_data(db):
    """Defense-in-Depth (Audit H-1): wenn ein Altbestand-Bucket einen
    Benchmark hat, der nicht in ALLOWED_BENCHMARKS steht, wird kein
    yfinance-Call abgesetzt — benchmark_return_pct bleibt None.
    """
    from unittest.mock import MagicMock

    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Bad")
    # Allowlist umgehen: Direct-DB-Write (simuliert Altbestand)
    bucket.benchmark = "EVIL.TICKER"
    await db.commit()
    today = date.today()
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=2), value=1000, peak=1000)
    await _add_snapshot(db, user, bucket.id, d=today, value=1100, peak=1100)
    mock_yf = MagicMock()
    with patch("services.benchmark_service.get_benchmark_monthly_returns", new=mock_yf):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    assert result["benchmark_return_pct"] is None
    assert result["benchmark_ticker"] == "EVIL.TICKER"
    # Wichtig: yfinance darf NICHT angefasst worden sein
    mock_yf.assert_not_called()


async def test_compare_to_benchmark_unknown_period_raises(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="X")
    await db.commit()
    with pytest.raises(ValueError):
        await compare_to_benchmark(db, user.id, bucket.id, period="quartal")


async def test_compare_to_benchmark_unknown_bucket_returns_empty(db):
    user = await _make_user(db)
    res = await compare_to_benchmark(db, user.id, uuid.uuid4(), period="ytd")
    assert res == {}


# ---------- get_bucket_cashflows --------------------------------------------

async def test_cashflows_sum_inflows_minus_outflows(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="CF")
    await db.commit()
    pos = await _make_position(db, user, bucket_id=bucket.id)
    today = date.today()
    db.add(Transaction(
        user_id=user.id,
        position_id=pos.id,
        date=today,
        type=TransactionType.buy,
        shares=Decimal("5"),
        price_per_share=Decimal("100"),
        total_chf=Decimal("500"),
        fees_chf=Decimal("0"),
    ))
    db.add(Transaction(
        user_id=user.id,
        position_id=pos.id,
        date=today,
        type=TransactionType.sell,
        shares=Decimal("2"),
        price_per_share=Decimal("110"),
        total_chf=Decimal("220"),
        fees_chf=Decimal("0"),
    ))
    await db.commit()
    res = await get_bucket_cashflows(db, user.id, bucket.id)
    # buy=Inflow(+500), sell=Outflow(-220) → 280
    assert res["net_cash_flow_chf"] == 280.0
