"""Vollreview 11/2026, Fixer smtp: url_guard.

K003/X28 (DNS mit Zeitlimit, ohne den Event-Loop zu blockieren), K092 (Socket zur
geprüften IP), X06/K030 (post_pinned liest den Body nie).

Kein echtes Netz: die Namensauflösung ist ersetzt, Verbindungen gehen nur an
einen Server auf der Loopback-Adresse dieses Prozesses.
"""

import asyncio
import socket
import time

import httpx
import pytest

from services import url_guard
from services.url_guard import (
    UnresolvableHostError,
    UnsafeUrlError,
    open_pinned_socket,
    post_pinned,
    resolve_checked_addrs,
)

pytestmark = pytest.mark.asyncio


def _fake_dns(monkeypatch, *answers, delay: float = 0.0, error: BaseException | None = None):
    """Ersetzt socket.getaddrinfo, das loop.getaddrinfo im Executor aufruft.

    ``answers``: je Aufruf eine Adressliste; die letzte gilt für alle weiteren.
    Liefert die Liste der angefragten Hostnamen.
    """
    calls: list[str] = []

    def _getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        if delay:
            time.sleep(delay)
        if error is not None:
            raise error
        addrs = answers[min(len(calls), len(answers)) - 1]
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port or 0))
            for a in addrs
        ]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    return calls


async def _listen(host: str = "127.0.0.1"):
    """Server auf der Loopback-Adresse; liefert (server, port, Liste der Peers)."""
    peers: list[tuple] = []

    async def _handle(reader, writer):
        peers.append(writer.get_extra_info("sockname"))
        writer.close()

    server = await asyncio.start_server(_handle, host, 0)
    return server, server.sockets[0].getsockname()[1], peers


class TestResolveCheckedAddrs:
    async def test_slow_nameserver_does_not_block_the_event_loop(self, monkeypatch):
        """K003: die Auflösung läuft im Executor, der Loop bedient andere Requests weiter."""
        _fake_dns(monkeypatch, ["93.184.216.34"], delay=0.3)
        ticks = 0

        async def _ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        ticker = asyncio.create_task(_ticker())
        try:
            addrs = await resolve_checked_addrs("slow.example.org", None)
        finally:
            ticker.cancel()
        assert addrs == [(socket.AF_INET, "93.184.216.34")]
        assert ticks >= 5

    async def test_silent_nameserver_is_cut_off(self, monkeypatch):
        """K003: ein Nameserver ohne Antwort kostet höchstens das Zeitlimit."""
        _fake_dns(monkeypatch, ["93.184.216.34"], delay=0.5)
        started = time.monotonic()
        with pytest.raises(UnresolvableHostError):
            await resolve_checked_addrs("dead.example.org", None, timeout=0.05)
        assert time.monotonic() - started < 0.4

    async def test_default_limit_is_three_seconds(self):
        assert url_guard.RESOLVE_TIMEOUT == 3.0

    @pytest.mark.parametrize("error", [
        socket.gaierror("nope"),
        UnicodeError("label empty or too long"),
        OSError("resolver broken"),
    ])
    async def test_resolver_errors_are_one_error_type(self, monkeypatch, error):
        _fake_dns(monkeypatch, [], error=error)
        with pytest.raises(UnresolvableHostError):
            await resolve_checked_addrs("x.example.org", None)

    async def test_empty_label_needs_no_mock(self):
        """X28: «a..b» scheitert im IDNA-Codec, noch vor jeder DNS-Anfrage."""
        with pytest.raises(UnresolvableHostError):
            await resolve_checked_addrs("a..b", None)

    @pytest.mark.parametrize("addr", ["100.64.0.1", "10.0.0.5", "127.0.0.1", "169.254.169.254", "::1"])
    async def test_internal_address_is_rejected(self, monkeypatch, addr):
        """K092: auch 100.64.0.0/10 (CGNAT, Tailscale) gilt als intern."""
        _fake_dns(monkeypatch, [addr])
        with pytest.raises(UnsafeUrlError) as exc:
            await resolve_checked_addrs("smtp.example.org", 587)
        assert not isinstance(exc.value, UnresolvableHostError)

    async def test_one_internal_address_among_public_ones_is_enough(self, monkeypatch):
        _fake_dns(monkeypatch, ["93.184.216.34", "10.0.0.5"])
        with pytest.raises(UnsafeUrlError):
            await resolve_checked_addrs("smtp.example.org", 587)


