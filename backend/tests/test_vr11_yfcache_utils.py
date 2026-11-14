"""Vollreview 11/2026, Fixer yfcache: services/utils.py, chart_service.py,
ticker_info_service.py.

- K011: Negativ-Marker im Sammelabruf der Kursreihen, single_flight um den Download.
- K023: yf_download bekommt Listen, nie verbundene Zeichenketten.
- K100: nur bekannte Währungscodes erreichen Cache, DB und Yahoo.
- K125: prefetch_close_series liest per MGET.
- K115: gültige yfinance-Periode «6mo».
- K042: Yahoo-Währung GBp/GBX wird zu GBP.
- K059: ticker_info läuft im eigenen Pool.

Netzfrei: yf_download und yf_ticker_attr sind ersetzt.
"""
from __future__ import annotations

import ast
import inspect
import threading
import time
from datetime import date

import pandas as pd
import pytest
from httpx import AsyncClient
from sqlalchemy import select

import services.cache_service as cache_service
import services.chart_service as chart_service
import services.utils as utils
from services import cache

TEST_PASSWORD = "TestPassw0rd!2026"


@pytest.fixture(autouse=True)
def local_cache(monkeypatch):
    """Ohne Redis: der Prozessspeicher ist die einzige Quelle, je Test frisch."""
    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    cache._mem_clear()
    yield
    cache._mem_clear()


def _batch_frame(tickers: list[str], rows: int = 300) -> pd.DataFrame:
    """Frame wie yf_download(group_by="ticker"): Spalten (Ticker, Feld)."""
    idx = pd.date_range("2025-01-01", periods=rows, freq="D")
    frame = pd.DataFrame({(t, "Close"): [float(i + 1) for i in range(rows)] for t in tickers}, index=idx)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


class _Download:
    """Ersatz für utils.yf_download: liefert Reihen nur für ``known``."""

    def __init__(self, known: set[str], delay: float = 0.0):
        self.known = known
        self.delay = delay
        self.calls: list[object] = []
        self._lock = threading.Lock()

    def __call__(self, tickers, **kwargs):
        with self._lock:
            self.calls.append(tickers)
        if self.delay:
            time.sleep(self.delay)
        have = [t for t in tickers if t in self.known]
        return _batch_frame(have) if have else pd.DataFrame()


# --- K011: Negativ-Marker und single_flight im Sammelabruf ------------------------


class TestPrefetchNegativeCache:
    def test_ticker_without_data_is_not_downloaded_again(self, monkeypatch):
        """Anleihen und erfundene Ticker erreichen _get_close_series nie; ohne
        Marker lud jeder Summary-Request sie erneut."""
        download = _Download({"GOOD"})
        monkeypatch.setattr(utils, "yf_download", download)

        utils.prefetch_close_series(["GOOD", "DEADBOND"])
        utils.prefetch_close_series(["GOOD", "DEADBOND"])
        utils.prefetch_close_series(["DEADBOND"])

        assert download.calls == [["GOOD", "DEADBOND"]]
        assert len(cache.get("close:GOOD:2y")) == 300
        assert len(cache.get("close:GOOD:1y")) == 252

    def test_marker_lives_fifteen_minutes(self, monkeypatch):
        monkeypatch.setattr(utils, "yf_download", _Download(set()))
        utils.prefetch_close_series(["DEADBOND"])

        _, expires_at = cache._mem_cache["close_miss:DEADBOND:2y"]
        assert 890 < expires_at - time.monotonic() <= 900

    def test_failed_batch_is_not_repeated(self, monkeypatch):
        calls: list[object] = []

        def boom(tickers, **kwargs):
            calls.append(tickers)
            raise RuntimeError("yahoo down")

        monkeypatch.setattr(utils, "yf_download", boom)
        utils.prefetch_close_series(["AAA", "BBB"])
        utils.prefetch_close_series(["AAA", "BBB"])
        assert calls == [["AAA", "BBB"]]

    def test_marker_does_not_hide_the_ticker_from_get_close_series(self, monkeypatch):
        """Der Marker bremst nur den Sammelabruf. Für MA und MRS versucht
        _get_close_series weiter den Einzelabruf und den DB-Fallback."""
        download = _Download(set())
        monkeypatch.setattr(utils, "yf_download", download)
        db_series = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2026-01-01", periods=3))
        monkeypatch.setattr(cache_service, "get_close_series_from_db", lambda t, p: db_series)

        utils.prefetch_close_series(["DBONLY"])
        got = utils._get_close_series("DBONLY", "2y")

        assert got is not None and list(got.values) == [1.0, 2.0, 3.0]
        assert download.calls == [["DBONLY"], ["DBONLY"]]  # Batch, dann Einzelabruf

    def test_series_found_later_ends_the_marker_path(self, monkeypatch):
        download = _Download(set())
        monkeypatch.setattr(utils, "yf_download", download)
        utils.prefetch_close_series(["LATE"])

        cache.set("close:LATE:2y", pd.Series([float(i) for i in range(300)]))
        utils.prefetch_close_series(["LATE"])

        assert len(download.calls) == 1
        assert len(cache.get("close:LATE:1y")) == 252  # 1y weiter aus 2y abgeleitet

    def test_metal_spot_tickers_get_no_marker(self, monkeypatch):
        monkeypatch.setattr(utils, "yf_download", _Download(set()))
        utils.prefetch_close_series(["XAUCHF=X"])
        assert cache._mem_cache == {}


