"""Vollreview 11/2026: Snapshot-Regen, Trigger und Sperre.

K001  Buchung mit Datum heute schreibt den heutigen Snapshot neu
K006  Deckel für die Spanne eines Regens
K007  Tages-Replay läuft als reine Funktion in einem Thread
K056  Inserts als executemany
K076  Sperre je Nutzer, Bucket-Insert mit ON CONFLICT
K079  kein Überschreiben der Historie bei fehlenden Kursreihen
K080  /regenerate-snapshots über den Schutz, 409 bei laufendem Regen
K131  Pence-Prüfung nicht auf dem Event-Loop
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import event, select

from constants.limits import MAX_REGEN_SPAN_DAYS
from db import engine as test_engine
from models.bucket import BucketSnapshot
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position
from models.price_cache import PriceCache
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services import snapshot_service, snapshot_trigger
from services.bucket_service import create_bucket, create_system_buckets
from services.snapshot_service import (
    SnapshotLockBusy,
    _lock_user_snapshots,
    _record_user_snapshot,
    regenerate_snapshots,
)

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


@contextmanager
def capture_sql():
    """Sammelt (statement, executemany) aller Statements der Test-Engine."""
    statements: list[tuple[str, bool]] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, executemany))

    event.listen(test_engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _before)


async def _user_with_bucket(db):
    user = User(email=f"rg{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
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


def _frame(prices: dict[str, float | None], start: date, end: date) -> pd.DataFrame:
    """Kurs-Frame wie yf_download: Wert None ergibt eine leere Reihe."""
    cal = pd.date_range(start, end, freq="D")
    cols = {
        ("Close", t): np.full(len(cal), np.nan if v is None else v)
        for t, v in prices.items()
    }
    df = pd.DataFrame(cols, index=cal)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    if len(prices) == 1:
        df = pd.DataFrame({"Close": df[("Close", next(iter(prices)))]})
    return df


def _fake_yf(prices: dict[str, float | None]):
    def fake(all_tickers, **kwargs):
        start = date.fromisoformat(kwargs["start"])
        end = date.fromisoformat(kwargs["end"])
        return _frame({t: prices.get(t) for t in all_tickers}, start, end)
    return fake


async def _drain_trigger_tasks():
    # Mit Zeitlimit: ein Rückfall soll den Test scheitern lassen, nicht die Suite anhalten.
    while snapshot_trigger._pending_tasks:
        await asyncio.wait_for(
            asyncio.gather(*list(snapshot_trigger._pending_tasks)), timeout=30
        )


async def _snapshots(db, uid) -> list[PortfolioSnapshot]:
    # populate_existing: der Hintergrund-Task schreibt über eine eigene Session.
    return list((await db.execute(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == uid)
        .order_by(PortfolioSnapshot.date)
        .execution_options(populate_existing=True)
    )).scalars().all())


# --- K001 -------------------------------------------------------------------


async def test_k001_today_booking_rewrites_today_snapshot(db, monkeypatch):
    """Der Tageslauf hat den heutigen Snapshot schon geschrieben. Eine Buchung mit
    Datum heute muss ihn neu schreiben, sonst fehlt ihr Cashflow dauerhaft:
    der Snapshot des Folgetags summiert nur die Cashflows des Folgetags."""
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket, current_price=Decimal("100"))
    today = date.today()

    await _record_user_snapshot(db, user.id, today)  # Tageslauf von 07:00
    await db.commit()
    before = (await _snapshots(db, user.id))[0]
    assert float(before.total_value_chf) == 1000.0
    assert float(before.net_cash_flow_chf) == 0.0

    # Kauf von 5 Stück zu 100 mit Datum heute.
    pos.shares = Decimal("15")
    pos.cost_basis_chf = Decimal("1500")
    db.add(_buy(user, pos, today, 5, 100, 500))
    await db.commit()

    snapshot_trigger.trigger_snapshot_regen(user.id, today)
    await _drain_trigger_tasks()

    snaps = await _snapshots(db, user.id)
    assert len(snaps) == 1
    assert float(snaps[0].total_value_chf) == 1500.0
    assert float(snaps[0].net_cash_flow_chf) == 500.0

    bucket_snap = (await db.execute(
        select(BucketSnapshot).where(
            BucketSnapshot.user_id == user.id, BucketSnapshot.bucket_id == bucket.id,
        ).execution_options(populate_existing=True)
    )).scalars().one()
    assert float(bucket_snap.total_value_chf) == 1500.0
    assert float(bucket_snap.net_cash_flow_chf) == 500.0


async def test_k001_today_booking_does_not_start_full_regen(monkeypatch):
    regen = AsyncMock()
    today_refresh = AsyncMock()
    monkeypatch.setattr("services.snapshot_service.regenerate_snapshots", regen)
    monkeypatch.setattr("services.snapshot_service.refresh_today_snapshot", today_refresh)
    uid = uuid.uuid4()

    snapshot_trigger.trigger_snapshot_regen(uid, date.today())
    await _drain_trigger_tasks()

    today_refresh.assert_awaited_once_with(uid)
    regen.assert_not_awaited()


async def test_k001_none_and_future_dates_do_nothing(monkeypatch):
    regen = AsyncMock()
    today_refresh = AsyncMock()
    monkeypatch.setattr("services.snapshot_service.regenerate_snapshots", regen)
    monkeypatch.setattr("services.snapshot_service.refresh_today_snapshot", today_refresh)
    uid = uuid.uuid4()

    snapshot_trigger.trigger_snapshot_regen(uid, None)
    snapshot_trigger.trigger_snapshot_regen(uid, date.today() + timedelta(days=1))
    await _drain_trigger_tasks()

    regen.assert_not_awaited()
    today_refresh.assert_not_awaited()


async def test_k001_second_today_booking_runs_again(monkeypatch):
    """Trifft eine zweite Buchung ein, während der Task läuft, hat er das Ledger
    vielleicht schon gelesen: er läuft danach noch einmal."""
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def slow_refresh(user_id):
        calls.append(user_id)
        started.set()
        await release.wait()

    monkeypatch.setattr("services.snapshot_service.refresh_today_snapshot", slow_refresh)
    uid = uuid.uuid4()

    snapshot_trigger.trigger_snapshot_regen(uid, date.today())
    await asyncio.wait_for(started.wait(), timeout=5)
    snapshot_trigger.trigger_snapshot_regen(uid, date.today())
    snapshot_trigger.trigger_snapshot_regen(uid, date.today())
    release.set()
    await _drain_trigger_tasks()

    assert calls == [uid, uid]
    assert uid not in snapshot_trigger._today_running
    assert uid not in snapshot_trigger._today_rerun


# --- K006 -------------------------------------------------------------------


async def test_k006_regen_refuses_span_beyond_cap(db, monkeypatch):
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket)
    too_old = date.today() - timedelta(days=MAX_REGEN_SPAN_DAYS + 1)
    db.add(_buy(user, pos, too_old, 10, 100, 1000))
    db.add(PortfolioSnapshot(
        user_id=user.id, date=date.today() - timedelta(days=3),
        total_value_chf=Decimal("1234"), cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
    ))
    await db.commit()

    def _no_download(*args, **kwargs):
        raise AssertionError("yf_download darf bei überschrittener Spanne nicht laufen")

    monkeypatch.setattr("services.snapshot_service.yf_download", _no_download)

    result = await regenerate_snapshots(db, user.id)

    assert result["snapshots_created"] == 0
    assert str(MAX_REGEN_SPAN_DAYS) in result["error"]
    snaps = await _snapshots(db, user.id)
    assert [float(s.total_value_chf) for s in snaps] == [1234.0]


async def test_k006_span_at_cap_still_runs(db, monkeypatch):
    """Genau MAX_REGEN_SPAN_DAYS ist erlaubt (Grenze ist «grösser als»)."""
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket)
    db.add(_buy(user, pos, date.today() - timedelta(days=30), 10, 100, 1000))
    await db.commit()
    monkeypatch.setattr(snapshot_service, "MAX_REGEN_SPAN_DAYS", 30)
    monkeypatch.setattr("services.snapshot_service.yf_download", _fake_yf({"AAA": 110.0}))
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    result = await regenerate_snapshots(db, user.id)

    assert "error" not in result
    assert result["snapshots_created"] > 0


# --- K007 / K056 ------------------------------------------------------------


async def test_k007_replay_runs_off_the_event_loop_with_plain_data(db, monkeypatch):
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket)
    db.add(_buy(user, pos, date.today() - timedelta(days=20), 10, 100, 1000))
    await db.commit()
    monkeypatch.setattr("services.snapshot_service.yf_download", _fake_yf({"AAA": 110.0}))
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    loop_thread = threading.get_ident()
    seen = {}
    real_replay = snapshot_service._replay_ledger
    real_series = snapshot_service._build_close_series

    def spy_replay(**kwargs):
        seen["replay_thread"] = threading.get_ident()
        seen["positions"] = list(kwargs["positions"].values())
        seen["txns"] = kwargs["all_txns"]
        return real_replay(**kwargs)

    def spy_series(*args):
        seen["series_thread"] = threading.get_ident()
        return real_series(*args)

    monkeypatch.setattr(snapshot_service, "_replay_ledger", spy_replay)
    monkeypatch.setattr(snapshot_service, "_build_close_series", spy_series)

    result = await regenerate_snapshots(db, user.id)

    assert result["snapshots_created"] > 0
    assert seen["replay_thread"] != loop_thread
    assert seen["series_thread"] != loop_thread
    # Kopien statt ORM-Objekten: im Thread darf kein Attributzugriff die DB berühren.
    assert all(isinstance(p, SimpleNamespace) for p in seen["positions"])
    assert all(isinstance(t, SimpleNamespace) for t in seen["txns"])


async def test_k056_k076_inserts_are_executemany_with_on_conflict(db, monkeypatch):
    """Mehr als 500 Zeilen je Tabelle: vorher je 500 Zeilen ein eigenes
    VALUES-Statement, der Bucket-Insert ohne ON CONFLICT."""
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket)
    db.add(_buy(user, pos, date.today() - timedelta(days=800), 10, 100, 1000))
    await db.commit()
    monkeypatch.setattr("services.snapshot_service.yf_download", _fake_yf({"AAA": 110.0}))
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    with capture_sql() as statements:
        result = await regenerate_snapshots(db, user.id)

    assert result["snapshots_created"] > 500
    assert result["bucket_snapshots_created"] > 500
    for table in ("portfolio_snapshots", "bucket_snapshots"):
        inserts = [(s, many) for s, many in statements if s.startswith(f"INSERT INTO {table}")]
        assert len(inserts) == 1, table
        statement, many = inserts[0]
        assert many is True, table
        assert "ON CONFLICT" in statement, table

    count = len((await db.execute(
        select(BucketSnapshot.id).where(BucketSnapshot.user_id == user.id)
    )).all())
    assert count == result["bucket_snapshots_created"]


# --- K076 -------------------------------------------------------------------


class _FakePgSession:
    """Session-Attrappe mit Postgres-Dialekt für den Sperr-Helfer."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.calls = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return SimpleNamespace(scalar=lambda: self._answers.pop(0))


