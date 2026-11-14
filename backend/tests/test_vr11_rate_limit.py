"""Vollreview 11/2026, Fundament: Client-IP und Rate-Limiter.

K018 (X-Forwarded-For fälschbar), K103 (IPv6 /64), X02 (Zähler je Pfad),
K032 (kein Default-Limit), K074 (Redis-Ausfall macht 500 oder blockiert).
"""

import socket
import time

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request as StarletteRequest

import utils
from constants import limits
from utils import get_client_ip, rate_limit_key


def _request(headers: dict[str, str] | list[tuple[str, str]] | None = None, client=("10.0.0.9", 1234)):
    items = headers.items() if isinstance(headers, dict) else (headers or [])
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in items],
        "client": client,
    }
    return StarletteRequest(scope)


class TestGetClientIp:
    def test_single_value_from_overwriting_proxy(self):
        assert get_client_ip(_request({"X-Forwarded-For": "203.0.113.9"})) == "203.0.113.9"

    def test_spoofed_left_entry_is_ignored(self):
        """Der Kern von K018: ein anhängender Proxy setzt die echte Adresse rechts.
        Vor dem Fix kam hier der linke, vom Client gewählte Wert zurück."""
        req = _request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
        assert get_client_ip(req) == "203.0.113.9"

    def test_rotating_spoof_values_keep_one_key(self):
        keys = {
            rate_limit_key(_request({"X-Forwarded-For": f"10.1.2.{i}, 203.0.113.9"}))
            for i in range(20)
        }
        assert keys == {"203.0.113.9"}

    def test_two_hops(self, monkeypatch):
        monkeypatch.setattr(utils.settings, "trusted_proxy_hops", 2)
        req = _request({"X-Forwarded-For": "6.6.6.6, 198.51.100.7, 172.68.1.1"})
        assert get_client_ip(req) == "198.51.100.7"

    def test_fewer_entries_than_hops_uses_leftmost(self, monkeypatch):
        monkeypatch.setattr(utils.settings, "trusted_proxy_hops", 3)
        req = _request({"X-Forwarded-For": "198.51.100.7, 172.68.1.1"})
        assert get_client_ip(req) == "198.51.100.7"

    @pytest.mark.parametrize("hops", [0, -5])
    def test_hops_below_one_count_as_one(self, monkeypatch, hops):
        monkeypatch.setattr(utils.settings, "trusted_proxy_hops", hops)
        req = _request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
        assert get_client_ip(req) == "203.0.113.9"

    def test_loopback_behind_an_appending_proxy_warns_once(self, monkeypatch, caplog):
        """Abnahme Fixlauf: nginx mit $proxy_add_x_forwarded_for hinter einem lokalen
        Tunnel hängt 127.0.0.1 an. Die Wahl bleibt 127.0.0.1 (der Eintrag links davon
        gilt erst mit TRUSTED_PROXY_HOPS=2), aber der Betreiber erhält eine Warnung."""
        monkeypatch.setattr(utils, "_warned_loopback_client", False)
        req = _request({"X-Forwarded-For": "198.51.100.7, 127.0.0.1"})
        with caplog.at_level("WARNING", logger="utils"):
            assert get_client_ip(req) == "127.0.0.1"
            assert get_client_ip(req) == "127.0.0.1"
        warnings = [r for r in caplog.records if "loopback" in r.getMessage()]
        assert len(warnings) == 1

        monkeypatch.setattr(utils.settings, "trusted_proxy_hops", 2)
        assert get_client_ip(req) == "198.51.100.7"

    def test_single_loopback_entry_does_not_warn(self, monkeypatch, caplog):
        """Ein Aufruf vom Host selbst (Healthcheck) ist kein Konfigurationsfehler."""
        monkeypatch.setattr(utils, "_warned_loopback_client", False)
        with caplog.at_level("WARNING", logger="utils"):
            assert get_client_ip(_request({"X-Forwarded-For": "127.0.0.1"})) == "127.0.0.1"
        assert not [r for r in caplog.records if "loopback" in r.getMessage()]

    @pytest.mark.parametrize("header", [
        "2001:db8:77::5%eth0",
        "2001:db8:77::5%" + "a" * 58,
    ])
    def test_ipv6_zone_is_dropped(self, header):
        """Nachabnahme: Die Zone ist frei wählbarer Text. Mit 58 Zeichen sprengte sie
        die Spalte ip_address (String(45)), der Login endete mit 500."""
        ip = get_client_ip(_request({"X-Forwarded-For": header}))
        assert ip == "2001:db8:77::5"
        assert len(ip) <= 45

    def test_several_header_lines_count_as_one_list(self):
        req = _request([("X-Forwarded-For", "6.6.6.6"), ("X-Forwarded-For", "203.0.113.9")])
        assert get_client_ip(req) == "203.0.113.9"

    def test_invalid_entry_falls_back_to_real_ip(self):
        req = _request({"X-Forwarded-For": "not-an-ip", "X-Real-IP": "198.51.100.20"})
        assert get_client_ip(req) == "198.51.100.20"

    def test_invalid_headers_fall_back_to_peer(self):
        req = _request({"X-Forwarded-For": "<script>", "X-Real-IP": "also bad"})
        assert get_client_ip(req) == "10.0.0.9"

    def test_garbage_peer_host_is_not_a_key(self):
        """uvicorn läuft mit --forwarded-allow-ips "*" und schreibt den linken
        X-Forwarded-For-Eintrag ungeprüft nach request.client.host."""
        req = _request({"X-Forwarded-For": "zufall-123"}, client=("zufall-123", 0))
        assert get_client_ip(req) == "unknown"

    @pytest.mark.parametrize("headers", [{}, {"X-Forwarded-For": ""}, {"X-Forwarded-For": " , ,"}])
    def test_never_empty(self, headers):
        assert get_client_ip(_request(headers, client=None)) == "unknown"
        assert get_client_ip(_request(headers)) == "10.0.0.9"

    def test_ipv6_is_canonicalised(self):
        req = _request({"X-Forwarded-For": "2001:0DB8:0000:0000:0000:0000:0000:0001"})
        assert get_client_ip(req) == "2001:db8::1"