class TestPrefetchSingleFlight:
    def test_parallel_requests_download_once(self, monkeypatch):
        """Summary, Alerts und Rebalancing rechnen beim Laden einer Seite
        gleichzeitig — vorher drei Abrufserien gegen Yahoo."""
        download = _Download({"AAA", "BBB"}, delay=0.3)
        monkeypatch.setattr(utils, "yf_download", download)

        start = threading.Barrier(4)
        errors: list[BaseException] = []

        def worker():
            try:
                start.wait(timeout=5)
                utils.prefetch_close_series(["AAA", "BBB", "^GSPC"])
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        assert all(not t.is_alive() for t in threads)
        assert len(download.calls) == 1
        assert cache.get("close:AAA:2y") is not None
        assert cache.get("close:BBB:1y") is not None

    def test_different_ticker_sets_do_not_wait_for_each_other(self, monkeypatch):
        """Der Schutz gilt je Ticker-Menge: ein hängender Abruf eines Nutzers
        hält den eines anderen nicht auf."""
        entered = threading.Event()
        release = threading.Event()
        calls: list[object] = []

        def download(tickers, **kwargs):
            calls.append(tickers)
            if tickers == ["SLOW"]:
                entered.set()
                release.wait(timeout=10)
            return _batch_frame(list(tickers))

        monkeypatch.setattr(utils, "yf_download", download)
        slow = threading.Thread(target=utils.prefetch_close_series, args=(["SLOW"],), daemon=True)
        slow.start()
        try:
            assert entered.wait(timeout=5)
            utils.prefetch_close_series(["FAST"])
            assert cache.get("close:FAST:2y") is not None
        finally:
            release.set()
            slow.join(timeout=10)
        assert not slow.is_alive()


class TestDownloadsUseLists:
    def test_prefetch_passes_one_list_element_per_ticker(self, monkeypatch):
        """Nie eine verbundene Zeichenkette: yfinance trennt sie an Komma und
        Leerzeichen, ein Ticker «A,B C» würde zu drei Abrufen. Freitext-Ticker
        (Vorsorge, Cash) bleiben still draussen, ohne Abruf und ohne Marker."""
        download = _Download(set())
        monkeypatch.setattr(utils, "yf_download", download)
        utils.prefetch_close_series(["AAPL", "A,B C", "Säule 3a", "BRK-B"])
        assert download.calls == [["AAPL", "BRK-B"]]
        assert "close_miss:A,B C:2y" not in cache._mem_cache
        assert "close_miss:Säule 3a:2y" not in cache._mem_cache

    def test_get_close_series_passes_a_list(self, monkeypatch):
        download = _Download(set())
        monkeypatch.setattr(utils, "yf_download", download)
        monkeypatch.setattr(cache_service, "get_close_series_from_db", lambda t, p: None)
        utils._get_close_series("BRK-B", "1y")
        assert download.calls == [["BRK-B"]]

    def test_get_close_series_skips_yahoo_for_free_text_tickers(self, monkeypatch):
        """Der DB-Fallback und der Negativ-Cache bleiben wie zuvor."""
        download = _Download(set())
        monkeypatch.setattr(utils, "yf_download", download)
        asked: list[str] = []
        monkeypatch.setattr(
            cache_service, "get_close_series_from_db", lambda t, p: asked.append(t) or None
        )
        assert utils._get_close_series("A,B,C", "1y") is None
        assert utils._get_close_series("A,B,C", "1y") is None
        assert download.calls == []
        assert asked == ["A,B,C"]
        assert cache.get("close:A,B,C:1y") == utils._CLOSE_NEG_SENTINEL

    @pytest.mark.parametrize(
        "call",
        [
            lambda: chart_service.get_breakout_events("A,B,C", "1y"),
            lambda: chart_service.get_support_resistance_levels("A,B,C"),
            lambda: chart_service.get_heartbeat_pattern("A,B,C"),
        ],
        ids=["breakouts", "levels", "heartbeat"],
    )
    def test_chart_service_passes_a_list(self, monkeypatch, call):
        download = _Download(set())
        monkeypatch.setattr(chart_service, "yf_download", download)
        monkeypatch.setattr(chart_service, "_get_close_series", lambda *a, **k: None)
        call()
        assert download.calls == [["A,B,C"]]

    def test_separator_ticker_reaches_yahoo_zero_times(self, monkeypatch):
        """Ende zu Ende durch den echten Wrapper: kein einziger Abruf."""
        import yf_patch

        seen: list[object] = []
        monkeypatch.setattr(yf_patch.yf, "download", lambda tickers, **k: seen.append(tickers) or pd.DataFrame())
        monkeypatch.setattr(cache_service, "get_close_series_from_db", lambda t, p: None)

        assert utils._get_close_series("AAPL,MSFT GOOG", "1y") is None
        assert chart_service.get_breakout_events("AAPL,MSFT GOOG", "1y") == []
        assert seen == []