class TestOpenPinnedSocket:
    async def test_connects_to_the_checked_address_and_resolves_once(self, monkeypatch):
        """K092: nach der Prüfung zeigt der Name woanders hin (Rebinding) — die
        Verbindung geht trotzdem an die geprüfte Adresse, ohne zweite Auflösung."""
        server, port, peers = await _listen()
        calls = _fake_dns(monkeypatch, ["127.0.0.1"], ["127.0.0.2"])
        monkeypatch.setattr(url_guard, "_is_unsafe_ip", lambda ip: False)
        try:
            sock = await open_pinned_socket("smtp.example.org", port)
            try:
                assert sock.getpeername() == ("127.0.0.1", port)
            finally:
                sock.close()
        finally:
            server.close()
            await server.wait_closed()
        assert calls == ["smtp.example.org"]

    async def test_internal_address_opens_no_connection(self, monkeypatch):
        server, port, peers = await _listen()
        _fake_dns(monkeypatch, ["127.0.0.1"])
        try:
            with pytest.raises(UnsafeUrlError):
                await open_pinned_socket("smtp.example.org", port)
            await asyncio.sleep(0.05)
        finally:
            server.close()
            await server.wait_closed()
        assert peers == []

    async def test_ntfy_allowlist_does_not_apply(self, monkeypatch):
        """Die Freigabe interner ntfy-Hosts öffnet keinen SMTP-Weg ins interne Netz."""
        from config import settings

        _fake_dns(monkeypatch, ["172.18.0.5"])
        monkeypatch.setattr(settings, "ntfy_allowed_private_hosts", "ntfy")
        with pytest.raises(UnsafeUrlError):
            await open_pinned_socket("ntfy", 25)

    async def test_falls_back_to_the_next_checked_address(self, monkeypatch):
        server, port, _ = await _listen("127.0.0.1")
        _fake_dns(monkeypatch, ["127.0.0.2", "127.0.0.1"])  # auf .2 hört niemand
        monkeypatch.setattr(url_guard, "_is_unsafe_ip", lambda ip: False)
        try:
            sock = await open_pinned_socket("smtp.example.org", port)
            try:
                assert sock.getpeername()[0] == "127.0.0.1"
            finally:
                sock.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_refused_connection_is_an_oserror(self, monkeypatch):
        server, port, _ = await _listen()
        server.close()
        await server.wait_closed()  # Port ist jetzt frei, niemand hört
        _fake_dns(monkeypatch, ["127.0.0.1"])
        monkeypatch.setattr(url_guard, "_is_unsafe_ip", lambda ip: False)
        with pytest.raises(OSError) as exc:
            await open_pinned_socket("smtp.example.org", port)
        assert not isinstance(exc.value, UnsafeUrlError)


class _Body(httpx.AsyncByteStream):
    """Antwort-Body, der mitzählt, ob ihn jemand liest."""

    def __init__(self):
        self.chunks_read = 0
        self.closed = False

    async def __aiter__(self):
        self.chunks_read += 1
        yield b"\x1f\x8b" + b"\x00" * 1024

    async def aclose(self):
        self.closed = True


def _mock_transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        url_guard.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


class TestPostPinnedBody:
    async def test_body_is_never_read(self, monkeypatch):
        """X06: 100 kB gzip wurden zu 100 MB im Speicher. Der Body bleibt jetzt liegen."""
        _fake_dns(monkeypatch, ["93.184.216.34"])
        body = _Body()
        seen = {}

        def handler(request):
            seen["accept_encoding"] = request.headers.get("accept-encoding")
            return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=body)

        _mock_transport(monkeypatch, handler)
        resp = await post_pinned("https://ntfy.example.com/", json={"a": 1})

        assert resp.status_code == 200
        assert resp.reason_phrase == "OK"
        assert body.chunks_read == 0
        assert body.closed is True
        assert resp.is_closed
        # K030: keine komprimierte Antwort anfordern, die Decoder bleiben aussen vor
        assert seen["accept_encoding"] == "identity"

    async def test_caller_cannot_ask_for_compression(self, monkeypatch):
        _fake_dns(monkeypatch, ["93.184.216.34"])
        seen = {}

        def handler(request):
            seen["accept_encoding"] = request.headers.get_list("accept-encoding")
            return httpx.Response(200)

        _mock_transport(monkeypatch, handler)
        await post_pinned("https://ntfy.example.com/", headers={"accept-encoding": "br, gzip"})
        assert seen["accept_encoding"] == ["identity"]

    async def test_error_status_still_raises_for_callers(self, monkeypatch):
        """Die Aufrufer brauchen nur Status und reason_phrase — beides ohne Body."""
        _fake_dns(monkeypatch, ["93.184.216.34"])
        body = _Body()
        _mock_transport(monkeypatch, lambda request: httpx.Response(403, stream=body))
        resp = await post_pinned("https://ntfy.example.com/")
        with pytest.raises(httpx.HTTPStatusError) as exc:
            resp.raise_for_status()
        assert exc.value.response.status_code == 403
        assert exc.value.response.reason_phrase == "Forbidden"
        assert body.chunks_read == 0

    async def test_total_time_is_bounded(self, monkeypatch):
        """X06: das httpx-Zeitlimit gilt je Leseschritt, nicht für den ganzen Aufruf."""
        _fake_dns(monkeypatch, ["93.184.216.34"])

        async def handler(request):
            await asyncio.sleep(5)
            return httpx.Response(200)

        _mock_transport(monkeypatch, handler)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await post_pinned("https://ntfy.example.com/", total_timeout=0.05)
        assert time.monotonic() - started < 2

    async def test_default_total_limit_is_ten_seconds(self):
        assert url_guard.POST_TOTAL_TIMEOUT == 10.0
