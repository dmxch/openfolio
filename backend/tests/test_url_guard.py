"""SSRF guard (url_guard) + ntfy send paths + currency-mismatch user isolation."""
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from config import settings
from services import ntfy_service, url_guard
from services.alert_service import generate_alerts
from services.url_guard import UnsafeUrlError, ensure_public_url


def _mock_dns(monkeypatch, *addrs: str):
    infos = [
        (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443))
        for a in addrs
    ]

    class _Loop:
        async def getaddrinfo(self, host, port, **kw):
            return infos

    monkeypatch.setattr(url_guard.asyncio, "get_running_loop", lambda: _Loop())


@pytest.mark.asyncio
@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.1.2.3", "192.168.1.5", "169.254.169.254", "::1",
    "::ffff:127.0.0.1", "0.0.0.0", "172.16.0.1", "fe80::1", "224.0.0.1",
])
async def test_blocks_internal(monkeypatch, addr):
    _mock_dns(monkeypatch, addr)
    with pytest.raises(UnsafeUrlError):
        await ensure_public_url("https://ntfy.example.com/")


@pytest.mark.asyncio
async def test_allows_public(monkeypatch):
    _mock_dns(monkeypatch, "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")
    await ensure_public_url("https://ntfy.example.com/")


@pytest.mark.asyncio
async def test_mixed_resolution_blocked(monkeypatch):
    _mock_dns(monkeypatch, "93.184.216.34", "10.0.0.5")
    with pytest.raises(UnsafeUrlError):
        await ensure_public_url("https://ntfy.example.com/")


@pytest.mark.asyncio
async def test_allowlist_permits_private(monkeypatch):
    _mock_dns(monkeypatch, "172.18.0.5")
    monkeypatch.setattr(settings, "ntfy_allowed_private_hosts", "Ntfy, other")
    await ensure_public_url("http://ntfy:80")
    with pytest.raises(UnsafeUrlError):
        await ensure_public_url("http://ntfy2:80")


@pytest.mark.asyncio
async def test_resolution_failure_blocked(monkeypatch):
    class _Loop:
        async def getaddrinfo(self, *a, **kw):
            raise socket.gaierror("nope")

    monkeypatch.setattr(url_guard.asyncio, "get_running_loop", lambda: _Loop())
    with pytest.raises(UnsafeUrlError):
        await ensure_public_url("https://nonexistent.invalid/")


@pytest.mark.asyncio
async def test_send_inner_blocks_at_send_time(monkeypatch):
    _mock_dns(monkeypatch, "127.0.0.1")
    called = []

    class _Client:
        def __init__(self, *a, **kw):
            called.append(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            called.append("post")

    monkeypatch.setattr(ntfy_service.httpx, "AsyncClient", _Client)
    await ntfy_service._send_push_inner("https://rebind.example.com", "t", "T", "m")
    assert called == []


@pytest.mark.asyncio
async def test_send_test_push_blocked_and_no_redirects(monkeypatch):
    from types import SimpleNamespace
    cfg = SimpleNamespace(server_url="https://rebind.example.com", topic="t",
                          access_token_encrypted=None)
    _mock_dns(monkeypatch, "10.0.0.1")
    ok, err = await ntfy_service.send_push_test(cfg)
    assert not ok and "interne Adresse" in err

    _mock_dns(monkeypatch, "93.184.216.34")
    seen = {}

    class _Client:
        def __init__(self, *a, **kw):
            seen.update(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return httpx.Response(200, request=httpx.Request("POST", "https://x/"))

    monkeypatch.setattr(ntfy_service.httpx, "AsyncClient", _Client)
    ok, _ = await ntfy_service.send_push_test(cfg)
    assert ok and seen["follow_redirects"] is False


def _positions():
    return [{"ticker": "AAA", "market_value_chf": 1000.0, "type": "stock", "weight_pct": 5}]


def test_currency_mismatch_only_for_owner(monkeypatch):
    from services import alert_service
    mm = [{"user_id": "user-b", "ticker": "XYZ", "yf_ticker": "XYZ",
           "pos_currency": "CAD", "yf_currency": "USD"},
          {"ticker": "OLD", "yf_ticker": "OLD", "pos_currency": "CAD", "yf_currency": "USD"}]
    monkeypatch.setattr(alert_service.cache, "get",
                        lambda k, *a, **kw: mm if k == "currency_mismatches" else None)

    def cats(uid):
        return [a for a in generate_alerts(_positions(), None, {}, user_id=uid)
                if a["category"] == "currency_mismatch"]

    assert cats("user-a") == []
    assert cats(None) == []
    b = cats("user-b")
    assert len(b) == 1 and b[0]["ticker"] == "XYZ"
