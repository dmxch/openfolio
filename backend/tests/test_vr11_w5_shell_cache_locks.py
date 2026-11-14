"""Vollreview 11/2026, Welle 5, Fixer shell: services/cache.py.

R-yfanalysis-2: ``release_lock`` erreichte Redis bei offenem Circuit-Breaker
nicht. Der Schlüssel blieb bis zu seiner TTL stehen und sperrte jeden weiteren
Lauf. Die Freigabe wird jetzt gemerkt und beim Reconnect nachgeholt.
"""
from __future__ import annotations

import types

import pytest
import redis

from services import cache

SCAN = "screening-scan"
SCAN_KEY = f"{cache._LOCK_PREFIX}{SCAN}"
SCAN_TTL = 2100


class FlakyRedis:
    """Redis-Attrappe. ``error`` gesetzt: jeder Befehl scheitert damit, die Daten
    bleiben erhalten — Redis lebt weiter, nur dieser Prozess erreicht es nicht."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.calls: list[str] = []
        self.error: Exception | None = None

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.error is not None:
            raise self.error

    def ping(self):
        if self.error is not None:
            raise self.error
        return True

    def get(self, key):
        self._call("get")
        return self.store.get(key)

    def set(self, key, value, ex=None, nx=False):
        self._call("set")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, *keys):
        self._call("delete")
        for k in keys:
            self.store.pop(k, None)


def _timeout() -> Exception:
    return redis.exceptions.TimeoutError("Timeout reading from socket")


def _clear() -> None:
    cache._mem_clear()
    cache._pending_deletes.clear()
    cache._pending_lock_releases.clear()
    cache._local_locks.clear()
    cache._redis_locks.clear()


@pytest.fixture(autouse=True)
def clean_state():
    saved = (cache._redis, cache._redis_available, cache._redis_last_attempt)
    _clear()
    yield
    cache._redis, cache._redis_available, cache._redis_last_attempt = saved
    _clear()


@pytest.fixture
def clock(monkeypatch):
    """Nur die Uhr des cache-Moduls verstellen, nicht die des ganzen Prozesses."""
    now = [1000.0]
    monkeypatch.setattr(cache, "time", types.SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(cache, "_last_sweep", now[0])
    return now


@pytest.fixture
def fake():
    """Verbunden über das echte ``_get_redis``, damit der Circuit-Breaker mitspielt."""
    fake = FlakyRedis()
    cache._redis = fake
    cache._redis_available = True
    cache._redis_last_attempt = None
    return fake


def _one_timeout(fake: FlakyRedis) -> None:
    """Ein einzelner Redis-Aufruf läuft in den Timeout und öffnet den Breaker."""
    fake.error = _timeout()
    assert cache.get("price:AAPL") is None
    fake.error = None
    assert cache._redis_available is False


class TestReleaseDuringOutage:
    def test_release_behind_open_breaker_is_replayed_on_reconnect(self, clock, fake):
        """Szenario des Fundes: Scan hält das Lock, ein Timeout öffnet den Breaker,
        fünf Sekunden später endet der Scan. Der Schlüssel blieb 35 Minuten stehen."""
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True
        _one_timeout(fake)

        clock[0] += 5
        cache.release_lock(SCAN)
        assert SCAN_KEY in fake.store  # Redis war für die Freigabe nicht erreichbar

        clock[0] += 40  # nach dem Reconnect-Intervall
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True
        assert cache._pending_lock_releases == {}

    def test_reconnect_by_any_cache_call_frees_the_lock_for_other_processes(self, clock, fake):
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True
        _one_timeout(fake)
        cache.release_lock(SCAN)

        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        cache.get("price:AAPL")

        assert SCAN_KEY not in fake.store

    def test_release_that_hits_the_timeout_itself_is_replayed(self, clock, fake):
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True

        fake.error = _timeout()
        cache.release_lock(SCAN)  # darf nicht werfen
        fake.error = None
        assert SCAN_KEY in fake.store
        assert set(cache._pending_lock_releases) == {SCAN}

        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True

    def test_release_is_remembered_once_per_key(self, clock, fake):
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True
        _one_timeout(fake)

        cache.release_lock(SCAN)
        cache.release_lock(SCAN)  # zweite Freigabe ohne Lock

        assert cache._pending_lock_releases == {SCAN: 1000.0 + SCAN_TTL}

    def test_replay_failure_keeps_the_release(self, clock, fake):
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True
        _one_timeout(fake)
        cache.release_lock(SCAN)

        # PING antwortet, DELETE hängt wieder.
        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        fake.error = _timeout()
        fake.ping = lambda: True
        assert cache._get_redis() is None
        assert set(cache._pending_lock_releases) == {SCAN}

        fake.error = None
        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        assert cache._get_redis() is fake
        assert SCAN_KEY not in fake.store
        assert cache._pending_lock_releases == {}

    def test_rejected_release_is_not_retried_forever(self, clock, fake):
        """READONLY oder OOM kommen von einem Redis, das antwortet."""
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True
        fake.error = redis.exceptions.ResponseError("READONLY")
        fake.calls.clear()

        cache.release_lock(SCAN)
        assert cache._get_redis() is fake
        assert cache._get_redis() is fake

        assert fake.calls == ["delete", "delete"]  # Freigabe und ein Nachholversuch
        assert cache._pending_lock_releases == {}
        assert cache._redis_available is True


class TestReplayNeverTakesAForeignLock:
    def test_expired_lock_is_not_released_late(self, clock, fake):
        """Nach der TTL hat Redis den Schlüssel entfernt. Ein neuer Halter kann
        ihn belegt haben — das Nachholen darf dessen Lock nicht löschen."""
        assert cache.acquire_lock("job", ttl=60) is True
        _one_timeout(fake)
        cache.release_lock("job")

        fake.store[f"{cache._LOCK_PREFIX}job"] = "1"  # neuer Halter nach Ablauf der TTL
        clock[0] += 61
        assert cache._get_redis() is fake

        assert f"{cache._LOCK_PREFIX}job" in fake.store
        assert "delete" not in fake.calls
        assert cache._pending_lock_releases == {}

    def test_already_expired_lock_is_not_remembered(self, clock, fake):
        assert cache.acquire_lock("job", ttl=10) is True
        _one_timeout(fake)

        clock[0] += 11
        cache.release_lock("job")

        assert cache._pending_lock_releases == {}

    def test_process_local_lock_is_not_replayed(self, clock, fake):
        """Ein Lock aus dem lokalen Ersatz stand nie in Redis. Der Schlüssel dort
        gehört einem anderen Prozess."""
        _one_timeout(fake)
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True  # nur lokal
        assert SCAN_KEY not in fake.store
        fake.store[SCAN_KEY] = "1"  # ein anderer Prozess nimmt das Lock in Redis

        cache.release_lock(SCAN)
        assert cache._pending_lock_releases == {}

        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        assert cache._get_redis() is fake
        assert SCAN_KEY in fake.store

    def test_local_reacquire_forgets_that_the_lock_was_in_redis(self, clock, fake):
        assert cache.acquire_lock("job", ttl=5) is True
        _one_timeout(fake)

        clock[0] += 6  # Lock abgelaufen, Breaker noch offen
        assert cache.acquire_lock("job", ttl=600) is True  # nur lokal
        cache.release_lock("job")

        assert cache._pending_lock_releases == {}

    def test_new_redis_lock_drops_a_pending_release_for_the_same_key(self, clock, fake, monkeypatch):
        cache._pending_lock_releases["job"] = clock[0] + 600
        # Am Nachholen vorbei: der Zustand entsteht, wenn ein Nachholversuch
        # scheitert, sein DELETE Redis aber erreicht hat.
        monkeypatch.setattr(cache, "_get_redis", lambda: fake)

        assert cache.acquire_lock("job", ttl=600) is True

        assert cache._pending_lock_releases == {}


class TestBookkeeping:
    def test_release_with_reachable_redis_leaves_nothing_behind(self, fake):
        assert cache.acquire_lock("job", ttl=30) is True
        assert cache._redis_locks == {"job"}

        cache.release_lock("job")

        assert fake.store == {}
        assert cache._redis_locks == set()
        assert cache._pending_lock_releases == {}

    def test_remembered_releases_are_bounded(self, clock, fake, monkeypatch):
        monkeypatch.setattr(cache, "_PENDING_DELETES_MAX", 3)
        for i in range(10):
            assert cache.acquire_lock(f"job{i}", ttl=600) is True
        _one_timeout(fake)

        for i in range(10):
            cache.release_lock(f"job{i}")

        assert len(cache._pending_lock_releases) == 3

    def test_pruning_expired_local_locks_also_prunes_the_redis_marker(self, clock, fake, monkeypatch):
        monkeypatch.setattr(cache, "_LOCAL_LOCKS_PRUNE_SIZE", 3)
        for i in range(3):
            assert cache.acquire_lock(f"old{i}", ttl=1) is True
        fake.store.clear()  # in Redis sind sie abgelaufen

        clock[0] += 5
        assert cache.acquire_lock("new", ttl=1) is True

        assert set(cache._local_locks) == {"new"}
        assert cache._redis_locks == {"new"}

    def test_cache_deletes_are_still_replayed_together_with_lock_releases(self, clock, fake):
        fake.store[f"{cache._KEY_PREFIX}portfolio_summary:u1"] = '"old"'
        assert cache.acquire_lock(SCAN, ttl=SCAN_TTL) is True
        _one_timeout(fake)
        cache.delete("portfolio_summary:u1")
        cache.release_lock(SCAN)

        clock[0] += cache._REDIS_RETRY_INTERVAL + 1
        assert cache.get("portfolio_summary:u1") is None

        assert fake.store == {}
        assert cache._pending_deletes == set()
        assert cache._pending_lock_releases == {}
