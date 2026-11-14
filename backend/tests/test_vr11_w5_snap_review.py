"""Vollreview 11/2026, Welle 5: Fehler, die die Fixes an Snapshots und Summary einführten.

R-snapshots-1   Heute-Snapshot trägt die Cashflows seit dem letzten Snapshot
R-snapshots-2   Summary-Single-Flight hängt sich nicht an einen Lauf von vor der Buchung
R-pricecache-1  manuell bepreiste Position: Snapshot und Regen rechnen wie die Summary
R-yfanalysis-3  .L-Ticker mit unbekannter Notierungswährung wird nicht mit Divisor 1.0 bewertet
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from models.bucket import BucketSnapshot
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position, PriceSource, PricingMode
from models.price_cache import PriceCache
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services import cache, history_service, snapshot_service
from services import portfolio_service as ps
from services.bucket_service import create_bucket, create_system_buckets
from services.history_service import get_portfolio_history
from services.portfolio_service import _compute_market_value, get_portfolio_summary_cached
from services.snapshot_service import (
    _calc_portfolio_value_fast,
    _calc_position_value_chf,
    _daily_txn_cash_flow,
    _record_user_snapshot,
    regenerate_snapshots,
)

pytestmark = pytest.mark.asyncio

MONDAY = date(2026, 11, 9)
SATURDAY = MONDAY - timedelta(days=2)
THURSDAY = MONDAY - timedelta(days=4)


class _Monday(date):
    @classmethod
    def today(cls):
        return MONDAY


async def _user_with_bucket(db):
    user = User(email=f"w5{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    return user, bucket


async def _position(db, user, bucket, ticker="AAA", shares="10", cost="1000", **kw) -> Position:
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker=ticker, name=ticker,
        type=kw.pop("type", AssetType.stock), currency=kw.pop("currency", "CHF"),
        shares=Decimal(shares), cost_basis_chf=Decimal(cost), is_active=True, **kw,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


def _buy(user, pos, d: date, shares, price, total) -> Transaction:
    return Transaction(
        user_id=user.id, position_id=pos.id, type=TransactionType.buy, date=d,
        shares=Decimal(str(shares)), price_per_share=Decimal(str(price)),
        currency="CHF", total_chf=Decimal(str(total)),
    )


def _fake_yf(prices: dict[str, float | None]):
    """Kurs-Frame wie yf_download: Wert None ergibt eine leere Reihe."""
    def fake(all_tickers, **kwargs):
        cal = pd.date_range(kwargs["start"], kwargs["end"], freq="D")
        cols = {
            ("Close", t): np.full(len(cal), np.nan if prices.get(t) is None else prices[t])
            for t in all_tickers
        }
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        if len(all_tickers) == 1:
            df = pd.DataFrame({"Close": df[("Close", all_tickers[0])]})
        return df
    return fake


async def _snapshots(db, uid) -> list[PortfolioSnapshot]:
    return list((await db.execute(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == uid)
        .order_by(PortfolioSnapshot.date)
        .execution_options(populate_existing=True)
    )).scalars().all())


async def _bucket_snapshots(db, uid, bucket_id) -> list[BucketSnapshot]:
    return list((await db.execute(
        select(BucketSnapshot).where(
            BucketSnapshot.user_id == uid, BucketSnapshot.bucket_id == bucket_id,
        ).order_by(BucketSnapshot.date)
        .execution_options(populate_existing=True)
    )).scalars().all())


# --- R-snapshots-1 ----------------------------------------------------------


async def test_r_snapshots_1_today_snapshot_keeps_rolled_up_weekend_cashflow(db, monkeypatch):
    """Samstag: Kauf über 5'000. Montag: Regen, danach ein Kauf mit Datum heute.
    Der Heute-Snapshot darf den vom Regen auf den Montag gerollten Cashflow
    nicht löschen."""
    monkeypatch.setattr("services.snapshot_service.date", _Monday)
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"AAA": 100.0, "BBB": 100.0})
    )
    user, bucket = await _user_with_bucket(db)
    aaa = await _position(
        db, user, bucket, shares="1000", cost="100000", current_price=Decimal("100")
    )
    bbb = await _position(
        db, user, bucket, ticker="BBB", shares="50", cost="5000", current_price=Decimal("100")
    )
    db.add_all([
        _buy(user, aaa, THURSDAY, 1000, 100, 100000),
        _buy(user, bbb, SATURDAY, 50, 100, 5000),   # am Montag nachgetragen
    ])
    await db.commit()

    await regenerate_snapshots(db, user.id)
    monday = (await _snapshots(db, user.id))[-1]
    assert monday.date == MONDAY
    assert float(monday.total_value_chf) == 105000.0
    assert float(monday.net_cash_flow_chf) == 5000.0

    # Kauf über 1'000 mit Datum heute: der Trigger schreibt die heutige Zeile neu.
    aaa.shares = Decimal("1010")
    aaa.cost_basis_chf = Decimal("101000")
    db.add(_buy(user, aaa, MONDAY, 10, 100, 1000))
    await db.commit()
    await snapshot_service.refresh_today_snapshot(user.id)

    snaps = await _snapshots(db, user.id)
    assert snaps[-1].date == MONDAY
    assert float(snaps[-1].total_value_chf) == 106000.0
    assert float(snaps[-1].net_cash_flow_chf) == 6000.0
    # Jede Buchung steht in genau einer Zeile.
    assert sum(float(s.net_cash_flow_chf) for s in snaps) == 106000.0

    # Kontrolle: ein Regen auf demselben Stand schreibt denselben Cashflow.
    await regenerate_snapshots(db, user.id)
    assert float((await _snapshots(db, user.id))[-1].net_cash_flow_chf) == 6000.0


async def test_r_snapshots_1_previous_day_flow_is_not_counted_twice(db, monkeypatch):
    """Normalfall mit Vorzeile vom Vortag: es zählt nur der heutige Tag."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket, shares="18", cost="1800", current_price=Decimal("100"))
    today = date.today()
    yesterday = today - timedelta(days=1)
    db.add_all([
        PortfolioSnapshot(
            user_id=user.id, date=yesterday, total_value_chf=Decimal("1500"),
            cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("500"),
        ),
        _buy(user, pos, today - timedelta(days=30), 10, 100, 1000),
        _buy(user, pos, yesterday, 5, 100, 500),
        _buy(user, pos, today, 3, 100, 300),
    ])
    await db.commit()

    await _record_user_snapshot(db, user.id, today)
    await db.commit()

    snaps = await _snapshots(db, user.id)
    assert [s.date for s in snaps] == [yesterday, today]
    assert float(snaps[-1].net_cash_flow_chf) == 300.0


