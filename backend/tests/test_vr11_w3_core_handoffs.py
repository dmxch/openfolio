"""Vollreview 11/2026, Welle 3, Fixer «core»: Übergaben aus Welle 2.

K023  yf_download erhält Listen, ein Element je Symbol
K059  Abrufe am Ticker-Lock laufen über yf_to_thread
K116  fast_info-Felder unter dem Lock lesen (yf_fast_info)
K125  Kurse in einem Roundtrip (get_many)
K060  lesende Aufrufer nehmen die Summary aus dem Cache
K157  FTD-Download mit Grössengrenze
K141  Gesamtausfall des Kurs-Feeds
K084 / K145  Job-Health für ETF-Holdings und COT
X02 / B4  Limits je Route
B5    Ticker mit Leerzeichen oder Komma ergibt 422
"""
from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from httpx import AsyncClient
from limits import parse as parse_limit

import worker
from constants.limits import RL_READ, RL_TICKER_READ
from models.position import AssetType, Position
from models.price_cache import PriceCache
from models.watchlist import WatchlistItem
from services import price_staleness_service as staleness

TEST_PASSWORD = "TestPassw0rd!2026"


async def _login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _route_limits(name: str) -> list:
    import main  # noqa: F401 — registriert alle Routen am Limiter
    from api.auth import limiter

    return [lim.limit for lim in limiter._route_limits.get(name, [])]


class _Downloads:
    """yf_download-Attrappe: merkt sich das erste Argument jedes Aufrufs."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, tickers, **kwargs):
        self.calls.append(tickers)
        return pd.DataFrame()

    def assert_only_lists(self):
        assert self.calls, "yf_download wurde nicht aufgerufen"
        for arg in self.calls:
            assert isinstance(arg, list), f"Zeichenkette statt Liste: {arg!r}"
            assert all(" " not in t and "," not in t for t in arg)


# --- K023: Listen statt verbundener Zeichenketten ------------------------------


class TestK023CallersPassLists:
    def test_stock_scorer(self, monkeypatch):
        from services import stock_scorer

        dl = _Downloads()
        monkeypatch.setattr(stock_scorer, "yf_download", dl)
        monkeypatch.setattr(stock_scorer.cache, "get", lambda key: None)

        stock_scorer._download_and_analyze("W3K023")

        dl.assert_only_lists()
        assert dl.calls == [["W3K023", "^GSPC"]]

    def test_stock_scorer_with_cached_benchmark(self, monkeypatch):
        from services import stock_scorer

        dl = _Downloads()
        monkeypatch.setattr(stock_scorer, "yf_download", dl)
        monkeypatch.setattr(stock_scorer.cache, "get", lambda key: None)
        monkeypatch.setattr(
            stock_scorer, "_series_from_payload", lambda payload: pd.Series([1.0, 2.0])
        )

        stock_scorer._download_and_analyze("W3K023")

        assert dl.calls == [["W3K023"]]

    def test_correlation_matrix(self, monkeypatch):
        from services import correlation_service

        dl = _Downloads()
        monkeypatch.setattr(correlation_service, "yf_download", dl)

        correlation_service._fetch_close_matrix(["AAPL", "MSFT", "AAPL"], "90d")

        assert dl.calls == [["AAPL", "MSFT"]]

    def test_sector_rotation(self, monkeypatch):
        from services import sector_analyzer

        dl = _Downloads()
        monkeypatch.setattr(sector_analyzer, "yf_download", dl)
        monkeypatch.setattr(sector_analyzer.cache, "get", lambda key: None)

        assert sector_analyzer.get_sector_rotation() == []

        assert dl.calls == [list(sector_analyzer.SECTOR_ETFS.keys())]

    def test_benchmark_closes(self, monkeypatch):
        from services import benchmark_service

        dl = _Downloads()
        monkeypatch.setattr(benchmark_service, "yf_download", dl)

        assert benchmark_service._download_benchmark_closes("^GSPC", "w3:bench") is None

        assert dl.calls == [["^GSPC"]]

    async def test_pending_dividend_actions(self, monkeypatch):
        import asyncio

        from services import pending_dividend_service

        dl = _Downloads()
        monkeypatch.setattr(pending_dividend_service, "yf_download", dl)

        await pending_dividend_service._download_actions("NESN.SW", "1y", asyncio.Semaphore(1))

        assert dl.calls == [["NESN.SW"]]

    def test_vix(self, monkeypatch):
        from services import price_service

        dl = _Downloads()
        monkeypatch.setattr(price_service, "yf_download", dl)
        monkeypatch.setattr(price_service.cache, "get", lambda key: None)
        monkeypatch.setattr("services.cache_service.get_cached_price_sync", lambda *a, **k: None)

        assert price_service.get_vix() is None

        assert dl.calls == [["^VIX"]]

    async def test_seed_historical_prices(self, db, monkeypatch):
        from services import cache_service

        dl = _Downloads()
        monkeypatch.setattr(cache_service, "yf_download", dl)

        await cache_service.seed_historical_prices(db)

        assert dl.calls == [["^GSPC"], ["^VIX"]]

    def test_no_string_argument_left_in_core_services(self):
        """Kein Aufruf mit verbundener Zeichenkette in den Dateien dieses Fixers."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for rel in (
            "services/stock_scorer.py", "services/correlation_service.py",
            "services/sector_analyzer.py", "services/benchmark_service.py",
            "services/cache_service.py", "services/pending_dividend_service.py",
            "services/price_service.py", "services/history_service.py",
            "services/snapshot_service.py",
        ):
            text = (root / rel).read_text()
            for match in re.finditer(r"yf_download\(\s*([^,\n)]+)", text):
                arg = match.group(1).strip()
                if arg.startswith(('"', "'", 'f"', "f'")) or ".join(" in arg:
                    offenders.append(f"{rel}: {arg}")
        assert offenders == []


