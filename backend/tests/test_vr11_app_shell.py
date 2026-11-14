"""Vollreview 11/2026, Fundament: main.py und middleware/metrics.py.

K005/K022/X33 (Symbolsuche), K091 (Admin-Bootstrap), K164 (Body-Limit),
K082 (Health blockiert bei hängendem Redis), K020 (Metrik-Labels).
"""

import asyncio
import io
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from constants import limits

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Symbolsuche -------------------------------------------------------------


class _Yahoo:
    """Ersatz für services.api_utils.fetch_json_once (die Route importiert beim Aufruf)."""

    def __init__(self, fail: bool = False, delay: float = 0.0):
        self.calls: list[dict] = []
        self.fail = fail
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(params or {}))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("yahoo 429")
            count = int(params["quotesCount"])
            return {
                "quotes": [
                    {"symbol": f"SYM{i}", "quoteType": "EQUITY", "shortname": f"Name {i}"}
                    for i in range(count)
                ]
            }
        finally:
            self.active -= 1


@pytest.fixture
def yahoo(monkeypatch):
    from services import api_utils, cache

    fake = _Yahoo()
    monkeypatch.setattr(api_utils, "fetch_json_once", fake)
    # Ohne Redis: der Memory-Layer ist dann die einzige Quelle, je Test frisch.
    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    cache._mem_clear()
    yield fake
    cache._mem_clear()


class TestSymbolSearch:
    def test_route_carries_search_limit(self):
        import main  # noqa: F401 — registriert die Route am Limiter
        from api.auth import limiter

        route_limits = limiter._route_limits["main.search_symbols"]
        assert [str(l.limit) for l in route_limits] == ["60 per 1 minute"]
        assert limits.RL_SEARCH == "60/minute"

    async def test_limit_is_part_of_the_cache_key(self, client, yahoo):
        """X33: limit=1 kürzte vorher 5 Minuten lang die Treffer aller Nutzer."""
        token = await register_and_login(client, "search1@test.local")
        one = await client.get("/api/search/symbols?q=nes&limit=1", headers=auth(token))
        eight = await client.get("/api/search/symbols?q=nes&limit=8", headers=auth(token))
        assert len(one.json()["results"]) == 1
        assert len(eight.json()["results"]) == 8
        assert [c["quotesCount"] for c in yahoo.calls] == [1, 8]

        again = await client.get("/api/search/symbols?q=NES&limit=8", headers=auth(token))
        assert len(again.json()["results"]) == 8
        assert len(yahoo.calls) == 2  # aus dem Cache, Gross-/Kleinschreibung egal

    @pytest.mark.parametrize(
        "query",
        ["q=" + "a" * 65, "q=ab%00c", "q=ab%0Ac", "q=ab%7Fc", "q=abc&limit=0", "q=abc&limit=21", "q=abc&limit=x"],
    )
    async def test_invalid_input_is_rejected_before_yahoo(self, client, yahoo, query):
        token = await register_and_login(client, "search2@test.local")
        res = await client.get(f"/api/search/symbols?{query}", headers=auth(token))
        assert res.status_code == 422
        assert yahoo.calls == []

    async def test_valid_input_still_works(self, client, yahoo):
        token = await register_and_login(client, "search3@test.local")
        res = await client.get(
            "/api/search/symbols", params={"q": "Nestlé S&P 500", "limit": 20}, headers=auth(token)
        )
        assert res.status_code == 200
        assert len(res.json()["results"]) == 20
        assert yahoo.calls[0]["q"] == "Nestlé S&P 500"

    async def test_long_fund_name_is_accepted(self, client, yahoo):
        """Lange Fondsnamen passen nicht in 30 Zeichen; die Grenze liegt bei 64."""
        name = "iShares Core MSCI World UCITS ETF USD (Acc)"
        assert 30 < len(name) <= 64
        token = await register_and_login(client, "search6@test.local")
        res = await client.get("/api/search/symbols", params={"q": name}, headers=auth(token))
        assert res.status_code == 200
        assert yahoo.calls[0]["q"] == name
        res = await client.get("/api/search/symbols", params={"q": "a" * 64}, headers=auth(token))
        assert res.status_code == 200

    @pytest.mark.parametrize("query", ["", "q=", "q=%20%20"])
    async def test_empty_query_skips_yahoo(self, client, yahoo, query):
        token = await register_and_login(client, "search4@test.local")
        res = await client.get(f"/api/search/symbols?{query}", headers=auth(token))
        assert res.status_code == 200
        assert res.json() == {"results": []}
        assert yahoo.calls == []

    async def test_failure_is_cached_negatively(self, client, yahoo):
        from services import cache

        yahoo.fail = True
        token = await register_and_login(client, "search5@test.local")
        for _ in range(3):
            res = await client.get("/api/search/symbols?q=fail", headers=auth(token))
            assert res.json() == {"results": []}
        assert len(yahoo.calls) == 1

        _, expires_at = cache._mem_cache["symbol_search:fail:8"]
        assert 0 < expires_at - time.monotonic() <= 60

    async def test_requires_login(self, client, yahoo):
        assert (await client.get("/api/search/symbols?q=abc")).status_code == 401
        assert yahoo.calls == []

    async def test_at_most_three_parallel_yahoo_calls(self, monkeypatch, yahoo):
        import main
        from api.auth import limiter

        yahoo.delay = 0.05
        monkeypatch.setattr(limiter, "enabled", False)
        # Frisches Semaphore: ein modulweites bindet sich bei Andrang an den Loop des Tests.
        monkeypatch.setattr(main, "_symbol_search_semaphore", asyncio.Semaphore(3))

        results = await asyncio.gather(
            *(main.search_symbols(request=None, q=f"q{i}", limit=8, user=object()) for i in range(12))
        )
        assert all(len(r["results"]) == 8 for r in results)
        assert len(yahoo.calls) == 12
        assert yahoo.max_active == 3

    async def test_gives_up_when_no_slot_frees_in_time(self, monkeypatch, yahoo):
        """Bei langsamem Yahoo stauen sich Wartende nicht hinter den drei Slots."""
        import main
        from api.auth import limiter

        yahoo.delay = 0.3
        monkeypatch.setattr(limiter, "enabled", False)
        semaphore = asyncio.Semaphore(3)
        monkeypatch.setattr(main, "_symbol_search_semaphore", semaphore)
        monkeypatch.setattr(main, "_SYMBOL_SEARCH_SLOT_WAIT_S", 0.05)

        results = await asyncio.gather(
            *(main.search_symbols(request=None, q=f"slow{i}", limit=8, user=object()) for i in range(5))
        )
        assert sorted(len(r["results"]) for r in results) == [0, 0, 8, 8, 8]
        assert len(yahoo.calls) == 3
        assert semaphore._value == 3  # alle Slots wieder frei

    async def test_slot_is_released_after_failure(self, monkeypatch, yahoo):
        import main
        from api.auth import limiter

        yahoo.fail = True
        monkeypatch.setattr(limiter, "enabled", False)
        semaphore = asyncio.Semaphore(3)
        monkeypatch.setattr(main, "_symbol_search_semaphore", semaphore)

        for i in range(5):
            assert await main.search_symbols(request=None, q=f"bad{i}", limit=8, user=object()) == {"results": []}
        assert semaphore._value == 3

    def test_semaphore_is_module_wide_with_three_slots(self):
        import main

        assert isinstance(main._symbol_search_semaphore, asyncio.Semaphore)
        assert main._symbol_search_semaphore._value == 3


