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
- Antwortet Redis mitten im Betrieb nicht mehr (Timeout, Verbindungsfehler),
  gilt es für ``_REDIS_RETRY_INTERVAL`` als nicht erreichbar (Vollreview
  11/2026, K082). Sonst wartet JEDER Aufruf bis zu 2 s — viele davon in
  Schleifen auf dem Event-Loop.
- Der Prozessspeicher hat zwei getrennte Teile (K065/K081): den Redis-Ersatz
  für JSON-Werte, der nur bei einem Redis-Ausfall beschrieben wird und nach
  Einträgen UND Bytes begrenzt ist, und den Objektspeicher für Werte, die nie
  nach Redis können (Kursreihen), mit eigener Obergrenze.
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
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

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
        if (_pending_deletes or _pending_lock_releases) and not _replay_pending_deletes(_redis):
            return None
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
        if not _replay_pending_deletes(_redis):
            return None
        return _redis
    except Exception as e:
        _redis_available = False
        logger.warning(
            f"Redis unavailable, using in-memory fallback (retry in {int(_REDIS_RETRY_INTERVAL)}s): {e}"
        )
        return None


# --- Circuit-Breaker (K082) ---
#
# Builtin ConnectionError/TimeoutError (Socket-Ebene) sind OSError. Andere
# Fehler (ResponseError bei OOM, kaputtes JSON) kommen von einem Redis, das
# antwortet — dafür bleibt die Verbindung in Gebrauch.
_REDIS_DOWN_ERRORS = (RedisConnectionError, RedisTimeoutError, OSError)


def _note_redis_error(exc: BaseException) -> None:
    """Markiert Redis nach einem Timeout oder Verbindungsfehler als nicht
    erreichbar. ``_get_redis()`` liefert dann ``_REDIS_RETRY_INTERVAL`` Sekunden
    lang ``None`` (In-Memory-Fallback) und prüft danach mit einem PING neu."""
    global _redis_available, _redis_last_attempt
    if not isinstance(exc, _REDIS_DOWN_ERRORS):
        return
    if _redis_available:
        logger.warning(
            f"Redis not responding, using in-memory fallback (retry in {int(_REDIS_RETRY_INTERVAL)}s): {exc}"
        )
    _redis_available = False
    _redis_last_attempt = time.monotonic()


# Invalidierungen, die Redis nicht erreicht haben. Ohne Nachholen überlebt der
# alte Wert den Ausfall in Redis und gilt danach wieder als frisch — bis zu
# seiner TTL. Begrenzt: läuft die Menge voll, gehen weitere Löschungen verloren
# wie vor dem Circuit-Breaker.
_PENDING_DELETES_MAX = 5000
_pending_deletes: set[str] = set()
# Lock-Freigaben, die Redis nicht erreicht haben: key -> Ablauf des Locks
# (time.monotonic). Ohne Nachholen sperrt der Schlüssel bis zu seiner TTL jeden
# weiteren Lauf, obwohl der Job fertig ist (Vollreview 11/2026, R-yfanalysis-2).
_pending_lock_releases: dict[str, float] = {}
_pending_lock = threading.Lock()
# Locks, die dieser Prozess in Redis gesetzt hat. Nur ihre Freigabe wird
# nachgeholt: ein Lock aus dem lokalen Ersatz stand nie in Redis, der Schlüssel
# dort gehört dann einem anderen Prozess. Steht hier oben, weil das Modul weiter
# unten ``set`` überschreibt.
_redis_locks: set[str] = set()


def _remember_delete(key: str) -> None:
    with _pending_lock:
        if len(_pending_deletes) < _PENDING_DELETES_MAX:
            _pending_deletes.add(key)


def _remember_lock_release(key: str, expires_at: float | None) -> None:
    if expires_at is None or time.monotonic() >= expires_at:
        return
    with _pending_lock:
        if len(_pending_lock_releases) < _PENDING_DELETES_MAX:
            _pending_lock_releases[key] = expires_at