class TestRateLimitKey:
    def test_ipv4_unchanged(self):
        assert rate_limit_key(_request({"X-Forwarded-For": "203.0.113.9"})) == "203.0.113.9"

    def test_ipv6_addresses_of_one_64_share_a_key(self):
        """K103: wer ein /64 besitzt, wechselt sonst nach jedem Limit die Adresse."""
        a = rate_limit_key(_request({"X-Forwarded-For": "2001:db8:1:2::1"}))
        b = rate_limit_key(_request({"X-Forwarded-For": "2001:db8:1:2:ffff:ffff:ffff:ffff"}))
        other = rate_limit_key(_request({"X-Forwarded-For": "2001:db8:1:3::1"}))
        assert a == b == "2001:db8:1:2::/64"
        assert other != a

    def test_ipv4_mapped_ipv6_counts_as_ipv4(self):
        assert rate_limit_key(_request({"X-Forwarded-For": "::ffff:203.0.113.9"})) == "203.0.113.9"

    def test_zone_id_does_not_split_the_key(self):
        a = rate_limit_key(_request({"X-Forwarded-For": "fe80::1%eth0"}))
        b = rate_limit_key(_request({"X-Forwarded-For": "fe80::2%eth1"}))
        assert a == b == "fe80::/64"

    def test_unknown_stays_a_non_empty_key(self):
        assert rate_limit_key(_request({}, client=None)) == "unknown"


# --- Limiter: dieselbe Konstruktion wie in der App, anderer Storage ----------


def _build_app(storage_uri: str):
    from api.auth import build_limiter
    from main import enforce_default_rate_limit

    lim = build_limiter(storage_uri)
    app = FastAPI(dependencies=[Depends(enforce_default_rate_limit)])
    app.state.limiter = lim
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    router = APIRouter(prefix="/r")

    @router.get("/t/{x}")
    @lim.limit("2/minute")
    async def per_ticker(request: Request, x: str):
        return {"x": x}

    @router.get("/plain")
    async def plain():
        return {"ok": True}

    @router.get("/generous")
    @lim.limit("300/minute")
    async def generous(request: Request):
        return {"ok": True}

    @router.get("/exempt")
    @lim.exempt
    async def exempt():
        return {"ok": True}

    @app.get("/direct")
    async def direct():
        return {"ok": True}

    # Wie in main.py: die meisten Routen kommen über include_router.
    app.include_router(router)
    return app, lim


async def _statuses(client: AsyncClient, path: str, n: int) -> list[int]:
    return [(await client.get(path)).status_code for _ in range(n)]


def _default_amount() -> int:
    return int(limits.RL_DEFAULT.split("/")[0])


class TestLimiterConstruction:
    def test_app_limiter_settings(self):
        from api.auth import limiter

        assert limiter._key_func is rate_limit_key
        assert limiter._key_style == "endpoint"
        assert [str(l.limit) for group in limiter._default_limits for l in group] == ["240 per 1 minute"]
        assert limiter._in_memory_fallback_enabled is True
        assert limiter._swallow_errors is False

    def test_storage_options_reach_redis_client(self):
        """K074: slowapi reicht storage_options über limits an redis-py durch."""
        from api.auth import limiter

        kwargs = limiter._storage.storage.connection_pool.connection_kwargs
        assert kwargs["socket_timeout"] == 0.5
        assert kwargs["socket_connect_timeout"] == 0.5

    def test_app_registers_default_limit_and_exemptions(self):
        import main
        from api.auth import limiter

        assert main.enforce_default_rate_limit in [d.dependency for d in main.app.router.dependencies]
        assert main.app.state.limiter is limiter
        assert {
            "main.health",
            "main.composite_scan_health",
            "middleware.metrics.metrics_endpoint",
        } <= limiter._exempt_routes