# --- Admin-Bootstrap ---------------------------------------------------------


ADMIN_EMAIL = "boot-admin@test.local"
ADMIN_PASSWORD = "BootstrapPassw0rd!2026"


@pytest.fixture
def admin_env(monkeypatch):
    import main

    monkeypatch.setattr(main.settings, "admin_email", ADMIN_EMAIL)
    monkeypatch.setattr(main.settings, "admin_password", ADMIN_PASSWORD)


async def _add_user(db, email: str, is_admin: bool, is_active: bool = True):
    from models.user import User

    # Kein echter bcrypt-Hash nötig: der Bootstrap prüft kein Passwort.
    user = User(email=email, password_hash="x", is_admin=is_admin, is_active=is_active)
    db.add(user)
    await db.commit()
    return user


async def _admins(db) -> set[str]:
    from models.user import User

    db.expire_all()
    rows = await db.execute(select(User.email).where(User.is_admin == True))  # noqa: E712
    return {r[0] for r in rows}


class TestAdminBootstrap:
    async def test_creates_admin_on_empty_instance(self, db, admin_env):
        import main
        from models.user import User, UserSettings
        from services.auth_service import verify_password

        await main.create_admin_user()

        user = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalars().one()
        assert user.is_admin is True
        assert verify_password(ADMIN_PASSWORD, user.password_hash)
        count = await db.execute(
            select(func.count()).select_from(UserSettings).where(UserSettings.user_id == user.id)
        )
        assert count.scalar() == 1

    async def test_does_not_promote_when_an_admin_exists(self, db, admin_env):
        """K091: der Admin hat seine Adresse geändert, ein Nutzer belegt die alte
        aus ADMIN_EMAIL. Vor dem Fix machte ihn der nächste Start zum Admin."""
        import main

        await _add_user(db, "real-admin@test.local", is_admin=True)
        await _add_user(db, ADMIN_EMAIL, is_admin=False)

        await main.create_admin_user()

        assert await _admins(db) == {"real-admin@test.local"}

    async def test_does_not_create_second_admin(self, db, admin_env):
        import main
        from models.user import User

        await _add_user(db, "real-admin@test.local", is_admin=True)

        await main.create_admin_user()

        total = (await db.execute(select(func.count()).select_from(User))).scalar()
        assert total == 1
        assert await _admins(db) == {"real-admin@test.local"}

    async def test_never_promotes_an_existing_account(self, db, admin_env):
        """Abnahme Fixlauf: Ohne Admin belegt ein Nutzer die Adresse aus ADMIN_EMAIL
        (Registrierung oder change-email, beide ohne Bestätigung). Der Start darf
        ihn nicht zum Admin machen: er behielte sein eigenes Passwort."""
        import main

        await _add_user(db, "someone@test.local", is_admin=False)
        await _add_user(db, ADMIN_EMAIL, is_admin=False)

        await main.create_admin_user()

        assert await _admins(db) == set()

    async def test_is_idempotent(self, db, admin_env):
        import main
        from models.user import User

        await main.create_admin_user()
        await main.create_admin_user()

        total = (await db.execute(select(func.count()).select_from(User))).scalar()
        assert total == 1

    async def test_deactivated_admin_does_not_block_the_bootstrap(self, db, admin_env):
        """R-auth-3: der einzige Admin ist gesperrt. Der Start übersprang den
        Bootstrap trotzdem, und niemand erreichte mehr /api/admin."""
        import main
        from models.user import User
        from services.auth_service import verify_password

        await _add_user(db, "locked-admin@test.local", is_admin=True, is_active=False)

        await main.create_admin_user()

        user = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalars().one()
        assert user.is_admin is True
        assert user.is_active is True
        assert verify_password(ADMIN_PASSWORD, user.password_hash)
        locked = (
            await db.execute(select(User).where(User.email == "locked-admin@test.local"))
        ).scalars().one()
        assert locked.is_active is False  # der Start entsperrt niemanden

    async def test_active_admin_blocks_the_bootstrap_next_to_a_deactivated_one(self, db, admin_env):
        import main

        await _add_user(db, "locked-admin@test.local", is_admin=True, is_active=False)
        await _add_user(db, "real-admin@test.local", is_admin=True)

        await main.create_admin_user()

        assert await _admins(db) == {"locked-admin@test.local", "real-admin@test.local"}

    async def test_does_not_promote_while_only_deactivated_admins_exist(self, db, admin_env):
        """K091 bleibt behoben: ein Nutzer belegt die Adresse aus ADMIN_EMAIL und
        wartet, bis der Admin gesperrt ist."""
        import main
        from models.user import User

        await _add_user(db, "locked-admin@test.local", is_admin=True, is_active=False)
        await _add_user(db, ADMIN_EMAIL, is_admin=False)

        await main.create_admin_user()

        assert await _admins(db) == {"locked-admin@test.local"}
        total = (await db.execute(select(func.count()).select_from(User))).scalar()
        assert total == 2

    async def test_does_not_reactivate_the_deactivated_admin(self, db, admin_env):
        import main
        from models.user import User

        await _add_user(db, ADMIN_EMAIL, is_admin=True, is_active=False)

        await main.create_admin_user()

        user = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalars().one()
        assert user.is_active is False
        assert user.password_hash == "x"
        total = (await db.execute(select(func.count()).select_from(User))).scalar()
        assert total == 1


