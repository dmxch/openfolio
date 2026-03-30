import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

import redis

from config import settings

logger = logging.getLogger(__name__)

DEFAULT_TTL = 900  # 15 minutes
_KEY_PREFIX = "openfolio:"

# --- Redis connection ---

_redis: redis.Redis | None = None
_redis_available = False


def _get_redis() -> redis.Redis | None:
    global _redis, _redis_available
    if _redis is not None:
        return _redis if _redis_available else None
    try:
        _redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1,
            retry_on_timeout=True,
        )
        _redis.ping()
        _redis_available = True
        logger.info("Redis cache connected")
        return _redis
    except Exception as e:
        logger.warning(f"Redis unavailable, using in-memory fallback: {e}")
        _redis_available = False
        return None


# --- In-memory fallback (used when Redis is down) ---

_MAX_SIZE = 2500
_mem_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
_lock = threading.Lock()


def _mem_evict_expired():
    now = time.monotonic()
    expired = [k for k, (_, exp) in _mem_cache.items() if now > exp]
    for k in expired:
        del _mem_cache[k]


def _mem_get(key: str) -> Any | None:
    with _lock:
        entry = _mem_cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del _mem_cache[key]
            return None
        # Move to end for LRU (most recently used)
        _mem_cache.move_to_end(key)
        return value


def _mem_set(key: str, value: Any, ttl: int):
    with _lock:
        if key in _mem_cache:
            # Update existing: move to end
            _mem_cache.move_to_end(key)
        else:
            if len(_mem_cache) >= _MAX_SIZE:
                _mem_evict_expired()
                # Evict LRU (first item) if still at capacity
                while len(_mem_cache) >= _MAX_SIZE:
                    _mem_cache.popitem(last=False)
        _mem_cache[key] = (value, time.monotonic() + ttl)


def _mem_delete(key: str):
    with _lock:
        _mem_cache.pop(key, None)


def _mem_clear():
    with _lock:
        _mem_cache.clear()


# --- Public API (same interface as before) ---
#
# Strategy: JSON-serializable values (dicts, lists, numbers, strings) go to Redis
# for cross-worker sharing. Non-serializable values (pandas Series, DataFrames)
# stay in per-worker memory only.


def _is_json_serializable(value: Any) -> bool:
    """Check if a value can be safely round-tripped through JSON."""
    return isinstance(value, (dict, list, tuple, str, int, float, bool, type(None)))


def get(key: str) -> Any | None:
    # Check in-memory first (has pandas Series and other non-serializable data)
    mem = _mem_get(key)
    if mem is not None:
        return mem
    # Then check Redis
    r = _get_redis()
    if r:
        try:
            raw = r.get(f"{_KEY_PREFIX}{key}")
            if raw is not None:
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"Redis GET failed for key {key}: {e}")
    return None


def set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    if _is_json_serializable(value):
        # JSON-safe: store in Redis (shared) + local memory
        r = _get_redis()
        if r:
            try:
                r.set(f"{_KEY_PREFIX}{key}", json.dumps(value, default=str), ex=ttl)
            except Exception as e:
                logger.debug(f"Redis SET failed for key {key}: {e}")
        _mem_set(key, value, ttl)
    else:
        # Non-serializable (pandas Series etc.): local memory only
        _mem_set(key, value, ttl)


def delete(key: str) -> None:
    _mem_delete(key)
    r = _get_redis()
    if r:
        try:
            r.delete(f"{_KEY_PREFIX}{key}")
        except Exception as e:
            logger.debug(f"Redis DELETE failed for key {key}: {e}")


def clear() -> None:
    r = _get_redis()
    if r:
        try:
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor, match=f"{_KEY_PREFIX}*", count=100)
                if keys:
                    r.delete(*keys)
                if cursor == 0:
                    break
            return
        except Exception as e:
            logger.debug(f"Redis CLEAR failed, falling back to memory clear: {e}")
    _mem_clear()


# --- Stampede prevention (per-key async locks, always in-memory) ---

_key_locks: dict[str, asyncio.Lock] = {}
_key_locks_lock = threading.Lock()


def get_key_lock(key: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for a cache key (stampede prevention)."""
    with _key_locks_lock:
        if key not in _key_locks:
            _key_locks[key] = asyncio.Lock()
        return _key_locks[key]


async def get_or_compute(key: str, compute_fn: Any, ttl: int = DEFAULT_TTL) -> Any:
    """Get from cache or compute with per-key lock to prevent stampedes."""
    cached = get(key)
    if cached is not None:
        return cached

    lock = get_key_lock(key)
    async with lock:
        cached = get(key)
        if cached is not None:
            return cached

        value = await compute_fn()
        set(key, value, ttl)
        return value