# --- K125: MGET statt Einzelabfragen ----------------------------------------------


class _CountingRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.get_calls = 0
        self.mget_calls = 0

    def get(self, key):
        self.get_calls += 1
        return self.store.get(key)

    def mget(self, keys):
        self.mget_calls += 1
        return [self.store.get(k) for k in keys]

    def set(self, key, value, ex=None, nx=False):
        self.store[key] = value
        return True

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


class TestPrefetchBatchesCacheReads:
    def test_warm_prefetch_needs_two_roundtrips(self, monkeypatch):
        """Vorher zwei bis drei GET je Ticker und Summary-Request."""
        fake = _CountingRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        tickers = [f"T{i}" for i in range(50)]
        for t in tickers:
            cache.set(f"close:{t}:2y", pd.Series([float(i) for i in range(300)]))

        def no_download(*a, **k):
            raise AssertionError("alles gecacht — kein Download erwartet")

        monkeypatch.setattr(utils, "yf_download", no_download)
        utils.prefetch_close_series(tickers)

        assert fake.get_calls == 0
        assert fake.mget_calls == 2
        assert len(cache.get("close:T49:1y")) == 252


# --- K100: Währungscodes ----------------------------------------------------------


def _fx_frame(rate: float) -> pd.DataFrame:
    return pd.DataFrame({"Close": [rate, rate]}, index=pd.date_range("2026-11-10", periods=2))


class TestExtendedFx:
    @pytest.fixture
    def no_db(self, monkeypatch):
        monkeypatch.setattr(cache_service, "get_cached_price_sync", lambda *a, **k: None)

    @pytest.mark.parametrize("code", ["QQQAA", "QQQ", "X1", "ZZ1", "", "USDT", "A,B", "EUR USD", None])
    def test_unknown_code_touches_neither_cache_nor_db_nor_yahoo(self, monkeypatch, code):
        def boom(*a, **k):
            raise AssertionError("darf für unbekannte Codes nicht laufen")

        monkeypatch.setattr(utils, "yf_download", boom)
        monkeypatch.setattr(cache_service, "get_cached_price_sync", boom)

        assert utils._resolve_extended_fx(code) is None
        assert cache._mem_cache == {}  # kein Schlüssel aus der Eingabe

    def test_iso_code_is_resolved_once(self, monkeypatch, no_db):
        calls: list[object] = []
        monkeypatch.setattr(utils, "yf_download", lambda t, **k: calls.append(t) or _fx_frame(0.085))

        assert utils._resolve_extended_fx("SEK") == pytest.approx(0.085)
        assert utils._resolve_extended_fx("SEK") == pytest.approx(0.085)
        assert utils._resolve_extended_fx("sek") == pytest.approx(0.085)
        assert calls == [["SEKCHF=X"]]

    def test_failure_is_cached_negatively(self, monkeypatch, no_db):
        calls: list[object] = []
        monkeypatch.setattr(utils, "yf_download", lambda t, **k: calls.append(t) or pd.DataFrame())

        for _ in range(5):
            assert utils._resolve_extended_fx("KPW") is None
        assert calls == [["KPWCHF=X"]]
        _, expires_at = cache._mem_cache["fx_ext:KPW"]
        assert 0 < expires_at - time.monotonic() <= 300

    @pytest.mark.parametrize("code,pair", [("CNH", "CNHCHF=X"), ("GBX", "GBXCHF=X"), ("GBp", "GBPCHF=X")])
    def test_market_codes_outside_iso_behave_as_before(self, monkeypatch, no_db, code, pair):
        calls: list[object] = []
        monkeypatch.setattr(utils, "yf_download", lambda t, **k: calls.append(t) or _fx_frame(0.12))
        assert utils._resolve_extended_fx(code) == pytest.approx(0.12)
        assert calls == [[pair]]

    def test_db_rate_is_used_before_yahoo(self, monkeypatch):
        seen: list[str] = []

        def db_rate(pair, fallback_days=0):
            seen.append(pair)
            return {"price": 0.61}

        monkeypatch.setattr(cache_service, "get_cached_price_sync", db_rate)
        monkeypatch.setattr(utils, "yf_download", lambda *a, **k: pytest.fail("kein Yahoo-Abruf erwartet"))
        assert utils._resolve_extended_fx("aud") == pytest.approx(0.61)
        assert seen == ["AUDCHF=X"]