# --- K059: yf_to_thread statt Default-Executor ---------------------------------


class _ToThreadSpy:
    def __init__(self, result=None):
        self.calls: list[tuple] = []
        self.result = result

    async def __call__(self, func, *args, **kwargs):
        self.calls.append((getattr(func, "__name__", str(func)), args))
        return self.result


def _forbid_default_executor(monkeypatch, module):
    async def _forbidden(func, *args, **kwargs):
        raise AssertionError(f"asyncio.to_thread für {getattr(func, '__name__', func)}")

    monkeypatch.setattr(module.asyncio, "to_thread", _forbidden)


class TestK059TickerLockCallsUseOwnPool:
    async def test_stock_profile_route(self, client, monkeypatch):
        import api.stock as stock_api

        spy = _ToThreadSpy(result={"ticker": "AAPL", "name": "Apple"})
        monkeypatch.setattr(stock_api, "yf_to_thread", spy)
        headers = await _login(client, "w3-k059-profile@example.com")

        res = await client.get("/api/stock/AAPL/profile", headers=headers)

        assert res.status_code == 200, res.text
        assert spy.calls == [("get_company_profile", ("AAPL",))]

    async def test_stock_search_route(self, client, monkeypatch):
        import api.stock as stock_api

        spy = _ToThreadSpy(result=[{"ticker": "NVDA", "name": "NVIDIA", "type": "equity"}])
        monkeypatch.setattr(stock_api, "yf_to_thread", spy)
        headers = await _login(client, "w3-k059-search@example.com")

        res = await client.get("/api/stock/search?q=nvda", headers=headers)

        assert res.status_code == 200, res.text
        assert [r["ticker"] for r in res.json()] == ["NVDA"]
        assert spy.calls == [("_yf_search", ("NVDA",))]

    async def test_eps_scanner_fallback(self, monkeypatch):
        import yf_patch
        from services import eps_scanner_service

        spy = _ToThreadSpy(result=None)
        monkeypatch.setattr(yf_patch, "yf_to_thread", spy)
        _forbid_default_executor(monkeypatch, eps_scanner_service)

        await eps_scanner_service.fetch_yfinance_eps("AAPL")

        assert spy.calls == [("yf_earnings_dates", ("AAPL", 16))]

    async def test_rich_earnings_fallback(self, monkeypatch):
        from services import earnings_service

        spy = _ToThreadSpy(result=None)
        monkeypatch.setattr(earnings_service, "yf_to_thread", spy)
        monkeypatch.setattr(earnings_service, "_fetch_finnhub_earnings", AsyncMock(return_value=None))
        _forbid_default_executor(monkeypatch, earnings_service)

        await earnings_service._fetch_rich_earnings("W3K059RICH", AsyncMock(), uuid.uuid4())

        assert spy.calls == [("get_next_earnings_date", ("W3K059RICH",))]

    async def test_refresh_all_earnings(self, db, monkeypatch):
        from services import earnings_service

        uid = uuid.uuid4()
        db.add(Position(
            user_id=uid, bucket_id=uuid.uuid4(), ticker="NOVN", name="Novartis",
            type=AssetType.stock, yfinance_ticker="NOVN.SW", currency="CHF",
            shares=Decimal("3"), cost_basis_chf=Decimal("300"), is_active=True,
        ))
        await db.commit()
        spy = _ToThreadSpy(result=date.today() + timedelta(days=20))
        monkeypatch.setattr(earnings_service, "yf_to_thread", spy)
        _forbid_default_executor(monkeypatch, earnings_service)

        result = await earnings_service.refresh_all_earnings(db, uid)

        assert spy.calls == [("get_next_earnings_date", ("NOVN.SW",))]
        assert result["updated"] == 1

    async def test_worker_earnings_refresh(self, db, monkeypatch):
        import yf_patch

        db.add(Position(
            user_id=uuid.uuid4(), bucket_id=uuid.uuid4(), ticker="ROG", name="Roche",
            type=AssetType.stock, yfinance_ticker="ROG.SW", currency="CHF",
            shares=Decimal("3"), cost_basis_chf=Decimal("900"), is_active=True,
        ))
        await db.commit()
        earnings_day = date.today() + timedelta(days=12)
        spy = _ToThreadSpy(result=earnings_day)
        monkeypatch.setattr(yf_patch, "yf_to_thread", spy)
        _forbid_default_executor(monkeypatch, worker)

        await worker._refresh_earnings_dates()

        assert spy.calls == [("get_next_earnings_date", ("ROG.SW",))]

    def test_screening_and_history_call_sites(self):
        """Beide Stellen liegen tief in langen Abläufen; geprüft wird der Aufruf im Quelltext."""
        import inspect

        from services import history_service
        from services.screening import screening_service

        screening = inspect.getsource(screening_service).replace(" ", "")
        history = inspect.getsource(history_service).replace(" ", "")
        assert "awaityf_to_thread(get_next_earnings_date,t)" in screening
        assert "asyncio.to_thread(get_next_earnings_date" not in screening
        assert "awaityf_to_thread(benchmark_quote_currency,benchmark)" in history
        assert "asyncio.to_thread(benchmark_quote_currency" not in history

    async def test_yf_to_thread_runs_in_the_ticker_pool(self):
        """Der eigene Pool hält den Default-Executor frei."""
        import threading

        import yf_patch

        name = await yf_patch.yf_to_thread(lambda: threading.current_thread().name)

        assert name.startswith("yf-ticker")


