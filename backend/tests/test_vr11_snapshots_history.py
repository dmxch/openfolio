"""Vollreview 11/2026: Portfolio-Historie.

K007  Reihenaufbau und Tages-Replay in einem Thread
K008  ein Lauf je Schlüssel, höchstens zwei Kurs-Downloads, nur gehaltene Ticker
K016  DB-Connection vor dem Download zurückgeben
K024  Fenster vor dem Cache-Schlüssel klemmen, Benchmark-Allowlist
K029  Enddatum in der Zukunft
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from db import async_session
from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services import history_service
from services.bucket_service import create_bucket, create_system_buckets
from services.history_service import _pids_held_in_window, get_portfolio_history

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


class _YfSpy:
    """yf_download-Attrappe: zählt Aufrufe und gleichzeitige Läufe."""

    def __init__(self, delay: float = 0.0, db=None):
        self.delay = delay
        self.db = db
        self.calls: list[list[str]] = []
        self.threads: list[int] = []
        self.in_transaction: list[bool] = []
        self.max_parallel = 0
        self._running = 0
        self._lock = threading.Lock()

    def __call__(self, all_tickers, **kwargs):
        with self._lock:
            self.calls.append(sorted(all_tickers))
            self.threads.append(threading.get_ident())
            if self.db is not None:
                self.in_transaction.append(self.db.in_transaction())
            self._running += 1
            self.max_parallel = max(self.max_parallel, self._running)
        try:
            if self.delay:
                time.sleep(self.delay)
            cal = pd.date_range(kwargs["start"], kwargs["end"], freq="D")
            cols = {("Close", t): np.full(len(cal), 100.0) for t in all_tickers}
            df = pd.DataFrame(cols, index=cal)
            df.columns = pd.MultiIndex.from_tuples(df.columns)
            return df
        finally:
            with self._lock:
                self._running -= 1


async def _depot(db, inception: date, with_old: bool = False):
    """NESN.SW seit ``inception``; optional OLD.SW, gekauft und 30 Tage später verkauft."""
    user = User(email=f"hi{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()

    async def _pos(ticker, shares, active=True):
        pos = Position(
            user_id=user.id, bucket_id=bucket.id, ticker=ticker, name=ticker,
            type=AssetType.stock, currency="CHF", shares=Decimal(shares),
            cost_basis_chf=Decimal("10000"), is_active=active,
        )
        db.add(pos)
        await db.commit()
        await db.refresh(pos)
        return pos

    def _txn(pos, ttype, d, shares):
        return Transaction(
            user_id=user.id, position_id=pos.id, type=ttype, date=d,
            shares=Decimal(shares), price_per_share=Decimal("100"),
            currency="CHF", total_chf=Decimal(shares) * 100,
        )

    nesn = await _pos("NESN.SW", "100")
    db.add(_txn(nesn, TransactionType.buy, inception, "100"))
    if with_old:
        old = await _pos("OLD.SW", "0", active=False)
        db.add(_txn(old, TransactionType.buy, inception, "50"))
        db.add(_txn(old, TransactionType.sell, inception + timedelta(days=30), "50"))
    await db.commit()
    return user


def _patch(monkeypatch, spy):
    monkeypatch.setattr("services.history_service.yf_download", spy)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(
        "services.benchmark_service.benchmark_quote_currency", lambda t: "CHF"
    )


# --- K029 -------------------------------------------------------------------


async def test_k029_end_in_the_future_is_clamped_to_today(db, monkeypatch):
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy()
    _patch(monkeypatch, spy)

    hist = await get_portfolio_history(
        db, today - timedelta(days=20), date(9999, 12, 30), user_id=user.id
    )

    assert hist["data"][-1]["date"] == today.isoformat()
    assert len(hist["data"]) == 21


async def test_k029_start_after_end_is_empty_without_download(db, monkeypatch):
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy()
    _patch(monkeypatch, spy)

    hist = await get_portfolio_history(
        db, today - timedelta(days=5), today - timedelta(days=10), user_id=user.id
    )
    future = await get_portfolio_history(
        db, today + timedelta(days=5), today + timedelta(days=10), user_id=user.id
    )

    assert hist == history_service._leeres_ergebnis()
    assert future == history_service._leeres_ergebnis()
    assert spy.calls == []


# --- K024 -------------------------------------------------------------------


async def test_k024_windows_before_inception_share_one_cache_entry(db, monkeypatch):
    """start ist frei wählbar. Jeder Wert vor der Inception ergibt dieselbe Reihe
    und muss denselben Schlüssel treffen, sonst erzwingt er einen neuen
    Kurs-Download."""
    today = date.today()
    inception = today - timedelta(days=40)
    user = await _depot(db, inception)
    spy = _YfSpy()
    _patch(monkeypatch, spy)

    results = [
        await get_portfolio_history(db, inception - timedelta(days=offset), end, user_id=user.id)
        for offset, end in ((10, today), (500, today), (9000, today + timedelta(days=400)))
    ]

    assert len(spy.calls) == 1
    assert results[0]["data"][0]["date"] == inception.isoformat()
    assert results[1] == results[0] and results[2] == results[0]


async def test_k024_history_route_rejects_benchmark_outside_allowlist(client):
    await client.post("/api/auth/register", json={"email": "k024@example.com", "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": "k024@example.com", "password": TEST_PASSWORD})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    for path in ("/api/portfolio/history", "/api/portfolio/risk-metrics"):
        res = await client.get(f"{path}?benchmark=AAPL", headers=headers)
        assert res.status_code == 400, path
        assert res.json()["detail"] == "Ungültiger Benchmark-Ticker"

    # Werte der Allowlist und der Default bleiben erlaubt (leeres Depot: leere Antwort).
    res = await client.get("/api/portfolio/history?benchmark=MTUM", headers=headers)
    assert res.status_code == 200
    res = await client.get("/api/portfolio/history", headers=headers)
    assert res.status_code == 200


# --- K008 -------------------------------------------------------------------


async def test_k008_concurrent_calls_share_one_computation(db, monkeypatch):
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy(delay=0.15)
    _patch(monkeypatch, spy)

    async def _call():
        async with async_session() as session:
            return await get_portfolio_history(
                session, today - timedelta(days=30), today, user_id=user.id
            )

    results = await asyncio.gather(*[_call() for _ in range(4)])

    assert len(spy.calls) == 1
    assert all(r == results[0] for r in results)
    assert results[0]["data"]
    assert history_service.single_flight.__module__ == "services.portfolio_service"


async def test_k008_at_most_two_downloads_run_in_parallel(db, monkeypatch):
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy(delay=0.15)
    _patch(monkeypatch, spy)

    variants = [
        dict(benchmark="^GSPC"), dict(benchmark="^SSMI"), dict(benchmark="URTH"),
        dict(benchmark="^GSPC", downsample=False), dict(benchmark="^GSPC", liquid=True),
    ]

    async def _call(kwargs):
        async with async_session() as session:
            return await get_portfolio_history(
                session, today - timedelta(days=30), today, user_id=user.id, **kwargs
            )

    results = await asyncio.gather(*[_call(v) for v in variants])

    assert len(spy.calls) == 5
    assert spy.max_parallel == 2
    assert all(r["data"] for r in results)


async def test_k008_no_free_slot_returns_empty_and_is_not_cached(db, monkeypatch):
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy()
    _patch(monkeypatch, spy)
    monkeypatch.setattr(history_service, "_DOWNLOAD_SLOT_WAIT_SECONDS", 0.1)

    slots = history_service._YF_DOWNLOAD_SLOTS
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    try:
        busy = await get_portfolio_history(db, today - timedelta(days=30), today, user_id=user.id)
    finally:
        slots.release()
        slots.release()

    assert busy == history_service._leeres_ergebnis()
    assert spy.calls == []
    # Der Platz ist wieder frei und das leere Ergebnis liegt nicht im Cache.
    again = await get_portfolio_history(db, today - timedelta(days=30), today, user_id=user.id)
    assert again["data"]
    assert len(spy.calls) == 1


async def test_k008_download_slot_is_released_after_failure(db, monkeypatch):
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))

    def boom(*args, **kwargs):
        raise RuntimeError("yahoo down")

    _patch(monkeypatch, boom)

    hist = await get_portfolio_history(db, today - timedelta(days=30), today, user_id=user.id)

    assert hist == history_service._leeres_ergebnis()
    slots = history_service._YF_DOWNLOAD_SLOTS
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    slots.release()
    slots.release()


async def test_k008_only_tickers_held_in_window_are_downloaded(db, monkeypatch):
    """OLD.SW wurde 30 Tage nach der Inception verkauft. Ein Fenster danach
    braucht seinen Kurs nicht; eines, das die Haltezeit schneidet, schon."""
    today = date.today()
    inception = today - timedelta(days=200)
    user = await _depot(db, inception, with_old=True)
    spy = _YfSpy()
    _patch(monkeypatch, spy)

    late = await get_portfolio_history(db, today - timedelta(days=60), today, user_id=user.id)
    full = await get_portfolio_history(db, inception, today, user_id=user.id)

    assert spy.calls[0] == ["NESN.SW", "^GSPC"]
    assert spy.calls[1] == ["NESN.SW", "OLD.SW", "^GSPC"]
    # 100 x 100 im späten Fenster; am Inception-Tag zusätzlich 50 x 100 für OLD.SW.
    assert late["data"][0]["value"] == 10000.0
    assert full["data"][0]["value"] == 15000.0
    assert full["data"][-1]["value"] == 10000.0


def test_k008_pids_held_in_window():
    d = date(2025, 1, 1)
    changes = {
        d: [("a", 10.0), ("b", 5.0)],
        d + timedelta(days=10): [("b", -5.0)],             # b vor dem Fenster verkauft
        d + timedelta(days=40): [("c", 3.0)],              # c im Fenster gekauft
        d + timedelta(days=45): [("c", -3.0), ("e", 1.0), ("e", -1.0)],  # e nur innerhalb eines Tages
        d + timedelta(days=90): [("f", 7.0)],              # f nach dem Fenster
    }
    start, end = d + timedelta(days=30), d + timedelta(days=60)

    assert _pids_held_in_window(changes, {"seed": 2.0}, start, end) == {"a", "c", "seed"}
    # Fenster ohne jede Änderung: der Bestand zu Fensterbeginn zählt.
    assert _pids_held_in_window(changes, {}, d + timedelta(days=50), d + timedelta(days=60)) == {"a"}
    # Fenster vor der ersten Änderung: nichts gehalten.
    assert _pids_held_in_window(changes, {}, d - timedelta(days=9), d - timedelta(days=1)) == set()


# --- K007 / K016 ------------------------------------------------------------


async def test_k007_series_and_replay_run_off_the_event_loop(db, monkeypatch):
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy()
    _patch(monkeypatch, spy)

    loop_thread = threading.get_ident()
    seen = {}
    real_replay = history_service._replay_history
    real_series = history_service._build_price_series

    def spy_replay(**kwargs):
        seen["replay"] = threading.get_ident()
        seen["positions"] = list(kwargs["positions"].values())
        return real_replay(**kwargs)

    def spy_series(*args):
        seen["series"] = threading.get_ident()
        return real_series(*args)

    monkeypatch.setattr(history_service, "_replay_history", spy_replay)
    monkeypatch.setattr(history_service, "_build_price_series", spy_series)

    hist = await get_portfolio_history(db, today - timedelta(days=30), today, user_id=user.id)

    assert hist["data"]
    assert seen["replay"] != loop_thread
    assert seen["series"] != loop_thread
    assert not any(isinstance(p, Position) for p in seen["positions"])


async def test_k016_connection_is_released_before_the_download(db, monkeypatch):
    """Während des Kurs-Downloads darf die Session keine Transaktion offen halten:
    sonst belegt jeder wartende Request eine Connection aus dem Pool."""
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy(db=db)
    _patch(monkeypatch, spy)

    hist = await get_portfolio_history(db, today - timedelta(days=30), today, user_id=user.id)

    assert hist["data"]
    assert spy.in_transaction == [False]


async def test_k016_pending_changes_are_not_committed(db, monkeypatch):
    """Trägt die Session ungeschriebene Änderungen, gehört die Transaktion dem
    Aufrufer: kein Commit durch die Historie."""
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))
    spy = _YfSpy(db=db)
    _patch(monkeypatch, spy)

    pending = UserSettings(user_id=uuid.uuid4(), noticed_buckets_migration=True)
    with db.no_autoflush:
        db.add(pending)
        hist = await get_portfolio_history(db, today - timedelta(days=30), today, user_id=user.id)
        assert hist["data"]
        assert spy.in_transaction == [True]
        assert pending in db.new
    await db.rollback()


# --- Ausfall ----------------------------------------------------------------


async def test_result_without_any_price_series_is_cached_only_briefly(db, monkeypatch):
    """Liefert Yahoo keine einzige Reihe, zeigt die Antwort Ersatzwerte. Sie darf
    nicht 15 Minuten im Cache stehen."""
    today = date.today()
    user = await _depot(db, today - timedelta(days=40))

    def empty_yf(all_tickers, **kwargs):
        cal = pd.date_range(kwargs["start"], kwargs["end"], freq="D")
        df = pd.DataFrame({("Close", t): np.full(len(cal), np.nan) for t in all_tickers}, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    ttls = []
    real_set = history_service.cache.set

    def spy_set(key, value, ttl=900):
        if key.startswith("portfolio_history:"):
            ttls.append(ttl)
        return real_set(key, value, ttl)

    monkeypatch.setattr("services.cache.set", spy_set)
    _patch(monkeypatch, empty_yf)
    await get_portfolio_history(db, today - timedelta(days=30), today, user_id=user.id)

    _patch(monkeypatch, _YfSpy())
    await get_portfolio_history(db, today - timedelta(days=29), today, user_id=user.id)

    assert ttls == [history_service.DEGRADED_CACHE_TTL, history_service.CACHE_TTL]