class TestLimiterBehaviour:
    async def test_path_parameter_values_share_one_counter(self):
        """X02: mit key_style="url" bekam jeder Ticker ein eigenes Budget."""
        app, _ = _build_app("memory://")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = [(await c.get(f"/r/t/TICKER{i}")).status_code for i in range(4)]
        assert codes == [200, 200, 429, 429]

    async def test_clients_have_separate_counters(self):
        app, _ = _build_app("memory://")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            for ip in ("203.0.113.1", "203.0.113.2"):
                codes = [
                    (await c.get(f"/r/t/A{i}", headers={"X-Forwarded-For": ip})).status_code
                    for i in range(3)
                ]
                assert codes == [200, 200, 429]

    @pytest.mark.parametrize("path", ["/r/plain", "/direct"])
    async def test_undecorated_route_gets_default_limit(self, path):
        """K032: gilt auch für Routen aus include_router (/r/plain). Genau die
        liess die SlowAPIMiddleware ohne Limit."""
        app, _ = _build_app("memory://")
        n = _default_amount()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = await _statuses(c, path, n + 2)
        assert codes[:n] == [200] * n
        assert codes[n:] == [429, 429]

    async def test_default_limit_counts_per_route(self):
        app, _ = _build_app("memory://")
        n = _default_amount()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await _statuses(c, "/r/plain", n + 1))[-1] == 429
            assert (await c.get("/direct")).status_code == 200

    async def test_decorated_route_does_not_count_against_default(self):
        app, _ = _build_app("memory://")
        n = _default_amount()
        assert n < 300
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = await _statuses(c, "/r/generous", 300)
            assert codes == [200] * 300
            assert (await c.get("/r/generous")).status_code == 429

    async def test_exempt_route_has_no_limit(self):
        app, _ = _build_app("memory://")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = await _statuses(c, "/r/exempt", _default_amount() + 5)
        assert set(codes) == {200}

    async def test_disabled_limiter_skips_default_limit(self):
        """So behandelt die Suite den Limiter (conftest: limiter.enabled = False)."""
        app, lim = _build_app("memory://")
        lim.enabled = False
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = await _statuses(c, "/r/plain", _default_amount() + 5)
        assert set(codes) == {200}


class TestLimiterStorageOutage:
    async def test_refused_connection_falls_back_to_memory(self):
        """K074: ohne Fallback antwortete jede limitierte Route mit 500."""
        app, lim = _build_app("redis://127.0.0.1:1/0")  # Port 1: niemand hört zu
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            codes = [(await c.get(f"/r/t/A{i}")).status_code for i in range(3)]
            assert codes == [200, 200, 429]  # das Limit gilt weiter, im Speicher
            assert (await c.get("/r/plain")).status_code == 200
        assert lim._storage_dead is True

    async def test_hanging_storage_times_out_instead_of_blocking(self):
        """Ein Redis, das Verbindungen annimmt und nie antwortet: ohne
        socket_timeout wartete der Aufruf im Event-Loop ohne Frist."""
        server = socket.socket()
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(8)  # der Kernel nimmt an, niemand antwortet
            app, lim = _build_app(f"redis://127.0.0.1:{server.getsockname()[1]}/0")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                start = time.monotonic()
                first = await c.get("/r/t/A")
                elapsed = time.monotonic() - start
                assert first.status_code == 200
                # 0.5 s Timeout, dazu höchstens eine Rückfrage an den Storage.
                assert elapsed < 3.0
                assert [(await c.get(f"/r/t/B{i}")).status_code for i in range(2)] == [200, 429]
            assert lim._storage_dead is True
        finally:
            server.close()


class TestRealAppDefaultLimit:
    async def test_route_without_own_limit_returns_429(self, client, monkeypatch):
        """Die echte App: Dependency, Exception-Handler und Middleware-Stapel
        zusammen. Der Zähler läuft im Speicher, damit kein Redis-Stand mitspielt."""
        from limits.storage import MemoryStorage
        from limits.strategies import FixedWindowRateLimiter

        from api.auth import limiter

        res = await client.post(
            "/api/auth/register", json={"email": "rl@test.local", "password": "TestPassw0rd!2026"}
        )
        assert res.status_code == 201
        login = await client.post(
            "/api/auth/login", json={"email": "rl@test.local", "password": "TestPassw0rd!2026"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        storage = MemoryStorage()
        monkeypatch.setattr(limiter, "_storage", storage)
        monkeypatch.setattr(limiter, "_limiter", FixedWindowRateLimiter(storage))
        monkeypatch.setattr(limiter, "_storage_dead", False)
        monkeypatch.setattr(limiter, "enabled", True)

        codes = [
            (await client.get("/api/cache/status", headers=headers)).status_code
            for _ in range(_default_amount() + 1)
        ]
        assert codes[0] == 200
        # Gilt auch, falls die Route später ein eigenes, engeres Limit bekommt.
        assert codes[-1] == 429
        assert set(codes) == {200, 429}

        # Ausgenommen bleibt ausgenommen, auch wenn der Client sein Budget verbraucht hat.
        limited = await client.get("/api/cache/status", headers=headers)
        assert limited.status_code == 429
        assert "error" in limited.json()
        assert (await client.get("/api/health/composite-scan")).status_code == 200
