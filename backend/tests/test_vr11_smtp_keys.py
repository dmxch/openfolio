"""Vollreview 11/2026, Fixer smtp: API-Keys globaler Jobs, Makro-Cache, ntfy.

K095/X37 (System-Key vor Admin-Key, nie ein Nutzer-Key, kein Key in Redis),
K142 (Makro-Cache: kein Löschen durch beliebige Nutzer, ein Abruf je Cache-Miss),
K154 (keine Zugangsdaten in Logs und in der ntfy-URL), K046 (Sammel-Push je
Alarm-Gruppe), K002 (Passwortprüfung der API-Key-Erstellung ausserhalb des Loops).
"""

import asyncio
import logging
import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import update

from config import settings
from models import Base
from models.user import User, UserSettings
from services import cache, ntfy_service, settings_service
from services import macro_indicators_service as macro
from services.auth_service import encrypt_value
from services.quant import estimate_revisions_service as revisions
from services.url_guard import UnsafeUrlError

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _no_system_keys(monkeypatch):
    monkeypatch.setattr(settings, "fmp_system_api_key", "")
    monkeypatch.setattr(settings, "fred_system_api_key", "")


@pytest.fixture
def mem_cache(monkeypatch):
    """Cache ohne Redis: der Memory-Layer ist die einzige Quelle, je Test frisch."""
    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    cache._mem_clear()
    yield cache
    cache._mem_clear()


def _user(email: str, *, is_admin: bool, age_days: int, is_active: bool = True,
          fmp: str | None = None, fred: str | None = None) -> tuple[User, UserSettings]:
    user = User(
        id=uuid4(), email=email, password_hash="x", is_admin=is_admin, is_active=is_active,
        created_at=datetime(2026, 1, 1) - timedelta(days=age_days),
    )
    user_settings = UserSettings(
        user_id=user.id,
        fmp_api_key=encrypt_value(fmp) if fmp else None,
        fred_api_key=encrypt_value(fred) if fred else None,
    )
    return user, user_settings


async def _add(db, *pairs) -> None:
    for user, user_settings in pairs:
        db.add(user)
        await db.flush()
        db.add(user_settings)
    await db.commit()


class TestGetSystemApiKey:
    async def test_key_of_a_plain_user_never_feeds_global_jobs(self, db):
        """K095: der erste Nutzer mit Key bezahlte die Abrufe für alle."""
        await _add(db, _user("user@test.local", is_admin=False, age_days=900, fmp="user-key", fred="user-fred"))
        assert await settings_service.get_system_api_key(db, "fmp_api_key") is None
        assert await settings_service.get_system_api_key(db, "fred_api_key") is None

    async def test_oldest_admin_with_a_key_wins(self, db):
        await _add(
            db,
            _user("user@test.local", is_admin=False, age_days=900, fmp="user-key"),
            _user("young@test.local", is_admin=True, age_days=10, fmp="young-admin-key"),
            _user("old@test.local", is_admin=True, age_days=500, fmp="old-admin-key"),
            _user("oldest-no-key@test.local", is_admin=True, age_days=800),
            _user("gone@test.local", is_admin=True, age_days=700, is_active=False, fmp="inactive-key"),
        )
        assert await settings_service.get_system_api_key(db, "fmp_api_key") == "old-admin-key"

    async def test_operator_key_beats_every_account(self, db, monkeypatch):
        await _add(db, _user("admin@test.local", is_admin=True, age_days=500, fmp="admin-key", fred="admin-fred"))
        monkeypatch.setattr(settings, "fmp_system_api_key", "  system-fmp  ")
        monkeypatch.setattr(settings, "fred_system_api_key", "system-fred")
        assert await settings_service.get_system_api_key(db, "fmp_api_key") == "system-fmp"
        assert await settings_service.get_system_api_key(db, "fred_api_key") == "system-fred"

    async def test_undecryptable_admin_key_is_skipped(self, db):
        broken_user, broken_settings = _user("broken@test.local", is_admin=True, age_days=500)
        broken_settings.fmp_api_key = "not-a-fernet-token"
        await _add(
            db,
            (broken_user, broken_settings),
            _user("ok@test.local", is_admin=True, age_days=100, fmp="ok-key"),
        )
        assert await settings_service.get_system_api_key(db, "fmp_api_key") == "ok-key"

    async def test_unknown_field_is_refused(self, db):
        with pytest.raises(ValueError):
            await settings_service.get_system_api_key(db, "finnhub_api_key")
        with pytest.raises(ValueError):
            settings_service.get_system_api_key_sync("password_hash")


