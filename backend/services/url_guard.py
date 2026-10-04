"""SSRF guard for user-supplied outbound URLs (e.g. ntfy server URL).

Resolves the host and rejects the URL if ANY resolved address is loopback,
private, link-local, reserved, multicast or unspecified (IPv4 + IPv6, including
IPv4-mapped IPv6). Hostnames listed in the operator allowlist
(NTFY_ALLOWED_PRIVATE_HOSTS) are exempt.
"""
import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

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


async def ensure_public_url(url: str) -> None:
    """Raise UnsafeUrlError if the URL host resolves to a non-public address.

    Also raises on resolution failure (fail closed).
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as e:
        raise UnsafeUrlError("invalid url") from e
    if not host:
        raise UnsafeUrlError("missing host")

    if host.lower() in _allowed_hosts():
        return

    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as e:
        raise UnsafeUrlError(f"cannot resolve host: {type(e).__name__}") from e
    if not infos:
        raise UnsafeUrlError("host did not resolve")

    for info in infos:
        addr = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as e:
            raise UnsafeUrlError("unparseable address") from e
        if _is_unsafe_ip(ip):
            raise UnsafeUrlError("host resolves to an internal address")