async def test_r_snapshots_1_without_previous_row_only_the_day_counts(db, monkeypatch):
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket, shares="13", cost="1300", current_price=Decimal("100"))
    today = date.today()
    db.add_all([
        _buy(user, pos, today - timedelta(days=30), 10, 100, 1000),
        _buy(user, pos, today, 3, 100, 300),
    ])
    await db.commit()

    await _record_user_snapshot(db, user.id, today)
    await db.commit()

    snaps = await _snapshots(db, user.id)
    assert len(snaps) == 1
    assert float(snaps[0].net_cash_flow_chf) == 300.0
    # Der Vertrag der Hilfsfunktion: ohne after_date genau ein Tag, mit after_date
    # die Spanne (after_date, snapshot_date].
    assert await _daily_txn_cash_flow(db, user.id, today) == 300.0
    assert await _daily_txn_cash_flow(
        db, user.id, today, after_date=today - timedelta(days=30)
    ) == 300.0
    assert await _daily_txn_cash_flow(
        db, user.id, today, after_date=today - timedelta(days=31)
    ) == 1300.0


# --- R-snapshots-2 ----------------------------------------------------------


async def test_r_snapshots_2_call_after_a_write_does_not_join_the_older_run(db, monkeypatch):
    """Ein Lauf rechnet noch, der Nutzer bucht. Der Aufruf danach muss neu
    rechnen und darf nicht das Ergebnis des Laufs von vor der Buchung bekommen."""
    from api.portfolio import invalidate_portfolio_cache

    uid = uuid.uuid4()
    ledger = {"n_txn": 1}
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow_summary(db, user_id=None):
        nonlocal calls
        calls += 1
        seen = ledger["n_txn"]          # Stand beim Lesen der Datenbank
        if calls == 1:
            started.set()
            await release.wait()
        return {"positions": [], "n_txn": seen}

    monkeypatch.setattr(ps, "get_portfolio_summary", slow_summary)

    first = asyncio.create_task(get_portfolio_summary_cached(db, uid))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        ledger["n_txn"] = 2             # Buchung
        invalidate_portfolio_cache(str(uid))

        second = await asyncio.wait_for(get_portfolio_summary_cached(db, uid), timeout=5)
    finally:
        release.set()
    assert second["n_txn"] == 2
    assert calls == 2
    assert (await first)["n_txn"] == 1
    # Im Cache steht der neue Stand; der alte Lauf schreibt nicht darüber.
    assert cache.get(f"portfolio_summary:{uid}") == {"positions": [], "n_txn": 2}


