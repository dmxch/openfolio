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
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from models.bucket import BucketSnapshot, PositionBucketHistory
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


async def _backdate_bucket(db, bucket, *, days_ago: int) -> None:
    """created_at vor die Snapshots setzen. Sonst klemmt compare_to_benchmark
    das Vergleichsfenster auf das (per default heutige) Erstellungsdatum und
    schliesst die backdateten Test-Snapshots aus."""
    bucket.created_at = datetime.combine(
        date.today() - timedelta(days=days_ago), datetime.min.time()
    )
    await db.commit()


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


async def _add_relabel(db, position_id, *, to_bucket_id, d: date, from_bucket_id=None):
    """Bucket-Wechsel-Eintrag (position_bucket_history) auf Datum d setzen.

    Spiegelt was move_position_to_bucket real schreibt: ein History-Eintrag,
    KEINE Transaction. Der zugehoerige bucket_snapshot springt also im Wert,
    aber net_cash_flow_chf bleibt 0."""
    db.add(PositionBucketHistory(
        position_id=position_id,
        from_bucket_id=from_bucket_id,
        to_bucket_id=to_bucket_id,
        changed_at=datetime.combine(d, datetime.min.time()),
        changed_by="user",
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
    # created_at vor die 2025-Snapshots, sonst klemmt der Inception-Filter alles weg.
    await _backdate_bucket(db, bucket, days_ago=500)
    # Monat 1 (Baseline): End-Wert 1000.
    # Monat 2: Cashflow Mitte Monat +100 → Tages-TWR neutralisiert den Inflow:
    #   1000 -> 1100 (cf +100): (1100-100)/1000 = 1.0 (0% Performance)
    #   1100 -> 1200 (cf 0):    1200/1100      = 1.0909 (+9.09%)
    #   Feb-TWR = 1.0 * 1.0909 - 1 = 9.09% (nicht 10% wie die alte Boundary-Formel).
    await _add_snapshot(db, user, bucket.id, d=date(2025, 1, 31), value=1000, peak=1000, cf=0)
    await _add_snapshot(db, user, bucket.id, d=date(2025, 2, 15), value=1100, peak=1100, cf=100)
    await _add_snapshot(db, user, bucket.id, d=date(2025, 2, 28), value=1200, peak=1200, cf=0)
    result = await get_bucket_monthly_returns(db, user.id, bucket.id)
    months = result["months"]
    assert len(months) == 1
    feb = months[0]
    assert feb["year"] == 2025
    assert feb["month"] == 2
    assert feb["return_pct"] == pytest.approx(9.09, abs=0.01)
    assert result["annual_totals"][2025] == pytest.approx(9.09, abs=0.01)


async def test_monthly_returns_empty_when_no_snapshots(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Empty")
    await db.commit()
    res = await get_bucket_monthly_returns(db, user.id, bucket.id)
    assert res == {"months": [], "annual_totals": {}}


async def test_monthly_compound_reconciles_with_ytd_twr(db):
    """Kern-Eigenschaft von Option A: Monats-Compound == YTD-TWR, weil beide
    dasselbe Produkt der Tages-Sub-Returns sind (nur anders gruppiert). Genau
    die Diskrepanz, mit der die Untersuchung anfing (-7.53% YTD vs +1.61%).
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Reconcile", benchmark="^GSPC")
    await db.commit()
    await _backdate_bucket(db, bucket, days_ago=120)
    for d, v in [
        (date(2026, 3, 31), 1000),
        (date(2026, 4, 15), 1100),
        (date(2026, 4, 30), 1050),
        (date(2026, 5, 15), 1200),
        (date(2026, 5, 30), 1150),
    ]:
        await _add_snapshot(db, user, bucket.id, d=d, value=v, peak=v, cf=0)
    monthly = await get_bucket_monthly_returns(db, user.id, bucket.id)
    compound = 1.0
    for m in monthly["months"]:
        compound *= (1 + m["return_pct"] / 100)
    monthly_total = (compound - 1) * 100
    with patch("services.benchmark_service.get_benchmark_window_return", return_value=0.0):
        bench = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    # Monats-Compound reconciliert mit dem YTD/all-TWR (modulo Rundung) ...
    assert bench["bucket_return_pct"] == pytest.approx(monthly_total, abs=0.05)
    # ... und beide entsprechen dem teleskopierten 1000->1150 = +15%.
    assert bench["bucket_return_pct"] == pytest.approx(15.0, abs=0.1)


# ---------- compare_to_benchmark --------------------------------------------

async def test_compare_to_benchmark_twr_chained(db):
    """TWR-Chaining ueber tageweise Sub-Returns (analog drawdown_service).

    Sub-Return Tag t = (V_t - cf_t) / V_{t-1}.

    Snapshots:
      Tag 1: V=1000, cf=0
      Tag 2: V=1100, cf=+50   (Sub-Return = (1100-50)/1000 = 1.05  -> +5%)
      Tag 3: V=1200, cf=0     (Sub-Return = (1200-0)/1100   = 1.0909 -> +9.09%)
    TWR = 1.05 * 1.0909 - 1 ≈ 0.1455 = 14.55%.

    Die alte simplifizierte Formel (V_end - cf_sum) / V_start - 1 hatte
    diesen Wert mit 15.0% systematisch ueberzeichnet (wirkt nur bei mid-
    period Cashflows merkbar; bei tiny V_start + grossem Inflow eskaliert
    es — siehe test_compare_to_benchmark_handles_mid_period_inflow).
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="TWR", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    await _backdate_bucket(db, bucket, days_ago=10)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=3), value=1000, peak=1000, cf=0)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=2), value=1100, peak=1100, cf=50)
    await _add_snapshot(db, user, bucket.id, d=today, value=1200, peak=1200, cf=0)
    with patch(
        "services.benchmark_service.get_benchmark_window_return",
        return_value=5.0,
    ):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    assert result["bucket_return_pct"] == pytest.approx(14.55, abs=0.01)
    assert result["benchmark_ticker"] == "^GSPC"
    assert result["benchmark_name"] == "S&P 500"
    assert result["benchmark_return_pct"] == 5.0
    assert result["delta_pct"] == pytest.approx(14.55 - 5.0, abs=0.01)


