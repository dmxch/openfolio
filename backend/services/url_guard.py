"""SSRF guard for user-supplied outbound targets (ntfy server URL, SMTP host).

Resolves the host and rejects the target if ANY resolved address is loopback,
private, link-local, reserved, multicast or unspecified (IPv4 + IPv6, including
IPv4-mapped IPv6). Hostnames listed in the operator allowlist of the channel
(NTFY_ALLOWED_PRIVATE_HOSTS for ntfy, SMTP_ALLOWED_PRIVATE_HOSTS for SMTP) are
exempt from the IP check (but still pinned). The two lists are separate: a
host released for ntfy is not released for SMTP.

To defeat DNS rebinding, senders must use ``post_pinned`` (HTTP) or
``open_pinned_socket`` (other protocols, e.g. SMTP): both resolve ONCE, check all
addresses and connect to the checked IP (Host header / TLS SNI keep the hostname).
"""
import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import httpx

from config import settings

logger = logging.getLogger(__name__)


# The host is user-chosen: a silent nameserver or a slow server must not hold a
# request or a worker job for long.
RESOLVE_TIMEOUT = 3.0
POST_TOTAL_TIMEOUT = 10.0


class UnsafeUrlError(ValueError):
    """URL points to an internal/unsafe address or cannot be resolved."""


class UnresolvableHostError(UnsafeUrlError):
    """Host could not be resolved (DNS failure, timeout or invalid name)."""


def _split_hosts(raw: str | None) -> set[str]:
    return {h.strip().lower() for h in (raw or "").split(",") if h.strip()}


def _allowed_hosts() -> set[str]:
    return _split_hosts(getattr(settings, "ntfy_allowed_private_hosts", ""))


def is_smtp_private_host_allowed(host: str) -> bool:
    """True if the operator released ``host`` for user SMTP configs
    (SMTP_ALLOWED_PRIVATE_HOSTS: comma-separated, exact, case-insensitive)."""
    allowed = _split_hosts(getattr(settings, "smtp_allowed_private_hosts", ""))
    return (host or "").strip().lower() in allowed


def _is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


@dataclass(frozen=True)
class PinnedTarget:
    """A URL whose host was resolved and checked once; connect to ``ip``."""
    scheme: str
    host: str
    port: int
    ip: str
    path_query: str
    userinfo: tuple[str, str] | None = None


def _fmt_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


async def resolve_checked_addrs(
    host: str,
    port: int | None,
    *,
    allow_internal: bool = False,
    timeout: float = RESOLVE_TIMEOUT,
) -> list[tuple[int, str]]:
    """Resolve ``host`` once within ``timeout`` and validate ALL addresses.

    Returns ``(family, address)`` pairs in resolver order. Raises
    UnresolvableHostError on DNS failure, timeout or an invalid name, and
    UnsafeUrlError if any address is not public (unless ``allow_internal``).
    """
    try:
        loop = asyncio.get_running_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout
        )
    # TimeoutError is an OSError; UnicodeError comes from the IDNA codec ("a..b").
    except (socket.gaierror, UnicodeError, OSError) as e:
        raise UnresolvableHostError(f"cannot resolve host: {type(e).__name__}") from e
    if not infos:
        raise UnresolvableHostError("host did not resolve")

    addrs: list[tuple[int, str]] = []
    for info in infos:
        addr = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as e:
            raise UnsafeUrlError("unparseable address") from e
        if not allow_internal and _is_unsafe_ip(ip):
            raise UnsafeUrlError("host resolves to an internal address")
        addrs.append((info[0], addr))
    return addrs


