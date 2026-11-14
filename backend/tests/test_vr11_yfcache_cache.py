"""Vollreview 11/2026, Fixer yfcache: services/cache.py.

- K081: JSON-Werte liegen nur bei einem Redis-Ausfall im Prozess; der Ersatz
  hat ein Byte-Budget, eine Grenze je Eintrag und räumt Abgelaufenes ab.
- K065: Kursreihen haben einen eigenen Speicher mit eigener Obergrenze.
- K082: Timeout oder Verbindungsfehler öffnen einen Circuit-Breaker;
  Invalidierungen aus dieser Zeit werden nachgeholt.
"""
from __future__ import annotations

import json
import types

import pandas as pd
import pytest
import redis

from services import cache


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.calls: list[str] = []
        self.pings = 0

    def ping(self):
        self.pings += 1
        return True

    def get(self, key):
        self.calls.append("get")
        return self.store.get(key)

    def mget(self, keys):
        self.calls.append("mget")
        return [self.store.get(k) for k in keys]

    def set(self, key, value, ex=None, nx=False):
        self.calls.append("set")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, *keys):
        self.calls.append("delete")
        for k in keys:
            self.store.pop(k, None)

    def scan(self, cursor, match=None, count=None):
        return 0, list(self.store)


class FailingRedis(FakeRedis):
    """Jeder Befehl scheitert mit ``error``; PING antwortet, sobald ``healthy``."""

    def __init__(self, error: Exception):
        super().__init__()
        self.error = error
        self.healthy = False

    def _fail(self, name):
        self.calls.append(name)
        if not self.healthy:
            raise self.error

    def ping(self):
        self.pings += 1
        if not self.healthy:
            raise self.error
        return True

    def get(self, key):
        self._fail("get")
        return self.store.get(key)

    def mget(self, keys):
        self._fail("mget")
        return [self.store.get(k) for k in keys]

    def set(self, key, value, ex=None, nx=False):
        self._fail("set")
        self.store[key] = value
        return True

    def delete(self, *keys):
        self._fail("delete")
        for k in keys:
            self.store.pop(k, None)


@pytest.fixture(autouse=True)
def clean_state():
    saved = (cache._redis, cache._redis_available, cache._redis_last_attempt)
    cache._mem_clear()
    cache._pending_deletes.clear()
    cache._local_locks.clear()
    yield
    cache._redis, cache._redis_available, cache._redis_last_attempt = saved
    cache._mem_clear()
    cache._pending_deletes.clear()
    cache._local_locks.clear()