# --- K116: fast_info unter dem Lock --------------------------------------------


class TestK116FastInfoUnderLock:
    def test_get_stock_price_reads_fields_through_yf_fast_info(self, monkeypatch):
        from services import price_service

        calls: list[tuple] = []

        def _fast_info(ticker, fields):
            calls.append((ticker, tuple(fields)))
            return {"last_price": 110.0, "previous_close": 100.0, "currency": None}

        monkeypatch.setattr(price_service, "yf_fast_info", _fast_info)
        monkeypatch.setattr(price_service.cache, "get", lambda key: None)
        monkeypatch.setattr(price_service.cache, "set", lambda *a, **k: None)
        monkeypatch.setattr(price_service, "_in_event_loop", lambda: False)
        monkeypatch.setattr("services.cache_service.get_cached_price_sync", lambda *a, **k: None)

        result = price_service.get_stock_price("W3K116")

        assert calls == [("W3K116", ("last_price", "previous_close", "currency"))]
        assert result == {"price": 110.0, "currency": "USD", "change_pct": 10.0}
        assert not hasattr(price_service, "yf_ticker_attr")

    def test_dividend_currency_reads_through_yf_fast_info(self, monkeypatch):
        from services import dividend_service

        def _no_attr(*args):
            raise AssertionError("fast_info über yf_ticker_attr")

        monkeypatch.setattr(dividend_service, "yf_ticker_attr", _no_attr)
        monkeypatch.setattr(dividend_service, "yf_fast_info", lambda t, f: {"currency": "GBp"})
        assert dividend_service.resolve_dividend_currency("SWDA.L", "GBP") == ("GBP", 100.0)

        monkeypatch.setattr(dividend_service, "yf_fast_info", lambda t, f: {"currency": None})
        assert dividend_service.resolve_dividend_currency("NESN.SW", "CHF") == ("CHF", 1.0)