@pytest.fixture
def sync_db():
    """Die Sync-Engine der Suite hat eine eigene In-Memory-DB ohne Tabellen."""
    from db import SyncSessionLocal, sync_engine

    Base.metadata.create_all(sync_engine)
    try:
        with SyncSessionLocal() as session:
            yield session
    finally:
        Base.metadata.drop_all(sync_engine)


class TestSyncTwinAndFredKey:
    def _add(self, session, *pairs):
        for user, user_settings in pairs:
            session.add(user)
            session.flush()
            session.add(user_settings)
        session.commit()

    async def test_sync_twin_follows_the_same_rule(self, sync_db):
        self._add(
            sync_db,
            _user("user@test.local", is_admin=False, age_days=900, fred="user-fred"),
            _user("young@test.local", is_admin=True, age_days=10, fred="young-fred"),
            _user("old@test.local", is_admin=True, age_days=500, fred="old-fred"),
        )
        assert settings_service.get_system_api_key_sync("fred_api_key") == "old-fred"
        assert macro._get_fred_api_key() == "old-fred"

    async def test_fred_key_of_a_plain_user_is_not_used(self, sync_db):
        self._add(sync_db, _user("user@test.local", is_admin=False, age_days=900, fred="user-fred"))
        assert macro._get_fred_api_key() is None

    async def test_decrypted_key_never_enters_the_cache(self, sync_db, mem_cache, monkeypatch):
        """K095/X37: der Klartext-Key lag 5 Minuten unter «fred_api_key» in Redis und
        galt dort nach dem Löschen weiter."""
        self._add(sync_db, _user("admin@test.local", is_admin=True, age_days=500, fred="admin-fred"))
        writes: list[tuple] = []
        real_set = cache.set
        monkeypatch.setattr(cache, "set", lambda key, value, *a, **kw: (writes.append((key, value)), real_set(key, value, *a, **kw)))

        assert macro._get_fred_api_key() == "admin-fred"
        assert macro._get_fred_api_key() == "admin-fred"

        assert writes == []
        assert cache.get("fred_api_key") is None

    async def test_changed_key_is_effective_at_once(self, sync_db, mem_cache):
        """X37: ohne Key-Cache gibt es keinen veralteten Eintrag mehr."""
        user, user_settings = _user("admin@test.local", is_admin=True, age_days=500, fred="first")
        self._add(sync_db, (user, user_settings))
        assert macro._get_fred_api_key() == "first"
        user_settings.fred_api_key = None
        sync_db.commit()
        assert macro._get_fred_api_key() is None

    async def test_operator_key_needs_no_database(self, monkeypatch):
        monkeypatch.setattr(settings, "fred_system_api_key", "system-fred")
        assert macro._get_fred_api_key() == "system-fred"

    async def test_database_error_means_no_key(self):
        # Ohne die Fixture sync_db fehlen die Tabellen: der Fehler bleibt im Helfer.
        assert settings_service.get_system_api_key_sync("fred_api_key") is None


class TestEstimateRevisionsKey:
    async def test_job_skips_without_admin_or_system_key(self, db, monkeypatch):
        """K095: der Job lief mit dem Key eines beliebigen Nutzers."""
        await _add(db, _user("user@test.local", is_admin=False, age_days=900, fmp="user-key"))
        universe = AsyncMock(return_value=["AAPL"])
        monkeypatch.setattr(revisions, "_resolve_universe", universe)

        result = await revisions.refresh_estimate_revisions(db)

        assert result["status"] == "no_key"
        universe.assert_not_awaited()

    async def test_job_uses_the_system_key(self, db, monkeypatch):
        await _add(db, _user("admin@test.local", is_admin=True, age_days=500, fmp="admin-key"))
        monkeypatch.setattr(settings, "fmp_system_api_key", "system-fmp")
        monkeypatch.setattr(revisions, "_resolve_universe", AsyncMock(return_value=["AAPL"]))
        fetch = AsyncMock(return_value=None)
        monkeypatch.setattr(revisions, "_fetch_estimate_for_ticker", fetch)

        result = await revisions.refresh_estimate_revisions(db)

        assert result["status"] == "ok"
        fetch.assert_awaited_once_with("AAPL", "system-fmp")


