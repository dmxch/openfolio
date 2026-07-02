"""Regression tests for Review-Fix Batch D (Code-Review 2026-07-02).

Covers:
- H6: Scorer-Analysis überlebt den JSON-Round-Trip (Redis) mit identischer
  Kriterien-Bewertung — passed-Sets sind über Prozesse deterministisch.
- M5: cache.get() liest Redis-first — Cross-Worker-Invalidation wirkt.
- M6: _get_redis() versucht nach einem Fehlstart periodisch neu zu verbinden.
- M30: Redis-Fehler leaken nie zum Aufrufer.
- M21: ^GSPC-Benchmark liegt in eigenem Cache-Key; Folge-Scores laden nur
  noch den Ticker.
- M13: Wyckoff-Volumen-Slope ist unabhängig vom absoluten Volumen-Niveau.
- LOW: Serien werden vor positional-Indexing gemeinsam aligned.
- LOW: Negative-Caching in get_breakout_events / get_support_resistance_levels.
- LOW: totes "weight"-Feld an Kriterium id=8 entfernt.

Kein Netz: yf_download wird mit synthetischen DataFrames gemockt.
"""
from __future__ import annotations

import json
import types

import numpy as np
import pandas as pd
import pytest

from services import cache


# --- Cache state isolation -------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_cache_state():
    """Isolate the module-global cache state per test."""
    cache._mem_clear()
    cache._redis = None
    cache._redis_available = False
    cache._redis_last_attempt = None
    yield
    cache._mem_clear()
    cache._redis = None
    cache._redis_available = False
    cache._redis_last_attempt = None


class FakeRedis:
    """Minimal in-process stand-in for redis.Redis (decode_responses=True)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)

    def ping(self):
        return True

    def scan(self, cursor, match=None, count=None):
        return 0, list(self.store.keys())


class BrokenRedis(FakeRedis):
    def get(self, key):
        raise ConnectionError("redis get boom")

    def set(self, key, value, ex=None):
        raise ConnectionError("redis set boom")

    def delete(self, *keys):
        raise ConnectionError("redis delete boom")


# --- M5: Redis-first reads --------------------------------------------------

class TestCacheRedisFirst:
    def test_cross_worker_invalidation_effective(self, monkeypatch):
        """Löscht ein anderer Worker den Redis-Key, darf die prozesslokale
        Memory-Kopie NICHT mehr zählen (vorher: bis zu 60s stale)."""
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)

        cache.set("k1", {"a": 1})
        assert cache.get("k1") == {"a": 1}

        # Simulierter delete() im anderen Worker: nur Redis-Key verschwindet
        fake.store.clear()
        assert cache.get("k1") is None

    def test_fresh_redis_value_wins_over_stale_memory(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)

        cache.set("k2", {"v": "old"})
        # Anderer Worker schreibt einen neuen Wert direkt nach Redis
        fake.store[f"{cache._KEY_PREFIX}k2"] = json.dumps({"v": "new"})
        assert cache.get("k2") == {"v": "new"}

    def test_non_serializable_values_survive_redis_miss(self, monkeypatch):
        """pandas Series liegen nur im Memory — ein Redis-Miss darf sie
        nicht verschlucken (sonst yf-Hammering pro Request)."""
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)

        s = pd.Series([1.0, 2.0, 3.0])
        cache.set("k3", s)
        got = cache.get("k3")
        assert isinstance(got, pd.Series)
        assert list(got.values) == [1.0, 2.0, 3.0]

    def test_memory_fallback_when_redis_down(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        cache.set("k4", {"a": 1})
        assert cache.get("k4") == {"a": 1}

    def test_delete_removes_both_layers(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("k6", {"a": 1})
        cache.delete("k6")
        assert f"{cache._KEY_PREFIX}k6" not in fake.store
        assert cache.get("k6") is None


# --- M30: Fehler leaken nie -------------------------------------------------

class TestCacheErrorIsolation:
    def test_redis_errors_never_leak(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: BrokenRedis())

        cache.set("k5", {"a": 1})            # darf nicht raisen
        assert cache.get("k5") == {"a": 1}   # Memory-Fallback greift
        cache.delete("k5")                   # darf nicht raisen
        assert cache.get("k5") is None
        cache.clear()                        # darf nicht raisen


# --- M6: Reconnect nach Fehlstart --------------------------------------------

class TestRedisReconnect:
    def test_reconnect_after_failed_first_attempt(self, monkeypatch):
        clock = {"t": 1000.0}
        monkeypatch.setattr(
            cache, "time", types.SimpleNamespace(monotonic=lambda: clock["t"])
        )

        pings = {"n": 0}

        class FlakyClient(FakeRedis):
            def ping(self):
                pings["n"] += 1
                if pings["n"] == 1:
                    raise ConnectionError("redis not up yet")
                return True

        flaky = FlakyClient()
        monkeypatch.setattr(
            cache, "redis", types.SimpleNamespace(from_url=lambda *a, **kw: flaky)
        )

        # Erstversuch schlägt fehl → In-Memory-Fallback
        assert cache._get_redis() is None
        assert pings["n"] == 1

        # Innerhalb des Retry-Intervalls: KEIN neuer Verbindungsversuch
        clock["t"] += 5.0
        assert cache._get_redis() is None
        assert pings["n"] == 1

        # Nach Ablauf des Intervalls: Retry → verbunden (vorher: für die
        # gesamte Prozess-Lebensdauer festgenagelt)
        clock["t"] += cache._REDIS_RETRY_INTERVAL + 1.0
        assert cache._get_redis() is flaky
        assert pings["n"] == 2
        assert cache._redis_available is True


# --- Synthetic yfinance frames -----------------------------------------------

def _make_price_frame(
    ticker: str, days: int = 520, seed: int = 7, with_gaps: bool = False
) -> pd.DataFrame:
    """MultiIndex-(ticker, field)-Frame wie yf_download(group_by="ticker")."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-07-01", periods=days, freq="B")
    close = pd.Series(np.linspace(80.0, 140.0, days) + rng.normal(0, 1.0, days), index=idx)
    high = close + rng.uniform(0.2, 1.5, days)
    low = close - rng.uniform(0.2, 1.5, days)
    open_ = close + rng.normal(0, 0.5, days)
    volume = pd.Series(rng.integers(800_000, 1_400_000, days).astype(float), index=idx)
    if with_gaps:
        # NaN-Lücken an UNTERSCHIEDLICHEN Tagen pro Serie → getrenntes
        # dropna() erzeugt verschieden lange Serien (Misalignment-Szenario)
        volume.iloc[100] = np.nan
        high.iloc[200] = np.nan
    frame = pd.concat(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        axis=1,
    )
    frame.columns = pd.MultiIndex.from_product([[ticker], frame.columns])
    return frame