def _replay_pending_deletes(r: redis.Redis) -> bool:
    """Löscht die gemerkten Schlüssel in Redis und holt gemerkte Lock-Freigaben
    nach. ``False``, wenn Redis dabei wieder ausfällt — beides bleibt dann
    gemerkt."""
    now = time.monotonic()
    with _pending_lock:
        keys = list(_pending_deletes)
        _pending_deletes.clear()
        locks = dict(_pending_lock_releases)
        _pending_lock_releases.clear()
    names = [f"{_KEY_PREFIX}{k}" for k in keys]
    # Nach dem Ablauf hat Redis das Lock selbst entfernt. Der Schlüssel kann
    # dann einem neuen Halter gehören und bleibt stehen.
    names += [f"{_LOCK_PREFIX}{k}" for k, expires_at in locks.items() if now < expires_at]
    try:
        for i in range(0, len(names), 500):
            r.delete(*names[i:i + 500])
        return True
    except Exception as e:
        logger.debug(f"Redis replay of {len(names)} deletes failed: {e}")
        _note_redis_error(e)
        if _redis_available:
            # Redis antwortet, lehnt das Löschen aber ab: nicht bei jedem
            # Aufruf neu versuchen. Die Schlüssel laufen über ihre TTL aus.
            return True
        with _pending_lock:
            _pending_deletes.update(keys[:_PENDING_DELETES_MAX])
            for k, expires_at in locks.items():
                _pending_lock_releases.setdefault(k, expires_at)
        return False


# --- Prozessspeicher ---
#
# _mem_cache: Ersatz für Redis. JSON-Werte landen hier nur, solange Redis nicht
#   erreichbar ist oder ein Schreibzugriff scheitert (K081). Bei laufendem
#   Redis liest get() diese Kopien nie; früher spiegelte set() trotzdem jeden
#   Wert hierher, und Schlüssel mit Datum (Historie, mehrere 100 KB je Eintrag)
#   sammelten sich in jedem Prozess an.
# _obj_cache: Werte, die nie nach Redis können (pandas Series). Eigene
#   Obergrenze, damit JSON-Einträge keine Kursreihen verdrängen (K065) —
#   eine verdrängte Reihe kostet einen Yahoo-Download im Request.

_MAX_SIZE = 2500  # Einträge im Redis-Ersatz
_MEM_MAX_BYTES = 32 * 1024 * 1024  # Budget des Redis-Ersatzes, gemessen als JSON
_MEM_MAX_ENTRY_BYTES = 4 * 1024 * 1024  # grössere Werte bleiben ungecacht
_OBJ_MAX_SIZE = 4000  # Einträge im Objektspeicher
_SWEEP_INTERVAL = 60.0  # Sekunden zwischen zwei Läufen gegen abgelaufene Einträge

_mem_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
_mem_sizes: dict[str, int] = {}
_mem_bytes = 0
_obj_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
_last_sweep = 0.0
_lock = threading.Lock()  # schützt beide Speicher und ihre Zähler


def _mem_drop(key: str) -> None:
    """Entfernt key aus dem Redis-Ersatz. Aufrufer hält ``_lock``."""
    global _mem_bytes
    if _mem_cache.pop(key, None) is not None:
        _mem_bytes -= _mem_sizes.pop(key, 0)


def _evict_expired(now: float) -> None:
    """Aufrufer hält ``_lock``."""
    for k in [k for k, (_, exp) in _mem_cache.items() if now > exp]:
        _mem_drop(k)
    for k in [k for k, (_, exp) in _obj_cache.items() if now > exp]:
        del _obj_cache[k]


def _maybe_sweep() -> None:
    """Räumt abgelaufene Einträge höchstens alle ``_SWEEP_INTERVAL`` Sekunden ab.

    Ohne das verschwinden sie erst, wenn ein Speicher voll ist: Schlüssel, die
    nie wieder gelesen werden, hielten ihren Wert bis dahin fest.
    """
    global _last_sweep
    now = time.monotonic()
    if 0 <= now - _last_sweep < _SWEEP_INTERVAL:
        return
    with _lock:
        _last_sweep = now
        _evict_expired(now)


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str))
    except Exception:
        # Nicht serialisierbar trotz JSON-Typ (z.B. Tupel als dict-Schlüssel):
        # grob schätzen statt den Wert abzulehnen.
        try:
            return len(str(value))
        except Exception:
            return 0


def _mem_get(key: str) -> Any | None:
    with _lock:
        entry = _mem_cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            _mem_drop(key)
            return None
        # Move to end for LRU (most recently used)
        _mem_cache.move_to_end(key)
        return value


