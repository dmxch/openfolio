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
from models.precious_metal_item import GRAMS_PER_TROY_OZ, PreciousMetalItem
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


async def test_real_estate_excluded_from_history(db, monkeypatch):
    """Invariante #2 (Guard seit 28.6.): real_estate ist komplett aus
    /performance/history (portfolio_indexed) ausgeschlossen. Eine no-txn
    real_estate-Position mit cost_basis>0 wuerde ohne Guard als statischer Wert
    in die rekonstruierte Reihe lecken (static_positions-Pfad) — hier gepinnt,
    dass nur die liquide Aktie zaehlt."""
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    # Liquide Aktie — liefert die Reihe.
    stock = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="AAA", name="Aktie",
        type=AssetType.stock, currency="CHF",
        shares=Decimal("10"), cost_basis_chf=Decimal("1000"), is_active=True,
    )
    db.add(stock)
    await db.commit()
    await db.refresh(stock)
    db.add(Transaction(
        user_id=user.id, position_id=stock.id, type=TransactionType.buy,
        date=d0, shares=Decimal("10"), price_per_share=Decimal("100"),
        currency="CHF", total_chf=Decimal("1000"),
    ))
    # Immobilie ohne Txn, cost_basis>0 → wuerde ohne Guard als static value lecken.
    re = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="HAUS", name="Eigenheim",
        type=AssetType.real_estate, currency="CHF",
        shares=Decimal("0"), cost_basis_chf=Decimal("500000"), is_active=True,
    )
    db.add(re)
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            cols[("Close", t)] = np.full(len(cal), 100.0 if t == "AAA" else 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "CHF")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id)
    points = hist.get("data", [])
    assert points
    # 10 × 100 CHF = 1000 (nur Aktie). Die Immobilie (cost_basis 500'000) ist excluded.
    last = points[-1]["value"]
    assert last == pytest.approx(1000.0, rel=0.02), f"erwartet ~1000 (nur Aktie), war {last}"
    assert last < 10_000, "real_estate cost_basis ist in die History geleckt!"


async def test_transaction_less_gold_marked_not_flat(db, monkeypatch):
    """Regression: Edelmetalle (gold_org) werden aus precious_metal_items gesynct
    und haben KEINE Transaktionen. Frueher landeten sie im static_positions-Pfad
    und wurden mit konstantem cost_basis emittiert -> flache Reihe (Vola 0,
    degenerierte Risiko-/Faktor-/Drawdown-Kennzahlen). Erwartung jetzt: ueber die
    Futures-Mapping (XAUCHF=X -> GC=F × USDCHF) taeglich markiert, Reihe variiert."""
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="HardMoney", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)

    # Physisches Gold: 10 Unzen, cost_basis 18'000 CHF, KEINE Transaktion.
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="XAUCHF=X",
        name="Gold (physisch)", type=AssetType.commodity, currency="CHF",
        gold_org=True, shares=Decimal("10"), cost_basis_chf=Decimal("18000"),
        is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    # 10 oz, gekauft VOR dem Fenster -> ueber das ganze Fenster gehalten + markiert.
    db.add(PreciousMetalItem(
        user_id=user.id, position_id=pos.id, metal_type="gold", form="bar",
        weight_grams=Decimal(str(10 * GRAMS_PER_TROY_OZ)),
        purchase_date=d0 - timedelta(days=10), purchase_price_chf=Decimal("18000"),
        is_sold=False,
    ))
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            if t == "GC=F":
                cols[("Close", t)] = np.linspace(2000.0, 2100.0, len(cal))  # USD/oz, steigend
            elif t == "USDCHF=X":
                cols[("Close", t)] = np.full(len(cal), 0.90)
            else:  # benchmark u.a.
                cols[("Close", t)] = np.full(len(cal), 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"USD": 0.90})
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "USD")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id, liquid=True)
    points = hist.get("data", [])
    assert points, "keine Datenpunkte"

    values = [p["value"] for p in points]
    # Markiert, NICHT flach auf cost_basis 18'000.
    assert max(values) - min(values) > 100, f"Reihe ist flach: {values[:3]}..."
    # Letzter Tag: 10 oz × 2100 USD × 0.90 = 18'900 CHF (Futures-marked, ≠ 18'000 cost_basis).
    assert points[-1]["value"] == pytest.approx(18900.0, rel=0.01), points[-1]["value"]
    assert abs(points[-1]["value"] - 18000.0) > 100, "noch auf cost_basis eingefroren"
    # Performance-Index hat sich bewegt (nicht konstant 100).
    assert points[-1]["portfolio_indexed"] != pytest.approx(100.0, abs=0.5)