async def test_r_snapshots_2_concurrent_calls_still_share_one_run(db, monkeypatch):
    """Ohne Buchung dazwischen bleibt es bei einer Berechnung (K060)."""
    uid = uuid.uuid4()
    calls = 0

    async def slow_summary(db, user_id=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"positions": [], "n": calls}

    monkeypatch.setattr(ps, "get_portfolio_summary", slow_summary)

    results = await asyncio.gather(*[get_portfolio_summary_cached(db, uid) for _ in range(4)])

    assert calls == 1
    assert all(r is results[0] for r in results)
    assert not ps._inflight


# --- R-pricecache-1 ---------------------------------------------------------


async def _manual_position(db, user, bucket, **kw) -> Position:
    return await _position(
        db, user, bucket, ticker=kw.pop("ticker", "NESN.SW"), shares="10", cost="900",
        current_price=Decimal("50"), pricing_mode=PricingMode.manual,
        price_source=kw.pop("price_source", PriceSource.manual), **kw,
    )


async def test_r_pricecache_1_snapshot_values_manual_position_like_the_summary(db, monkeypatch):
    """Nutzer A führt NESN.SW manuell mit Kurs 50. Ein anderer Nutzer hat den
    Ticker auf der Watchlist: price:NESN.SW = 92. Summary, Tages-Snapshot und
    Bucket-Snapshot müssen denselben Wert zeigen."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    user, bucket = await _user_with_bucket(db)
    pos = await _manual_position(db, user, bucket)
    cache.set("price:NESN.SW", {"price": 92.0, "currency": "CHF", "change_pct": 0.0})
    try:
        summary_value = _compute_market_value(pos, {}, price_map={"NESN.SW": {"price": 92.0}})[0]
        total, _cash = await _calc_portfolio_value_fast(db, user.id)
        position_value = await _calc_position_value_chf(pos, {})

        today = date.today()
        await _record_user_snapshot(db, user.id, today)
        await db.commit()
    finally:
        cache.delete("price:NESN.SW")

    assert summary_value == 500.0
    assert total == 500.0
    assert position_value == 500.0
    assert float((await _snapshots(db, user.id))[-1].total_value_chf) == 500.0
    assert float((await _bucket_snapshots(db, user.id, bucket.id))[-1].total_value_chf) == 500.0


async def test_r_pricecache_1_auto_position_still_reads_the_price_cache(db, monkeypatch):
    """Gegenprobe: ohne manuellen Modus gilt weiter price:<Ticker>."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    user, bucket = await _user_with_bucket(db)
    pos = await _position(
        db, user, bucket, ticker="NESN.SW", shares="10", cost="900", current_price=Decimal("50")
    )
    cache.set("price:NESN.SW", {"price": 92.0, "currency": "CHF", "change_pct": 0.0})
    try:
        total, _cash = await _calc_portfolio_value_fast(db, user.id)
        position_value = await _calc_position_value_chf(pos, {})
    finally:
        cache.delete("price:NESN.SW")

    assert total == 920.0
    assert position_value == 920.0


async def test_r_pricecache_1_manual_position_in_foreign_currency_uses_fx(db, monkeypatch):
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"USD": 0.9})
    user, bucket = await _user_with_bucket(db)
    pos = await _manual_position(db, user, bucket, ticker="XYZ", currency="USD")
    cache.set("price:XYZ", {"price": 92.0, "currency": "USD", "change_pct": 0.0})
    try:
        total, _cash = await _calc_portfolio_value_fast(db, user.id)
    finally:
        cache.delete("price:XYZ")

    assert total == pytest.approx(450.0)
    assert _compute_market_value(pos, {"USD": 0.9})[0] == pytest.approx(450.0)


