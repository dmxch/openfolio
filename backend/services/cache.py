"""Shared cache layer: Redis (cross-process source of truth) + in-memory fallback.

Design-Notizen (Review 2026-07-02, M5/M6/M30):

- Der Redis-Client ist BEWUSST synchron (``redis``, nicht ``redis.asyncio``):
  die Cache-API wird sowohl aus sync Worker-/Service-Code als auch aus async
  Handlern (dort teils via ``asyncio.to_thread``) aufgerufen. Mitigation statt
  Async-Umbau: kurze Socket-Timeouts (connect/ops ~1s), und JEDER Redis-Fehler
  wird geschluckt und auf den In-Memory-Layer degradiert — Cache-Fehler dürfen
  nie zum Aufrufer leaken (M30).
- Reads sind REDIS-FIRST (M5): mit 2 uvicorn-Workern in Prod machte ein
  Memory-first-Read die Cross-Worker-Invalidation wirkungslos (bis zu
  TTL-alte Zahlen nach Writes). Der Memory-Layer zählt beim Read nur noch,
  wenn Redis down ist — plus für Werte, die nie in Redis liegen können
  (pandas Series & Co., siehe ``set()``).
- Ein fehlgeschlagener Verbindungsaufbau wird periodisch erneut versucht
  (alle ``_REDIS_RETRY_INTERVAL`` Sekunden, M6), statt den Prozess für seine
  gesamte Lebensdauer auf den In-Memory-Fallback festzunageln.
"""

import asyncio
import contextlib
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
_redis_last_attempt: float | None = None
_REDIS_RETRY_INTERVAL = 30.0  # seconds between reconnect attempts after failure


def _get_redis() -> redis.Redis | None:
    global _redis, _redis_available, _redis_last_attempt
    if _redis is not None and _redis_available:
        return _redis
    # Reconnect-Throttle (M6): Nach einem Fehlversuch frühestens nach
    # _REDIS_RETRY_INTERVAL erneut probieren. Vorher galt ein einziger
    # Fehlstart (z.B. Worker vor Redis hochgefahren) für die gesamte
    # Prozess-Lebensdauer → permanenter In-Memory-Fallback, silent stale
    # bis Container-Restart.
    now = time.monotonic()
    if _redis_last_attempt is not None and (now - _redis_last_attempt) < _REDIS_RETRY_INTERVAL:
        return None
    _redis_last_attempt = now
    try:
        if _redis is None:
            _redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,  # M30: kurz — Client ist sync, darf nie lange blockieren
                socket_timeout=1,
                # NICHT entfernen, auch wenn Linter es als deprecated markieren: ueber
                # den from_url-Pfad (nicht Redis.__init__) ist das die einzige Quelle
                # des Connection-Retries. Ohne das Flag faellt Retry(NoBackoff(), 1)
                # still auf Retry(NoBackoff(), 0).
                retry_on_timeout=True,
                # redis-py 8 macht RESP3 zum Wire-Default. Response-Shapes blieben zwar
                # gleich (legacy_responses), aber RESP3 aktiviert die Maintenance-
                # Notifications-Probe: der Pool schickt dann bei JEDEM Connect ein
                # `CLIENT MAINT_NOTIFICATIONS ON ...`, das unser redis:7-alpine nicht
                # kennt. Im Auto-Modus wird der ResponseError geschluckt und nur auf
                # debug geloggt — es bricht also nichts, kostet aber pro Verbindung
                # einen sinnlosen Roundtrip. protocol=2 haelt den Handshake bitgleich
                # zu vorher; erst mit einem Redis >= 8 lohnt sich RESP3.
                protocol=2,
                # Der Pool-Default sank in redis-py 8 von 2**31 auf 100. Explizit
                # setzen, damit die neue Obergrenze nicht unbemerkt greift: ein
                # ConnectionError daraus wuerde unten stillschweigend als
                # "Redis weg" verbucht und auf den In-Memory-Fallback degradieren.
                max_connections=64,
            )
        _redis.ping()
        _redis_available = True
        logger.info("Redis cache connected")
        return _redis
    except Exception as e:
        _redis_available = False
        logger.warning(
            f"Redis unavailable, using in-memory fallback (retry in {int(_REDIS_RETRY_INTERVAL)}s): {e}"
        )
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
    # Redis-first (M5): Redis ist die Autorität für JSON-Werte — ein
    # Memory-first-Read würde Cross-Worker-Invalidation aushebeln (die
    # prozesslokale Kopie im anderen uvicorn-Worker überlebte bis TTL).
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(f"{_KEY_PREFIX}{key}")
            if raw is not None:
                return json.loads(raw)
            # Redis-Miss: Key wurde invalidiert oder ist abgelaufen. Der
            # Memory-Layer zählt hier nur noch für Werte, die nie in Redis
            # liegen können (pandas Series etc., siehe set()) — ein
            # JSON-fähiger Memory-Eintrag ohne Redis-Pendant ist stale.
            mem = _mem_get(key)
            if mem is not None and not _is_json_serializable(mem):
                return mem
            return None
        except Exception as e:
            logger.debug(f"Redis GET failed for key {key}: {e}")
    # Redis down oder Fehler → In-Memory-Fallback
    return _mem_get(key)


