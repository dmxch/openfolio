"""Unit-Tests fuer den geteilten Cap-HTTP-Helfer (_http.capped_request):

Response-Size-Cap gegen OOM durch feindliche/kaputte Feeds — ohne echtes Netz
(httpx.MockTransport). Geprueft: Body-Rueckgabe bei 200, None bei HTTP!=200,
Content-Length-frueh-Abbruch, gestreamter Ueberlauf, Netzwerkfehler, POST-Body.
"""
import httpx

from services.etf_adapters._http import capped_get, capped_request
from services.etf_adapters.base import BROWSER_UA


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_returns_body_on_200():
    out = await capped_get(
        "https://x/y", adapter="t", ticker="T",
        transport=_transport(lambda req: httpx.Response(200, content=b"hello-world")),
    )
    assert out == b"hello-world"


async def test_non_200_returns_none():
    out = await capped_get(
        "https://x/y", adapter="t", ticker="T",
        transport=_transport(lambda req: httpx.Response(404, content=b"nope")),
    )
    assert out is None


async def test_content_length_over_cap_returns_none():
    # MockTransport setzt content-length automatisch aus dem content -> Frueh-Abbruch.
    out = await capped_get(
        "https://x/y", adapter="t", ticker="T", max_bytes=10,
        transport=_transport(lambda req: httpx.Response(200, content=b"x" * 100)),
    )
    assert out is None


async def test_streamed_body_over_cap_returns_none():
    # Ohne Content-Length greift der Cap erst waehrend der Byte-Akkumulation.
    def handler(req):
        r = httpx.Response(200, content=b"x" * 100)
        r.headers.pop("content-length", None)
        return r

    out = await capped_get(
        "https://x/y", adapter="t", ticker="T", max_bytes=10,
        transport=_transport(handler),
    )
    assert out is None


async def test_body_at_cap_boundary_passes():
    # Genau max_bytes ist noch erlaubt (Cap greift erst bei > max_bytes).
    out = await capped_get(
        "https://x/y", adapter="t", ticker="T", max_bytes=100,
        transport=_transport(lambda req: httpx.Response(200, content=b"x" * 100)),
    )
    assert out == b"x" * 100


async def test_network_error_returns_none():
    def handler(req):
        raise httpx.ConnectError("boom")

    out = await capped_get(
        "https://x/y", adapter="t", ticker="T", transport=_transport(handler),
    )
    assert out is None


async def test_post_sends_json_body_and_merges_headers():
    seen: dict = {}

    def handler(req):
        seen["method"] = req.method
        seen["body"] = req.content
        seen["headers"] = req.headers
        return httpx.Response(200, content=b"{}")

    out = await capped_request(
        "POST", "https://x/y", adapter="t", ticker="T",
        json_body={"productIds": ["IE00BJ0KDQ92"]},
        headers={"Accept": "application/json"},  # Caller-Header -> Merge-Pfad
        transport=_transport(handler),
    )
    assert out == b"{}"
    assert seen["method"] == "POST"
    assert b"IE00BJ0KDQ92" in seen["body"]
    # Der BROWSER_UA-Seed ist load-bearing (Issuer-WAFs 403en Default-UAs) und muss
    # trotz Caller-Headern erhalten bleiben; der Caller-Header wird zusaetzlich gemergt.
    assert seen["headers"]["user-agent"] == BROWSER_UA
    assert seen["headers"]["accept"] == "application/json"


async def test_get_seeds_browser_ua_and_forwards_params():
    seen: dict = {}

    def handler(req):
        seen["ua"] = req.headers.get("user-agent")
        seen["url"] = str(req.url)
        return httpx.Response(200, content=b"ok")

    out = await capped_get(
        "https://x/y", adapter="t", ticker="T",
        params={"cusip": "IE00BJ0KDQ92"}, transport=_transport(handler),
    )
    assert out == b"ok"
    assert seen["ua"] == BROWSER_UA                 # UA auch ohne Caller-Header gesetzt
    assert "cusip=IE00BJ0KDQ92" in seen["url"]      # params an client.stream durchgereicht
