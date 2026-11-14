"""Vollreview 11/2026, Fixer «analysis»: Journal, Korrelation, Konzentration, Routen.

K070 (Journal lädt alle Bodies), K071 (Korrelation lädt je Filter neu),
K126 (Sync-DB im Event-Loop), K012 (zwei Summaries je Score), K158 (Nutzerdaten
im geteilten Cache-Objekt), K023 (ungeprüfte Ticker), K029 (Enddatum ohne
Obergrenze), X02 (Limit der Score-Route).
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from httpx import AsyncClient
from limits import parse as parse_limit

import services.concentration_service as cs
import services.correlation_service as corr
import services.sector_classification_service as scs
import services.trade_journal_service as tj
from constants.limits import RL_READ, RL_TICKER_READ
from models.position import AssetType, Position, PriceSource
from models.report import Report
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket

TEST_PASSWORD = "TestPassw0rd!2026"


async def _login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _route_limits(name: str) -> list:
    import api.analysis  # noqa: F401 — registriert die Routen am Limiter
    from api.auth import limiter

    return [lim.limit for lim in limiter._route_limits.get(name, [])]


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


async def _make_txn(db, user, *, ticker: str = "AAPL") -> Transaction:
    liquid = await get_liquid_default_bucket(db, user.id)
    pos = Position(
        user_id=user.id, bucket_id=liquid.id, ticker=ticker, name=f"{ticker} Inc",
        type=AssetType.stock, currency="USD", price_source=PriceSource.yahoo,
        shares=Decimal("10"), cost_basis_chf=Decimal("1500"),
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    txn = Transaction(
        position_id=pos.id, user_id=user.id, type=TransactionType.buy, date=date(2026, 6, 18),
        shares=Decimal("10"), price_per_share=Decimal("150"), currency="USD",
        fx_rate_to_chf=Decimal("0.9"), total_chf=Decimal("1350"),
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


def _report(user, **over) -> Report:
    base = dict(
        user_id=user.id, category="trade", title="Trade-Plan", report_date=date(2026, 6, 17),
        body="...", content_hash=uuid.uuid4().hex, ticker="AAPL", side="buy",
    )
    base.update(over)
    return Report(**base)


# --- K070: Trade-Journal ------------------------------------------------------


class TestK070TradeJournal:
    async def test_only_the_head_of_the_body_is_loaded(self, db, monkeypatch):
        user = await _make_user(db)
        prose = "Die These: relative Stärke steigt und die 200-Tage-Linie hält.\n"
        db.add(_report(user, body=prose + "x" * 200_000))
        await db.commit()

        seen: list[int] = []
        real_excerpt = tj._excerpt

        def _spy(body, max_len=180):
            seen.append(len(body or ""))
            return real_excerpt(body, max_len)

        monkeypatch.setattr(tj, "_excerpt", _spy)

        res = await tj.get_trade_journal(db, user.id)

        assert seen == [4000], "der volle 200-KB-Body darf die DB nicht verlassen"
        assert res["entries"][0]["rationale"].startswith("Die These: relative Stärke")

    async def test_entries_are_capped_but_summary_counts_everything(self, db, monkeypatch):
        monkeypatch.setattr(tj, "_MAX_JOURNAL_ENTRIES", 3)
        user = await _make_user(db)
        txn_a = await _make_txn(db, user, ticker="OLD1")
        txn_b = await _make_txn(db, user, ticker="OLD2")
        # Die beiden ältesten Pläne sind ausgeführt und fallen aus dem Limit.
        db.add(_report(user, title="alt-1", report_date=date(2026, 1, 1), linked_transaction_id=txn_a.id))
        db.add(_report(user, title="alt-2", report_date=date(2026, 1, 2), linked_transaction_id=txn_b.id))
        for day in (10, 11, 12):
            db.add(_report(user, title=f"neu-{day}", report_date=date(2026, 6, day)))
        await db.commit()

        res = await tj.get_trade_journal(db, user.id)

        assert [e["title"] for e in res["entries"]] == ["neu-12", "neu-11", "neu-10"]
        assert res["summary"] == {"total": 5, "executed": 2, "open": 3}

    async def test_foreign_transaction_does_not_count_as_executed(self, db):
        owner = await _make_user(db)
        other = await _make_user(db)
        foreign_txn = await _make_txn(db, other, ticker="MSFT")
        db.add(_report(owner, linked_transaction_id=foreign_txn.id))
        db.add(_report(other, linked_transaction_id=foreign_txn.id))
        await db.commit()

        res = await tj.get_trade_journal(db, owner.id)

        assert res["summary"] == {"total": 1, "executed": 0, "open": 1}
        assert res["entries"][0]["status"] == "open"
        assert res["entries"][0]["ist"] is None

    def test_journal_route_is_rate_limited(self):
        assert _route_limits("api.analysis.trade_journal_endpoint") == [parse_limit(RL_READ)]


# --- K071: Korrelationsmatrix -------------------------------------------------


class _CorrPos:
    def __init__(self, id_: str, ticker: str, type_value: str = "stock"):
        self.id = uuid.UUID(id_)
        self.ticker = ticker
        self.name = ticker
        self.type = type("T", (), {"value": type_value})()
        self.yfinance_ticker = ticker
        self.gold_org = False
        self.sector = None


class _CorrDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        rows = self._rows
        return MagicMock(scalars=lambda: MagicMock(all=lambda: rows))


def _corr_fixture(tickers: list[str]):
    ids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(1, len(tickers) + 1)]
    rows = [_CorrPos(i, t) for i, t in zip(ids, tickers)]
    summary = {"positions": [
        {"id": i, "ticker": t, "name": t, "type": "stock", "sector": None, "weight_pct": 10.0}
        for i, t in zip(ids, tickers)
    ]}
    return rows, summary


def _close_frame(series: dict[str, list[float]]) -> pd.DataFrame:
    n = len(next(iter(series.values())))
    return pd.DataFrame(series, index=pd.bdate_range(end="2026-04-07", periods=n))


@pytest.fixture
def clean_close_cache():
    corr._close_cache.clear()
    yield
    corr._close_cache.clear()


class TestK071Correlation:
    async def test_parallel_requests_share_one_download(self, clean_close_cache):
        rows, summary = _corr_fixture(["VR11A", "VR11B"])
        frame = _close_frame({
            "VR11A": [100 + i for i in range(40)],
            "VR11B": [50 + (i % 7) for i in range(40)],
        })
        downloads: list[tuple] = []

        def _slow_fetch(tickers, period):
            downloads.append((tuple(tickers), period))
            time.sleep(0.2)
            return frame

        with patch.object(corr, "get_portfolio_summary_cached", return_value=summary), \
             patch.object(corr, "_fetch_close_matrix", side_effect=_slow_fetch):
            first, second = await asyncio.gather(
                corr.compute_correlation_matrix(_CorrDB(rows), uuid.uuid4(), period="90d"),
                corr.compute_correlation_matrix(_CorrDB(rows), uuid.uuid4(), period="90d"),
            )

        assert downloads == [(("VR11A", "VR11B"), "90d")]
        assert first["matrix"] == second["matrix"]
        assert first["warnings"] == []

    async def test_filter_change_with_same_tickers_reuses_the_download(self, clean_close_cache):
        rows, summary = _corr_fixture(["VR11C", "VR11D"])
        frame = _close_frame({
            "VR11C": [100 + i for i in range(40)],
            "VR11D": [80 - (i % 5) for i in range(40)],
        })
        fetch = MagicMock(return_value=frame)

        with patch.object(corr, "get_portfolio_summary_cached", return_value=summary), \
             patch.object(corr, "_fetch_close_matrix", fetch):
            for include_cash in (False, True):
                await corr.compute_correlation_matrix(
                    _CorrDB(rows), uuid.uuid4(), period="90d", include_cash=include_cash,
                )
            # Andere Periode = andere Kursreihen = eigener Download.
            await corr.compute_correlation_matrix(_CorrDB(rows), uuid.uuid4(), period="1y")

        assert fetch.call_count == 2

    async def test_incomplete_frame_expires_before_the_degenerate_result(self, clean_close_cache):
        rows, summary = _corr_fixture(["VR11E", "VR11F"])
        partial = _close_frame({"VR11E": [100 + i for i in range(40)]})

        with patch.object(corr, "get_portfolio_summary_cached", return_value=summary), \
             patch.object(corr, "_fetch_close_matrix", return_value=partial):
            res = await corr.compute_correlation_matrix(_CorrDB(rows), uuid.uuid4(), period="90d")

        assert "no_price_data:VR11F" in res["warnings"]
        (expires_at, _frame), = corr._close_cache.values()
        assert expires_at - time.monotonic() <= 30 < corr.DEGENERATE_CACHE_TTL

    async def test_matrix_is_built_off_the_event_loop(self, clean_close_cache):
        rows, summary = _corr_fixture(["VR11G", "VR11H"])
        frame = _close_frame({
            "VR11G": [100 + i for i in range(40)],
            "VR11H": [60 + (i % 3) for i in range(40)],
        })
        threads: list[threading.Thread] = []
        real_returns = corr._compute_returns

        def _spy(close_df, *args, **kwargs):
            threads.append(threading.current_thread())
            return real_returns(close_df, *args, **kwargs)

        with patch.object(corr, "get_portfolio_summary_cached", return_value=summary), \
             patch.object(corr, "_fetch_close_matrix", return_value=frame), \
             patch.object(corr, "_compute_returns", side_effect=_spy):
            await corr.compute_correlation_matrix(_CorrDB(rows), uuid.uuid4(), period="90d")

        assert threads and all(t is not threading.main_thread() for t in threads)

    def test_build_matrix_matches_the_elementwise_reference(self):
        n = 60
        frame = _close_frame({
            "UP": [100 + i + (i % 4) for i in range(n)],
            "UP2": [200 + 2 * i + 2 * (i % 4) for i in range(n)],
            "WAVE": [100 + 5 * ((i * 7) % 11) for i in range(n)],
            "FLAT": [50.0] * n,  # Rendite konstant 0 -> Korrelation NaN -> None
        })
        meta = {t: {"type": "stock", "sector": None} for t in frame.columns}

        built = corr._build_matrix(frame, list(frame.columns) + ["GONE"], meta)

        returns, _ = corr._compute_returns(frame)
        reference = returns.corr()
        expected_matrix = [
            [None if pd.isna(reference.iat[i, j]) else round(float(reference.iat[i, j]), 4)
             for j in range(len(reference.columns))]
            for i in range(len(reference.columns))
        ]
        assert built["matrix_tickers"] == list(reference.columns)
        assert built["matrix"] == expected_matrix
        flat = built["matrix_tickers"].index("FLAT")
        assert built["matrix"][flat][0] is None
        assert built["warnings"] == ["no_price_data:GONE"]
        assert built["observations"] == len(returns)

        cols = list(reference.columns)
        expected_pairs = {
            (cols[i], cols[j]): expected_matrix[i][j]
            for i in range(len(cols)) for j in range(i + 1, len(cols))
            if expected_matrix[i][j] is not None and abs(reference.iat[i, j]) >= 0.7
        }
        pairs = built["high_correlations"]
        assert {(p["ticker_a"], p["ticker_b"]): p["correlation"] for p in pairs} == expected_pairs
        assert ("UP", "UP2") in expected_pairs
        strengths = [abs(p["correlation"]) for p in pairs]
        assert strengths == sorted(strengths, reverse=True)
        assert all("korreliert" in p["interpretation"] for p in pairs)


# --- K126 / K012: Konzentration -----------------------------------------------


def _summary() -> dict:
    return {
        "total_market_value_chf": 10_000.0,
        "positions": [
            {"ticker": "AAPL", "yfinance_ticker": "AAPL", "name": "Apple", "type": "stock",
             "weight_pct": 60.0, "market_value_chf": 6000.0},
            {"ticker": "SPY", "yfinance_ticker": "SPY", "name": "SPDR S&P 500", "type": "etf",
             "weight_pct": 40.0, "market_value_chf": 4000.0},
        ],
    }


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class TestK126SectorClassificationOffLoop:
    async def test_sync_classification_runs_in_a_worker_thread(self, monkeypatch):
        threads: dict[str, threading.Thread] = {}

        def _target(ticker):
            threads["target"] = threading.current_thread()
            return "Technology"

        def _bulk(tickers):
            threads[f"bulk:{','.join(sorted(tickers))}"] = threading.current_thread()
            return {t: "Technology" for t in tickers}

        monkeypatch.setattr(cs, "_classify_target_sector", _target)
        monkeypatch.setattr(scs, "classify_tickers_bulk", _bulk)
        monkeypatch.setattr(
            "services.portfolio_service.get_portfolio_summary", AsyncMock(return_value=_summary())
        )
        db = AsyncMock()
        # 1. Overlap-Abfrage (leer), 2. ETF-Holdings ohne gespeicherten Sektor.
        db.execute = AsyncMock(side_effect=[_Rows([]), _Rows([("SPY", "MSFT", 7.0, None)])])

        result = await cs.get_concentration_for_ticker(db, "AAPL", uuid.uuid4())

        assert set(threads) == {"target", "bulk:AAPL", "bulk:MSFT"}
        assert all(t is not threading.main_thread() for t in threads.values())
        assert result["sector"]["sector"] == "Technology"


class TestK012SingleSummaryPerScore:
    async def test_with_summary_returns_the_loaded_summary(self, monkeypatch):
        summary = _summary()
        summary_mock = AsyncMock(return_value=summary)
        monkeypatch.setattr("services.portfolio_service.get_portfolio_summary", summary_mock)
        monkeypatch.setattr(cs, "_classify_target_sector", lambda t: None)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_Rows([]))

        concentration, returned = await cs.get_concentration_with_summary(db, "AAPL", uuid.uuid4())

        assert returned is summary
        assert summary_mock.await_count == 1
        assert concentration["single_name"]["direct_position_chf"] == pytest.approx(6000.0)
        # Der bestehende Einstieg liefert weiter nur den Konzentrationsblock.
        assert await cs.get_concentration_for_ticker(db, "AAPL", uuid.uuid4()) == concentration

    async def test_score_endpoint_computes_the_summary_once(self, client, monkeypatch):
        headers = await _login(client, "k012@example.com")
        summary_mock = AsyncMock(return_value=_summary())
        monkeypatch.setattr("services.portfolio_service.get_portfolio_summary", summary_mock)
        monkeypatch.setattr(cs, "_classify_target_sector", lambda t: None)
        assessment = {"ticker": "AAPL", "score": 14, "max_score": 18, "price": 180.0}

        with patch("services.scoring_service.assess_ticker", return_value=assessment):
            res = await client.get("/api/analysis/score/AAPL", headers=headers)

        assert res.status_code == 200, res.text
        assert summary_mock.await_count == 1, "eine Summary je Score-Request, nicht zwei"
        data = res.json()
        assert data["liquid_portfolio_chf"] == 10_000.0
        assert data["concentration"]["single_name"]["direct_position_chf"] == 6000.0


# --- K158: Nutzerdaten nie ins geteilte Assessment ----------------------------


class TestK158NoUserDataInSharedAssessment:
    async def test_score_does_not_mutate_the_cached_assessment(self, client, monkeypatch):
        headers = await _login(client, "k158@example.com")
        monkeypatch.setattr(
            "services.portfolio_service.get_portfolio_summary", AsyncMock(return_value=_summary())
        )
        monkeypatch.setattr(cs, "_classify_target_sector", lambda t: None)
        # Ein Objekt für alle Aufrufer — so liegt das Assessment im Prozess-Cache.
        shared = {"ticker": "AAPL", "score": 14, "max_score": 18, "price": 180.0}

        with patch("services.scoring_service.assess_ticker", return_value=shared):
            res = await client.get("/api/analysis/score/AAPL", headers=headers)

        assert res.status_code == 200, res.text
        assert res.json()["liquid_portfolio_chf"] == 10_000.0
        assert shared == {"ticker": "AAPL", "score": 14, "max_score": 18, "price": 180.0}

    async def test_failed_concentration_does_not_mutate_it_either(self, client, monkeypatch):
        headers = await _login(client, "k158b@example.com")
        monkeypatch.setattr(
            "services.portfolio_service.get_portfolio_summary",
            AsyncMock(side_effect=RuntimeError("summary down")),
        )
        shared = {"ticker": "AAPL", "score": 14, "max_score": 18, "price": 180.0}

        with patch("services.scoring_service.assess_ticker", return_value=shared):
            res = await client.get("/api/analysis/score/AAPL", headers=headers)

        assert res.status_code == 200, res.text
        assert res.json()["concentration"]["sector"] == {"status": "no_sector"}
        assert "concentration" not in shared


# --- K023: Ticker-Form an Pfad und Watchlist ----------------------------------

_BAD_TICKERS = ["AAPL,MSFT", "AAPL%20MSFT", "A" * 31, "AAPL;DROP"]


class TestK023TickerValidation:
    @pytest.mark.parametrize("bad", _BAD_TICKERS)
    @pytest.mark.parametrize("route, target", [
        ("/api/analysis/mrs-history/{t}", "services.chart_service.get_mrs_history"),
        ("/api/analysis/breakouts/{t}", "services.chart_service.get_breakout_events"),
        ("/api/analysis/levels/{t}", "services.chart_service.get_support_resistance_levels"),
        ("/api/analysis/reversal/{t}", "services.chart_service.get_three_point_reversal"),
        ("/api/analysis/heartbeat/{t}", "services.chart_service.get_heartbeat_pattern"),
        ("/api/analysis/score/{t}", "services.scoring_service.assess_ticker"),
        ("/api/stock/{t}/profile", "api.stock.get_company_profile"),
    ])
    async def test_ticker_lists_never_reach_yahoo(self, client, route, target, bad):
        headers = await _login(client, "k023@example.com")

        with patch(target) as yahoo_bound:
            res = await client.get(route.format(t=bad), headers=headers)

        assert res.status_code == 422, res.text
        yahoo_bound.assert_not_called()

    async def test_resistance_route_rejects_ticker_lists(self, client):
        headers = await _login(client, "k023r@example.com")
        res = await client.put(
            "/api/analysis/resistance/AAPL,MSFT", json={"manual_resistance": 1.0}, headers=headers,
        )
        assert res.status_code == 422

    @pytest.mark.parametrize("good", ["BRK-B", "ROG.SW", "%5EGSPC", "EURUSD=X", "BTC-USD", "aapl"])
    async def test_real_ticker_shapes_still_pass(self, client, good):
        headers = await _login(client, "k023g@example.com")

        with patch("services.chart_service.get_breakout_events", return_value=[]) as events:
            res = await client.get(f"/api/analysis/breakouts/{good}", headers=headers)

        assert res.status_code == 200, res.text
        events.assert_called_once()

    @pytest.mark.parametrize("bad", ["AA,AB,AC", "AA AB", "A" * 31, ""])
    async def test_watchlist_rejects_non_ticker_values(self, client, bad):
        headers = await _login(client, "k023w@example.com")
        res = await client.post(
            "/api/analysis/watchlist", json={"ticker": bad, "name": "Sammelabruf"}, headers=headers,
        )
        assert res.status_code == 422, res.text

    async def test_watchlist_accepts_exchange_suffix(self, client):
        headers = await _login(client, "k023ok@example.com")
        res = await client.post(
            "/api/analysis/watchlist", json={"ticker": "ROG.SW", "name": "Roche"}, headers=headers,
        )
        assert res.status_code == 201, res.text

    @pytest.mark.parametrize("query, lookups", [("APPLE INC", 0), ("AAPL", 1)])
    async def test_search_fallback_only_looks_up_ticker_shaped_input(self, client, query, lookups):
        headers = await _login(client, "k023s@example.com")
        info = MagicMock(return_value={})

        with patch("yf_patch.yf_search", side_effect=RuntimeError("search down")), \
             patch("yf_patch.yf_ticker_attr", info):
            res = await client.get("/api/stock/search", params={"q": query}, headers=headers)

        assert res.status_code == 200, res.text
        assert info.call_count == lookups


# --- K029: Enddatum der Faktor-Decomposition ----------------------------------


class TestK029FactorDecompositionEnd:
    async def test_future_end_is_clamped_to_today(self, client):
        headers = await _login(client, "k029@example.com")
        service = AsyncMock(return_value={"betas": {}})

        with patch("services.factor_decomposition_service.factor_decomposition", service):
            res = await client.get(
                "/api/analysis/factor-decomposition", params={"end": "9999-12-30"}, headers=headers,
            )

        assert res.status_code == 200, res.text
        _db, start, end = service.await_args.args[:3]
        assert end <= date.today()
        assert start == end - timedelta(days=365 * 5)

    async def test_past_end_is_kept(self, client):
        headers = await _login(client, "k029b@example.com")
        service = AsyncMock(return_value={"betas": {}})

        with patch("services.factor_decomposition_service.factor_decomposition", service):
            await client.get(
                "/api/analysis/factor-decomposition",
                params={"start": "2024-01-01", "end": "2025-01-01"}, headers=headers,
            )

        assert service.await_args.args[1:3] == (date(2024, 1, 1), date(2025, 1, 1))

    async def test_start_after_today_is_rejected(self, client):
        headers = await _login(client, "k029c@example.com")
        service = AsyncMock(return_value={})

        with patch("services.factor_decomposition_service.factor_decomposition", service):
            res = await client.get(
                "/api/analysis/factor-decomposition",
                params={"start": "2999-01-01", "end": "9999-12-30"}, headers=headers,
            )

        assert res.status_code == 400
        service.assert_not_awaited()


# --- X02: Score-Limit trägt eine Tabelle voller Ticker ------------------------


def test_score_route_uses_the_per_ticker_read_limit():
    assert _route_limits("api.analysis.get_score") == [parse_limit(RL_TICKER_READ)]