# --- Body-Limit --------------------------------------------------------------


class TestBodyLimit:
    async def test_chunked_body_is_refused(self, client):
        """K164: ohne Content-Length griff das 10-MB-Limit nicht."""
        sent = 0

        async def body():
            nonlocal sent
            for _ in range(4):
                sent += 1
                yield b"x" * 1024

        res = await client.post("/api/errors", content=body())
        assert res.status_code == 411
        assert "Content-Length" in res.json()["detail"]

    async def test_transfer_encoding_wins_over_content_length(self, client):
        res = await client.post(
            "/api/errors",
            content=b"{}",
            headers={"Transfer-Encoding": "chunked", "Content-Length": "2"},
        )
        assert res.status_code == 411

    async def test_declared_oversize_is_still_refused(self, client):
        res = await client.post(
            "/api/errors", content=b"{}", headers={"Content-Length": str(10 * 1024 * 1024 + 1)}
        )
        assert res.status_code == 413

    async def test_plain_body_passes(self, client):
        res = await client.post("/api/errors", json={"message": "boom"})
        assert res.status_code == 200

    async def test_multipart_upload_passes(self, client):
        """Uploads über python-multipart tragen Content-Length und laufen weiter."""
        token = await register_and_login(client, "upload@test.local")
        csv = b"Date,Type,Ticker,Shares,Price,Currency,Total\n2025-01-15,buy,AAPL,10,150.00,USD,1500.00\n"
        res = await client.post(
            "/api/import/analyze",
            files={"file": ("test.csv", io.BytesIO(csv), "text/csv")},
            headers=auth(token),
        )
        assert "content-length" in res.request.headers
        assert "transfer-encoding" not in res.request.headers
        assert res.status_code == 200, res.text
        assert res.json()["row_count"] == 1