def _make_batch_frame(ticker: str, with_gaps: bool = False) -> pd.DataFrame:
    """Batch-Download-Frame für '<ticker> ^GSPC'."""
    stock = _make_price_frame(ticker, seed=7, with_gaps=with_gaps)
    bench = _make_price_frame("^GSPC", seed=13)
    return pd.concat([stock, bench], axis=1)


_FAKE_INFO = {
    "shortName": "Test Corp",
    "sector": "Technology",
    "industry": "Software",
    "currency": "USD",
    "marketCap": 5_000_000_000,
    "averageVolume": 1_000_000,
    "sharesOutstanding": 50_000_000,
}


def _run_score_stock(monkeypatch, stock_scorer, analysis: dict) -> dict:
    """score_stock mit fixiertem Analysis-Dict und ohne externe Abhängigkeiten."""
    import services.chart_service as chart_service
    import services.earnings_service as earnings_service

    monkeypatch.setattr(stock_scorer, "_download_and_analyze", lambda t: analysis)
    monkeypatch.setattr(stock_scorer, "yf_ticker_attr", lambda t, a: dict(_FAKE_INFO))
    monkeypatch.setattr(earnings_service, "get_next_earnings_date", lambda t: None)
    monkeypatch.setattr(
        chart_service,
        "compute_industry_mrs_simple",
        lambda db, t: {"passed": None, "industry_name": None, "reason": "not_computed"},
    )
    return stock_scorer.score_stock("H6T")


# --- H6: deterministische Scores über den Redis-Round-Trip -------------------