async def resolve_public_target(url: str) -> PinnedTarget:
    """Resolve once, validate ALL addresses, return the first as pinned target.

    Raises UnsafeUrlError on invalid URL, resolution failure or any non-public
    address (allowlisted hosts skip the IP check but are still pinned).
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        scheme = parts.scheme.lower()
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise UnsafeUrlError("invalid url") from e
    if scheme not in ("http", "https"):
        raise UnsafeUrlError("unsupported scheme")
    if not host:
        raise UnsafeUrlError("missing host")

    allowed = host.lower() in _allowed_hosts()
    addrs = await resolve_checked_addrs(host, port, allow_internal=allowed)

    path_query = parts.path or "/"
    if parts.query:
        path_query += "?" + parts.query
    userinfo = None
    if parts.username is not None:
        userinfo = (unquote(parts.username), unquote(parts.password or ""))
    return PinnedTarget(scheme, host, port, addrs[0][1], path_query, userinfo)


async def open_pinned_socket(
    host: str, port: int, *, timeout: float = 10.0, allow_internal: bool = False
) -> socket.socket:
    """Open a TCP connection to ``host:port`` on a once-resolved, validated public IP.

    For protocols without an HTTP client (SMTP): the caller hands the connected
    socket to its library and keeps ``host`` for TLS. Resolving once and connecting
    to the checked address defeats DNS rebinding. No allowlist is read here: the
    caller passes ``allow_internal=True`` for a host its own allowlist releases
    (SMTP: ``is_smtp_private_host_allowed``). The connection is pinned either way.

    Raises UnsafeUrlError (unresolvable or internal address) or OSError (connect
    failed or took longer than ``timeout`` over all addresses).
    """
    addrs = await resolve_checked_addrs(host, port, allow_internal=allow_internal)
    loop = asyncio.get_running_loop()
    last_error: OSError | None = None
    async with asyncio.timeout(timeout):
        for family, addr in addrs:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setblocking(False)
            try:
                await loop.sock_connect(sock, (addr, port))
            except OSError as e:
                sock.close()
                last_error = e
            except BaseException:
                sock.close()
                raise
            else:
                return sock
    raise last_error or OSError("no address to connect to")


async def ensure_public_url(url: str) -> None:
    """Raise UnsafeUrlError if the URL host resolves to a non-public address.

    Also raises on resolution failure (fail closed). Storage-time check only;
    senders must use ``post_pinned``.
    """
    try:
        host = urlsplit(url).hostname
    except ValueError as e:
        raise UnsafeUrlError("invalid url") from e
    if host and host.lower() in _allowed_hosts():
        return
    await resolve_public_target(url)


async def post_pinned(
    url: str,
    *,
    json: object = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
    total_timeout: float = POST_TOTAL_TIMEOUT,
) -> httpx.Response:
    """POST to ``url`` connecting to the once-resolved, validated IP (anti DNS-rebinding).

    The request URL carries the IP; ``Host`` header and (https) TLS SNI /
    certificate verification use the original hostname. No redirects.

    The response body is NEVER read: the server is user-chosen, and a few kB of
    compressed body expand to gigabytes in memory. The returned response is closed;
    only status code, reason phrase and headers are usable. ``timeout`` bounds each
    network phase, ``total_timeout`` the whole call (TimeoutError).
    """
    async with asyncio.timeout(total_timeout):
        target = await resolve_public_target(url)
        default_port = 443 if target.scheme == "https" else 80
        try:
            # IDN hosts: Host header and SNI must be ASCII (punycode)
            ascii_host = target.host.encode("idna").decode("ascii")
        except UnicodeError as e:
            raise UnsafeUrlError("invalid hostname") from e
        host_header = _fmt_host(ascii_host)
        if target.port != default_port:
            host_header += f":{target.port}"
        pinned_url = f"{target.scheme}://{_fmt_host(target.ip)}:{target.port}{target.path_query}"
        req_headers = {
            k: v for k, v in (headers or {}).items() if k.lower() != "accept-encoding"
        }
        req_headers["Host"] = host_header
        # No compressed answers: keeps the decoders (brotli, zstd, gzip) out of reach.
        req_headers["Accept-Encoding"] = "identity"
        extensions = {"sni_hostname": ascii_host} if target.scheme == "https" else {}
        # Userinfo in the URL (https://user:pw@host) was httpx BasicAuth before pinning;
        # keep it, unless an explicit Authorization header (access token) is set.
        auth = None
        if target.userinfo and not any(k.lower() == "authorization" for k in req_headers):
            auth = httpx.BasicAuth(*target.userinfo)
        # One client per call (never share: a pool keyed by IP could reuse a connection
        # established with another SNI). trust_env=False: a proxy would resolve the
        # target itself and ignore sni_hostname, breaking the pin.
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                "POST", pinned_url, json=json, headers=req_headers, extensions=extensions, auth=auth
            ) as resp:
                return resp
