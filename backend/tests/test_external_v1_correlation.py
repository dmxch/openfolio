"""Integration tests for GET /api/v1/external/analysis/correlation-matrix."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.test_external_api import api_auth, create_api_token, register_and_login

pytestmark = pytest.mark.asyncio


_MOCK_RESPONSE = {
    "as_of": "2026-04-08T00:00:00",
    "period": "90d",
    "observations": 60,
    "filters": {
        "include_cash": False,
        "include_pension": False,
        "include_commodity": True,
        "include_crypto": True,
    },
    "tickers": [
        {"yf_ticker": "AAA", "ticker": "AAA", "name": "AAA", "type": "stock", "sector": "Technology", "weight_pct": 50.0},
        {"yf_ticker": "BBB", "ticker": "BBB", "name": "BBB", "type": "stock", "sector": "Technology", "weight_pct": 50.0},
    ],
    "matrix": [[1.0, 0.85], [0.85, 1.0]],
    "high_correlations": [
        {
            "ticker_a": "AAA",
            "ticker_b": "BBB",
            "correlation": 0.85,
            "interpretation": "gleicher Sektor (Technology) — stark positiv korreliert",
        }
    ],
    "concentration": {
        "hhi": 0.5,
        "effective_n": 2.0,
        "max_weight_ticker": "AAA",
        "max_weight_pct": 50.0,
        "classification": "high",
    },
    "warnings": [],
}


async def test_correlation_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/analysis/correlation-matrix")
    assert res.status_code == 401


async def test_correlation_returns_200_with_mock(client: AsyncClient):
    jwt = await register_and_login(client, email="corr1@example.com")
    created = await create_api_token(client, jwt)

    with patch(
        "api.external_v1.compute_correlation_matrix",
        new=AsyncMock(return_value=_MOCK_RESPONSE),
    ):
        res = await client.get(
            "/api/v1/external/analysis/correlation-matrix?period=90d",
            headers=api_auth(created["token"]),
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["period"] == "90d"
    assert len(body["tickers"]) == 2
    # Diagonal sanity
    assert body["matrix"][0][0] == 1.0
    assert body["matrix"][1][1] == 1.0
    assert body["concentration"]["hhi"] == 0.5


async def test_correlation_invalid_period_returns_422(client: AsyncClient):
    """FastAPI returns 422 for regex-validation failures on query params."""
    jwt = await register_and_login(client, email="corr2@example.com")
    created = await create_api_token(client, jwt)

    res = await client.get(
        "/api/v1/external/analysis/correlation-matrix?period=foo",
        headers=api_auth(created["token"]),
    )
    # Regex validation via Query(pattern=...) -> 422 Unprocessable Entity
    assert res.status_code == 422


async def test_correlation_cache_hit_returns_same_data(client: AsyncClient):
    jwt = await register_and_login(client, email="corr3@example.com")
    created = await create_api_token(client, jwt)

    mock = AsyncMock(return_value=_MOCK_RESPONSE)
    with patch("api.external_v1.compute_correlation_matrix", new=mock):
        r1 = await client.get(
            "/api/v1/external/analysis/correlation-matrix?period=90d",
            headers=api_auth(created["token"]),
        )
        r2 = await client.get(
            "/api/v1/external/analysis/correlation-matrix?period=90d",
            headers=api_auth(created["token"]),
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    # Service only invoked on the first call (second call served from cache).
    assert mock.await_count == 1
