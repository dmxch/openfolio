import ipaddress
import logging

from fastapi import Request

from config import settings

logger = logging.getLogger(__name__)

# Einmal je Prozess warnen, nicht bei jedem Request.
_warned_loopback_client = False


def _valid_ip(value: str | None) -> str | None:
    """Return the canonical form of an IP address, or None if value is not one."""
    if not value:
        return None
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if addr.version == 6 and addr.scope_id is not None:
        # Zone-ID (fe80::1%eth0) verwerfen: sie ist frei wählbarer Text und passt
        # nicht in die Spalten für IP-Adressen (String(45)).
        addr = ipaddress.IPv6Address(int(addr))
    return str(addr)


def _warn_if_loopback(ip: str, entry_count: int, hops: int) -> None:
    """Warnt, wenn die gewählte Client-IP eine Loopback-Adresse ist.

    Links davon stehen weitere Einträge: Ein Proxy auf demselben Host hat seine
    Gegenstelle angehängt (nginx mit ``$proxy_add_x_forwarded_for`` hinter einem
    Cloudflare-Tunnel). Dann tragen alle Besucher dieselbe Adresse und teilen
    sich jedes Rate-Limit. Die Wahl bleibt trotzdem stehen: der Eintrag links
    davon gilt nur, wenn der Betreiber TRUSTED_PROXY_HOPS erhöht.
    """
    global _warned_loopback_client
    if _warned_loopback_client or not ipaddress.ip_address(ip).is_loopback:
        return
    _warned_loopback_client = True
    logger.warning(
        "Client IP resolves to loopback %s although X-Forwarded-For has %d entries "
        "(TRUSTED_PROXY_HOPS=%d). All visitors share one rate limit. Let the proxy "
        "overwrite X-Forwarded-For with the visitor address. Raise TRUSTED_PROXY_HOPS "
        "only if every request passes all proxies.",
        ip, entry_count, hops,
    )


def get_client_ip(request: Request) -> str:
    """Client-IP hinter den vertrauten Reverse-Proxys. Nie leer: IP oder "unknown".

    Aus X-Forwarded-For zählt der Eintrag, den der letzte vertraute Proxy gesetzt
    hat: Position ``trusted_proxy_hops`` von rechts. Alles links davon stammt vom
    Client und ist frei wählbar. Hat die Liste weniger Einträge, gilt der linke.

    Jeder Kandidat muss eine gültige IP sein. Das gilt auch für
    request.client.host: uvicorn läuft mit ``--forwarded-allow-ips "*"`` und
    übernimmt dort den linken X-Forwarded-For-Eintrag ungeprüft.
    """
    # Mehrere Header-Zeilen sind gleichbedeutend mit einer kommagetrennten Liste.
    entries = [e.strip() for e in ",".join(request.headers.getlist("X-Forwarded-For")).split(",")]
    entries = [e for e in entries if e]
    if entries:
        hops = max(1, settings.trusted_proxy_hops)
        index = max(0, len(entries) - hops)
        ip = _valid_ip(entries[index])
        if ip:
            if index > 0:
                _warn_if_loopback(ip, len(entries), hops)
            return ip
    ip = _valid_ip(request.headers.get("X-Real-IP"))
    if ip:
        return ip
    ip = _valid_ip(request.client.host if request.client else None)
    return ip or "unknown"


def rate_limit_key(request: Request) -> str:
    """Schlüssel des Rate-Limiters: Client-IP, IPv6 auf das /64-Netz gekürzt.

    Ein IPv6-Anschluss verfügt über mindestens ein ganzes /64. Ohne die Kürzung
    hätte jede der 2^64 Adressen darin ein eigenes Limit.
    """
    ip = get_client_ip(request)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip  # "unknown"
    if addr.version == 6:
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        # Über den Integer-Wert kürzen: das verwirft auch eine Zone-ID (fe80::1%eth0).
        return f"{ipaddress.IPv6Address((int(addr) >> 64) << 64)}/64"
    return ip