def set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    if _is_json_serializable(value):
        # JSON-safe: store in Redis (shared) + local memory (Redis-down fallback)
        r = _get_redis()
        if r:
            try:
                r.set(f"{_KEY_PREFIX}{key}", json.dumps(value, default=str), ex=ttl)
            except Exception as e:
                # WARNING statt debug: get() liest Redis-first — schlagen
                # Writes fehl (OOM/noeviction, readonly-Replica), ist der
                # Wert effektiv uncachebar und jeder Read ein Miss. Ohne
                # sichtbares Log ist dieser Degradations-Modus kaum
                # diagnostizierbar (Review 2026-07-02).
                logger.warning(f"Redis SET failed for key {key}: {e}")
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
    # Memory-Layer IMMER leeren: pandas-Werte leben NUR dort, und bei
    # Redis-Ausfall dient er als Read-Fallback — ein nur-Redis-Clear liesse
    # solche Einträge bis zum TTL-Ablauf weiterleben (Review 2026-06-10, LOW).
    _mem_clear()
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
        except Exception as e:
            logger.debug(f"Redis CLEAR failed (memory already cleared): {e}")


# --- Stampede prevention, Thread-Pfad ---
#
# Der Cache-Miss-Pfad der Preis-/Kursabfragen laeuft SYNCHRON und wird aus
# async-Handlern via ``asyncio.to_thread`` aufgerufen — die Nebenlaeufigkeit
# entsteht also ueber Threads, nicht ueber Tasks. Die weiter unten stehenden
# ``asyncio.Lock``-Helfer schuetzen dort NICHTS: ein asyncio.Lock ist nicht
# thread-safe und haelt zwei Threads nicht auseinander.
#
# Ohne Schutz laedt bei kaltem Cache jeder gleichzeitige Request dieselbe Reihe
# erneut. Das ist nicht nur Verschwendung: parallele yfinance-Bursts sind die
# dokumentierte Ursache stundenlanger IP-Sperren (siehe yf_patch / Semaphore).

_SINGLE_FLIGHT_TIMEOUT = 30.0  # Sekunden, die ein Follower auf den Leader wartet

_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


@contextlib.contextmanager
def single_flight(key: str, timeout: float = _SINGLE_FLIGHT_TIMEOUT):
    """Genau ein Producer pro Key ueber Thread-Grenzen hinweg.

    Liefert ``True``  → dieser Thread ist der Leader und soll den Wert erzeugen
                        (und in den Cache schreiben).
    Liefert ``False`` → ein anderer Thread war schneller und ist inzwischen
                        fertig; der Aufrufer liest den Wert aus dem Cache.

    Der Leader raeumt seinen Eintrag auch bei einer Exception ab und weckt die
    Wartenden — sonst haengt der naechste Request bis zum Timeout. Laeuft der
    Timeout ab (Leader haengt oder ist gestorben), bekommt der Follower ``True``
    und laedt selbst: doppelt laden ist unschoen, haengen ist schlimmer.

    Absichtlich NICHT verteilt: das schuetzt pro Prozess, nicht ueber die
    uvicorn-Worker hinweg. Ein Redis-Lock waere die naechste Stufe — dafuer
    muesste aber jeder Ausfallmodus (Lock-Halter stirbt, Redis weg) sauber
    abgefangen sein, und der Nutzen sinkt mit jedem Worker weniger stark als
    das Risiko steigt.
    """
    with _inflight_lock:
        ev = _inflight.get(key)
        leader = ev is None
        if leader:
            ev = threading.Event()
            _inflight[key] = ev

    if leader:
        try:
            yield True
        finally:
            # Reihenfolge pop-dann-set ist Absicht: ein Thread, der genau
            # dazwischen ankommt, wird Zweit-Leader und laedt einmal zusaetzlich,
            # statt auf ein Event zu warten, das nie wieder gesetzt wird. Die
            # umgekehrte Reihenfolge waere im Erfolgsfall minimal sparsamer,
            # verloere aber im Fehlerfall den Retry. Der Double-Check im
            # Aufrufer entschaerft das Fenster ohnehin.
            with _inflight_lock:
                _inflight.pop(key, None)
            ev.set()
        return

    if not ev.wait(timeout):
        # Bewusster, begrenzter Trade-off: haengt der Leader laenger als das
        # Timeout, laufen ALLE Wartenden gleichzeitig los. Das ist eine Herde —
        # aber eine um das Timeout verzoegerte und auf die Zahl der gleichzeitigen
        # Requests begrenzte, also strikt besser als der Zustand ohne Schutz
        # (dort feuerte sie sofort). Eine Neuwahl unter den Wartenden waere
        # sparsamer, braucht aber ein Uebernahme-Protokoll mit eigenen
        # Fehlerpfaden — in einem Nebenlaeufigkeits-Primitiv ist Vorhersagbarkeit
        # mehr wert als die letzte Ersparnis in einem seltenen Ausnahmefall.
        logger.warning(
            "single_flight: %.0fs auf den Leader fuer %s gewartet — lade selbst",
            timeout, key,
        )
        yield True
        return
    yield False


# --- Stampede prevention (per-key async locks, always in-memory) ---
#
# NUR fuer rein-async Aufrufer. Wer aus einem Thread (``asyncio.to_thread``)
# kommt, nimmt ``single_flight`` oben — ein asyncio.Lock haelt Threads nicht
# auseinander. Aktuell hat ``get_or_compute`` keinen Aufrufer.

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
