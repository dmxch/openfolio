"""Test fuer die LSE-Pence-Korrektur in history_service.

Regression: yfinance quotiert viele London-.L-Titel in Pence (GBp). Ohne ÷100
blies die historische Wert-Rekonstruktion (/performance/history, Faktor-
Decomposition, Bucket-Drawdown) Pence-.L-Haltefenster auf das ~100-fache auf
(realer Prod-Bug: Buch sprang in .L-Haltefenstern auf 0.8-4M statt ~0.3M).

Hier: eine SWDA.L-Position (yfinance liefert Pence), mit absichtlich falscher
pos.currency='USD'. Erwartung: Wert in CHF ueber GBP-FX und durch 100 geteilt,
NICHT 100x ueberhoeht.
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


async def test_pence_lse_value_divided_by_100(db, monkeypatch):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    # SWDA.L: yfinance quotiert in Pence; pos.currency hier absichtlich 'USD'
    # (so wie es bei Import-Altbestand vorkommt) → muss auf GBP korrigiert werden.
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="SWDA.L",
        name="iShares Core MSCI World",
        type=AssetType.etf, currency="USD",
        shares=Decimal("100"), cost_basis_chf=Decimal("9000"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    db.add(Transaction(
        user_id=user.id, position_id=pos.id, type=TransactionType.buy,
        date=d0, shares=Decimal("100"), price_per_share=Decimal("90"),
        currency="GBP", total_chf=Decimal("9900"),
    ))
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            if t == "SWDA.L":
                cols[("Close", t)] = np.full(len(cal), 9000.0)  # Pence (= 90 GBP)
            elif t == "GBPCHF=X":
                cols[("Close", t)] = np.full(len(cal), 1.10)
            else:  # benchmark u.a.
                cols[("Close", t)] = np.full(len(cal), 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"GBP": 1.1})
    # yfinance fast_info als Pence melden → _pence_divisor=100, _resolved_currency='GBP'
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "GBp")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id)
    points = hist.get("data", [])
    assert points, "keine Datenpunkte"

    # 100 Aktien × (9000 Pence / 100 = 90 GBP) × 1.10 GBPCHF = 9900 CHF
    last_value = points[-1]["value"]
    assert last_value == pytest.approx(9900.0, rel=0.01), f"erwartet ~9900, war {last_value}"
    # Ohne Fix waere es ~990'000 (100x) — explizit ausschliessen.
    assert last_value < 50_000


async def test_usd_quoted_lse_not_divided(db, monkeypatch):
    """Gegenprobe: EIMI.L quotiert in USD, NICHT Pence → KEINE ÷100-Division.

    .L-Suffix sagt nichts ueber die Waehrung; nur GBp-Quotes werden geteilt.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="EIMI.L",
        name="iShares Core MSCI EM IMI",
        type=AssetType.etf, currency="USD",
        shares=Decimal("100"), cost_basis_chf=Decimal("4500"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    db.add(Transaction(
        user_id=user.id, position_id=pos.id, type=TransactionType.buy,
        date=d0, shares=Decimal("100"), price_per_share=Decimal("50"),
        currency="USD", total_chf=Decimal("4500"),
    ))
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            if t == "EIMI.L":
                cols[("Close", t)] = np.full(len(cal), 50.0)  # USD, KEIN Pence
            elif t == "USDCHF=X":
                cols[("Close", t)] = np.full(len(cal), 0.90)
            else:
                cols[("Close", t)] = np.full(len(cal), 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"USD": 0.9})
    # fast_info meldet USD → _pence_divisor=1.0, _resolved_currency='USD'
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "USD")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id)
    points = hist.get("data", [])
    assert points
    # 100 × 50 USD × 0.90 = 4500 CHF — NICHT durch 100 geteilt (waere 45 CHF)
    assert points[-1]["value"] == pytest.approx(4500.0, rel=0.01)