# --- Health ------------------------------------------------------------------


class _SlowRedis:
    def __init__(self, seconds: float):
        self.seconds = seconds

    def ping(self):
        time.sleep(self.seconds)
        return True


class _OutageRedis:
    """Erst erreichbar, dann ausgefallen: jeder Befehl wirft einen Verbindungsfehler."""

    def __init__(self):
        self.down = False

    def _check(self):
        if self.down:
            import redis

            raise redis.exceptions.ConnectionError("Connection refused")

    def ping(self):
        self._check()
        return True

    def get(self, key):
        self._check()
        return None

    def delete(self, *keys):
        self._check()


@pytest.fixture
def cache_state():
    """Verbindungszustand von services.cache sichern und wiederherstellen."""
    from services import cache

    saved = (cache._redis, cache._redis_available, cache._redis_last_attempt)
    yield cache
    cache._redis, cache._redis_available, cache._redis_last_attempt = saved


class TestHealthRedisPing:
    async def test_outage_behind_open_circuit_breaker_is_degraded(self, client, cache_state):
        """R-auth-1: nach dem ersten Fehler liefert ``_get_redis()`` None. Health
        hielt das für «kein Redis» und meldete ok."""
        cache = cache_state
        fake = _OutageRedis()
        cache._redis, cache._redis_available, cache._redis_last_attempt = fake, True, None
        assert (await client.get("/api/health")).json() == {"status": "ok"}

        fake.down = True
        assert cache.get("vr11:any") is None  # ein Request öffnet den Breaker
        assert cache._redis_available is False
        assert cache._get_redis() is None

        for _ in range(3):
            assert (await client.get("/api/health")).json() == {"status": "degraded"}

        # Auch der Reconnect-Versuch nach dem Intervall ändert nichts daran.
        cache._redis_last_attempt = time.monotonic() - cache._REDIS_RETRY_INTERVAL - 1
        assert (await client.get("/api/health")).json() == {"status": "degraded"}

        fake.down = False
        cache._redis_last_attempt = time.monotonic() - cache._REDIS_RETRY_INTERVAL - 1
        assert (await client.get("/api/health")).json() == {"status": "ok"}

    async def test_configured_but_never_reached_redis_is_degraded(self, client, cache_state):
        cache = cache_state
        fake = _OutageRedis()
        fake.down = True
        # Zustand nach einem gescheiterten ersten Verbindungsversuch.
        cache._redis, cache._redis_available, cache._redis_last_attempt = fake, False, time.monotonic()

        token = await register_and_login(client, "health-down@test.local")
        body = (await client.get("/api/health", headers=auth(token))).json()
        assert body["status"] == "degraded"
        assert body["redis"] == "disconnected"

    async def test_busy_default_thread_pool_does_not_fake_an_outage(self, client, monkeypatch):
        """R-auth-2: der PING wartete im Standard-Pool hinter fremden Aufgaben,
        bis die Frist ablief."""
        import threading

        import main
        from services import cache

        monkeypatch.setattr(cache, "_get_redis", lambda: _SlowRedis(0))
        monkeypatch.setattr(main, "_HEALTH_REDIS_TIMEOUT_S", 0.5)

        release = threading.Event()
        # Mehr Aufgaben als der Standard-Pool Threads hat (höchstens 32).
        blockers = [asyncio.create_task(asyncio.to_thread(release.wait, 10)) for _ in range(40)]
        await asyncio.sleep(0.05)
        try:
            start = time.monotonic()
            res = await client.get("/api/health")
            elapsed = time.monotonic() - start
        finally:
            release.set()
            await asyncio.gather(*blockers)

        assert res.json() == {"status": "ok"}
        assert elapsed < 0.4

    def test_ping_has_its_own_small_thread_pool(self):
        import main

        assert main._health_executor._max_workers == 2

    async def test_hanging_redis_does_not_block_the_event_loop(self, client, monkeypatch):
        """K082: der synchrone PING lief im Event-Loop."""
        import main
        from services import cache

        monkeypatch.setattr(cache, "_get_redis", lambda: _SlowRedis(0.6))
        monkeypatch.setattr(main, "_HEALTH_REDIS_TIMEOUT_S", 0.1)

        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        try:
            start = time.monotonic()
            res = await client.get("/api/health")
            elapsed = time.monotonic() - start
        finally:
            task.cancel()

        assert res.status_code == 200
        assert res.json() == {"status": "degraded"}
        assert elapsed < 0.5  # Frist, nicht die 0.6 s des PING
        assert ticks >= 3  # der Loop lief während des PING weiter

    async def test_ping_error_is_degraded(self, client, monkeypatch):
        from services import cache

        class Broken:
            def ping(self):
                raise ConnectionError("down")

        monkeypatch.setattr(cache, "_get_redis", lambda: Broken())
        assert (await client.get("/api/health")).json() == {"status": "degraded"}

    async def test_no_redis_is_not_degraded(self, client, monkeypatch):
        from services import cache

        monkeypatch.setattr(cache, "_get_redis", lambda: None)
        # Ohne Client, sonst pingt Health ihn direkt (offener Circuit-Breaker).
        monkeypatch.setattr(cache, "_redis", None)
        assert (await client.get("/api/health")).json() == {"status": "ok"}

    async def test_reachable_redis_is_ok(self, client, monkeypatch):
        from services import cache

        monkeypatch.setattr(cache, "_get_redis", lambda: _SlowRedis(0))
        token = await register_and_login(client, "health@test.local")
        body = (await client.get("/api/health", headers=auth(token))).json()
        assert body["status"] == "ok"
        assert body["redis"] == "connected"