class TestScorerJsonRoundTrip:
    def test_cached_dict_is_fully_json_serializable(self, monkeypatch):
        """Der Aliasing-Hack (Series nachträglich ans Cache-Objekt hängen)
        ist weg: das gecachte Dict enthält keine _-Keys und übersteht
        json.dumps ohne default=str-Stringifizierung von Serien."""
        from services import stock_scorer

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        batch = _make_batch_frame("H6T", with_gaps=True)
        monkeypatch.setattr(stock_scorer, "yf_download", lambda *a, **kw: batch)

        fresh = stock_scorer._download_and_analyze("H6T")
        assert isinstance(fresh.get("_close_series"), pd.Series)

        stored = cache.get("scorer_data:H6T")
        assert isinstance(stored, dict)
        assert not any(k.startswith("_") for k in stored)
        json.dumps(stored)  # darf nicht raisen
        assert stored["series"]["close"] is not None
        assert stored["series"]["volume"] is not None

    def test_json_roundtrip_yields_identical_passed_sets(self, monkeypatch):
        """Kernforderung H6: Redis-Hit im anderen Prozess (= JSON-Round-Trip)
        liefert exakt dieselbe Kriterien-Bewertung wie das frische Objekt."""
        from services import stock_scorer

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        batch = _make_batch_frame("H6T", with_gaps=True)
        monkeypatch.setattr(stock_scorer, "yf_download", lambda *a, **kw: batch)

        fresh = stock_scorer._download_and_analyze("H6T")

        # Simulierter Cross-Prozess-Redis-Hit: nur die JSON-Repräsentation
        wire = json.loads(
            json.dumps({k: v for k, v in fresh.items() if not k.startswith("_")})
        )
        rehydrated = stock_scorer._attach_series(wire)
        assert isinstance(rehydrated.get("_close_series"), pd.Series)

        fresh_score = _run_score_stock(monkeypatch, stock_scorer, fresh)
        cached_score = _run_score_stock(monkeypatch, stock_scorer, rehydrated)

        fresh_passed = {c["id"]: c["passed"] for c in fresh_score["criteria"]}
        cached_passed = {c["id"]: c["passed"] for c in cached_score["criteria"]}
        assert fresh_passed == cached_passed
        assert fresh_score["score"] == cached_score["score"]
        assert fresh_score["max_score"] == cached_score["max_score"]
        assert fresh_score["pct"] == cached_score["pct"]
        assert fresh_score["rating"] == cached_score["rating"]

        # Die vormals verlorenen Serien-Kriterien sind im "Redis-Hit"-Pfad
        # bewertbar (vorher fielen 16/17/18 auf None und 21 verlor den Modifier)
        assert cached_passed[16] is not None
        assert cached_passed[17] is not None
        assert cached_passed[18] is not None
        mod21 = next(c for c in cached_score["criteria"] if c["id"] == 21)
        assert mod21["score_modifier"] is not None

    def test_dead_weight_field_removed(self, monkeypatch):
        """LOW: das nie konsumierte "weight"-Feld (Kriterium id=8) ist weg —
        die Aggregation zählt alle Kriterien mit 1."""
        from services import stock_scorer

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        batch = _make_batch_frame("H6T")
        monkeypatch.setattr(stock_scorer, "yf_download", lambda *a, **kw: batch)
        fresh = stock_scorer._download_and_analyze("H6T")
        score = _run_score_stock(monkeypatch, stock_scorer, fresh)
        assert all("weight" not in c for c in score["criteria"])

    def test_series_payload_roundtrip_helpers(self):
        from services.stock_scorer import _series_from_payload, _series_to_payload

        idx = pd.date_range("2025-01-01", periods=5, freq="B")
        s = pd.Series([1.5, 2.5, np.nan, 4.5, 5.5], index=idx)
        payload = _series_to_payload(s)
        assert payload is not None
        json.dumps(payload)  # JSON-fähig
        back = _series_from_payload(payload)
        assert isinstance(back, pd.Series)
        assert len(back) == 4  # NaN gedroppt
        assert list(back.values) == [1.5, 2.5, 4.5, 5.5]
        assert back.index[0] == idx[0]

        # Defensive Pfade
        assert _series_to_payload(None) is None
        assert _series_from_payload(None) is None
        assert _series_from_payload("kein dict") is None
        assert _series_from_payload({"index": ["2025-01-01"], "values": []}) is None


