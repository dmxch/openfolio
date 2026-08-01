"""Tests fuer die CHF-Umrechnung der Benchmark-Kurve in history_service.

Regression (Prod-Befund 1.8.2026, gleiche Klasse wie benchmark_service): Die
Portfolio-Reihe ist CHF, die Benchmark-Kurve stand in Notierungswaehrung. Im
Chart lagen beide uebereinander ("vs. S&P 500"), und
``risk_metrics_service`` leitet Information Ratio, Tracking Error sowie
``benchmark_annualized_return_pct`` aus genau dieser Reihe ab — eine
Waehrungsbewegung von 3 % verschob die aktive Rendite um rund 3 pp und konnte
das IR-Vorzeichen kippen.

Aufbau: eine CHF-Position mit konstantem Kurs (Portfolio flach) und ein
Benchmark mit konstantem Kurs in USD, waehrend USD/CHF um 10 % steigt. Die
Benchmark-Kurve MUSS diese 10 % zeigen — ohne Umrechnung waere sie flach.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.history_service import get_portfolio_history

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


async def _chf_position(db, user, bucket, d0):
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="NESN.SW",
        name="Nestle", type=AssetType.stock, currency="CHF",
        shares=Decimal("100"), cost_basis_chf=Decimal("10000"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    db.add(Transaction(
        user_id=user.id, position_id=pos.id, type=TransactionType.buy,
        date=d0, shares=Decimal("100"), price_per_share=Decimal("100"),
        currency="CHF", total_chf=Decimal("10000"),
    ))
    await db.commit()
    return pos


def _fake_yf_factory(cal, fx_series):
    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            if t == "USDCHF=X":
                cols[("Close", t)] = fx_series
            elif t == "NESN.SW":
                cols[("Close", t)] = np.full(len(cal), 100.0)
            else:  # Benchmark: konstant in USD
                cols[("Close", t)] = np.full(len(cal), 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df
    return fake_yf


async def test_benchmark_curve_is_converted_to_chf(db, monkeypatch):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    await _chf_position(db, user, bucket, d0)

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")
    # USD/CHF steigt in der Mitte des Fensters von 0.80 auf 0.88 (+10 %).
    half = len(cal) // 2
    fx = np.concatenate([np.full(half, 0.80), np.full(len(cal) - half, 0.88)])

    monkeypatch.setattr("services.history_service.yf_download", _fake_yf_factory(cal, fx))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"USD": 0.88})
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "CHF")
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "USD"
    )

    hist = await get_portfolio_history(db, d0, today, user_id=user.id)
    points = hist.get("data", [])
    assert points, "keine Datenpunkte"

    # Benchmark konstant in USD, USD/CHF +10 % → CHF-Kurve +10 %.
    assert hist["summary"]["benchmark_return_pct"] == pytest.approx(10.0, abs=0.1), (
        "Benchmark-Kurve nicht in CHF — ohne Umrechnung waere sie flach (0 %)"
    )
    assert points[-1]["benchmark"] == pytest.approx(5000 * 0.88, rel=0.001)
    # Portfolio selbst bleibt flach (CHF-Position, konstanter Kurs).
    assert hist["summary"]["return_pct"] == pytest.approx(0.0, abs=0.1)


async def test_benchmark_omitted_when_currency_unknown(db, monkeypatch):
    """Unbekannte Notierungswaehrung → gar keine Benchmark-Kurve.

    Eine fehlende Kurve faellt im Chart auf, eine waehrungsgemischte nicht.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    await _chf_position(db, user, bucket, d0)

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")
    fx = np.full(len(cal), 0.88)

    monkeypatch.setattr("services.history_service.yf_download", _fake_yf_factory(cal, fx))
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"USD": 0.88})
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "CHF")
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: None
    )

    hist = await get_portfolio_history(db, d0, today, user_id=user.id)
    points = hist.get("data", [])
    assert points, "keine Datenpunkte"
    assert all("benchmark" not in p for p in points)
    assert "benchmark_return_pct" not in hist["summary"]