# --- K125: ein Roundtrip für viele Kurse ---------------------------------------


class TestK125OneRoundtrip:
    def test_get_stock_prices_bulk_uses_get_many(self, monkeypatch):
        from services import price_service

        many: list[list[str]] = []

        def _get_many(keys):
            many.append(list(keys))
            return {"price:AAPL": {"price": 1.0, "currency": "USD", "change_pct": 0.5}}

        def _no_get(key):
            raise AssertionError(f"Einzel-GET für {key}")

        db_asked: list[list[str]] = []

        def _db(tickers, fallback_days=5):
            db_asked.append(list(tickers))
            return {"MSFT": {"price": 2.0, "currency": "USD"}}

        monkeypatch.setattr(price_service.cache, "get_many", _get_many)
        monkeypatch.setattr(price_service.cache, "get", _no_get)
        monkeypatch.setattr(price_service.cache, "set", lambda *a, **k: None)
        monkeypatch.setattr("services.cache_service.get_cached_prices_batch_sync", _db)

        result = price_service.get_stock_prices_bulk(["AAPL", "MSFT", "AAPL", "NONE"])

        assert many == [["price:AAPL", "price:MSFT", "price:NONE"]]
        assert db_asked == [["MSFT", "NONE"]]
        assert result["AAPL"]["price"] == 1.0
        assert result["MSFT"] == {"price": 2.0, "currency": "USD", "change_pct": None}
        assert "NONE" not in result

    async def test_watchlist_reads_all_prices_in_one_call(self, db, monkeypatch):
        from services import watchlist_service

        uid = uuid.uuid4()
        db.add_all([
            WatchlistItem(user_id=uid, ticker="W3A", name="A", is_active=True),
            WatchlistItem(user_id=uid, ticker="W3B", name="B", is_active=True),
        ])
        db.add(PriceCache(ticker="W3B", date=date.today(), close=42, currency="CHF", source="yahoo"))
        await db.commit()
        many: list[list[str]] = []

        def _get_many(keys):
            many.append(sorted(keys))
            return {"price:W3A": {"price": 10.0, "currency": "USD", "change_pct": 1.5}}

        def _no_get(key):
            raise AssertionError(f"Einzel-GET für {key}")

        monkeypatch.setattr(watchlist_service.app_cache, "get_many", _get_many)
        monkeypatch.setattr(watchlist_service.app_cache, "get", _no_get)

        data = await watchlist_service.get_watchlist_data(db, uid)

        assert many == [["price:W3A", "price:W3B"]]
        items = {i["ticker"]: i for i in data["items"]}
        assert items["W3A"]["price"] == 10.0 and items["W3A"]["change_pct"] == 1.5
        assert items["W3B"]["price"] == 42.0  # Rückgriff auf price_cache bleibt


# --- K060: Summary aus dem Cache -----------------------------------------------


class TestK060ReadersUseCachedSummary:
    async def test_rebalancing_plan_uses_given_summary(self, db, monkeypatch):
        from services import rebalancing_service as rs
        from services.bucket_service import create_bucket

        uid = uuid.uuid4()
        bucket = await create_bucket(db, uid, name="Core")
        bucket.target_pct = Decimal("50")
        await db.commit()

        async def _alloc(_db, _uid):
            return [{"bucket_id": str(bucket.id), "name": "Core", "kind": "user",
                     "value_chf": 4000.0, "pct": 40.0, "color": None},
                    {"bucket_id": "x", "name": "Rest", "kind": "system",
                     "value_chf": 6000.0, "pct": 60.0, "color": None}]

        async def _no_load(*args, **kwargs):
            raise AssertionError("Summary trotz Vorgabe neu geladen")

        monkeypatch.setattr(rs, "get_allocations_by_bucket", _alloc)
        monkeypatch.setattr(rs, "get_portfolio_summary_cached", _no_load)
        summary = {"positions": [{"type": "cash", "market_value_chf": 500.0}]}

        plan = await rs.get_rebalancing_plan(db, uid, summary=summary)

        assert plan["available_cash_chf"] == 500.0
        assert plan["total_underweight_chf"] == 1000.0
        assert plan["cash_covers_underweight_pct"] == 50.0

    async def test_services_do_not_bind_the_uncached_summary(self):
        from services import (
            correlation_service,
            net_worth_service,
            position_rebalancing_service,
            rebalancing_service,
        )

        for module in (
            correlation_service, net_worth_service,
            position_rebalancing_service, rebalancing_service,
        ):
            assert hasattr(module, "get_portfolio_summary_cached"), module.__name__
            assert not hasattr(module, "get_portfolio_summary"), module.__name__

    async def test_concentration_helpers_read_the_summary_cache(self, monkeypatch):
        import services.concentration_service as cs

        summary = {"positions": [
            {"ticker": "SPY", "name": "SPDR", "type": "etf", "market_value_chf": 3000.0},
        ]}
        cached = AsyncMock(return_value=summary)

        async def _uncached(*args, **kwargs):
            raise AssertionError("ungecachte Summary berechnet")

        monkeypatch.setattr("services.portfolio_service.get_portfolio_summary_cached", cached)
        monkeypatch.setattr("services.portfolio_service.get_portfolio_summary", _uncached)

        etf_map = await cs._get_user_etf_positions_with_values(AsyncMock(), uuid.uuid4())
        direct = await cs._get_user_direct_position(AsyncMock(), "SPY", uuid.uuid4())

        assert etf_map == {"SPY": {"name": "SPDR", "market_value_chf": 3000.0}}
        assert direct["market_value_chf"] == 3000.0
        assert cached.await_count == 2