@pytest.mark.parametrize("yahoo_close", [92.0, None], ids=["yahoo_known", "yahoo_unknown"])
async def test_r_pricecache_1_regen_does_not_jump_at_the_daily_boundary(
    db, monkeypatch, yahoo_close
):
    """Der Regen schreibt die Reihe bis heute, der Tageslauf den nächsten Punkt.
    Bewertet der Regen eine manuelle Position mit dem Yahoo-Schlusskurs (92)
    oder dem Einstand (900), springt die Reihe an dieser Grenze ohne Cashflow."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.snapshot_service.yf_download",
        _fake_yf({"AAA": 100.0, "NESN.SW": yahoo_close}),
    )
    user, bucket = await _user_with_bucket(db)
    today = date.today()
    anchor = await _position(db, user, bucket, current_price=Decimal("100"))
    manual = await _manual_position(db, user, bucket)
    db.add_all([
        _buy(user, anchor, today - timedelta(days=10), 10, 100, 1000),
        _buy(user, manual, today - timedelta(days=5), 10, 90, 900),
    ])
    await db.commit()

    result = await regenerate_snapshots(db, user.id)
    assert "error" not in result

    daily_total, _cash = await _calc_portfolio_value_fast(db, user.id)
    assert daily_total == 1500.0                      # 10 x 100 + 10 x 50
    snaps = await _snapshots(db, user.id)
    assert float(snaps[-1].total_value_chf) == daily_total
    # Ab dem Kauf der manuellen Position steht jeder Tag auf dem manuellen Kurs.
    since_buy = [s for s in snaps if s.date >= today - timedelta(days=5)]
    assert since_buy and all(float(s.total_value_chf) == 1500.0 for s in since_buy)
    buckets = await _bucket_snapshots(db, user.id, bucket.id)
    assert float(buckets[-1].total_value_chf) == daily_total


async def test_r_pricecache_1_regen_static_manual_position_keeps_manual_value(db, monkeypatch):
    """Manuelle Position ohne Transaktion (Bestandserfassung): auch sie bekommt
    im Regen keinen Yahoo-Schlusskurs."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"AAA": 100.0, "NESN.SW": 92.0})
    )
    user, bucket = await _user_with_bucket(db)
    anchor = await _position(db, user, bucket, current_price=Decimal("100"))
    await _manual_position(db, user, bucket)
    db.add(_buy(user, anchor, date.today() - timedelta(days=10), 10, 100, 1000))
    await db.commit()

    await regenerate_snapshots(db, user.id)

    snaps = await _snapshots(db, user.id)
    assert snaps and all(float(s.total_value_chf) == 1500.0 for s in snaps)


async def test_r_pricecache_1_manual_ticker_without_series_does_not_block_the_regen(
    db, monkeypatch
):
    """K079 bricht ab, wenn eine benötigte Kursreihe fehlt. Die Reihe einer
    manuellen Position liest der Replay nicht: sie darf den Regen nicht sperren."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"AAA": 100.0, "NESN.SW": None})
    )
    user, bucket = await _user_with_bucket(db)
    today = date.today()
    anchor = await _position(db, user, bucket, current_price=Decimal("100"))
    manual = await _manual_position(db, user, bucket)
    db.add_all([
        _buy(user, anchor, today - timedelta(days=10), 10, 100, 1000),
        _buy(user, manual, today - timedelta(days=5), 10, 90, 900),
        # Yahoo führt den Ticker: ein anderer Nutzer hat ihn auf der Watchlist.
        PriceCache(
            ticker="NESN.SW", date=today - timedelta(days=1), close=Decimal("92"),
            currency="CHF", source="yahoo",
        ),
    ])
    await db.commit()

    result = await regenerate_snapshots(db, user.id)

    assert "error" not in result
    assert float((await _snapshots(db, user.id))[-1].total_value_chf) == 1500.0


async def test_r_pricecache_1_regen_keeps_yahoo_close_for_auto_positions(db, monkeypatch):
    """Gegenprobe: ohne manuellen Modus bewertet der Regen weiter mit Yahoo."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"NESN.SW": 92.0})
    )
    user, bucket = await _user_with_bucket(db)
    pos = await _position(
        db, user, bucket, ticker="NESN.SW", shares="10", cost="900", current_price=Decimal("50")
    )
    db.add(_buy(user, pos, date.today() - timedelta(days=5), 10, 90, 900))
    await db.commit()

    await regenerate_snapshots(db, user.id)

    assert float((await _snapshots(db, user.id))[-1].total_value_chf) == 920.0