# --- M21: Benchmark-Cache ----------------------------------------------------

class TestBenchmarkCache:
    def test_second_ticker_downloads_without_benchmark(self, monkeypatch):
        from services import stock_scorer

        monkeypatch.setattr(cache, "_get_redis", lambda: None)

        calls: list[str] = []

        def fake_download(tickers, **kwargs):
            calls.append(tickers)
            if " " in tickers:
                return _make_batch_frame(tickers.split()[0])
            return _make_price_frame(tickers, seed=21)

        monkeypatch.setattr(stock_scorer, "yf_download", fake_download)

        first = stock_scorer._download_and_analyze("AAA")
        assert calls == ["AAA ^GSPC"]
        assert first["mrs"] is not None
        # Benchmark-Extrakt liegt jetzt im eigenen Key
        assert cache.get(stock_scorer._BENCH_CACHE_KEY) is not None

        second = stock_scorer._download_and_analyze("BBB")
        assert calls == ["AAA ^GSPC", "BBB"]  # nur der Ticker, kein ^GSPC mehr
        assert second["mrs"] is not None      # MRS aus gecachter Benchmark
        assert isinstance(second.get("_close_series"), pd.Series)


# --- M13: Wyckoff-Slope niveau-unabhängig -------------------------------------

class TestWyckoffSlopeNormalization:
    def _volumes(self, base: float, daily_change: float, days: int = 40) -> pd.Series:
        idx = pd.date_range("2025-01-01", periods=days, freq="B")
        values = base * np.exp(daily_change * np.arange(days))
        return pd.Series(values, index=idx)

    def test_slope_is_level_independent(self):
        from services.chart_service import _assess_wyckoff_volume

        idx = pd.date_range("2025-01-01", periods=40, freq="B")
        lows = pd.Series(np.full(40, 101.0), index=idx)  # kein Spring
        kwargs = dict(
            first_touch_date=idx[0],
            last_touch_date=idx[-1],
            support_level=100.0,
            lows=lows,
        )
        # −1.2 %/Tag relativer Volumen-Trend, einmal illiquide, einmal liquide
        small = _assess_wyckoff_volume(self._volumes(10_000.0, -0.012), **kwargs)
        big = _assess_wyckoff_volume(self._volumes(10_000_000.0, -0.012), **kwargs)

        assert small["volume_slope_pct_per_day"] == pytest.approx(-1.2, abs=0.01)
        assert big["volume_slope_pct_per_day"] == pytest.approx(-1.2, abs=0.01)
        # Vor dem Fix: Division durch ln(median) → ~9.2 vs ~16.1 → ungleich
        assert small["volume_slope_pct_per_day"] == big["volume_slope_pct_per_day"]
        assert small["score"] == big["score"] == 1  # shrinking ≤ −0.5 %/d

    def test_rising_volume_still_scores_minus_one(self):
        from services.chart_service import _assess_wyckoff_volume

        idx = pd.date_range("2025-01-01", periods=40, freq="B")
        lows = pd.Series(np.full(40, 101.0), index=idx)
        result = _assess_wyckoff_volume(
            self._volumes(1_000_000.0, +0.012),
            first_touch_date=idx[0],
            last_touch_date=idx[-1],
            support_level=100.0,
            lows=lows,
        )
        assert result["volume_slope_pct_per_day"] == pytest.approx(1.2, abs=0.01)
        assert result["score"] == -1


# --- LOW: Serien-Alignment ----------------------------------------------------