# --- K157: FTD-Download mit Grössengrenze --------------------------------------


def _ftd_zip(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("cnsfails.txt", "\n".join(lines))
    return buf.getvalue()


class TestK157FtdDownloadIsCapped:
    async def test_download_goes_through_capped_get(self, monkeypatch):
        from services.screening import ftd_service

        calls: list[dict] = []

        async def _capped_get(url, **kwargs):
            calls.append({"url": url, **kwargs})
            if len(calls) == 1:
                return None  # erste Periode nicht verfügbar
            return _ftd_zip([
                "SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE",
                "20261001|1|GME|600000|GAMESTOP|20",
                "20261001|2|TINY|10|TINY CO|1",
            ])

        monkeypatch.setattr(ftd_service, "capped_get", _capped_get)
        monkeypatch.setattr(ftd_service, "_get_latest_periods", lambda: ["202610a", "202609b"])

        result = await ftd_service.fetch_ftd_data()

        assert result == {"GME": {"total_shares": 600000, "period": "202609b"}}
        assert len(calls) == 2
        assert calls[1]["adapter"] == "ftd_service" and calls[1]["ticker"] == "202609b"
        assert calls[1]["headers"] == {"User-Agent": ftd_service.SEC_UA}
        assert not hasattr(ftd_service, "get_async_client")

    async def test_oversized_zip_member_is_rejected(self, monkeypatch):
        from services.screening import ftd_service

        async def _capped_get(url, **kwargs):
            return _ftd_zip(["HEADER", "20261001|1|GME|600000|GAMESTOP|20"])

        def _capped_read(zf, name):
            raise ValueError("zip member exceeds the unpack cap")

        monkeypatch.setattr(ftd_service, "capped_get", _capped_get)
        monkeypatch.setattr(ftd_service, "read_zip_member_capped", _capped_read)
        monkeypatch.setattr(ftd_service, "_get_latest_periods", lambda: ["202610a"])

        assert await ftd_service.fetch_ftd_data() == {}


# --- K141: Gesamtausfall des Kurs-Feeds ----------------------------------------


def _stale_pos(ticker):
    return Position(
        user_id=uuid.uuid4(), bucket_id=uuid.uuid4(), ticker=ticker, name=ticker,
        type=AssetType.stock, is_active=True, shares=1.0,
    )


class TestK141WholeFeedOutage:
    async def test_all_tickers_equally_old_is_an_outage(self, db):
        today = date(2026, 11, 13)
        last = today - timedelta(days=9)
        db.add_all([_stale_pos("NOVN.SW"), _stale_pos("ROG.SW")])
        db.add_all([
            PriceCache(ticker="NOVN.SW", date=last, close=90, currency="CHF", source="yahoo"),
            PriceCache(ticker="ROG.SW", date=last, close=250, currency="CHF", source="yahoo"),
        ])
        await db.commit()

        report = await staleness.check_price_staleness(db, today=today)

        # Gegen den frischesten Ticker fällt keiner ab — gegen heute alle.
        assert report["stale_count"] == 0
        assert report["feed_outage"] is True
        assert report["feed_lag_days"] == 9

    async def test_weekend_and_holiday_lag_is_no_outage(self, db):
        today = date(2026, 11, 13)
        db.add(_stale_pos("NOVN.SW"))
        db.add(PriceCache(
            ticker="NOVN.SW", date=today - timedelta(days=staleness.STALE_THRESHOLD_DAYS),
            close=90, currency="CHF", source="yahoo",
        ))
        await db.commit()

        report = await staleness.check_price_staleness(db, today=today)

        assert report["feed_outage"] is False
        assert report["feed_lag_days"] == staleness.STALE_THRESHOLD_DAYS

    async def test_outage_sends_alert_even_without_single_stale_ticker(self, db, monkeypatch):
        db.add(_stale_pos("NOVN.SW"))
        db.add(PriceCache(
            ticker="NOVN.SW", date=date.today() - timedelta(days=12),
            close=90, currency="CHF", source="yahoo",
        ))
        await db.commit()
        sent: list[dict] = []

        async def _send(to, subject, body_html):
            sent.append({"to": to, "subject": subject, "body": body_html})
            return True

        monkeypatch.setattr(staleness, "send_email", _send)
        monkeypatch.setattr(staleness, "has_smtp_configured", lambda: True)
        monkeypatch.setattr(staleness.settings, "alert_email_to", "ops@example.com")

        report = await staleness.run_staleness_check_with_alert(db)

        assert report["feed_outage"] is True and report["email_sent"] is True
        assert sent[0]["subject"] == "OpenFolio: Kurs-Feed steht seit 12 Tagen"
        assert "Der gesamte Kurs-Feed steht." in sent[0]["body"]

    async def test_fresh_feed_without_stale_ticker_sends_nothing(self, db, monkeypatch):
        db.add(_stale_pos("NOVN.SW"))
        db.add(PriceCache(
            ticker="NOVN.SW", date=date.today(), close=90, currency="CHF", source="yahoo",
        ))
        await db.commit()

        async def _send(**kwargs):
            raise AssertionError("Mail trotz frischem Feed")

        monkeypatch.setattr(staleness, "send_email", _send)
        monkeypatch.setattr(staleness, "has_smtp_configured", lambda: True)
        monkeypatch.setattr(staleness.settings, "alert_email_to", "ops@example.com")

        report = await staleness.run_staleness_check_with_alert(db)

        assert report["feed_outage"] is False and "email_sent" not in report


# --- K084 / K145: Job-Health ---------------------------------------------------


@pytest.fixture
def clean_failures():
    worker._reported_failures.clear()
    yield
    worker._reported_failures.clear()


class TestWorkerJobHealth:
    async def test_etf_holdings_errors_reach_job_health(self, monkeypatch, clean_failures):
        result = {"refreshed": [], "skipped": [], "etf_count": 2,
                  "errors": [{"etf_ticker": "IWDA", "error": "x"}, {"etf_ticker": "CSPX", "error": "y"}]}
        monkeypatch.setattr(
            "services.etf_holdings_service.refresh_all_user_etfs", AsyncMock(return_value=result)
        )
        monkeypatch.setattr(worker, "_check_sector_coverage_after_refresh", AsyncMock())

        await worker._health_tracked(worker.etf_holdings_refresh_job, "etf_holdings_refresh")()

        assert worker._reported_failures["etf_holdings_refresh"] == "etf_holdings_refresh: 2 ETF failed"

    async def test_etf_holdings_without_errors_stays_green(self, monkeypatch, clean_failures):
        result = {"refreshed": [{"etf_ticker": "IWDA"}], "skipped": [], "errors": [], "etf_count": 1}
        monkeypatch.setattr(
            "services.etf_holdings_service.refresh_all_user_etfs", AsyncMock(return_value=result)
        )
        monkeypatch.setattr(worker, "_check_sector_coverage_after_refresh", AsyncMock())

        await worker._health_tracked(worker.etf_holdings_refresh_job, "etf_holdings_refresh")()

        assert worker._reported_failures == {}

    @pytest.mark.parametrize("result, expected", [
        ({"inserted": 3, "errors": ["2026: HTTP 503"], "status": "partial"},
         "cot_refresh: 2026: HTTP 503"),
        ({"inserted": 0, "errors": [], "status": "no_data"}, "cot_refresh: no_data"),
        ({"inserted": 3, "errors": [], "status": "ok"}, None),
    ])
    async def test_cot_status_reaches_job_health(self, monkeypatch, clean_failures, result, expected):
        monkeypatch.setattr(
            "services.macro.cot_service.refresh_cot_snapshots", AsyncMock(return_value=result)
        )

        await worker._health_tracked(worker.cot_weekly_refresh, "cot_weekly_refresh")()

        assert worker._reported_failures.get("cot_weekly_refresh") == expected


# --- X02 / B4: Limits je Route -------------------------------------------------


@pytest.mark.parametrize("route, limit", [
    ("api.stock.profile", RL_TICKER_READ),
    ("api.eps_scanner.get_results", "60/minute"),
    ("api.analysis.get_mrs_history", RL_READ),
    ("api.analysis.get_breakouts", RL_READ),
    ("api.analysis.get_levels", RL_READ),
    ("api.analysis.get_reversal", RL_READ),
    ("api.analysis.get_heartbeat", RL_READ),
    ("api.screening.get_ticker_result", RL_READ),
])
def test_route_limits(route, limit):
    assert _route_limits(route) == [parse_limit(limit)]


# --- B5: Ticker mit Leerzeichen oder Komma -------------------------------------

BAD_TICKERS = ["AAPL,MSFT", "AAPL MSFT"]


class TestB5TickerPatternIsApplied:
    @pytest.mark.parametrize("bad", BAD_TICKERS)
    async def test_stock_profile(self, client, monkeypatch, bad):
        import api.stock as stock_api

        called = AsyncMock(return_value={})
        monkeypatch.setattr(stock_api, "yf_to_thread", called)
        headers = await _login(client, "w3-b5-stock@example.com")

        res = await client.get(f"/api/stock/{bad}/profile", headers=headers)

        assert res.status_code == 422, res.text
        called.assert_not_awaited()

    @pytest.mark.parametrize("bad", BAD_TICKERS)
    @pytest.mark.parametrize("path", [
        "/api/analysis/mrs-history/{t}",
        "/api/analysis/breakouts/{t}",
        "/api/analysis/levels/{t}",
        "/api/analysis/reversal/{t}",
        "/api/analysis/heartbeat/{t}",
        "/api/analysis/score/{t}",
    ])
    async def test_analysis_read_routes(self, client, monkeypatch, path, bad):
        def _no_thread(*args, **kwargs):
            raise AssertionError("Dienst trotz ungültigem Ticker aufgerufen")

        monkeypatch.setattr("api.analysis.asyncio.to_thread", _no_thread)
        headers = await _login(client, "w3-b5-analysis@example.com")

        res = await client.get(path.format(t=bad), headers=headers)

        assert res.status_code == 422, res.text

    @pytest.mark.parametrize("bad", BAD_TICKERS)
    async def test_analysis_resistance_route(self, client, bad):
        headers = await _login(client, "w3-b5-resistance@example.com")

        res = await client.put(
            f"/api/analysis/resistance/{bad}", json={"manual_resistance": 10.0}, headers=headers
        )

        assert res.status_code == 422, res.text

    @pytest.mark.parametrize("bad", BAD_TICKERS)
    async def test_positions_test_price_query(self, client, monkeypatch, bad):
        import api.positions as positions_api

        def _no_price(ticker):
            raise AssertionError("Kursabruf trotz ungültigem Ticker")

        monkeypatch.setattr(positions_api, "get_stock_price", _no_price)
        headers = await _login(client, "w3-b5-positions@example.com")

        res = await client.get(
            f"/api/portfolio/positions/{uuid.uuid4()}/test-price",
            params={"yfinance_ticker": bad}, headers=headers,
        )

        assert res.status_code == 422, res.text

    @pytest.mark.parametrize("bad", BAD_TICKERS)
    async def test_etf_sectors_put(self, client, bad):
        headers = await _login(client, "w3-b5-etf@example.com")
        body = {"sectors": [{"sector": "Technology", "weight_pct": 100.0}]}

        res = await client.put(f"/api/etf-sectors/{bad}", json=body, headers=headers)

        assert res.status_code == 422, res.text

    async def test_valid_ticker_still_passes(self, client, monkeypatch):
        import api.stock as stock_api

        monkeypatch.setattr(stock_api, "yf_to_thread", AsyncMock(return_value={"ticker": "BRK-B"}))
        headers = await _login(client, "w3-b5-valid@example.com")

        res = await client.get("/api/stock/BRK-B/profile", headers=headers)

        assert res.status_code == 200, res.text