class TestMacroCacheOnKeySave:
    async def _make_admin(self, db, email):
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()

    async def test_plain_user_cannot_clear_the_shared_cache(self, client, mem_cache):
        """K142: jedes Speichern oder Löschen eines FRED-Keys leerte den Makro-Cache aller."""
        token = await register_and_login(client, "fred-user@test.local")
        cache.set("macro_indicators", {"indicators": []}, ttl=900)

        res = await client.put("/api/settings/fred-api-key", json={"api_key": "abc123"}, headers=auth(token))
        assert res.status_code == 200
        assert cache.get("macro_indicators") is not None

        res = await client.delete("/api/settings/fred-api-key", headers=auth(token))
        assert res.status_code == 204
        assert cache.get("macro_indicators") is not None

    async def test_cache_drops_when_the_effective_key_changes(self, client, db, mem_cache):
        token = await register_and_login(client, "fred-admin@test.local")
        await self._make_admin(db, "fred-admin@test.local")

        cache.set("macro_indicators", {"indicators": []}, ttl=900)
        await client.put("/api/settings/fred-api-key", json={"api_key": "admin-key"}, headers=auth(token))
        assert cache.get("macro_indicators") is None

        cache.set("macro_indicators", {"indicators": []}, ttl=900)
        await client.delete("/api/settings/fred-api-key", headers=auth(token))
        assert cache.get("macro_indicators") is None

    async def test_admin_save_changes_nothing_under_an_operator_key(self, client, db, mem_cache, monkeypatch):
        token = await register_and_login(client, "fred-admin2@test.local")
        await self._make_admin(db, "fred-admin2@test.local")
        monkeypatch.setattr(settings, "fred_system_api_key", "system-fred")

        cache.set("macro_indicators", {"indicators": []}, ttl=900)
        await client.put("/api/settings/fred-api-key", json={"api_key": "admin-key"}, headers=auth(token))
        assert cache.get("macro_indicators") is not None


class TestMacroFetchLock:
    async def test_cold_cache_fetches_once_for_parallel_requests(self, mem_cache, monkeypatch):
        """K142: bei kaltem Cache startete jeder gleichzeitige Request alle Abrufe neu."""
        fetches = 0

        async def _shiller():
            nonlocal fetches
            fetches += 1
            await asyncio.sleep(0.05)
            return 31.5

        async def _none(*args, **kwargs):
            return None

        async def _empty(*args, **kwargs):
            return []

        import services.price_service as price_service

        monkeypatch.setattr(macro, "_fetch_lock", asyncio.Lock())  # an den Loop dieses Tests binden
        monkeypatch.setattr(macro, "_get_fred_api_key", lambda: None)
        monkeypatch.setattr(macro, "_scrape_shiller_pe", _shiller)
        monkeypatch.setattr(macro, "_fred_get", _none)
        monkeypatch.setattr(macro, "_fred_get_series", _empty)
        monkeypatch.setattr(price_service, "get_vix", lambda: None)

        results = await asyncio.gather(*(macro.fetch_all_indicators() for _ in range(6)))

        assert fetches == 1
        assert all(r == results[0] for r in results)
        assert results[0]["indicators"][0]["value"] == 31.5

        # Warmer Cache: kein weiterer Abruf, auch ohne Lock-Wartezeit
        await macro.fetch_all_indicators()
        assert fetches == 1


def _ntfy_cfg(server_url: str = "https://ntfy.example.com", **kw) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=kw.get("user_id") or uuid4(), server_url=server_url, topic="topic",
        access_token_encrypted=None, is_enabled=True,
    )


SECRET_URL = "https://alice:s3cr3t-pw@ntfy.example.com:8443/base"