async def test_summary_drawdown_unaffected_by_sell_outflow(db):
    """Regression: Ein Sell (Outflow) darf nicht als Drawdown vs Peak gelten.

    Wealth-Index-basierte Peak-Berechnung neutralisiert Cashflows:
      Tag 1: V=1000, wealth=1.0, peak=1.0
      Tag 2: V=1200, wealth=1.2, peak=1.2 (asset gewinnt)
      Tag 3: V=700, cf=-500 (Sell): wealth = 1.2 * 1200/1200 = 1.2, peak=1.2

    drawdown_vs_peak_pct = (1.2/1.2 - 1) * 100 = 0%, NICHT (700-1200)/1200 = -41%.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="SellTest")
    await db.commit()
    today = date.today()
    await _backdate_bucket(db, bucket, days_ago=10)
    # Snapshots mit korrekt befuelltem wealth_index/peak_wealth_index
    from models.bucket import BucketSnapshot
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=bucket.id, date=today - timedelta(days=2),
        total_value_chf=Decimal("1000"), cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal("0"), running_peak_chf=Decimal("1000"),
        wealth_index=Decimal("1.0"), running_peak_wealth_index=Decimal("1.0"),
    ))
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=bucket.id, date=today - timedelta(days=1),
        total_value_chf=Decimal("1200"), cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal("0"), running_peak_chf=Decimal("1200"),
        wealth_index=Decimal("1.2"), running_peak_wealth_index=Decimal("1.2"),
    ))
    # Sell: V=700, cf=-500. wealth = 1.2 * (700 - (-500))/1200 = 1.2 (unveraendert)
    db.add(BucketSnapshot(
        user_id=user.id, bucket_id=bucket.id, date=today,
        total_value_chf=Decimal("700"), cash_chf=Decimal("0"),
        net_cash_flow_chf=Decimal("-500"), running_peak_chf=Decimal("1200"),
        wealth_index=Decimal("1.2"), running_peak_wealth_index=Decimal("1.2"),
    ))
    await db.commit()
    summary = await get_bucket_summary(db, user.id, bucket.id)
    assert summary["drawdown_vs_peak_pct"] == pytest.approx(0.0, abs=0.01), (
        f"Sell hat fakly Drawdown ausgeloest: {summary['drawdown_vs_peak_pct']}%"
    )
    # Peak-CHF: Wert am Tag des Wealth-Index-Peaks (gestern bei 1200)
    assert summary["running_peak_chf"] == 1200.0


async def test_compare_to_benchmark_handles_mid_period_inflow(db):
    """Regression: Bucket mit tinem V_start und grossem GEBUCHTEM Mid-Period-Inflow.

    Szenario "Hard Money": Bucket existiert seit Jan 1 mit 100 CHF Cash.
    Anfang April wird eine Position fuer 10'000 CHF gekauft — ein echter Buy
    bucht net_cash_flow_chf=+10'000 in den Snapshot. Asset gewinnt 10% bis
    heute → V=11'100.

    Alte simplifizierte Formel: (11'100 - 10'000) / 100 - 1 = 1000% (Bug).
    Korrekte TWR (Chain): der gebuchte Cashflow wird abgezogen, bleibt nur die
    10% Asset-Performance, ≈ 10%.

    (Der net_cf=0-Fall — Re-Label OHNE Transaction — ist separat in
    test_compare_to_benchmark_neutralizes_relabel_jump abgedeckt.)
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="HardMoney", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    await _backdate_bucket(db, bucket, days_ago=120)
    # Bucket bestand mit 100 CHF Cash 90 Tage lang
    for i in range(90, 30, -1):
        await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=i), value=100, peak=100, cf=0)
    # Tag t-30: Position eingebucht (+10'000)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=30), value=10100, peak=10100, cf=10000)
    # Bis heute langsamer Anstieg auf 11'100 (≈ 10% Asset-Gain)
    for i in range(29, -1, -1):
        # linear von 10100 → 11100
        v = 10100 + (11100 - 10100) * (30 - i) / 30
        await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=i), value=round(v, 2), peak=round(v, 2), cf=0)
    with patch(
        "services.benchmark_service.get_benchmark_window_return",
        return_value=2.0,
    ):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    # Erwartung: TWR liegt nahe 10% (nur Asset-Performance), nicht 1000%
    assert result["bucket_return_pct"] is not None
    assert 5.0 <= result["bucket_return_pct"] <= 15.0, (
        f"Mid-period inflow blaeht Return auf {result['bucket_return_pct']}% — "
        f"sollte ~10% sein (nur die Asset-Performance, Inflow neutralisiert)"
    )