async def test_k076_lock_is_noop_on_sqlite(db):
    with capture_sql() as statements:
        await _lock_user_snapshots(db, uuid.uuid4())
    assert statements == []


async def test_k076_lock_polls_until_acquired(monkeypatch):
    monkeypatch.setattr(snapshot_service, "_SNAPSHOT_LOCK_POLL_SECONDS", 0)
    uid = uuid.uuid4()
    session = _FakePgSession([False, False, True])

    await _lock_user_snapshots(session, uid)

    assert len(session.calls) == 3
    sql, params = session.calls[0]
    assert "pg_try_advisory_xact_lock" in sql
    assert params["ns"] == snapshot_service._SNAPSHOT_LOCK_NAMESPACE
    assert params["key"] == int.from_bytes(uid.bytes[:4], "big", signed=True)
    assert -2**31 <= params["key"] < 2**31


async def test_k076_lock_without_wait_raises_busy():
    session = _FakePgSession([False])
    with pytest.raises(SnapshotLockBusy):
        await _lock_user_snapshots(session, uuid.uuid4(), wait=False)
    assert len(session.calls) == 1


async def test_k076_lock_gives_up_after_max_wait(monkeypatch):
    monkeypatch.setattr(snapshot_service, "_SNAPSHOT_LOCK_POLL_SECONDS", 0)
    monkeypatch.setattr(snapshot_service, "_SNAPSHOT_LOCK_MAX_WAIT_SECONDS", 0)
    session = _FakePgSession([False])
    with pytest.raises(SnapshotLockBusy):
        await _lock_user_snapshots(session, uuid.uuid4())