class TestNtfyLogs:
    """K154: die volle Server-URL samt Basic-Auth stand bei jeder Push im Log."""

    def _assert_clean(self, caplog):
        text = caplog.text
        assert "ntfy.example.com" in text
        assert "s3cr3t-pw" not in text and "alice" not in text

    async def test_success_logs_the_host_only(self, caplog):
        resp = MagicMock()
        with caplog.at_level(logging.INFO, logger="services.ntfy_service"), \
             patch.object(ntfy_service, "post_pinned", AsyncMock(return_value=resp)):
            await ntfy_service._send_push_inner(SECRET_URL, "t", "T", "m")
        self._assert_clean(caplog)

    async def test_blocked_push_logs_the_host_only(self, caplog):
        with caplog.at_level(logging.INFO, logger="services.ntfy_service"), \
             patch.object(ntfy_service, "post_pinned", AsyncMock(side_effect=UnsafeUrlError("internal"))):
            await ntfy_service._send_push_inner(SECRET_URL, "t", "T", "m")
            ok, _ = await ntfy_service.send_push_test(_ntfy_cfg(SECRET_URL))
        assert ok is False
        self._assert_clean(caplog)

    async def test_http_error_logs_the_host_only(self, caplog):
        request = httpx.Request("POST", "https://93.184.216.34/")
        error = httpx.HTTPStatusError("503", request=request, response=httpx.Response(503, request=request))
        resp = MagicMock()
        resp.raise_for_status.side_effect = error
        with caplog.at_level(logging.INFO, logger="services.ntfy_service"), \
             patch.object(ntfy_service, "post_pinned", AsyncMock(return_value=resp)):
            await ntfy_service._send_push_inner(SECRET_URL, "t", "T", "m")
        self._assert_clean(caplog)

    async def test_total_timeout_gives_a_clear_message(self):
        with patch.object(ntfy_service, "post_pinned", AsyncMock(side_effect=TimeoutError())):
            ok, message = await ntfy_service.send_push_test(_ntfy_cfg())
        assert ok is False
        assert message.startswith("Zeitüberschreitung")


class TestNtfyUrlWithCredentials:
    async def test_new_config_with_userinfo_is_rejected(self, client, monkeypatch):
        """K154: server_url liegt im Klartext in der DB und kommt in Antworten zurück."""
        from services import url_guard

        monkeypatch.setattr(url_guard, "ensure_public_url", AsyncMock())
        token = await register_and_login(client, "ntfy-userinfo@test.local")

        for url in (SECRET_URL, "https://alice@ntfy.example.com"):
            res = await client.put(
                "/api/settings/ntfy", json={"server_url": url, "topic": "t"}, headers=auth(token),
            )
            assert res.status_code == 422, url
            detail = res.json()["detail"]
            assert detail.startswith("Server-URL darf keine Zugangsdaten")
            assert "s3cr3t-pw" not in detail and "alice" not in detail
        assert (await client.get("/api/settings/ntfy", headers=auth(token))).json()["configured"] is False

        res = await client.put(
            "/api/settings/ntfy",
            json={"server_url": "https://ntfy.example.com:8443/base", "topic": "t"},
            headers=auth(token),
        )
        assert res.status_code == 200

    async def test_stored_config_with_userinfo_keeps_working(self, monkeypatch):
        """Schon gespeicherte URLs mit Zugangsdaten senden weiter (Basic-Auth)."""
        sent = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(ntfy_service, "post_pinned", sent)
        ok, _ = await ntfy_service.send_push_test(_ntfy_cfg(SECRET_URL))
        assert ok is True
        assert sent.await_args.args[0] == SECRET_URL + "/"


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None, **kwargs):
        self.store[key] = value


def _alerts(*tickers: str) -> list[dict]:
    return [{"title": f"{t}: Kurs über CHF 100.00", "message": "m", "severity": "high"} for t in tickers]


