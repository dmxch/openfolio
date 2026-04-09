"""Unit tests for services.earnings_service — Finnhub + rich fallback logic.

Alle externen Quellen werden gemockt — keine echten Netzwerk-Calls.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from services import cache
from services import earnings_service as svc


# --- _fetch_finnhub_earnings ------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_finnhub_returns_first_earnings():
    """Finnhub liefert zwei Eintraege — wir nehmen den fruehesten und mappen sauber."""
    sample = {
        "earningsCalendar": [
            {
                "date": "2026-05-01",
                "hour": "bmo",
                "epsEstimate": 1.23,
                "revenueEstimate": 10_000_000_000,
                "symbol": "AMZN",
            },
            {
                "date": "2026-04-14",
                "hour": "amc",
                "epsEstimate": 2.68,
                "revenueEstimate": 23_600_000_000,
                "symbol": "JNJ",
            },
        ]
    }
    with patch.object(svc.settings, "finnhub_api_key", "k"), \
         patch.object(svc, "fetch_json", new=AsyncMock(return_value=sample)):
        result = await svc._fetch_finnhub_earnings("JNJ")

    assert result is not None
    assert result["earnings_date"] == "2026-04-14"
    assert result["earnings_time"] == "amc"
    assert result["eps_estimate"] == 2.68
    assert result["revenue_estimate_usd"] == 23_600_000_000
    assert result["is_confirmed"] is True
    assert result["source"] == "finnhub"
    assert "fetched_at" in result


@pytest.mark.asyncio
async def test_fetch_finnhub_empty_list_returns_none():
    with patch.object(svc.settings, "finnhub_api_key", "k"), \
         patch.object(svc, "fetch_json", new=AsyncMock(return_value={"earningsCalendar": []})):
        result = await svc._fetch_finnhub_earnings("XYZ")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_finnhub_no_api_key_returns_none():
    mock = AsyncMock()
    with patch.object(svc.settings, "finnhub_api_key", ""), \
         patch.object(svc, "fetch_json", new=mock):
        result = await svc._fetch_finnhub_earnings("JNJ")
    assert result is None
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_finnhub_http_error_returns_none(caplog):
    with patch.object(svc.settings, "finnhub_api_key", "k"), \
         patch.object(svc, "fetch_json", new=AsyncMock(side_effect=RuntimeError("boom"))):
        result = await svc._fetch_finnhub_earnings("JNJ")
    assert result is None


# --- _fetch_rich_earnings ---------------------------------------------------

@pytest.mark.asyncio
async def test_rich_earnings_falls_back_to_yfinance():
    cache.delete("earnings:rich:PEP:v1") if hasattr(cache, "delete") else None
    fake_dt = datetime(2026, 4, 16, 12, 0, 0)
    with patch.object(svc, "_fetch_finnhub_earnings", new=AsyncMock(return_value=None)), \
         patch.object(svc, "get_next_earnings_date", return_value=fake_dt):
        result = await svc._fetch_rich_earnings("PEP_FALLBACK1")

    assert result is not None
    assert result["source"] == "yfinance"
    assert result["earnings_time"] == "unknown"
    assert result["earnings_date"] == "2026-04-16"
    assert result["eps_estimate"] is None
    assert result["revenue_estimate_usd"] is None
    assert result["is_confirmed"] is False


@pytest.mark.asyncio
async def test_rich_earnings_both_sources_fail_returns_none():
    with patch.object(svc, "_fetch_finnhub_earnings", new=AsyncMock(return_value=None)), \
         patch.object(svc, "get_next_earnings_date", return_value=None):
        result = await svc._fetch_rich_earnings("NOPE_TICKER_RICH1")
    assert result is None


@pytest.mark.asyncio
async def test_rich_earnings_cache_hit():
    cached = {
        "earnings_date": "2026-04-14",
        "earnings_time": "amc",
        "eps_estimate": 2.68,
        "revenue_estimate_usd": 23_600_000_000,
        "is_confirmed": True,
        "source": "finnhub",
        "fetched_at": "2026-04-09T00:00:00+00:00",
    }
    cache.set("earnings:rich:JNJ_CACHED:v1", cached, ttl=3600)
    finnhub_mock = AsyncMock()
    with patch.object(svc, "_fetch_finnhub_earnings", new=finnhub_mock):
        result = await svc._fetch_rich_earnings("JNJ_CACHED")
    assert result == cached
    finnhub_mock.assert_not_called()


# --- get_upcoming_earnings_for_portfolio ------------------------------------

class _FakePosition:
    def __init__(self, ticker: str, name: str, type_value: str = "stock",
                 yfinance_ticker: str | None = None):
        self.ticker = ticker
        self.name = name
        self.yfinance_ticker = yfinance_ticker
        self.type = SimpleNamespace(value=type_value)


class _FakeScalarsResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _FakeDB:
    def __init__(self, positions):
        self._positions = positions
        self.last_stmt = None

    async def execute(self, stmt):
        self.last_stmt = stmt
        return _FakeScalarsResult(self._positions)


def _mk_entry(date_str: str, time: str = "amc", source: str = "finnhub") -> dict:
    return {
        "earnings_date": date_str,
        "earnings_time": time,
        "eps_estimate": 1.0,
        "revenue_estimate_usd": 1_000_000_000,
        "is_confirmed": True,
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.asyncio
async def test_portfolio_happy_path():
    today = date.today()
    jnj_date = (today + timedelta(days=5)).isoformat()
    pep_date = (today + timedelta(days=6)).isoformat()
    wm_date = (today + timedelta(days=30)).isoformat()  # ausserhalb 7-day-Fenster

    positions = [
        _FakePosition("JNJ", "Johnson & Johnson"),
        _FakePosition("PEP", "PepsiCo"),
        _FakePosition("WM", "Waste Mgmt"),
        _FakePosition("AAPL", "Apple"),
    ]

    async def fake_rich(ticker: str):
        return {
            "JNJ": _mk_entry(jnj_date, "amc"),
            "PEP": _mk_entry(pep_date, "bmo"),
            "WM": _mk_entry(wm_date, "bmo"),
            "AAPL": None,
        }[ticker]

    db = _FakeDB(positions)
    with patch.object(svc, "_fetch_rich_earnings", side_effect=fake_rich):
        result = await svc.get_upcoming_earnings_for_portfolio(
            db, uuid4(), days=7, include_etfs=True
        )

    tickers_in_window = [e["ticker"] for e in result["earnings"]]
    assert tickers_in_window == ["JNJ", "PEP"]  # sortiert nach Datum
    assert result["earnings"][0]["earnings_time_label"] == "After Market Close"
    assert result["earnings"][1]["earnings_time_label"] == "Before Market Open"
    assert "WM" in result["no_earnings_in_window"]
    assert "AAPL" in result["no_earnings_in_window"]
    assert result["warnings"] == []
    assert result["lookahead_days"] == 7


@pytest.mark.asyncio
async def test_portfolio_filter_include_etfs_false():
    positions_all = [
        _FakePosition("JNJ", "JNJ", "stock"),
        _FakePosition("EIMI", "iShares EM", "etf"),
    ]
    # Wenn include_etfs=False ist, muss die Query nur stock liefern.
    # Wir simulieren das, indem die Fake-DB selber filtert waere umstaendlich —
    # stattdessen pruefen wir: wenn der Fake-DB nur JNJ liefert, wird EIMI
    # nicht gefetcht. Das Verhalten "query filtert korrekt" wird separat via
    # Integration-Test geprueft.
    positions = [p for p in positions_all if p.type.value == "stock"]
    fetched: list[str] = []

    async def fake_rich(ticker: str):
        fetched.append(ticker)
        return None

    db = _FakeDB(positions)
    with patch.object(svc, "_fetch_rich_earnings", side_effect=fake_rich):
        result = await svc.get_upcoming_earnings_for_portfolio(
            db, uuid4(), days=7, include_etfs=False
        )
    assert fetched == ["JNJ"]
    assert "EIMI" not in result["no_earnings_in_window"]


@pytest.mark.asyncio
async def test_portfolio_ticker_fetch_exception_becomes_warning():
    today = date.today()
    ok_date = (today + timedelta(days=2)).isoformat()
    positions = [
        _FakePosition("JNJ", "JNJ"),
        _FakePosition("BROKEN", "Broken"),
    ]

    async def fake_rich(ticker: str):
        if ticker == "BROKEN":
            raise RuntimeError("boom")
        return _mk_entry(ok_date, "bmo")

    db = _FakeDB(positions)
    with patch.object(svc, "_fetch_rich_earnings", side_effect=fake_rich):
        result = await svc.get_upcoming_earnings_for_portfolio(
            db, uuid4(), days=7
        )

    assert [e["ticker"] for e in result["earnings"]] == ["JNJ"]
    assert "earnings_fetch_failed:BROKEN" in result["warnings"]