async def test_k076_regen_locks_before_reading_the_ledger(db, monkeypatch):
    user, bucket = await _user_with_bucket(db)
    pos = await _position(db, user, bucket)
    db.add(_buy(user, pos, date.today() - timedelta(days=5), 10, 100, 1000))
    await db.commit()
    monkeypatch.setattr("services.snapshot_service.yf_download", _fake_yf({"AAA": 110.0}))
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    lock_calls = []

    with capture_sql() as statements:
        async def fake_lock(session, user_id, *, wait=True):
            lock_calls.append((user_id, wait, len(statements)))

        monkeypatch.setattr(snapshot_service, "_lock_user_snapshots", fake_lock)
        await regenerate_snapshots(db, user.id, wait_for_lock=False)

    # Genau eine Sperre, vor dem ersten Statement, mit dem gewünschten Wartemodus.
    assert lock_calls == [(user.id, False, 0)]


async def test_k076_daily_snapshot_takes_the_same_lock(db, monkeypatch):
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})
    user, bucket = await _user_with_bucket(db)
    await _position(db, user, bucket, current_price=Decimal("100"))
    lock_calls = []

    with capture_sql() as statements:
        async def fake_lock(session, user_id, *, wait=True):
            lock_calls.append((user_id, len(statements)))

        monkeypatch.setattr(snapshot_service, "_lock_user_snapshots", fake_lock)
        await _record_user_snapshot(db, user.id, date.today())

    assert lock_calls == [(user.id, 0)]