class TestFxRateFallback:
    def test_unknown_code_costs_no_db_queries(self, monkeypatch):
        """Vorher fünf Sync-Abfragen (get_fallback_fx) je unbekanntem Code."""
        monkeypatch.setattr(utils, "get_fx_rates_batch", lambda: {"CHF": 1.0, "USD": 0.88})
        monkeypatch.setattr(utils, "get_fallback_fx", lambda: pytest.fail("kein DB-Fallback erwartet"))
        monkeypatch.setattr(utils, "yf_download", lambda *a, **k: pytest.fail("kein Yahoo-Abruf erwartet"))
        monkeypatch.setattr(cache_service, "get_cached_price_sync", lambda *a, **k: pytest.fail("keine DB"))

        assert utils.get_fx_rate("QQQAA", "CHF") == 1.0
        assert utils.get_fx_rate("QQQAA", "QQQAB") == 1.0

    def test_standard_currency_still_uses_the_db_fallback(self, monkeypatch):
        monkeypatch.setattr(utils, "get_fx_rates_batch", lambda: {"CHF": 1.0})
        monkeypatch.setattr(utils, "get_fallback_fx", lambda: {"USDCHF": 0.9})
        assert utils.get_fx_rate("USD", "CHF") == pytest.approx(0.9)


# --- K115: gültige yfinance-Periode -------------------------------------------------


def _close_series_periods(module) -> list[str]:
    tree = ast.parse(inspect.getsource(module))
    periods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_get_close_series":
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                periods.append(node.args[1].value)
    return periods


class TestClosePeriods:
    @pytest.mark.parametrize("module", [chart_service, utils], ids=["chart_service", "utils"])
    def test_every_period_is_valid_for_yfinance(self, module):
        """«6m» kennt yfinance nicht (YFInvalidPeriodError) — der Abruf lieferte nie Daten."""
        from yfinance.utils import is_valid_period_format

        periods = _close_series_periods(module)
        assert periods, "keine Aufrufe gefunden — Test prüft nichts"
        assert [p for p in periods if not is_valid_period_format(p)] == []

    def test_three_point_reversal_requests_six_months(self, monkeypatch):
        seen: list[tuple] = []
        series = pd.Series([float(i) for i in range(120)], index=pd.date_range("2026-05-01", periods=120))

        def fake_close(ticker, period="1y"):
            seen.append((ticker, period))
            return series

        monkeypatch.setattr(chart_service, "_get_close_series", fake_close)
        result = chart_service.get_three_point_reversal("NOBODY")

        assert seen == [("NOBODY", "6mo")]
        assert "detected" in result

    def test_db_fallback_knows_the_period(self):
        """get_close_series_from_db bildet unbekannte Perioden still auf 365 Tage ab."""
        source = inspect.getsource(cache_service.get_close_series_from_db)
        assert '"6mo": 180' in source


# --- K042 / K059: ticker_info_service ------------------------------------------------