def _breakout_series_with_volume_gap() -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bestätigter Breakout (Tag 1 = vorgestern... genauer: Tag 1 gestern,
    Tag 2 heute), aber die Volumen-Serie hat eine dropna()-Lücke weiter vorne —
    positional wären closes/volumes um einen Tag verschoben."""
    np.random.seed(42)
    closes = list(100 + np.random.normal(0, 0.5, 60))
    highs = [c + 0.3 for c in closes]
    volumes = [1_000_000.0] * 60

    recent_high = max(highs[-20:])
    day1_close = recent_high + 5
    closes.append(day1_close)
    highs.append(day1_close + 0.5)
    volumes.append(2_500_000.0)
    # Tag 2: hält über der Resistance → confirmed
    closes.append(day1_close + 1)
    highs.append(day1_close + 1.3)
    volumes.append(1_100_000.0)

    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    closes_s = pd.Series(closes, index=idx)
    highs_s = pd.Series(highs, index=idx)
    volumes_s = pd.Series(volumes, index=idx).drop(idx[10])  # dropna()-Lücke
    return closes_s, highs_s, volumes_s


class TestSeriesAlignment:
    def test_breakout_confirm_despite_volume_gap(self):
        from services.chart_service import check_breakout_confirmed_today

        c, h, v = _breakout_series_with_volume_gap()
        assert len(v) == len(c) - 1  # Misalignment-Vorbedingung
        result = check_breakout_confirmed_today(c, h, v)
        assert result["passed"] is True
        assert result["reason"] is None

    def test_breakout_events_align_gapped_volume(self, monkeypatch):
        """get_breakout_events darf bei NaN-Lücken im Volumen nicht auf
        verschobene Indizes rechnen — der bestätigte Breakout bleibt erkannt."""
        import services.chart_service as chart_service

        monkeypatch.setattr(cache, "_get_redis", lambda: None)

        c, h, v = _breakout_series_with_volume_gap()
        # Roh-Frame wie von yfinance: Volumen-Lücke als NaN am gemeinsamen Index
        data = pd.DataFrame({"Close": c, "High": h, "Volume": v.reindex(c.index)})
        monkeypatch.setattr(chart_service, "yf_download", lambda *a, **kw: data)

        events = chart_service.get_breakout_events("ALGN", "2y")
        confirmed = [e for e in events if e["status"] == "confirmed"]
        assert len(confirmed) == 1
        assert confirmed[0]["volume_ratio"] >= 1.5

    def test_scorer_donchian_aligned_with_gaps(self, monkeypatch):
        """_download_and_analyze übersteht Serien mit NaN-Lücken an
        unterschiedlichen Tagen und liefert konsistente Donchian-Werte."""
        from services import stock_scorer

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        batch = _make_batch_frame("GAPT", with_gaps=True)
        monkeypatch.setattr(stock_scorer, "yf_download", lambda *a, **kw: batch)

        result = stock_scorer._download_and_analyze("GAPT")
        assert result["donchian"]["channel_high"] is not None
        assert result["donchian"]["channel_low"] is not None
        # Aufwärtstrend-Fixture: das 20-Tage-Hoch liegt sinnvoll nahe am Kurs
        assert result["donchian"]["channel_high"] > 100


# --- LOW: Negative-Caching -----------------------------------------------------

class TestNegativeCaching:
    def test_breakout_events_empty_result_cached(self, monkeypatch):
        import services.chart_service as chart_service

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        calls = {"n": 0}

        def fake_download(*a, **kw):
            calls["n"] += 1
            return pd.DataFrame()

        monkeypatch.setattr(chart_service, "yf_download", fake_download)

        assert chart_service.get_breakout_events("EMPT", "1y") == []
        assert calls["n"] == 1
        # Zweiter Request kommt aus dem 5-min-Negativ-Cache — kein Download
        assert chart_service.get_breakout_events("EMPT", "1y") == []
        assert calls["n"] == 1

    def test_breakout_events_error_path_cached(self, monkeypatch):
        import services.chart_service as chart_service

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        calls = {"n": 0}

        def fake_download(*a, **kw):
            calls["n"] += 1
            raise RuntimeError("yf down")

        monkeypatch.setattr(chart_service, "yf_download", fake_download)

        assert chart_service.get_breakout_events("ERRT", "1y") == []
        assert chart_service.get_breakout_events("ERRT", "1y") == []
        assert calls["n"] == 1

    def test_levels_empty_result_cached(self, monkeypatch):
        import services.chart_service as chart_service

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        calls = {"n": 0}

        def fake_download(*a, **kw):
            calls["n"] += 1
            return pd.DataFrame()

        monkeypatch.setattr(chart_service, "yf_download", fake_download)
        monkeypatch.setattr(chart_service, "_get_close_series", lambda *a, **kw: None)

        first = chart_service.get_support_resistance_levels("EMPT2")
        assert first["current_price"] is None
        assert first["swing_lows"] == []
        assert calls["n"] == 1

        second = chart_service.get_support_resistance_levels("EMPT2")
        assert second == first
        assert calls["n"] == 1
