"""Integration tests for GET /api/v1/external/macro/ch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from services import cache
from tests.test_external_api import api_auth, create_api_token, register_and_login

pytestmark = pytest.mark.asyncio


_MOCK_SNAPSHOT = {
    "as_of": "2026-04-08T12:00:00",
    "snb": {
        "policy_rate_pct": 0.5,
        "policy_rate_changed_on": "2025-12-12",
        "next_meeting": "2026-06-19",
    },
    "saron": {
        "current_pct": 0.45,
        "as_of": "2026-04-08",
        "delta_30d_bps": -2.0,
        "trend": "stable",
    },
    "fx": {
        "chf_eur": {"rate": 1.0512, "as_of": "2026-04-08", "delta_30d_pct": 0.4, "trend": "chf_stronger"},
        "chf_usd": {"rate": 1.1234, "as_of": "2026-04-08", "delta_30d_pct": -0.1, "trend": "stable"},
    },
    "ch_inflation": {
        "cpi_yoy_pct": 1.2,
        "cpi_as_of": "2026-03-01",
        "core_cpi_yoy_pct": None,
    },
    "ch_rates": {
        "eidg_10y_yield_pct": 0.48,
        "delta_30d_bps": 3.0,
        "trend": "stable",
    },
    "smi_vs_sp500_30d": {
        "smi_return_pct": 2.1,
        "sp500_return_pct": 1.4,
        "relative_pct": 0.7,
    },
    "warnings": ["ch_core_cpi_unavailable"],
}


@pytest.fixture(autouse=True)
def _clear_macro_cache():
    """Jeder Test faengt mit leerem Cache an, sonst beeinflussen sich die
    Tests gegenseitig (der Endpoint cached 6h).
    """
    cache.delete("external:macro:ch:v1")
    yield
    cache.delete("external:macro:ch:v1")


async def test_macro_ch_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/macro/ch")
    assert res.status_code == 401


async def test_macro_ch_returns_200_with_schema(client: AsyncClient):
    jwt = await register_and_login(client, email="macro1@example.com")
    created = await create_api_token(client, jwt)

    with patch(
        "api.external_v1.get_ch_macro_snapshot",
        new=AsyncMock(return_value=_MOCK_SNAPSHOT),
    ):
        res = await client.get(
            "/api/v1/external/macro/ch",
            headers=api_auth(created["token"]),
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["snb"]["policy_rate_pct"] == 0.5
    assert body["saron"]["current_pct"] == 0.45
    assert body["fx"]["chf_eur"]["rate"] == 1.0512
    assert body["ch_inflation"]["cpi_yoy_pct"] == 1.2
    assert body["ch_rates"]["eidg_10y_yield_pct"] == 0.48
    assert body["smi_vs_sp500_30d"]["relative_pct"] == 0.7
    assert "ch_core_cpi_unavailable" in body["warnings"]


async def test_macro_ch_cache_hit(client: AsyncClient):
    jwt = await register_and_login(client, email="macro2@example.com")
    created = await create_api_token(client, jwt)

    mock = AsyncMock(return_value=_MOCK_SNAPSHOT)
    with patch("api.external_v1.get_ch_macro_snapshot", new=mock):
        r1 = await client.get(
            "/api/v1/external/macro/ch",
            headers=api_auth(created["token"]),
        )
        r2 = await client.get(
            "/api/v1/external/macro/ch",
            headers=api_auth(created["token"]),
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert mock.await_count == 1  # zweiter Call aus Cache


async def test_macro_ch_service_crash_returns_503(client: AsyncClient):
    jwt = await register_and_login(client, email="macro3@example.com")
    created = await create_api_token(client, jwt)

    with patch(
        "api.external_v1.get_ch_macro_snapshot",
        new=AsyncMock(side_effect=RuntimeError("gather blew up")),
    ):
        res = await client.get(
            "/api/v1/external/macro/ch",
            headers=api_auth(created["token"]),
        )

    assert res.status_code == 503
    assert res.json()["detail"] == "ch_macro_unavailable"