# --- K079 -------------------------------------------------------------------


async def _regen_depot(db, tickers=("AAA", "BBB")):
    user, bucket = await _user_with_bucket(db)
    for ticker in tickers:
        pos = await _position(db, user, bucket, ticker=ticker)
        db.add(_buy(user, pos, date.today() - timedelta(days=10), 10, 100, 1000))
    db.add(PortfolioSnapshot(
        user_id=user.id, date=date.today() - timedelta(days=3),
        total_value_chf=Decimal("4321"), cash_chf=Decimal("0"), net_cash_flow_chf=Decimal("0"),
    ))
    await db.commit()
    return user


def _price_row(ticker, days_ago, source="yahoo") -> PriceCache:
    return PriceCache(
        ticker=ticker, date=date.today() - timedelta(days=days_ago),
        close=Decimal("100"), currency="CHF", source=source,
    )


async def test_k079_all_series_empty_keeps_old_snapshots(db, monkeypatch):
    """Yahoo-Sperre: yf_download wirft nicht, es liefert leere Reihen. price_cache
    kennt die Ticker — der Regen darf die Historie nicht mit Einstandswerten
    überschreiben."""
    user = await _regen_depot(db)
    db.add(_price_row("AAA", days_ago=200))
    await db.commit()
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"AAA": None, "BBB": None})
    )
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    result = await regenerate_snapshots(db, user.id)

    assert result["snapshots_created"] == 0
    assert "error" in result
    assert result["missing_price_series"] == ["AAA"]
    snaps = await _snapshots(db, user.id)
    assert [float(s.total_value_chf) for s in snaps] == [4321.0]


async def test_k079_held_ticker_with_fresh_price_but_no_series_aborts(db, monkeypatch):
    user = await _regen_depot(db)
    db.add(_price_row("BBB", days_ago=1))
    await db.commit()
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"AAA": 110.0, "BBB": None})
    )
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    result = await regenerate_snapshots(db, user.id)

    assert result["snapshots_created"] == 0
    assert result["missing_price_series"] == ["BBB"]
    snaps = await _snapshots(db, user.id)
    assert [float(s.total_value_chf) for s in snaps] == [4321.0]


@pytest.mark.parametrize("row", [None, ("BBB", 30, "yahoo"), ("BBB", 1, "metal_spot")])
async def test_k079_ticker_unknown_to_yahoo_does_not_block(db, monkeypatch, row):
    """Kein Beleg, dass Yahoo den Ticker führt (kein Kurs, alter Kurs, fremde
    Quelle): der Regen läuft wie bisher und bewertet mit dem Einstandswert."""
    user = await _regen_depot(db)
    if row:
        db.add(_price_row(*row))
        await db.commit()
    monkeypatch.setattr(
        "services.snapshot_service.yf_download", _fake_yf({"AAA": 110.0, "BBB": None})
    )
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    result = await regenerate_snapshots(db, user.id)

    assert "error" not in result
    assert result["snapshots_created"] > 0
    snaps = await _snapshots(db, user.id)
    # AAA zum Kurs (10 x 110), BBB zum Einstandswert (1000).
    assert float(snaps[-1].total_value_chf) == 2100.0


async def test_k079_never_priced_depot_still_regenerates(db, monkeypatch):
    """Alle Reihen leer und price_cache kennt keinen der Ticker (nur manuell
    bepreiste Titel): kein Abbruch, sonst liefe für dieses Depot nie ein Regen."""
    user = await _regen_depot(db, tickers=("MANUAL1",))
    monkeypatch.setattr("services.snapshot_service.yf_download", _fake_yf({"MANUAL1": None}))
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {})

    result = await regenerate_snapshots(db, user.id)

    assert "error" not in result
    snaps = await _snapshots(db, user.id)
    assert float(snaps[-1].total_value_chf) == 1000.0


# --- K131 -------------------------------------------------------------------