# --- Metriken ----------------------------------------------------------------


def _labels(metric, name: str) -> set[str]:
    return {s.labels.get(name) for m in metric.collect() for s in m.samples}


class TestMetricsLabels:
    async def test_unmatched_paths_share_one_label(self, client):
        """K020: jeder unbekannte Pfad legte vorher eigene Serien an."""
        from middleware.metrics import REQUEST_COUNT, REQUEST_LATENCY

        paths = [f"/nirgendwo/{uuid.uuid4().hex}/{i}" for i in range(5)]
        for path in paths:
            assert (await client.get(path)).status_code == 404

        for metric in (REQUEST_COUNT, REQUEST_LATENCY):
            endpoints = _labels(metric, "endpoint")
            assert "unmatched" in endpoints
            assert not any(e.startswith("/nirgendwo") for e in endpoints)

    async def test_unmatched_api_path_is_not_normalised_into_a_label(self, client):
        from middleware.metrics import REQUEST_COUNT

        marker = uuid.uuid4().hex
        assert (await client.get(f"/api/{marker}/x")).status_code == 404
        assert not any(marker in (e or "") for e in _labels(REQUEST_COUNT, "endpoint"))

    async def test_unknown_method_becomes_other(self, client):
        from middleware.metrics import REQUEST_COUNT

        method = "X" + uuid.uuid4().hex[:8].upper()
        await client.request(method, "/api/cache/status")
        methods = _labels(REQUEST_COUNT, "method")
        assert "OTHER" in methods
        assert method not in methods

    def test_method_label_list(self):
        from middleware.metrics import _method_label

        for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            assert _method_label(method) == method
        assert _method_label("PROPFIND") == "OTHER"
        assert _method_label("get") == "OTHER"

    async def test_metrics_endpoint_serialises_in_a_thread(self, client, monkeypatch):
        import threading

        from middleware import metrics

        seen = {}

        def fake_generate_latest():
            seen["thread"] = threading.current_thread()
            return b"# fake\n"

        monkeypatch.setattr(metrics, "generate_latest", fake_generate_latest)
        res = await client.get("/metrics")
        assert res.status_code == 200
        assert res.text == "# fake\n"
        assert seen["thread"] is not threading.main_thread()
