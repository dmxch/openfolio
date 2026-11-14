"""Vollreview 11/2026, Fixer «analysis»: Earnings und EPS-Scanner.

K013 (Session je Ticker, kein Semaphor), K053 (Fehler 24 h negativ gecacht),
K004 (Scanner lädt die ganze Tabelle), K129 (ein Statement je Quartal).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from limits import parse as parse_limit
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from models.eps_quarterly import EpsQuarterly
from services import earnings_service as es
from services import eps_scanner_service as eps


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


# --- K053: Fehler und «kein Termin» getrennt cachen ---------------------------


class TestK053EarningsDateCache:
    def _setup(self, monkeypatch, calendar):
        cache = _RecordingCache()
        calls: list[str] = []

        def _attr(ticker, attr):
            calls.append(ticker)
            if isinstance(calendar, Exception):
                raise calendar
            return calendar

        monkeypatch.setattr(es, "cache", cache)
        monkeypatch.setattr(es, "yf_ticker_attr", _attr)
        return cache, calls

    def test_error_is_cached_for_five_minutes_only(self, monkeypatch):
        cache, calls = self._setup(monkeypatch, RuntimeError("429 Too Many Requests"))

        assert es.get_next_earnings_date("NVDA") is None
        assert es.get_next_earnings_date("NVDA") is None

        assert calls == ["NVDA"]
        assert cache.ttls["earnings:NVDA"] == 300, "ein Fehler darf nicht 24 h gelten"

    def test_no_date_keeps_24_hours(self, monkeypatch):
        cache, _calls = self._setup(monkeypatch, {"Earnings Date": []})

        assert es.get_next_earnings_date("NODATE") is None

        assert cache.store["earnings:NODATE"] == "none"
        assert cache.ttls["earnings:NODATE"] == 86400

    def test_hit_is_stored_json_safe_and_read_back(self, monkeypatch):
        upcoming = date.today() + timedelta(days=9)
        cache, calls = self._setup(monkeypatch, {"Earnings Date": [upcoming]})

        first = es.get_next_earnings_date("AAPL")
        stored = cache.store["earnings:AAPL"]
        # Nur JSON-fähige Werte erreichen Redis; ein datetime bliebe prozesslokal.
        assert isinstance(stored, str)
        assert json.loads(json.dumps(stored)) == stored

        second = es.get_next_earnings_date("AAPL")
        assert calls == ["AAPL"]
        assert first == second == datetime(upcoming.year, upcoming.month, upcoming.day)

    def test_timezone_aware_date_survives_the_cache(self, monkeypatch):
        upcoming = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=3)
        _cache, _calls = self._setup(monkeypatch, {"Earnings Date": [upcoming]})

        assert es.get_next_earnings_date("TZ") == upcoming
        assert es.get_next_earnings_date("TZ") == upcoming

    async def test_rich_lookup_failure_is_a_short_lived_sentinel(self, monkeypatch):
        cache = _RecordingCache()
        cache.set("earnings:FLAKY", "error", ttl=300)
        monkeypatch.setattr(es, "cache", cache)
        user = uuid.uuid4()

        with patch.object(es, "_fetch_finnhub_earnings", new=AsyncMock(return_value=None)), \
             patch.object(es, "get_next_earnings_date", return_value=None):
            result = await es._fetch_rich_earnings("FLAKY", None, user, api_key=None)

        assert result == {"__lookup_failed__": True}
        assert cache.ttls[f"earnings:rich:{user}:FLAKY:v1"] == 300

    async def test_portfolio_reports_lookup_failure_as_warning(self):
        positions = [SimpleNamespace(
            ticker="FLAKY", name="Flaky Inc", yfinance_ticker=None,
            type=SimpleNamespace(value="stock"),
        )]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: positions),
        )))

        with patch("services.settings_service.get_user_api_key", new=AsyncMock(return_value=None)), \
             patch.object(es, "_fetch_rich_earnings",
                          new=AsyncMock(return_value={"__lookup_failed__": True})):
            result = await es.get_upcoming_earnings_for_portfolio(db, uuid.uuid4(), days=7)

        assert result["warnings"] == ["earnings_fetch_failed:FLAKY"]
        assert result["no_earnings_in_window"] == []
        assert es.upcoming_earnings_cache_ttl(result) == 300

    def test_cache_ttl_helper_keeps_12h_for_clean_results(self):
        clean = {"warnings": ["finnhub_no_coverage:EIMI.L"]}
        assert es.upcoming_earnings_cache_ttl(clean) == 43200
        assert es.upcoming_earnings_cache_ttl({}) == 43200


# --- K013: Key einmal lesen, keine Session je Ticker, Semaphore(3) ------------


def _portfolio_db(tickers: list[str]):
    positions = [
        SimpleNamespace(ticker=t, name=t, yfinance_ticker=None, type=SimpleNamespace(value="stock"))
        for t in tickers
    ]
    return SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: positions),
    )))


class TestK013UpcomingEarnings:
    async def test_key_is_read_once_and_passed_to_every_ticker(self):
        tickers = [f"T{i}" for i in range(8)]
        seen: list[tuple] = []

        async def _fake_rich(ticker, db, user_id, api_key=None):
            seen.append((ticker, db, api_key))
            return None

        key_mock = AsyncMock(return_value="finnhub-key")
        with patch("services.settings_service.get_user_api_key", new=key_mock), \
             patch.object(es, "_fetch_rich_earnings", side_effect=_fake_rich):
            await es.get_upcoming_earnings_for_portfolio(_portfolio_db(tickers), uuid.uuid4())

        assert key_mock.await_count == 1
        assert sorted(t for t, _db, _key in seen) == tickers
        # Kein Branch bekommt eine Session — der Key reist als Argument mit.
        assert {db for _t, db, _key in seen} == {None}
        assert {key for _t, _db, key in seen} == {"finnhub-key"}

    async def test_at_most_three_fetches_run_at_once(self):
        active = 0
        peak = 0

        async def _fake_rich(ticker, db, user_id, api_key=None):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return None

        with patch("services.settings_service.get_user_api_key", new=AsyncMock(return_value=None)), \
             patch.object(es, "_fetch_rich_earnings", side_effect=_fake_rich):
            await es.get_upcoming_earnings_for_portfolio(
                _portfolio_db([f"S{i}" for i in range(12)]), uuid.uuid4()
            )

        assert peak == 3

    def test_module_opens_no_session_of_its_own(self):
        assert not hasattr(es, "async_session")

    async def test_finnhub_fetch_with_given_key_skips_the_db(self):
        key_mock = AsyncMock(return_value="from-db")
        with patch("services.settings_service.get_user_api_key", new=key_mock):
            # None = «kein Key konfiguriert»: weder DB-Zugriff noch HTTP-Call.
            assert await es._fetch_finnhub_earnings("JNJ", None, uuid.uuid4(), api_key=None) is None
        key_mock.assert_not_awaited()


# --- K004: nur die jüngsten Quartale je Ticker laden --------------------------


def _quarter_end(i: int) -> date:
    """i-tes Quartalsende ab 2015-03-31, aufsteigend."""
    year, q = divmod(i, 4)
    month = (q + 1) * 3
    day = 31 if month in (3, 12) else 30
    return date(2015 + year, month, day)


async def _seed_quarters(db, ticker: str, count: int) -> None:
    now = datetime(2026, 11, 1, 4, 0, 0)
    for i in range(count):
        db.add(EpsQuarterly(
            ticker=ticker, period_end=_quarter_end(i), eps=Decimal(str(1 + i)),
            source="finnhub", fetched_at=now,
        ))
    await db.commit()


class TestK004ScannerLoadsOnlyRecentQuarters:
    async def test_at_most_compute_window_rows_per_ticker_leave_the_db(self, db, monkeypatch):
        await _seed_quarters(db, "LONG", 40)
        await _seed_quarters(db, "SHORT", 3)

        loaded: list[int] = []
        original_execute = db.execute

        async def _spy(stmt, *args, **kwargs):
            if "eps_quarterly" in str(stmt):
                loaded.append(len((await original_execute(stmt, *args, **kwargs)).all()))
            return await original_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(db, "execute", _spy)

        res = await eps.get_scanner_results(db, uuid.uuid4(), min_quarters=2, sort_by="ticker", sort_asc=True)

        assert loaded == [eps.COMPUTE_WINDOW + 3], "LONG darf nur seine 12 jüngsten Quartale laden"
        by_ticker = {r["ticker"]: r for r in res["results"]}
        assert by_ticker["LONG"]["quarter_count"] == eps.COMPUTE_WINDOW
        assert by_ticker["SHORT"]["quarter_count"] == 3
        # Die jüngsten Quartale, aufsteigend: das letzte ist das neueste.
        assert by_ticker["LONG"]["latest_eps"] == 40.0
        assert by_ticker["LONG"]["quarters"][-1]["period_end"] == _quarter_end(39).isoformat()
        periods = [q["period_end"] for q in by_ticker["LONG"]["quarters"]]
        assert periods == sorted(periods)
        assert res["total"] == 2

    async def test_metrics_match_the_pure_calculation(self, db):
        await _seed_quarters(db, "LONG", 40)

        res = await eps.get_scanner_results(db, uuid.uuid4(), min_quarters=2)

        points = [
            eps.QuarterPoint(period_end=_quarter_end(i), eps=float(1 + i), source="finnhub",
                             fetched_at=datetime(2026, 11, 1, 4, 0, 0))
            for i in range(40 - eps.COMPUTE_WINDOW, 40)
        ]
        expected = eps.compute_metrics(points, eps.Thresholds())
        got = res["results"][0]
        for key in ("quarters", "latest_eps", "yoy_growth_pct", "yoy_flag", "streak_count",
                    "super_quarter", "record_quarter", "turnaround", "quarter_count"):
            assert got[key] == expected[key], key
        # Fallback ohne Job-Status: jüngstes fetched_at der geladenen Zeilen.
        assert res["data_refreshed_at"] == "2026-11-01T04:00:00"

    def test_results_route_is_rate_limited(self):
        import api.eps_scanner  # noqa: F401 — registriert die Route am Limiter
        from api.auth import limiter

        registered = limiter._route_limits.get("api.eps_scanner.get_results", [])
        # Welle 3: 60 statt 20 je Minute, das Frontend lädt je Filteränderung neu.
        assert [lim.limit for lim in registered] == [parse_limit("60/minute")]


# --- K129: ein Multi-Row-Upsert der jüngsten 16 Quartale ----------------------


class TestK129UpsertQuarters:
    async def test_only_the_newest_quarters_are_written_in_one_statement(self, db, monkeypatch):
        points = [(_quarter_end(i), Decimal(str(i))) for i in range(40)]
        statements: list[str] = []
        original_execute = db.execute

        async def _spy(stmt, *args, **kwargs):
            statements.append(str(stmt))
            return await original_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(db, "execute", _spy)
        affected = await eps.upsert_quarters(db, "AAA", points, "finnhub")
        monkeypatch.undo()
        await db.commit()

        assert len(statements) == 1
        assert affected == eps.PERSIST_QUARTERS == 16
        rows = (await db.execute(
            select(EpsQuarterly.period_end).where(EpsQuarterly.ticker == "AAA")
            .order_by(EpsQuarterly.period_end)
        )).scalars().all()
        assert rows == [_quarter_end(i) for i in range(24, 40)]

    async def test_existing_quarters_are_updated_not_duplicated(self, db):
        first = [(_quarter_end(i), Decimal("1.00")) for i in range(4)]
        await eps.upsert_quarters(db, "BBB", first, "yfinance")
        await db.commit()

        # Restatement der letzten beiden Quartale plus ein neues.
        second = [(_quarter_end(i), Decimal("2.50")) for i in range(2, 5)]
        await eps.upsert_quarters(db, "BBB", second, "finnhub")
        await db.commit()

        rows = (await db.execute(
            select(EpsQuarterly.period_end, EpsQuarterly.eps, EpsQuarterly.source)
            .where(EpsQuarterly.ticker == "BBB").order_by(EpsQuarterly.period_end)
        )).all()
        assert [(r.period_end, float(r.eps), r.source) for r in rows] == [
            (_quarter_end(0), 1.0, "yfinance"),
            (_quarter_end(1), 1.0, "yfinance"),
            (_quarter_end(2), 2.5, "finnhub"),
            (_quarter_end(3), 2.5, "finnhub"),
            (_quarter_end(4), 2.5, "finnhub"),
        ]

    async def test_duplicate_period_in_one_batch_keeps_the_later_value(self, db):
        points = [
            (_quarter_end(0), Decimal("1.00")),
            (_quarter_end(1), Decimal("3.00")),
            (_quarter_end(0), Decimal("9.00")),
        ]

        assert await eps.upsert_quarters(db, "DUP", points, "finnhub") == 2
        await db.commit()

        count = await db.scalar(
            select(func.count()).select_from(EpsQuarterly).where(EpsQuarterly.ticker == "DUP")
        )
        value = await db.scalar(
            select(EpsQuarterly.eps).where(
                EpsQuarterly.ticker == "DUP", EpsQuarterly.period_end == _quarter_end(0)
            )
        )
        assert count == 2
        assert float(value) == 9.0

    async def test_empty_points_touch_nothing(self, db):
        assert await eps.upsert_quarters(db, "NONE", [], "finnhub") == 0

    def test_postgres_statement_targets_the_named_constraint(self):
        rows = [
            {"id": uuid.uuid4(), "ticker": "PG", "period_end": _quarter_end(i),
             "eps": Decimal("1"), "source": "finnhub", "fetched_at": datetime(2026, 11, 1)}
            for i in range(2)
        ]

        compiled = eps._upsert_statement("postgresql", rows).compile(dialect=postgresql.dialect())
        sql = str(compiled)

        assert sql.count("INSERT INTO eps_quarterly") == 1
        assert "ON CONFLICT ON CONSTRAINT uq_eps_quarterly_ticker_period DO UPDATE" in sql
        assert "ticker_m0" in compiled.params and "ticker_m1" in compiled.params
        for column in ("eps", "source", "fetched_at"):
            assert f"{column} = excluded.{column}" in sql
