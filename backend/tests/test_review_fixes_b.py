"""Regressionstests Review 2026-07-02, Batch B (History/Snapshots).

- H1: Fremdwährungs-Cash/Vorsorge-Salden werden in der History-Rekonstruktion
  mit FX konvertiert (saldo × fx), wie Live- und Snapshot-Pfad — nicht 1:1
  als CHF gezählt.
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


async def test_h1_fx_cash_converted_in_history(db, monkeypatch):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    # USD-Konto: Saldo 100'000 USD liegt (Invariante) in cost_basis_chf.
    cash = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="USD Konto",
        name="USD Cash", type=AssetType.cash, currency="USD",
        shares=Decimal("0"), cost_basis_chf=Decimal("100000"), is_active=True,
    )
    # Plus eine kleine CHF-Aktienposition, damit die Reihe Preisdaten hat.
    stock = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="SREN.SW",
        name="Swiss Re", type=AssetType.stock, currency="CHF",
        shares=Decimal("10"), cost_basis_chf=Decimal("1000"), is_active=True,
    )
    db.add_all([cash, stock])
    await db.commit()
    await db.refresh(stock)
    db.add(Transaction(
        user_id=user.id, position_id=stock.id, type=TransactionType.buy,
        date=d0, shares=Decimal("10"), price_per_share=Decimal("100"),
        currency="CHF", total_chf=Decimal("1000"),
    ))
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            if t == "USDCHF=X":
                cols[("Close", t)] = np.full(len(cal), 0.88)
            elif t == "SREN.SW":
                cols[("Close", t)] = np.full(len(cal), 100.0)
            else:  # Benchmark u.a.
                cols[("Close", t)] = np.full(len(cal), 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr(
        "services.history_service.get_fx_rates_batch", lambda: {"USD": 0.88}
    )
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "CHF")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id, liquid=False)
    points = hist.get("data", [])
    assert points, "keine Datenpunkte"

    # 100'000 USD × 0.88 + 10 × 100 CHF = 89'000 — NICHT 101'000 (Saldo 1:1).
    last_value = points[-1]["value"]
    assert last_value == pytest.approx(89_000.0, rel=0.01), f"war {last_value}"
    assert last_value < 95_000  # ohne Fix: 101'000


async def test_h1_liquid_mode_still_excludes_cash(db, monkeypatch):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    cash = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="USD Konto",
        name="USD Cash", type=AssetType.cash, currency="USD",
        shares=Decimal("0"), cost_basis_chf=Decimal("100000"), is_active=True,
    )
    stock = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="SREN.SW",
        name="Swiss Re", type=AssetType.stock, currency="CHF",
        shares=Decimal("10"), cost_basis_chf=Decimal("1000"), is_active=True,
    )
    db.add_all([cash, stock])
    await db.commit()
    await db.refresh(stock)
    db.add(Transaction(
        user_id=user.id, position_id=stock.id, type=TransactionType.buy,
        date=d0, shares=Decimal("10"), price_per_share=Decimal("100"),
        currency="CHF", total_chf=Decimal("1000"),
    ))
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            if t == "USDCHF=X":
                cols[("Close", t)] = np.full(len(cal), 0.88)
            elif t == "SREN.SW":
                cols[("Close", t)] = np.full(len(cal), 100.0)
            else:
                cols[("Close", t)] = np.full(len(cal), 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr(
        "services.history_service.get_fx_rates_batch", lambda: {"USD": 0.88}
    )
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "CHF")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id, liquid=True)
    points = hist.get("data", [])
    assert points, "keine Datenpunkte"
    # Liquid-Sicht: nur die Aktienposition (1'000 CHF), kein Cash.
    assert points[-1]["value"] == pytest.approx(1_000.0, rel=0.01)