def _mem_set(key: str, value: Any, ttl: int) -> None:
    global _mem_bytes
    size = _json_size(value)
    now = time.monotonic()
    if size > _MEM_MAX_ENTRY_BYTES:
        # Ein einzelner Riesenwert würde sonst den halben Ersatz verdrängen.
        _mem_delete(key)
        logger.debug(f"Value for key {key} too large for in-memory fallback ({size} bytes)")
        return
    with _lock:
        _obj_cache.pop(key, None)
        _mem_drop(key)
        if len(_mem_cache) >= _MAX_SIZE or _mem_bytes + size > _MEM_MAX_BYTES:
            _evict_expired(now)
            # Evict LRU (first item) until both limits hold
            while _mem_cache and (
                len(_mem_cache) >= _MAX_SIZE or _mem_bytes + size > _MEM_MAX_BYTES
            ):
                _mem_drop(next(iter(_mem_cache)))
        _mem_cache[key] = (value, now + ttl)
        _mem_sizes[key] = size
        _mem_bytes += size


def _obj_get(key: str) -> Any | None:
    with _lock:
        entry = _obj_cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del _obj_cache[key]
            return None
        _obj_cache.move_to_end(key)
        return value


def _obj_set(key: str, value: Any, ttl: int) -> None:
    now = time.monotonic()
    with _lock:
        # Ein Schlüssel lebt nur in einem der beiden Speicher: ein älterer
        # JSON-Wert (z.B. Negativ-Sentinel) darf die Reihe nicht überdecken.
        _mem_drop(key)
        if key in _obj_cache:
            _obj_cache.move_to_end(key)
        elif len(_obj_cache) >= _OBJ_MAX_SIZE:
            _evict_expired(now)
            while len(_obj_cache) >= _OBJ_MAX_SIZE:
                _obj_cache.popitem(last=False)
        _obj_cache[key] = (value, now + ttl)


def _local_get(key: str) -> Any | None:
    """Lesen ohne Redis: Redis-Ersatz, sonst Objektspeicher."""
    value = _mem_get(key)
    return value if value is not None else _obj_get(key)


def _mem_delete(key: str) -> None:
    with _lock:
        _mem_drop(key)
        _obj_cache.pop(key, None)


def _mem_clear() -> None:
    global _mem_bytes
    with _lock:
        _mem_cache.clear()
        _mem_sizes.clear()
        _mem_bytes = 0
        _obj_cache.clear()


# --- Public API ---
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
            # Redis-Miss: Key wurde invalidiert oder ist abgelaufen. Lokal
            # zählt hier nur der Objektspeicher (pandas Series etc., siehe
            # set()) — ein JSON-Eintrag im Redis-Ersatz ohne Redis-Pendant
            # stammt aus einem Ausfall und ist stale.
            return _obj_get(key)
        except Exception as e:
            logger.debug(f"Redis GET failed for key {key}: {e}")
            _note_redis_error(e)
    # Redis down oder Fehler → In-Memory-Fallback
    return _local_get(key)


def set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    _maybe_sweep()
    if not _is_json_serializable(value):
        # Non-serializable (pandas Series etc.): local memory only
        _obj_set(key, value, ttl)
        return
    r = _get_redis()
    if r is not None:
        try:
            r.set(f"{_KEY_PREFIX}{key}", json.dumps(value, default=str), ex=ttl)
        except Exception as e:
            # WARNING statt debug: get() liest Redis-first — schlagen
            # Writes fehl (OOM/noeviction, readonly-Replica), ist der
            # Wert effektiv uncachebar und jeder Read ein Miss. Ohne
            # sichtbares Log ist dieser Degradations-Modus kaum
            # diagnostizierbar (Review 2026-07-02).
            logger.warning(f"Redis SET failed for key {key}: {e}")
            _note_redis_error(e)
        else:
            # Redis hat den Wert: keine zweite Kopie im Prozess (K081). Eine
            # ältere lokale Kopie desselben Schlüssels wäre ab jetzt stale.
            _mem_delete(key)
            return
    # Redis nicht erreichbar oder Schreibfehler → Redis-Ersatz im Prozess
    _mem_set(key, value, ttl)


def delete(key: str) -> None:
    _mem_delete(key)
    r = _get_redis()
    if r is None:
        _remember_delete(key)
        return
    try:
        r.delete(f"{_KEY_PREFIX}{key}")
    except Exception as e:
        logger.debug(f"Redis DELETE failed for key {key}: {e}")
        _note_redis_error(e)
        _remember_delete(key)


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
            _note_redis_error(e)


