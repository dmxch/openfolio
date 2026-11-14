"""Vollreview 11/2026, Fundament: get_many und Locks in services/cache.py."""

import json
import types

import pandas as pd
import pytest

from services import cache


class FakeRedis:
    """Minimaler Redis-Ersatz: get/set (nx, ex), mget, delete."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.expiry: dict[str, int] = {}
        self.mget_calls = 0
        self.get_calls = 0

    def get(self, key):
        self.get_calls += 1
        return self.store.get(key)

    def mget(self, keys):
        self.mget_calls += 1
        return [self.store.get(k) for k in keys]

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)

    def scan(self, cursor, match=None, count=None):
        prefix = (match or "*").rstrip("*")
        return 0, [k for k in self.store if k.startswith(prefix)]


class BrokenRedis(FakeRedis):
    def mget(self, keys):
        raise ConnectionError("redis mget boom")

    def set(self, key, value, ex=None, nx=False):
        raise ConnectionError("redis set boom")

    def delete(self, *keys):
        raise ConnectionError("redis delete boom")


@pytest.fixture(autouse=True)
def clean_state():
    cache._mem_clear()
    cache._local_locks.clear()
    yield
    cache._mem_clear()
    cache._local_locks.clear()


class TestGetMany:
    def test_one_roundtrip_and_missing_keys_are_absent(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("a", {"v": 1})
        cache.set("b", [1, 2])

        assert cache.get_many(["a", "b", "missing"]) == {"a": {"v": 1}, "b": [1, 2]}
        assert fake.mget_calls == 1
        assert fake.get_calls == 0

    def test_uses_the_cache_key_prefix(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        fake.store[f"{cache._KEY_PREFIX}x"] = json.dumps({"from": "other worker"})
        assert cache.get_many(["x"]) == {"x": {"from": "other worker"}}

    def test_empty_list_needs_no_redis(self, monkeypatch):
        def fail():
            raise AssertionError("no redis call expected")

        monkeypatch.setattr(cache, "_get_redis", fail)
        assert cache.get_many([]) == {}

    def test_matches_get_for_every_key(self, monkeypatch):
        """Gleiche Regeln wie get(): Redis zuerst, stale Memory-Kopien zählen
        nicht, nicht JSON-fähige Werte kommen aus dem Speicher."""
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("fresh", {"v": "old"})
        fake.store[f"{cache._KEY_PREFIX}fresh"] = json.dumps({"v": "new"})
        cache.set("invalidated", {"v": 1})
        del fake.store[f"{cache._KEY_PREFIX}invalidated"]
        cache.set("series", pd.Series([1.0, 2.0]))
        cache.set("none", None)

        keys = ["fresh", "invalidated", "series", "none", "missing"]
        many = cache.get_many(keys)

        assert many["fresh"] == {"v": "new"}
        assert list(many["series"].values) == [1.0, 2.0]
        assert set(many) == {"fresh", "series"}
        for key in keys:
            single = cache.get(key)
            assert (key in many) == (single is not None)

    def test_memory_fallback_without_redis(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        cache.set("a", {"v": 1})
        assert cache.get_many(["a", "b"]) == {"a": {"v": 1}}

    def test_redis_error_never_leaks(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        cache.set("a", {"v": 1})
        monkeypatch.setattr(cache, "_get_redis", lambda: BrokenRedis())
        assert cache.get_many(["a", "b"]) == {"a": {"v": 1}}


class TestLocks:
    def test_redis_lock_is_exclusive_until_released(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)

        assert cache.acquire_lock("job", ttl=30) is True
        assert cache.acquire_lock("job", ttl=30) is False
        assert cache.acquire_lock("other", ttl=30) is True

        cache.release_lock("job")
        assert cache.acquire_lock("job", ttl=30) is True

    def test_redis_lock_uses_set_nx_ex(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.acquire_lock("job", ttl=45)
        assert fake.expiry == {"openfolio-lock:job": 45}

    def test_lock_of_another_process_is_respected(self, monkeypatch):
        fake = FakeRedis()
        fake.store["openfolio-lock:job"] = "1"  # hält ein anderer Prozess
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        assert cache.acquire_lock("job", ttl=30) is False

    def test_cache_clear_keeps_locks(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.set("value", 1)
        cache.acquire_lock("job", ttl=30)

        cache.clear()

        assert cache.get("value") is None
        assert cache.acquire_lock("job", ttl=30) is False

    def test_local_fallback_without_redis(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        assert cache.acquire_lock("job", ttl=30) is True
        assert cache.acquire_lock("job", ttl=30) is False
        cache.release_lock("job")
        assert cache.acquire_lock("job", ttl=30) is True

    def test_local_fallback_expires(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        now = [1000.0]
        # Nur die Uhr des cache-Moduls verstellen, nicht die des ganzen Prozesses.
        monkeypatch.setattr(cache, "time", types.SimpleNamespace(monotonic=lambda: now[0]))

        assert cache.acquire_lock("job", ttl=10) is True
        now[0] += 9.9
        assert cache.acquire_lock("job", ttl=10) is False
        now[0] += 0.2
        assert cache.acquire_lock("job", ttl=10) is True

    def test_redis_error_degrades_to_local_lock(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: BrokenRedis())
        assert cache.acquire_lock("job", ttl=30) is True
        assert cache.acquire_lock("job", ttl=30) is False
        cache.release_lock("job")  # darf nicht werfen
        assert cache.acquire_lock("job", ttl=30) is True

    def test_lock_taken_in_redis_survives_redis_outage(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        assert cache.acquire_lock("job", ttl=30) is True

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        assert cache.acquire_lock("job", ttl=30) is False

    def test_ttl_below_one_second_counts_as_one(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)
        cache.acquire_lock("job", ttl=0)
        assert fake.expiry == {"openfolio-lock:job": 1}

    def test_expired_local_entries_are_pruned(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        monkeypatch.setattr(cache, "_LOCAL_LOCKS_PRUNE_SIZE", 5)
        now = [1000.0]
        # Nur die Uhr des cache-Moduls verstellen, nicht die des ganzen Prozesses.
        monkeypatch.setattr(cache, "time", types.SimpleNamespace(monotonic=lambda: now[0]))

        for i in range(5):
            cache.acquire_lock(f"old{i}", ttl=1)
        now[0] += 5
        cache.acquire_lock("new", ttl=1)
        assert set(cache._local_locks) == {"new"}