async def test_compare_to_benchmark_neutralizes_relabel_jump(db):
    """Regression (Bucket-Card-Bug 27.05.26): Re-Label OHNE gebuchten Cashflow.

    move_position_to_bucket schreibt KEINE Transaction → der bucket_snapshot
    des Wechseltages springt um den vollen Positionswert, aber
    net_cash_flow_chf bleibt 0 (anders als beim gebuchten Buy in
    test_compare_to_benchmark_handles_mid_period_inflow). Der cashflow-
    bereinigte Sub-Return wuerde den Sprung sonst als Marktrendite verbuchen
    (auf Prod: +24.93% in 11 Tagen bei nur +1.53% S&P).

    Hier: Bucket 100 CHF, am Tag t-20 wird eine Position ~10'000 CHF
    reingelabelt (cf=0 + position_bucket_history-Eintrag), danach +9.9% Asset-
    Gewinn. Der Guard liest den Wechseltag aus der History und neutralisiert
    den Sprung → es bleibt nur die echte Asset-Performance.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="ReLabel", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    await _backdate_bucket(db, bucket, days_ago=40)
    pos = await _make_position(db, user, bucket_id=bucket.id, ticker="TSM")
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=30), value=100, peak=100, cf=0)
    # Re-Label-Tag: Wert springt 100 → 10'100, ABER net_cf bleibt 0.
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=20), value=10100, peak=10100, cf=0)
    await _add_relabel(db, pos.id, to_bucket_id=bucket.id, d=today - timedelta(days=20))
    await _add_snapshot(db, user, bucket.id, d=today, value=11100, peak=11100, cf=0)
    with patch(
        "services.benchmark_service.get_benchmark_window_return", return_value=2.0
    ):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    # Sprung neutralisiert → nur (11'100/10'100 - 1) ≈ +9.9%, NICHT +10'000%
    assert result["bucket_return_pct"] == pytest.approx(9.90, abs=0.1), (
        f"Re-Label-Sprung nicht neutralisiert: {result['bucket_return_pct']}%"
    )


async def test_compare_to_benchmark_keeps_real_volatile_day(db):
    """Kein Falsch-Positiv: ein echter grosser Markttag (cf=0, KEIN History-
    Eintrag) darf NICHT als Re-Label neutralisiert werden.

    Ein reiner Wert-Schwellenwert wuerde +20% an einem Tag faelschlich als
    Bucket-Wechsel werten. Da der Guard die exakten Wechseltage aus
    position_bucket_history liest (hier keine), bleibt der Tag eine echte
    Rendite.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Volatile", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    await _backdate_bucket(db, bucket, days_ago=10)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=3), value=1000, peak=1000, cf=0)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=2), value=1200, peak=1200, cf=0)
    await _add_snapshot(db, user, bucket.id, d=today, value=1200, peak=1200, cf=0)
    with patch(
        "services.benchmark_service.get_benchmark_window_return", return_value=5.0
    ):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    assert result["bucket_return_pct"] == pytest.approx(20.0, abs=0.01), (
        f"Echter Markttag faelschlich neutralisiert: {result['bucket_return_pct']}%"
    )


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
    await _backdate_bucket(db, bucket, days_ago=10)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=2), value=1000, peak=1000)
    await _add_snapshot(db, user, bucket.id, d=today, value=1100, peak=1100)
    mock_yf = MagicMock()
    with patch("services.benchmark_service.get_benchmark_window_return", new=mock_yf):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="all")
    # bucket_return_pct ist berechnet (Snapshots im Fenster) — wir erreichen also
    # den Benchmark-Block, und nur die Allowlist verhindert den yfinance-Call.
    assert result["bucket_return_pct"] is not None
    assert result["benchmark_return_pct"] is None
    assert result["benchmark_ticker"] == "EVIL.TICKER"
    # Wichtig: yfinance darf NICHT angefasst worden sein
    mock_yf.assert_not_called()


