"""Vollreview 11/2026, Fixer «analysis»: Dividenden.

K009 (kein Negativ-Cache), K015 (Refresh ohne Limit und ohne Sperre),
K057 (Detection lädt je Nutzer und Position), K170/K102 (Digest ohne Escaping).
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from limits import parse as parse_limit

import services.dividend_forecast_service as fc
import services.dividend_service as ds
import services.pending_dividend_service as pds
from constants.limits import RL_REFRESH
from models.position import AssetType, Position, PriceSource
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket


class _RecordingCache:
    """Dict-Cache, der die TTL je Schlüssel festhält."""

    def __init__(self):
        self.store: dict = {}
        self.ttls: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value
        self.ttls[key] = ttl


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await create_system_buckets(db, user.id)
    await get_liquid_default_bucket(db, user.id)
    await db.commit()
    return user


async def _pos(db, user, *, ticker: str, name: str | None = None) -> Position:
    liquid = await get_liquid_default_bucket(db, user.id)
    p = Position(
        user_id=user.id, bucket_id=liquid.id, ticker=ticker, name=name or f"{ticker} Inc",
        type=AssetType.stock, currency="USD", price_source=PriceSource.yahoo,
        shares=Decimal("10"), cost_basis_chf=Decimal("1000"),
    )
    db.add(p)
    await db.commit()
    return p


# --- K009: Negativ-Cache ------------------------------------------------------


class TestK009NegativeCache:
    def _setup(self, monkeypatch, dividends):
        cache = _RecordingCache()
        calls: list[str] = []

        def _attr(ticker, attr):
            if attr == "dividends":
                calls.append(ticker)
                if isinstance(dividends, Exception):
                    raise dividends
                return dividends
            return SimpleNamespace(currency="USD")

        monkeypatch.setattr(ds, "cache", cache)
        monkeypatch.setattr(ds, "yf_ticker_attr", _attr)
        # K116: die Währung kommt über yf_fast_info, nicht mehr über yf_ticker_attr.
        monkeypatch.setattr(ds, "yf_fast_info", lambda t, fields: {"currency": "USD"})
        monkeypatch.setattr(ds, "get_fx_rate", lambda c, t="CHF": 0.9)
        return cache, calls

    def test_ticker_without_dividends_asks_yahoo_once(self, monkeypatch):
        cache, calls = self._setup(monkeypatch, pd.Series([], dtype=float))
        since = date.today() - timedelta(days=365)

        assert ds.fetch_dividends("NODIV", since, shares=10.0) == []
        assert ds.fetch_dividends("NODIV", since, shares=10.0) == []

        assert calls == ["NODIV"], "der zweite Aufruf muss aus dem Negativ-Cache kommen"
        assert list(cache.ttls.values()) == [6 * 3600]

    def test_no_dividend_since_date_is_cached_too(self, monkeypatch):
        old = pd.Series([1.0], index=[pd.Timestamp(date.today() - timedelta(days=900))])
        cache, calls = self._setup(monkeypatch, old)
        since = date.today() - timedelta(days=30)

        assert ds.fetch_dividends("OLDDIV", since, shares=1.0) == []
        assert ds.fetch_dividends("OLDDIV", since, shares=1.0) == []

        assert calls == ["OLDDIV"]
        assert list(cache.ttls.values()) == [6 * 3600]

    def test_error_is_cached_only_briefly(self, monkeypatch):
        cache, calls = self._setup(monkeypatch, RuntimeError("429 Too Many Requests"))
        since = date.today() - timedelta(days=365)

        assert ds.fetch_dividends("BROKEN", since, shares=10.0) == []
        assert ds.fetch_dividends("BROKEN", since, shares=10.0) == []

        assert calls == ["BROKEN"]
        assert list(cache.ttls.values()) == [300]

    def test_hit_keeps_one_hour(self, monkeypatch):
        divs = pd.Series([2.0], index=[pd.Timestamp(date.today() - timedelta(days=30))])
        cache, calls = self._setup(monkeypatch, divs)

        rows = ds.fetch_dividends("PAYER", date.today() - timedelta(days=365), shares=10.0)

        assert rows[0]["total_chf"] == pytest.approx(10 * 2.0 * 0.9)
        assert list(cache.ttls.values()) == [3600]


# --- K015: Refresh mit Limit und Sperre je Nutzer -----------------------------


class TestK015RefreshLock:
    async def test_parallel_refresh_computes_once(self, db, monkeypatch):
        user = await _make_user(db)
        await _pos(db, user, ticker="KO")
        calls: list[str] = []
        started = threading.Event()
        release = threading.Event()

        def _slow_fetch(ticker, since_date, shares, currency="USD"):
            calls.append(ticker)
            started.set()
            release.wait(5)
            return [{"total_chf": 50.0, "dividend_per_share": 0.5, "date": "2026-03-02"}]

        monkeypatch.setattr(fc, "fetch_dividends", _slow_fetch)

        first = asyncio.create_task(fc.compute_dividend_forecast(db, user.id))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            # Der erste Lauf hält die Sperre: der zweite liefert den Cache-Stand
            # (noch leer) und fragt Yahoo nicht.
            second = await fc.compute_dividend_forecast(db, user.id)
            assert second["has_data"] is False
            assert calls == ["KO"]
        finally:
            release.set()
        result = await first
        assert result["forecast_12m_chf"] == 50.0

        # Nach dem Lauf ist die Sperre frei.
        await fc.compute_dividend_forecast(db, user.id)
        assert calls == ["KO", "KO"]

    async def test_lock_is_per_user(self, db, monkeypatch):
        a = await _make_user(db)
        b = await _make_user(db)
        assert fc.cache.acquire_lock(f"dividend_forecast_refresh:{a.id}", 30)
        try:
            monkeypatch.setattr(fc, "fetch_dividends", lambda *args, **kw: [])
            await _pos(db, b, ticker="PEP")
            res = await fc.compute_dividend_forecast(db, b.id)
            assert res["has_data"] is True and res["eligible_count"] == 1
        finally:
            fc.cache.release_lock(f"dividend_forecast_refresh:{a.id}")

    async def test_lock_is_released_after_an_error(self, db, monkeypatch):
        user_id = uuid.uuid4()

        async def _boom(_db, _uid):
            raise RuntimeError("db down")

        monkeypatch.setattr(fc, "_compute_dividend_forecast", _boom)
        with pytest.raises(RuntimeError):
            await fc.compute_dividend_forecast(db, user_id)

        key = f"dividend_forecast_refresh:{user_id}"
        assert fc.cache.acquire_lock(key, 5), "die Sperre darf einen Fehler nicht überleben"
        fc.cache.release_lock(key)

    def test_refresh_route_has_refresh_limit(self):
        import api.analysis  # noqa: F401 — registriert die Route am Limiter
        from api.auth import limiter

        registered = limiter._route_limits.get(
            "api.analysis.dividend_forecast_refresh_endpoint", []
        )
        assert [lim.limit for lim in registered] == [parse_limit(RL_REFRESH)]


# --- K057: ein Yahoo-Abruf je Ticker und Lauf ---------------------------------


class TestK057OneDownloadPerTicker:
    async def test_same_ticker_of_two_users_loads_once(self, db, monkeypatch):
        a = await _make_user(db)
        b = await _make_user(db)
        await _pos(db, a, ticker="AAPL")
        await _pos(db, a, ticker="MSFT")
        await _pos(db, b, ticker="AAPL")
        calls: list[str] = []

        def _fake_download(tickers, **kwargs):
            # K023: der Aufrufer übergibt eine Liste mit genau einem Symbol.
            assert isinstance(tickers, list) and len(tickers) == 1
            calls.append(tickers[0])
            return pd.DataFrame()

        monkeypatch.setattr(pds, "yf_download", _fake_download)

        stats = await pds.run_dividend_detection(db)

        assert sorted(calls) == ["AAPL", "MSFT"], "AAPL darf im Lauf nur einmal laden"
        assert stats["skipped"] == 3
        assert stats["errors"] == 0

    async def test_failed_download_is_not_repeated_but_counted_per_position(self, db, monkeypatch):
        a = await _make_user(db)
        b = await _make_user(db)
        await _pos(db, a, ticker="FAIL")
        await _pos(db, b, ticker="FAIL")
        calls: list[str] = []

        def _fake_download(tickers, **kwargs):
            assert isinstance(tickers, list) and len(tickers) == 1
            calls.append(tickers[0])
            raise RuntimeError("yahoo down")

        monkeypatch.setattr(pds, "yf_download", _fake_download)

        stats = await pds.run_dividend_detection(db)

        assert calls == ["FAIL"]
        assert stats["errors"] == 2


# --- K170 / K102: Digest-Mail escapt Ticker und Name --------------------------


class TestK170DigestEscaping:
    def test_markup_in_name_and_ticker_is_escaped(self):
        pending = SimpleNamespace(ex_date=date(2026, 11, 2), expected_gross_chf=Decimal("12.50"))
        position = SimpleNamespace(
            ticker="<b>EVIL</b>",
            name='<a href="https://phish.example">Konto bestätigen</a>',
        )

        _subject, body = pds._build_digest_email([(pending, position)])

        assert "<a href=\"https://phish.example\">" not in body
        assert "<b>EVIL</b>" not in body
        assert "&lt;a href=&quot;https://phish.example&quot;&gt;Konto bestätigen&lt;/a&gt;" in body
        assert "&lt;b&gt;EVIL&lt;/b&gt;" in body

    def test_missing_name_falls_back_to_escaped_ticker(self):
        pending = SimpleNamespace(ex_date=date(2026, 11, 2), expected_gross_chf=Decimal("1"))
        position = SimpleNamespace(ticker="A&B", name=None)

        _subject, body = pds._build_digest_email([(pending, position)])

        assert body.count("A&amp;B") == 2
        assert "CHF 1.00" in body