# --- Abnahme Fixlauf: Altbestand mit Modus manual und Preisquelle yahoo -------


async def test_legacy_manual_mode_yahoo_source_is_valued_like_a_live_position(db, monkeypatch):
    """Früheres Cash-Konto als Anleihe: Modus manual, Preisquelle yahoo.

    Der Worker lädt den Kurs weiter. Tages-Snapshot und Positionswert lesen
    deshalb wie vor dem Vollreview price:<Ticker>, nicht einen stehenden Kurs.
    """
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    user, bucket = await _user_with_bucket(db)
    pos = await _manual_position(db, user, bucket, price_source=PriceSource.yahoo)
    cache.set("price:NESN.SW", {"price": 92.0, "currency": "CHF", "change_pct": 0.0})
    try:
        total, _cash = await _calc_portfolio_value_fast(db, user.id)
        position_value = await _calc_position_value_chf(pos, {})
    finally:
        cache.delete("price:NESN.SW")

    assert total == 920.0
    assert position_value == 920.0


async def test_legacy_manual_mode_yahoo_source_replays_with_the_price_series(db, monkeypatch):
    """Der Regen bewertet den Altbestand ohne Kauf-Buchung weiter mit der
    Kursreihe. Ein stehender Kurs über die ganze Historie änderte alte Snapshots."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"AAA": 100.0, "NESN.SW": 92.0})
    )
    user, bucket = await _user_with_bucket(db)
    anchor = await _position(db, user, bucket, current_price=Decimal("100"))
    await _manual_position(db, user, bucket, price_source=PriceSource.yahoo)
    db.add(_buy(user, anchor, date.today() - timedelta(days=10), 10, 100, 1000))
    await db.commit()

    result = await regenerate_snapshots(db, user.id)

    assert "error" not in result
    snaps = await _snapshots(db, user.id)
    # 10 x 100 (AAA) + 10 x 92 (Yahoo-Schlusskurs), nicht 10 x 50 (current_price).
    assert snaps and all(float(s.total_value_chf) == 1920.0 for s in snaps)


# --- R-yfanalysis-3 ---------------------------------------------------------


def _raise(ticker):
    raise RuntimeError("ticker lock timeout")


async def _lse_depot(db, quote_ccy: str = "GBP"):
    """AAA mit Kauf, dazu VUSA.L ohne Transaktion (Bestandserfassung)."""
    user, bucket = await _user_with_bucket(db)
    anchor = await _position(db, user, bucket, current_price=Decimal("100"))
    db.add(_buy(user, anchor, date.today() - timedelta(days=10), 10, 100, 1000))
    await _position(
        db, user, bucket, ticker="VUSA.L", shares="5", cost="400", currency=quote_ccy,
        current_price=Decimal("80"),
    )
    await db.commit()
    return user


@pytest.mark.parametrize("lookup", [lambda t: None, _raise], ids=["none", "raises"])
async def test_r_yfanalysis_3_regen_ignores_series_when_quote_currency_is_unknown(
    db, monkeypatch, lookup
):
    """Yahoo liefert die Notierungswährung nicht (Fehler, Lock-Frist). Die Reihe
    steht in Pence (8000). Mit Divisor 1.0 stünde die Position 100-fach zu hoch
    in der ganzen Historie: 5 x 8000 x 1.1 = 44'000 statt 440."""
    user = await _lse_depot(db)
    monkeypatch.setattr("services.cache_service._quote_currency", lookup)
    monkeypatch.setattr(
        "services.snapshot_service.yf_download",
        _fake_yf({"AAA": 100.0, "VUSA.L": 8000.0, "GBPCHF=X": 1.1}),
    )
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"GBP": 1.1})

    result = await regenerate_snapshots(db, user.id)

    assert "error" not in result
    snaps = await _snapshots(db, user.id)
    # AAA 10 x 100, VUSA.L mit dem heutigen Wert als Rückfall: 5 x 80 x 1.1.
    assert snaps and all(
        float(s.total_value_chf) == pytest.approx(1440.0, abs=0.01) for s in snaps
    )