@pytest.fixture
def clock(monkeypatch):
    """Nur die Uhr des cache-Moduls verstellen, nicht die des ganzen Prozesses."""
    now = [1000.0]
    monkeypatch.setattr(cache, "time", types.SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(cache, "_last_sweep", now[0])
    return now


def _connect(fake) -> None:
    """Zustand wie nach einem erfolgreichen Verbindungsaufbau — über das echte
    ``_get_redis``, damit der Circuit-Breaker mitspielt."""
    cache._redis = fake
    cache._redis_available = True
    cache._redis_last_attempt = None


def _assert_accounting_consistent() -> None:
    assert set(cache._mem_sizes) == set(cache._mem_cache)
    assert cache._mem_bytes == sum(cache._mem_sizes.values())


# --- K081: Redis-Ersatz ---------------------------------------------------------


class TestJsonValuesStayOutOfProcessMemory:
    def test_no_local_copy_while_redis_is_up(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)

        for i in range(50):
            cache.set(f"portfolio_history:{i}", {"points": list(range(200))})

        assert len(cache._mem_cache) == 0
        assert cache._mem_bytes == 0
        assert cache.get("portfolio_history:7") == {"points": list(range(200))}

    def test_value_is_kept_locally_when_redis_is_down(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        value = {"a": [1, 2, 3]}
        cache.set("k", value)

        assert cache.get("k") == value
        assert cache._mem_bytes == len(json.dumps(value))
        _assert_accounting_consistent()

    def test_value_is_kept_locally_when_the_write_fails(self, monkeypatch):
        broken = FailingRedis(ConnectionError("redis set boom"))
        monkeypatch.setattr(cache, "_get_redis", lambda: broken)
        cache.set("k", {"a": 1})
        assert "k" in cache._mem_cache

    def test_successful_redis_write_drops_the_stale_local_copy(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        cache.set("k", {"v": "written during outage"})
        assert "k" in cache._mem_cache

        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("k", {"v": "fresh"})

        assert "k" not in cache._mem_cache
        _assert_accounting_consistent()
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        assert cache.get("k") is None  # nicht die alte Kopie


class TestFallbackLimits:
    @pytest.fixture(autouse=True)
    def no_redis(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)

    def test_byte_budget_evicts_least_recently_used(self, monkeypatch):
        monkeypatch.setattr(cache, "_MEM_MAX_BYTES", 1000)
        for i in range(30):
            cache.set(f"k{i}", "x" * 98)  # 100 Bytes als JSON

        assert cache._mem_bytes <= 1000
        assert len(cache._mem_cache) == 10
        assert cache.get("k29") == "x" * 98
        assert cache.get("k0") is None
        _assert_accounting_consistent()

    def test_default_budget_is_far_below_the_container_limit(self):
        assert cache._MEM_MAX_BYTES <= 64 * 1024 * 1024
        assert cache._MEM_MAX_ENTRY_BYTES < cache._MEM_MAX_BYTES

    def test_oversized_entry_is_not_kept(self, monkeypatch):
        monkeypatch.setattr(cache, "_MEM_MAX_ENTRY_BYTES", 50)
        cache.set("small", "ok")
        cache.set("big", "previous")
        cache.set("big", "x" * 100)

        assert cache.get("big") is None  # auch nicht der alte Wert
        assert cache.get("small") == "ok"
        _assert_accounting_consistent()

    def test_overwrite_and_delete_keep_the_byte_count(self):
        cache.set("k", "x" * 100)
        cache.set("k", "y")
        assert cache._mem_bytes == len(json.dumps("y"))
        cache.delete("k")
        assert cache._mem_bytes == 0
        _assert_accounting_consistent()

    def test_entry_count_limit_still_holds(self, monkeypatch):
        monkeypatch.setattr(cache, "_MAX_SIZE", 5)
        for i in range(12):
            cache.set(f"k{i}", i)
        assert len(cache._mem_cache) == 5
        assert cache.get("k11") == 11
        _assert_accounting_consistent()

    def test_expired_entries_are_swept_before_the_store_is_full(self, clock):
        """Vorher verschwanden abgelaufene Einträge erst bei 2500 Einträgen."""
        cache.set("history:2026-11-12", {"big": "x" * 500}, ttl=10)
        cache.set("series", pd.Series([1.0, 2.0]), ttl=10)
        cache.set("long", "stays", ttl=10_000)

        clock[0] += cache._SWEEP_INTERVAL + 1
        cache.set("trigger", 1)  # irgendein Schreibzugriff

        assert "history:2026-11-12" not in cache._mem_cache
        assert "series" not in cache._obj_cache
        assert cache.get("long") == "stays"
        _assert_accounting_consistent()

    def test_no_sweep_within_the_interval(self, clock):
        cache.set("short", "x", ttl=1)
        clock[0] += 5
        cache.set("trigger", 1)
        assert "short" in cache._mem_cache  # erst der nächste Lauf räumt ab
        assert cache.get("short") is None  # gelesen wird er trotzdem nicht mehr


# --- K065: eigener Speicher für Kursreihen ---------------------------------------


class TestObjectStore:
    def test_json_keys_do_not_evict_series(self, monkeypatch):
        """Vorher teilten sich Reihen und JSON-Kopien 2500 Plätze: ab rund 500
        Tickern flogen Reihen raus und kosteten einen Yahoo-Download."""
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        monkeypatch.setattr(cache, "_MAX_SIZE", 10)
        cache.set("close:AAPL:2y", pd.Series([1.0, 2.0, 3.0]))

        for i in range(100):
            cache.set(f"price:T{i}", {"price": i})

        got = cache.get("close:AAPL:2y")
        assert isinstance(got, pd.Series) and list(got.values) == [1.0, 2.0, 3.0]

    def test_series_do_not_evict_json_fallback_entries(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        monkeypatch.setattr(cache, "_OBJ_MAX_SIZE", 3)
        cache.set("fx_rates", {"USD": 0.88})
        for i in range(10):
            cache.set(f"close:T{i}:2y", pd.Series([float(i)]))

        assert cache.get("fx_rates") == {"USD": 0.88}
        assert len(cache._obj_cache) == 3
        assert cache.get("close:T9:2y") is not None
        assert cache.get("close:T0:2y") is None

    def test_object_store_is_larger_than_before(self):
        # 2 Reihen je Ticker (1y, 2y): die alte gemeinsame Grenze von 2500
        # reichte mit den JSON-Kopien nur für rund 500 Ticker.
        assert cache._OBJ_MAX_SIZE >= 4000

    def test_series_live_in_memory_even_with_redis(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("close:AAPL:2y", pd.Series([1.0]))
        assert fake.store == {}
        assert list(cache.get("close:AAPL:2y").values) == [1.0]
        assert list(cache.get_many(["close:AAPL:2y"])["close:AAPL:2y"].values) == [1.0]

    def test_a_key_lives_in_one_store_only(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        cache.set("close:X:2y", pd.Series([1.0]))
        cache.set("close:X:2y", "__no_data__")
        assert cache.get("close:X:2y") == "__no_data__"
        assert "close:X:2y" not in cache._obj_cache

        cache.set("close:X:2y", pd.Series([2.0]))
        assert list(cache.get("close:X:2y").values) == [2.0]
        assert "close:X:2y" not in cache._mem_cache
        _assert_accounting_consistent()

    def test_json_value_in_redis_replaces_an_older_series(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("k", pd.Series([1.0]))
        cache.set("k", [])
        fake.store.clear()  # TTL des JSON-Werts abgelaufen
        assert cache.get("k") is None  # nicht die alte Reihe

    def test_delete_and_clear_cover_both_stores(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        cache.set("a", pd.Series([1.0]))
        cache.set("b", {"v": 1})
        cache.delete("a")
        assert cache.get("a") is None
        cache.set("c", pd.Series([1.0]))
        cache.clear()
        assert cache.get("b") is None and cache.get("c") is None
        assert cache._mem_bytes == 0


# --- K082: Circuit-Breaker -------------------------------------------------------


_DOWN_ERRORS = [
    redis.exceptions.TimeoutError("Timeout reading from socket"),
    redis.exceptions.ConnectionError("Connection refused"),
    TimeoutError("timed out"),
    ConnectionResetError("reset by peer"),
]


class TestCircuitBreaker:
    @pytest.mark.parametrize("error", _DOWN_ERRORS, ids=lambda e: type(e).__module__ + "." + type(e).__name__)
    def test_first_failure_stops_further_redis_calls(self, clock, error):
        """Vorher wartete JEDER Aufruf bis zum Timeout — 50 Positionen, 50-mal."""
        hanging = FailingRedis(error)
        _connect(hanging)

        for i in range(50):
            assert cache.get(f"price:T{i}") is None

        assert hanging.calls == ["get"]
        assert cache._redis_available is False

    @pytest.mark.parametrize(
        "operation",
        [
            lambda: cache.get("k"),
            lambda: cache.set("k", 1),
            lambda: cache.delete("k"),
            lambda: cache.get_many(["k", "j"]),
            lambda: cache.acquire_lock("job", ttl=5),
            lambda: cache.release_lock("job"),
        ],
        ids=["get", "set", "delete", "get_many", "acquire_lock", "release_lock"],
    )
    def test_every_operation_opens_the_breaker(self, clock, operation):
        hanging = FailingRedis(redis.exceptions.TimeoutError("timeout"))
        _connect(hanging)

        operation()  # darf nicht werfen
        assert len(hanging.calls) == 1
        assert cache._get_redis() is None

    def test_values_written_during_the_outage_are_served_locally(self, clock):
        hanging = FailingRedis(redis.exceptions.TimeoutError("timeout"))
        _connect(hanging)

        cache.set("k", {"v": 1})  # scheitert, öffnet den Breaker
        cache.set("j", {"v": 2})
        assert cache.get("k") == {"v": 1}
        assert cache.get("j") == {"v": 2}
        assert cache.get_many(["k", "j"]) == {"k": {"v": 1}, "j": {"v": 2}}
        assert hanging.calls == ["set"]

    def test_breaker_closes_after_the_retry_interval(self, clock):
        hanging = FailingRedis(redis.exceptions.TimeoutError("timeout"))
        _connect(hanging)
        cache.get("k")

        clock[0] += cache._REDIS_RETRY_INTERVAL - 1
        assert cache._get_redis() is None
        assert hanging.pings == 0  # innerhalb des Intervalls kein Versuch

        hanging.healthy = True
        hanging.store[f"{cache._KEY_PREFIX}k"] = json.dumps("from redis")
        clock[0] += 2
        assert cache.get("k") == "from redis"
        assert hanging.pings == 1
        assert cache._redis_available is True

    def test_still_hanging_redis_costs_one_probe_per_interval(self, clock):
        hanging = FailingRedis(redis.exceptions.TimeoutError("timeout"))
        _connect(hanging)
        cache.get("k")

        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        for _ in range(20):
            assert cache.get("k") is None
        assert hanging.pings == 1
        assert hanging.calls == ["get"]

    def test_an_answering_redis_stays_in_use(self, clock):
        """OOM oder READONLY kommen von einem Redis, das antwortet."""
        full = FailingRedis(redis.exceptions.ResponseError("OOM command not allowed"))
        _connect(full)

        cache.set("k", 1)
        cache.get("k")
        assert full.calls == ["set", "get"]
        assert cache._redis_available is True

    def test_corrupt_json_does_not_open_the_breaker(self, clock):
        fake = FakeRedis()
        fake.store[f"{cache._KEY_PREFIX}k"] = "{not json"
        _connect(fake)
        assert cache.get("k") is None
        assert cache._redis_available is True


class TestDeletesDuringOutage:
    def test_invalidation_is_replayed_on_reconnect(self, clock):
        """Ohne Nachholen überlebt der alte Wert den Ausfall in Redis und gilt
        danach wieder als frisch."""
        flaky = FailingRedis(redis.exceptions.TimeoutError("timeout"))
        flaky.store[f"{cache._KEY_PREFIX}portfolio_summary:u1"] = json.dumps({"total": "old"})
        flaky.store[f"{cache._KEY_PREFIX}other"] = json.dumps("keep")
        _connect(flaky)

        cache.get("anything")  # öffnet den Breaker
        cache.delete("portfolio_summary:u1")  # Schreibzugriff eines Nutzers
        assert f"{cache._KEY_PREFIX}portfolio_summary:u1" in flaky.store

        flaky.healthy = True
        clock[0] += cache._REDIS_RETRY_INTERVAL + 1

        assert cache.get("portfolio_summary:u1") is None
        assert f"{cache._KEY_PREFIX}portfolio_summary:u1" not in flaky.store
        assert cache.get("other") == "keep"
        assert cache._pending_deletes == set()

    def test_failed_delete_itself_is_remembered(self, clock):
        flaky = FailingRedis(redis.exceptions.TimeoutError("timeout"))
        flaky.store[f"{cache._KEY_PREFIX}k"] = json.dumps("old")
        _connect(flaky)

        cache.delete("k")  # dieser Aufruf läuft in den Timeout
        assert cache._pending_deletes == {"k"}

        flaky.healthy = True
        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        assert cache.get("k") is None

    def test_replay_failure_keeps_the_keys(self, clock):
        flaky = FailingRedis(redis.exceptions.TimeoutError("timeout"))
        _connect(flaky)
        cache.delete("k")

        # PING antwortet, DELETE hängt wieder
        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        flaky.ping = lambda: True
        assert cache._get_redis() is None
        assert cache._pending_deletes == {"k"}
        assert cache._redis_available is False

    def test_rejected_replay_is_not_retried_forever(self, clock):
        readonly = FailingRedis(redis.exceptions.ResponseError("READONLY"))
        _connect(readonly)
        cache._pending_deletes.add("k")

        assert cache._get_redis() is readonly
        assert cache._get_redis() is readonly
        assert readonly.calls == ["delete"]
        assert cache._pending_deletes == set()

    def test_remembered_deletes_are_bounded(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        monkeypatch.setattr(cache, "_PENDING_DELETES_MAX", 5)
        for i in range(50):
            cache.delete(f"k{i}")
        assert len(cache._pending_deletes) == 5

    def test_delete_with_reachable_redis_leaves_nothing_pending(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("k", 1)
        cache.delete("k")
        assert fake.store == {}
        assert cache._pending_deletes == set()
