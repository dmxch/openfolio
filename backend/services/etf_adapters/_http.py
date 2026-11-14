"""Geteilter HTTP-Helfer fuer ETF-Holdings-Adapter: keyloser GET/POST mit
Response-Size-Cap.

Die Issuer-Feeds (Excel-Downloads UND JSON) werden ueber httpx GESTREAMT und
beim Ueberschreiten einer Byte-Obergrenze abgebrochen — ein feindlicher oder
kaputter Endpoint (falsches Content-Length, endloser Body) kann den Worker so
nicht per Riesen-Response OOM-en. Reale Holdings-Feeds sind < 5 MiB; die
Default-Obergrenze (64 MiB) ist ein grosszuegiger Backstop, kein enges Limit.

Rueckgabe = die vollen Response-Bytes bei Erfolg, sonst None (Netzwerkfehler /
HTTP != 200 / Content-Length ueber Cap / gestreamter Body ueber Cap). Der
Aufrufer loggt sein Adapter-Label bereits ueber den `adapter`-Parameter, sodass
die Adapter-fetch()-Methoden nur noch `content is None -> return None` pruefen.
"""
from __future__ import annotations

import logging
import zipfile

import httpx

from services.etf_adapters.base import BROWSER_UA

logger = logging.getLogger(__name__)

# Reale Holdings-Feeds sind < 5 MiB; grosszuegiger OOM-Backstop gegen Hostile-/
# Broken-Responses, nicht als funktionales Limit gedacht.
DEFAULT_MAX_BYTES: int = 64 * 1024 * 1024

# Obergrenze fuer EINEN entpackten Eintrag eines fremden ZIP-Archivs. Der Cap in
# capped_request zaehlt nur die uebertragenen Bytes; ein kleines Archiv kann sich
# zu Gigabytes entpacken. Reale Archive (CFTC, SEC) liegen entpackt unter 100 MiB.
DEFAULT_MAX_UNZIPPED_BYTES: int = 256 * 1024 * 1024


async def capped_request(
    method: str,
    url: str,
    *,
    adapter: str,
    ticker: str,
    headers: dict | None = None,
    params: dict | None = None,
    json_body: dict | None = None,
    timeout: float = 60.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    transport: httpx.BaseTransport | None = None,
    meta: dict | None = None,
) -> bytes | None:
    """Streamender GET/POST mit Response-Size-Cap. Siehe Modul-Docstring.

    `transport` ist nur fuer Tests (httpx.MockTransport) gedacht — Produktion
    laesst es None (echter Netzwerk-Transport).

    `meta` (optional) fuellt die Funktion mit `status` und `content_type` der
    Antwort — fuer Diagnose-Logs des Aufrufers, wenn der Body unerwartet aussieht.
    """
    hdrs = {"User-Agent": BROWSER_UA}
    if headers:
        hdrs.update(headers)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, transport=transport
        ) as client:
            async with client.stream(
                method, url, headers=hdrs, params=params, json=json_body
            ) as r:
                if meta is not None:
                    meta["status"] = r.status_code
                    meta["content_type"] = r.headers.get("content-type")
                if r.status_code != 200:
                    logger.warning("%s: HTTP %s fuer %s", adapter, r.status_code, ticker)
                    return None
                # Fruehes Abbrechen, wenn der Server eine ehrliche, zu grosse
                # Content-Length ankuendigt (spart das Herunterladen).
                clen = r.headers.get("content-length")
                if clen is not None:
                    try:
                        if int(clen) > max_bytes:
                            logger.warning(
                                "%s: Response %s B ueber Cap %s B fuer %s (abgebrochen)",
                                adapter, clen, max_bytes, ticker,
                            )
                            return None
                    except (ValueError, TypeError):
                        pass  # unlesbarer Header -> auf die Stream-Zaehlung verlassen
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > max_bytes:
                        logger.warning(
                            "%s: Response-Cap %s B ueberschritten fuer %s (abgebrochen)",
                            adapter, max_bytes, ticker,
                        )
                        return None
                return bytes(buf)
    except Exception as e:
        logger.warning("%s: Fetch fehlgeschlagen fuer %s: %s", adapter, ticker, e)
        return None


async def capped_get(url: str, **kwargs) -> bytes | None:
    """GET-Kurzform von capped_request (siehe dort)."""
    return await capped_request("GET", url, **kwargs)


def read_zip_member_capped(
    zf: zipfile.ZipFile, name: str, *, max_bytes: int = DEFAULT_MAX_UNZIPPED_BYTES,
) -> bytes:
    """Entpackt den Eintrag `name` und wirft ValueError, wenn er groesser als
    `max_bytes` ist.

    Prueft zuerst die im Archiv angekuendigte Groesse (ZipInfo.file_size), bevor
    ein Byte entpackt wird, und liest danach hoechstens `max_bytes` + 1.
    """
    info = zf.getinfo(name)
    if info.file_size > max_bytes:
        raise ValueError(
            f"zip member {name!r} is {info.file_size} bytes unpacked, cap is {max_bytes}"
        )
    with zf.open(info) as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"zip member {name!r} exceeds the unpack cap of {max_bytes} bytes")
    return data