async def test_r_yfanalysis_3_regen_still_prices_known_non_pence_lse_ticker(db, monkeypatch):
    """Gegenprobe: eine bekannte Notierung in USD bleibt bei Divisor 1.0 bewertet."""
    user = await _lse_depot(db, quote_ccy="USD")
    monkeypatch.setattr("services.cache_service._quote_currency", lambda t: "USD")
    monkeypatch.setattr(
        "services.snapshot_service.yf_download",
        _fake_yf({"AAA": 100.0, "VUSA.L": 30.0, "USDCHF=X": 0.9}),
    )
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"USD": 0.9})

    await regenerate_snapshots(db, user.id)

    # AAA 10 x 100 + VUSA.L 5 x 30 x 0.9
    snaps = await _snapshots(db, user.id)
    assert float(snaps[-1].total_value_chf) == pytest.approx(1135.0, abs=0.01)


async def _history_depot(db):
    user, bucket = await _user_with_bucket(db)
    d0 = date.today() - timedelta(days=20)
    aaa = await _position(db, user, bucket)
    swda = await _position(
        db, user, bucket, ticker="SWDA.L", shares="100", cost="9900", currency="GBP",
        type=AssetType.etf,
    )
    db.add_all([_buy(user, aaa, d0, 10, 100, 1000), _buy(user, swda, d0, 100, 90, 9900)])
    await db.commit()
    return user, d0


def _patch_history(monkeypatch, quote_currency):
    monkeypatch.setattr(
        "services.history_service.yf_download",
        _fake_yf({"AAA": 100.0, "SWDA.L": 9000.0, "GBPCHF=X": 1.1, "^GSPC": 5000.0}),
    )
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"GBP": 1.1})
    monkeypatch.setattr("services.benchmark_service.benchmark_quote_currency", lambda t: "CHF")
    monkeypatch.setattr("services.cache_service._quote_currency", quote_currency)


@pytest.mark.parametrize("lookup", [lambda t: None, _raise], ids=["none", "raises"])
async def test_r_yfanalysis_3_history_leaves_lse_position_unpriced_when_currency_unknown(
    db, monkeypatch, lookup
):
    """SWDA.L notiert in Pence (9000). Ohne Notierungswährung rechnete die
    Historie 100 x 9000 x 1.1 = 990'000 statt 9'900."""
    user, d0 = await _history_depot(db)
    ttls = []
    real_set = history_service.cache.set

    def spy_set(key, value, ttl=900):
        if key.startswith("portfolio_history:"):
            ttls.append(ttl)
        return real_set(key, value, ttl)

    monkeypatch.setattr("services.cache.set", spy_set)
    _patch_history(monkeypatch, lookup)

    hist = await get_portfolio_history(db, d0, date.today(), user_id=user.id)

    values = [p["value"] for p in hist["data"]]
    # Nur AAA trägt einen Kurs; die .L-Position steht nicht 100-fach in der Reihe.
    assert values and max(values) == pytest.approx(1000.0)
    # Die Währung kann beim nächsten Abruf bekannt sein: nur kurz cachen.
    assert ttls == [history_service.DEGRADED_CACHE_TTL]


async def test_r_yfanalysis_3_history_prices_lse_position_when_currency_is_known(
    db, monkeypatch
):
    """Gegenprobe: mit bekannter Notierung in Pence bleibt die Bewertung wie bisher."""
    user, d0 = await _history_depot(db)
    ttls = []
    real_set = history_service.cache.set

    def spy_set(key, value, ttl=900):
        if key.startswith("portfolio_history:"):
            ttls.append(ttl)
        return real_set(key, value, ttl)

    monkeypatch.setattr("services.cache.set", spy_set)
    _patch_history(monkeypatch, lambda t: "GBp")

    hist = await get_portfolio_history(db, d0, date.today(), user_id=user.id)

    # AAA 10 x 100 + SWDA.L 100 x (9000 / 100) x 1.1
    assert hist["data"][-1]["value"] == pytest.approx(10900.0, rel=1e-6)
    assert ttls == [history_service.CACHE_TTL]
