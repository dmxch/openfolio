"""SSRF guard for user-supplied outbound URLs (e.g. ntfy server URL).

Resolves the host and rejects the URL if ANY resolved address is loopback,
private, link-local, reserved, multicast or unspecified (IPv4 + IPv6, including
IPv4-mapped IPv6). Hostnames listed in the operator allowlist
(NTFY_ALLOWED_PRIVATE_HOSTS) are exempt from the IP check (but still pinned).

To defeat DNS rebinding, senders must use ``post_pinned``: it resolves ONCE, checks all
addresses and connects to the checked IP (Host header + TLS SNI keep the hostname).
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


class UnsafeUrlError(ValueError):
    """URL points to an internal/unsafe address or cannot be resolved."""


def _allowed_hosts() -> set[str]:
    raw = getattr(settings, "ntfy_allowed_private_hosts", "") or ""
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


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

    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as e:
        raise UnsafeUrlError(f"cannot resolve host: {type(e).__name__}") from e
    if not infos:
        raise UnsafeUrlError("host did not resolve")

    allowed = host.lower() in _allowed_hosts()
    addrs: list[str] = []
    for info in infos:
        addr = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as e:
            raise UnsafeUrlError("unparseable address") from e
        if not allowed and _is_unsafe_ip(ip):
            raise UnsafeUrlError("host resolves to an internal address")
        addrs.append(addr)

    path_query = parts.path or "/"
    if parts.query:
        path_query += "?" + parts.query
    userinfo = None
    if parts.username is not None:
        userinfo = (unquote(parts.username), unquote(parts.password or ""))
    return PinnedTarget(scheme, host, port, addrs[0], path_query, userinfo)


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
) -> httpx.Response:
    """POST to ``url`` connecting to the once-resolved, validated IP (anti DNS-rebinding).

    The request URL carries the IP; ``Host`` header and (https) TLS SNI /
    certificate verification use the original hostname. No redirects.
    """
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
    req_headers = dict(headers or {})
    req_headers["Host"] = host_header
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
        return await client.post(
            pinned_url, json=json, headers=req_headers, extensions=extensions, auth=auth
        )