async def test_compare_to_benchmark_clamps_to_bucket_inception(db):
    """Backfill-Klemmung: Snapshots vor created_at stammen aus dem proportionalen
    Backfill (= Portfolio-Rendite je Bucket) und duerfen den Vergleich nicht
    kontaminieren. Das Fenster startet am Erstellungsdatum; clamped=True und
    effective_start signalisieren der UI 'seit Bucket-Start' statt 'YTD'. Der
    Benchmark wird ueber exakt dasselbe Fenster gemessen.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Clamp", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    await _backdate_bucket(db, bucket, days_ago=10)
    # Synthetische Backfill-Historie VOR Erstellung — kuenstlicher 1000->5000-
    # Sprung, der den Return ohne Klemmung auf ~+410% aufblaehen wuerde:
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=30), value=1000, peak=1000, cf=0)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=20), value=5000, peak=5000, cf=0)
    # Reale Historie ab Erstellung: 5000 -> 5100 (= +2%)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=10), value=5000, peak=5000, cf=0)
    await _add_snapshot(db, user, bucket.id, d=today, value=5100, peak=5100, cf=0)
    with patch(
        "services.benchmark_service.get_benchmark_window_return", return_value=1.0
    ) as m:
        result = await compare_to_benchmark(db, user.id, bucket.id, period="ytd")
    # Nur die realen +2% ab Erstellung, NICHT der synthetische 1000->5000-Sprung
    assert result["bucket_return_pct"] == pytest.approx(2.0, abs=0.01)
    assert result["clamped"] is True
    assert result["effective_start"] == (today - timedelta(days=10)).isoformat()
    assert result["delta_pct"] == pytest.approx(1.0, abs=0.01)
    # Benchmark ueber exakt das reale Fenster (erster..letzter realer Snapshot)
    m.assert_called_once()
    assert m.call_args.args[1] == today - timedelta(days=10)
    assert m.call_args.args[2] == today


async def test_compare_to_benchmark_effective_start_is_first_real_snapshot(db):
    """effective_start meldet den ersten realen Snapshot (rows[0].date), nicht
    die Klemm-Grenze created_at — relevant wenn der Bucket an einem Wochenende/
    Feiertag erstellt wurde und der erste Snapshot Tage spaeter faellt. Sonst
    labelt die UI ein Datum, fuer das es noch keinen Messpunkt gibt.
    """
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="WeekendStart", benchmark="^GSPC")
    await db.commit()
    today = date.today()
    # created_at = today-12, aber erster Snapshot erst today-10 (2 Tage Luecke).
    await _backdate_bucket(db, bucket, days_ago=12)
    await _add_snapshot(db, user, bucket.id, d=today - timedelta(days=10), value=1000, peak=1000, cf=0)
    await _add_snapshot(db, user, bucket.id, d=today, value=1050, peak=1050, cf=0)
    with patch("services.benchmark_service.get_benchmark_window_return", return_value=0.0):
        result = await compare_to_benchmark(db, user.id, bucket.id, period="ytd")
    assert result["effective_start"] == (today - timedelta(days=10)).isoformat()
    assert result["effective_start"] != (today - timedelta(days=12)).isoformat()
    assert result["clamped"] is True


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