@pytest.fixture
def pushes(monkeypatch):
    """Ersetzt den Versand; liefert die Liste der gesendeten Pushes."""
    sent: list[dict] = []

    async def _capture(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(ntfy_service, "_send_push_inner", _capture)
    yield sent
    for task in list(ntfy_service._pending):
        task.cancel()
    ntfy_service._pending.clear()


async def _drain():
    await asyncio.gather(*list(ntfy_service._pending))


class TestPriceAlertAggregateDedup:
    async def test_second_group_of_the_day_is_sent(self, pushes):
        """K046: der Tages-Schlüssel verwarf jede weitere Sammel-Push des Tages —
        Preis-Alarme lösen nur einmal aus, die Meldung war verloren."""
        cfg, redis = _ntfy_cfg(), _FakeRedis()

        ntfy_service.send_push_aggregated(cfg, "price_alert", _alerts("AAPL", "MSFT", "TSLA"), redis_client=redis)
        ntfy_service.send_push_aggregated(cfg, "price_alert", _alerts("NESN", "ROG", "UBSG", "ABBN"), redis_client=redis)
        await _drain()

        assert [p["title"] for p in pushes] == ["3 Preis-Alarme ausgelöst", "4 Preis-Alarme ausgelöst"]

    async def test_same_group_is_sent_once_whatever_the_order(self, pushes):
        cfg, redis = _ntfy_cfg(), _FakeRedis()

        ntfy_service.send_push_aggregated(cfg, "price_alert", _alerts("AAPL", "MSFT", "TSLA"), redis_client=redis)
        ntfy_service.send_push_aggregated(cfg, "price_alert", _alerts("TSLA", "AAPL", "MSFT"), redis_client=redis)
        await _drain()

        assert len(pushes) == 1

    async def test_key_is_per_user_and_holds_no_alert_text(self, pushes):
        cfg_a, cfg_b, redis = _ntfy_cfg(), _ntfy_cfg(), _FakeRedis()

        ntfy_service.send_push_aggregated(cfg_a, "price_alert", _alerts("AAPL", "MSFT", "TSLA"), redis_client=redis)
        ntfy_service.send_push_aggregated(cfg_b, "price_alert", _alerts("AAPL", "MSFT", "TSLA"), redis_client=redis)
        await _drain()

        assert len(pushes) == 2
        assert len(redis.store) == 2
        assert all("AAPL" not in key and date.today().isoformat() not in key for key in redis.store)

    async def test_other_categories_keep_the_daily_key(self, pushes):
        cfg, redis = _ntfy_cfg(), _FakeRedis()

        ntfy_service.send_push_aggregated(cfg, "breakout", _alerts("AAPL", "MSFT", "TSLA"), redis_client=redis)
        ntfy_service.send_push_aggregated(cfg, "breakout", _alerts("NESN", "ROG", "UBSG"), redis_client=redis)
        await _drain()

        assert len(pushes) == 1
        assert f"ntfy_dedup_agg:{cfg.user_id}:breakout:{date.today().isoformat()}" in redis.store


class TestSettingsRouteDuties:
    async def test_api_token_password_check_leaves_the_event_loop(self, client, monkeypatch):
        """K002: bcrypt lief im Loop-Thread und hielt den Worker für die Dauer des Hashes an."""
        from services import auth_service

        threads: list[int] = []
        real = auth_service.verify_password_safe

        def _recording(password, password_hash):
            threads.append(threading.get_ident())
            return real(password, password_hash)

        token = await register_and_login(client, "token-pw@test.local")
        monkeypatch.setattr(auth_service, "verify_password_safe", _recording)

        res = await client.post(
            "/api/settings/api-tokens",
            json={"name": "k", "current_password": "falsch"},
            headers=auth(token),
        )
        assert res.status_code == 401
        res = await client.post(
            "/api/settings/api-tokens",
            json={"name": "k", "current_password": TEST_PASSWORD},
            headers=auth(token),
        )
        assert res.status_code == 201

        assert len(threads) == 2
        assert threading.get_ident() not in threads

    async def test_exports_carry_a_limit(self):
        import main  # noqa: F401 — registriert die Routen am Limiter
        from api.auth import limiter

        for name in ("api.settings.export_portfolio", "api.settings.export_transactions"):
            assert [str(l.limit) for l in limiter._route_limits[name]] == ["5 per 1 minute"], name