class TestNormalizeCurrency:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("GBp", "GBP"), ("GBX", "GBP"), ("gbx", "GBP"), ("GBP", "GBP"),
            ("usd", "USD"), (" EUR ", "EUR"), ("CHF", "CHF"), ("CNH", "CNH"),
            ("ZAc", None), ("ILA", None), ("USDT", None), ("", None), (None, None), (123, None),
        ],
    )
    def test_normalize(self, raw, expected):
        from services.ticker_info_service import _normalize_currency

        # .L-Ticker: nur dort wird Pence zu GBP (R-yfanalysis-6).
        assert _normalize_currency(raw, "SHEL.L") == expected


def _patch_info(monkeypatch, info: dict, threads: list[str] | None = None) -> list[str]:
    import yf_patch

    calls: list[str] = []

    def fake(ticker, attr):
        calls.append(ticker)
        if threads is not None:
            threads.append(threading.current_thread().name)
        return dict(info)

    monkeypatch.setattr(yf_patch, "yf_ticker_attr", fake)
    return calls


class TestTickerInfo:
    async def test_pence_quoted_ticker_yields_gbp(self, monkeypatch):
        from services.ticker_info_service import get_ticker_info_cached

        _patch_info(monkeypatch, {"shortName": "Shell plc", "currency": "GBp"})
        info = await get_ticker_info_cached("SHEL.L")

        assert info["currency"] == "GBP"
        assert cache.get("ticker_info:SHEL.L")["currency"] == "GBP"

    async def test_entry_cached_before_the_fix_is_normalized_on_read(self, monkeypatch):
        from services.ticker_info_service import get_ticker_info_cached

        calls = _patch_info(monkeypatch, {})
        cache.set("ticker_info:BP.L", {"shortName": "BP", "longName": None, "currency": "GBp"})

        info = await get_ticker_info_cached("BP.L")
        assert info == {"shortName": "BP", "longName": None, "currency": "GBP"}
        assert calls == []

    async def test_non_currency_code_is_unknown(self, monkeypatch):
        from services.ticker_info_service import get_ticker_info_cached

        _patch_info(monkeypatch, {"shortName": "Naspers", "currency": "ZAc"})
        info = await get_ticker_info_cached("NPN.JO")
        assert info["shortName"] == "Naspers"
        assert info["currency"] is None  # Aufrufer behält die Währung der Buchung

    async def test_lookup_runs_in_the_ticker_pool(self, monkeypatch):
        """K059: nicht im Default-Executor, den Summary, Kurse und FX brauchen."""
        from services.ticker_info_service import get_ticker_info_cached

        threads: list[str] = []
        _patch_info(monkeypatch, {"shortName": "Apple", "currency": "USD"}, threads)
        await get_ticker_info_cached("AAPL")
        assert len(threads) == 1 and threads[0].startswith("yf-ticker")


async def _login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


class TestPenceTickerEndToEnd:
    async def test_order_fill_creates_a_gbp_position_that_can_be_valued(self, client, db, monkeypatch):
        """Vorher: Position mit currency=GBp, die Summary fand keinen FX-Kurs und
        bewertete sie mit 0 CHF."""
        from models.position import Position
        from services.portfolio_service import _compute_market_value

        _patch_info(monkeypatch, {"shortName": "Shell plc", "currency": "GBp"})
        headers = await _login(client, "vr11-yfcache-gbp@test.local")

        order = await client.post(
            "/api/orders/pending",
            json={"ticker": "SHEL.L", "side": "buy", "shares": 10, "limit_price": 25.0,
                  "currency": "GBP", "expiry_type": "gtc"},
            headers=headers,
        )
        assert order.status_code in (200, 201), order.text
        fill = await client.post(
            f"/api/orders/pending/{order.json()['id']}/fill",
            json={"price_per_share": 25.0, "fill_date": date.today().isoformat(),
                  "fees_chf": 0, "fx_rate_to_chf": 1.12},
            headers=headers,
        )
        assert fill.status_code == 200, fill.text

        pos = (await db.execute(select(Position).where(Position.ticker == "SHEL.L"))).scalar_one()
        assert pos.currency == "GBP"

        # Kurs wie ihn der Worker schreibt: _pence_divisor hat Pence schon in Pfund umgerechnet.
        value_chf, price, currency, stale = _compute_market_value(
            pos, {"CHF": 1.0, "GBP": 1.12}, {"SHEL.L": {"price": 25.0, "currency": "GBP", "change_pct": 0}}
        )
        assert value_chf == pytest.approx(10 * 25.0 * 1.12)
        assert (price, currency, stale) == (25.0, "GBP", {})