async def test_gold_anchored_to_purchase_date_no_phantom(db, monkeypatch):
    """Adversarial-Review-Fix: das Edelmetall darf NICHT mit der aktuellen Menge ab
    Fensterstart gehalten werden (sonst Phantom-Rendite vor dem Kauf). Pro Item ein
    synthetischer holdings_change am echten purchase_date -> vor dem Kauf 0, danach
    markiert. Hier: Kauf in der Fenstermitte -> Reihe beginnt erst am Kauftag."""
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="HardMoney", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=20)
    buy_date = today - timedelta(days=10)

    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="XAUCHF=X",
        name="Gold (physisch)", type=AssetType.commodity, currency="CHF",
        gold_org=True, shares=Decimal("10"), cost_basis_chf=Decimal("18000"),
        is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    db.add(PreciousMetalItem(
        user_id=user.id, position_id=pos.id, metal_type="gold", form="bar",
        weight_grams=Decimal(str(10 * GRAMS_PER_TROY_OZ)),
        purchase_date=buy_date, purchase_price_chf=Decimal("18000"),
        is_sold=False,
    ))
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            if t == "GC=F":
                cols[("Close", t)] = np.linspace(2000.0, 2100.0, len(cal))
            elif t == "USDCHF=X":
                cols[("Close", t)] = np.full(len(cal), 0.90)
            else:
                cols[("Close", t)] = np.full(len(cal), 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"USD": 0.90})
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "USD")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id, liquid=True)
    points = hist.get("data", [])
    assert points, "keine Datenpunkte"

    # KEIN Datenpunkt vor dem Kaufdatum (vor Kauf 0 Bestand -> kein Wert).
    dates = [p["date"] for p in points]
    assert min(dates) >= buy_date.isoformat(), f"Phantom-Vorlauf vor Kauf: {min(dates)}"
    assert points[0]["date"] == buy_date.isoformat()
    # Letzter Tag markiert: 10 oz × 2100 × 0.90 = 18'900 CHF.
    assert points[-1]["value"] == pytest.approx(18900.0, rel=0.02)


async def test_index_survives_empty_gap_no_collapse(db, monkeypatch):
    """Regression (Prod-Bug Core-Bucket): wird ein Bucket/Portfolio zwischenzeitlich
    komplett verkauft (Wert 0, keine Punkte aufgezeichnet) und kommt spaeter zurueck,
    darf der cash-flow-bereinigte portfolio_indexed NICHT auf 0 kollabieren — sonst
    falsches -100% in Drawdown/Rolling/Equity, auch nachdem wieder Positionen da sind.
    Der Verkauf ist ein Cashflow, kein -100%-Markt-Verlust."""
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    today = date.today()
    d0 = today - timedelta(days=120)
    d_sell = today - timedelta(days=80)
    d_rebuy = today - timedelta(days=20)

    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="AAA", name="Aktie",
        type=AssetType.stock, currency="CHF",
        shares=Decimal("5"), cost_basis_chf=Decimal("600"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    # Kauf -> Verkauf (Bucket vollstaendig leer) -> Wiederkauf
    db.add(Transaction(user_id=user.id, position_id=pos.id, type=TransactionType.buy,
                       date=d0, shares=Decimal("10"), price_per_share=Decimal("100"),
                       currency="CHF", total_chf=Decimal("1000")))
    db.add(Transaction(user_id=user.id, position_id=pos.id, type=TransactionType.sell,
                       date=d_sell, shares=Decimal("10"), price_per_share=Decimal("100"),
                       currency="CHF", total_chf=Decimal("1000")))
    db.add(Transaction(user_id=user.id, position_id=pos.id, type=TransactionType.buy,
                       date=d_rebuy, shares=Decimal("5"), price_per_share=Decimal("100"),
                       currency="CHF", total_chf=Decimal("500")))
    await db.commit()

    cal = pd.date_range(d0 - timedelta(days=5), today, freq="D")

    def fake_yf(all_tickers, **k):
        cols = {}
        for t in all_tickers:
            cols[("Close", t)] = np.full(len(cal), 100.0 if t == "AAA" else 5000.0)
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("services.history_service.yf_download", fake_yf)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "CHF")

    hist = await get_portfolio_history(db, d0, today, user_id=user.id)
    pts = hist.get("data", [])
    assert pts, "keine Datenpunkte"
    # KEIN Punkt darf portfolio_indexed == 0 haben (Kollaps-Schutz).
    zeros = [p for p in pts if p["portfolio_indexed"] == 0]
    assert not zeros, f"Index kollabiert auf 0 bei {[p['date'] for p in zeros][:3]}"
    # Nach dem Wiedereinstieg traegt der Index den Vorlauf-Stand weiter (~100, > 0).
    assert pts[-1]["portfolio_indexed"] == pytest.approx(100.0, abs=0.5)