def get_many(keys: list[str]) -> dict[str, Any]:
    """Liest mehrere Schlüssel in einem Roundtrip (MGET).

    Gleiche Regeln wie ``get()``: Redis zuerst, lokal zählt bei erreichbarem
    Redis nur der Objektspeicher, und der Prozessspeicher ersetzt Redis bei
    einem Ausfall ganz. Fehlende Schlüssel fehlen im Ergebnis — ebenso ein
    gecachtes ``None``, das auch ``get()`` nicht von einem Miss unterscheidet.
    """
    if not keys:
        return {}
    result: dict[str, Any] = {}
    r = _get_redis()
    if r is not None:
        try:
            raws = r.mget([f"{_KEY_PREFIX}{k}" for k in keys])
            for key, raw in zip(keys, raws):
                value = json.loads(raw) if raw is not None else _obj_get(key)
                if value is not None:
                    result[key] = value
            return result
        except Exception as e:
            logger.debug(f"Redis MGET failed for {len(keys)} keys: {e}")
            _note_redis_error(e)
            result = {}
    for key in keys:
        value = _local_get(key)
        if value is not None:
            result[key] = value
    return result


# --- Locks (prozessübergreifend über Redis) ---
#
# Eigener Präfix ausserhalb von _KEY_PREFIX: clear() löscht alle Cache-Schlüssel
# und nähme sonst jedem laufenden Job sein Lock weg.

_LOCK_PREFIX = "openfolio-lock:"
_LOCAL_LOCKS_PRUNE_SIZE = 1000
_local_locks: dict[str, float] = {}  # key -> Ablauf (time.monotonic)
_local_locks_lock = threading.Lock()  # schützt _local_locks und _redis_locks


def _local_lock_acquire(key: str, ttl: int, force: bool = False) -> bool:
    now = time.monotonic()
    with _local_locks_lock:
        if not force:
            expires_at = _local_locks.get(key)
            if expires_at is not None and now < expires_at:
                return False
        if len(_local_locks) >= _LOCAL_LOCKS_PRUNE_SIZE:
            for k in [k for k, exp in _local_locks.items() if now >= exp]:
                del _local_locks[k]
                _redis_locks.discard(k)
        _local_locks[key] = now + ttl
        # force kommt nur vom Redis-Pfad: dann steht das Lock auch in Redis.
        if force:
            _redis_locks.add(key)
        else:
            _redis_locks.discard(key)
        return True


def acquire_lock(key: str, ttl: int) -> bool:
    """Versucht, das Lock ``key`` für ``ttl`` Sekunden zu nehmen. Blockiert nie.

    Mit Redis gilt das Lock über alle Prozesse (SET NX EX). Ohne Redis gilt ein
    Ersatz mit Ablaufzeit, der nur den eigenen Prozess schützt: lieber ein
    schwächeres Lock als ein Job, der bei einem Redis-Ausfall gar nicht läuft.

    Das Lock kennt keinen Besitzer. ``release_lock`` ruft nur auf, wer es
    bekommen hat, und ``ttl`` muss die Arbeit sicher überdauern — sonst gibt der
    erste Halter das Lock des zweiten frei.
    """
    ttl = max(1, int(ttl))
    r = _get_redis()
    if r is not None:
        try:
            acquired = bool(r.set(f"{_LOCK_PREFIX}{key}", "1", nx=True, ex=ttl))
            if acquired:
                # Lokal mitführen: fällt Redis danach aus, sieht der Ersatz das Lock.
                _local_lock_acquire(key, ttl, force=True)
                # Eine noch gemerkte Freigabe träfe sonst dieses neue Lock.
                with _pending_lock:
                    _pending_lock_releases.pop(key, None)
            return acquired
        except Exception as e:
            logger.warning(f"Redis lock failed for {key}, using process-local lock: {e}")
            _note_redis_error(e)
    return _local_lock_acquire(key, ttl)


def release_lock(key: str) -> None:
    """Gibt das Lock ``key`` frei. Fehler erreichen den Aufrufer nie; spätestens
    die TTL räumt auf.

    Erreicht die Freigabe Redis nicht, holt der nächste erfolgreiche
    Redis-Zugriff sie nach — solange das Lock nicht ohnehin abgelaufen ist.
    """
    with _local_locks_lock:
        expires_at = _local_locks.pop(key, None)
        in_redis = key in _redis_locks
        _redis_locks.discard(key)
    r = _get_redis()
    if r is None:
        if in_redis:
            _remember_lock_release(key, expires_at)
        return
    try:
        r.delete(f"{_LOCK_PREFIX}{key}")
    except Exception as e:
        logger.debug(f"Redis lock release failed for {key}: {e}")
        _note_redis_error(e)
        if in_redis:
            _remember_lock_release(key, expires_at)


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