async def test_k131_pence_check_runs_in_a_thread(db, monkeypatch):
    """.L-Position ohne Kauf: die Notierungswährung kommt von Yahoo (bei kaltem
    Cache ein blockierender Abruf) und darf nicht auf dem Event-Loop laufen."""
    user, bucket = await _user_with_bucket(db)
    anchor = await _position(db, user, bucket, ticker="AAA")
    db.add(_buy(user, anchor, date.today() - timedelta(days=10), 10, 100, 1000))
    await _position(db, user, bucket, ticker="VUSA.L", shares="5", cost="400", currency="GBP")
    await db.commit()

    loop_thread = threading.get_ident()
    seen_threads = []

    def fake_quote_currency(ticker):
        seen_threads.append(threading.get_ident())
        return "GBp"

    monkeypatch.setattr("services.cache_service._quote_currency", fake_quote_currency)
    monkeypatch.setattr(
        "services.snapshot_service.yf_download",
        _fake_yf({"AAA": 100.0, "VUSA.L": 8000.0, "GBPCHF=X": 1.1}),
    )
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"GBP": 1.1})

    result = await regenerate_snapshots(db, user.id)

    assert "error" not in result
    assert seen_threads and all(t != loop_thread for t in seen_threads)
    snaps = await _snapshots(db, user.id)
    # AAA 10 x 100 + VUSA.L 5 x (8000 Pence / 100) x 1.1 = 1000 + 440
    assert float(snaps[-1].total_value_chf) == pytest.approx(1440.0, abs=0.01)


# --- K080 -------------------------------------------------------------------


async def _login(client, email):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _user_id(db, email) -> uuid.UUID:
    return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def test_k080_regenerate_endpoint_runs_through_the_guard(client, db, monkeypatch):
    headers = await _login(client, "k080a@example.com")
    uid = await _user_id(db, "k080a@example.com")
    regen = AsyncMock(return_value={"snapshots_created": 7})
    monkeypatch.setattr("services.snapshot_service.regenerate_snapshots", regen)

    res = await client.post("/api/portfolio/regenerate-snapshots", headers=headers)

    assert res.status_code == 200
    assert res.json() == {"snapshots_created": 7}
    regen.assert_awaited_once()
    assert regen.await_args.args[1] == uid
    assert regen.await_args.kwargs == {"wait_for_lock": False}
    assert uid not in snapshot_trigger._running_users


async def test_k080_regenerate_endpoint_answers_409_while_running(client, db, monkeypatch):
    headers = await _login(client, "k080b@example.com")
    uid = await _user_id(db, "k080b@example.com")
    regen = AsyncMock(return_value={"snapshots_created": 7})
    monkeypatch.setattr("services.snapshot_service.regenerate_snapshots", regen)

    snapshot_trigger._running_users.add(uid)
    try:
        res = await client.post("/api/portfolio/regenerate-snapshots", headers=headers)
    finally:
        snapshot_trigger._running_users.discard(uid)

    assert res.status_code == 409
    regen.assert_not_awaited()


async def test_k080_regenerate_endpoint_answers_409_when_other_process_holds_lock(
    client, db, monkeypatch,
):
    headers = await _login(client, "k080c@example.com")
    uid = await _user_id(db, "k080c@example.com")
    monkeypatch.setattr(
        "services.snapshot_service.regenerate_snapshots",
        AsyncMock(side_effect=SnapshotLockBusy("busy")),
    )

    res = await client.post("/api/portfolio/regenerate-snapshots", headers=headers)

    assert res.status_code == 409
    assert uid not in snapshot_trigger._running_users


async def test_k080_trigger_during_foreground_run_queues_a_rerun(monkeypatch):
    """Eine Buchung während eines Vordergrund-Regens geht nicht verloren: nach
    dessen Ende läuft ein weiterer Regen."""
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def slow_regen(db, user_id, **kwargs):
        calls.append(kwargs)
        started.set()
        await release.wait()
        return {"snapshots_created": 1}

    monkeypatch.setattr("services.snapshot_service.regenerate_snapshots", slow_regen)
    uid = uuid.uuid4()

    foreground = asyncio.create_task(snapshot_trigger.run_snapshot_regen(uid))
    await asyncio.wait_for(started.wait(), timeout=5)
    assert await snapshot_trigger.run_snapshot_regen(uid) is None
    snapshot_trigger.trigger_snapshot_regen(uid, date.today() - timedelta(days=30))
    release.set()
    assert await foreground == {"snapshots_created": 1}
    await _drain_trigger_tasks()

    assert calls == [{"wait_for_lock": False}, {}]
    assert uid not in snapshot_trigger._running_users
