"""Integration tests for GET /api/v1/external/portfolio/upcoming-earnings.

Service-Layer wird gemockt — wir pruefen nur Router-Semantik (Auth,
Query-Validation, Cache, Error-Handling).
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def _register_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


async def _create_api_token(client: AsyncClient, jwt: str) -> str:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "test"},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _sample_payload() -> dict:
    today = date.today()
    return {
        "as_of": "2026-04-09T00:00:00+00:00",
        "lookahead_days": 7,
        "earnings": [
            {
                "ticker": "JNJ",
                "name": "Johnson & Johnson",
                "type": "stock",
                "earnings_date": (today + timedelta(days=5)).isoformat(),
                "days_until": 5,
                "earnings_time": "amc",
                "earnings_time_label": "After Market Close",
                "eps_estimate": 2.68,
                "revenue_estimate_usd": 23_600_000_000,
                "is_confirmed": True,
                "source": "finnhub",
            }
        ],
        "no_earnings_in_window": ["AAPL"],
        "warnings": [],
    }


async def test_upcoming_earnings_requires_api_key(client):
    res = await client.get("/api/v1/external/portfolio/upcoming-earnings")
    assert res.status_code == 401


async def test_upcoming_earnings_returns_200_with_schema(client):
    jwt = await _register_login(client, "earn1@example.com")
    token = await _create_api_token(client, jwt)

    with patch(
        "api.external_v1.get_upcoming_earnings_for_portfolio",
        new=AsyncMock(return_value=_sample_payload()),
    ):
        res = await client.get(
            "/api/v1/external/portfolio/upcoming-earnings",
            headers={"X-API-Key": token},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    for key in ("as_of", "lookahead_days", "earnings", "no_earnings_in_window", "warnings"):
        assert key in body
    assert body["earnings"][0]["ticker"] == "JNJ"
    assert body["earnings"][0]["earnings_time"] == "amc"


async def test_upcoming_earnings_days_validation(client):
    jwt = await _register_login(client, "earn2@example.com")
    token = await _create_api_token(client, jwt)
    headers = {"X-API-Key": token}

    with patch(
        "api.external_v1.get_upcoming_earnings_for_portfolio",
        new=AsyncMock(return_value=_sample_payload()),
    ):
        r0 = await client.get(
            "/api/v1/external/portfolio/upcoming-earnings?days=0", headers=headers
        )
        r100 = await client.get(
            "/api/v1/external/portfolio/upcoming-earnings?days=100", headers=headers
        )
        r14 = await client.get(
            "/api/v1/external/portfolio/upcoming-earnings?days=14", headers=headers
        )

    assert r0.status_code == 422
    assert r100.status_code == 422
    assert r14.status_code == 200


async def test_upcoming_earnings_cache_hit(client):
    jwt = await _register_login(client, "earn3@example.com")
    token = await _create_api_token(client, jwt)
    headers = {"X-API-Key": token}

    mock = AsyncMock(return_value=_sample_payload())
    with patch("api.external_v1.get_upcoming_earnings_for_portfolio", new=mock):
        r1 = await client.get(
            "/api/v1/external/portfolio/upcoming-earnings?days=7", headers=headers
        )
        r2 = await client.get(
            "/api/v1/external/portfolio/upcoming-earnings?days=7", headers=headers
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Zweiter Call muss aus dem Cache kommen.
    assert mock.call_count == 1


async def test_upcoming_earnings_service_crash_returns_503(client):
    jwt = await _register_login(client, "earn4@example.com")
    token = await _create_api_token(client, jwt)

    with patch(
        "api.external_v1.get_upcoming_earnings_for_portfolio",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        res = await client.get(
            "/api/v1/external/portfolio/upcoming-earnings?days=5",
            headers={"X-API-Key": token},
        )

    assert res.status_code == 503
    assert res.json()["detail"] == "upcoming_earnings_unavailable"
