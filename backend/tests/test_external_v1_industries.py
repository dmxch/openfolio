"""Integration tests for GET /api/v1/external/market/industries."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from models.market_industry import MarketIndustry
from tests.test_external_api import api_auth, create_api_token, register_and_login

pytestmark = pytest.mark.asyncio


_MOCK_RESPONSE = {
    "scraped_at": "2026-04-23T00:00:00+00:00",
    "period": "ytd",
    "count": 2,
    "rows": [
        {"slug": "semis", "name": "Semiconductors", "change_pct": 1.5, "perf_ytd": 40.0,
         "perf_1w": 2.0, "perf_1m": 5.0, "perf_3m": 10.0, "perf_6m": 20.0,
         "perf_1y": 55.0, "perf_5y": 180.0, "perf_10y": 500.0,
         "market_cap": 3_000_000_000_000.0, "volume": 50_000_000.0},
        {"slug": "utilities", "name": "Utilities", "change_pct": -0.3, "perf_ytd": 4.0,
         "perf_1w": 0.1, "perf_1m": 1.0, "perf_3m": 2.0, "perf_6m": 3.0,
         "perf_1y": 7.0, "perf_5y": 30.0, "perf_10y": 80.0,
         "market_cap": 500_000_000_000.0, "volume": 5_000_000.0},
    ],
}


async def test_industries_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/market/industries")
    assert res.status_code == 401


async def test_industries_returns_200_with_mock(client: AsyncClient):
    jwt = await register_and_login(client, email="ind1@example.com")
    created = await create_api_token(client, jwt)

    with patch(
        "api.external_v1.get_latest_industries",
        new=AsyncMock(return_value=_MOCK_RESPONSE),
    ):
        res = await client.get(
            "/api/v1/external/market/industries?period=ytd",
            headers=api_auth(created["token"]),
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert body["period"] == "ytd"
    assert body["rows"][0]["slug"] == "semis"


async def test_industries_invalid_period_returns_422(client: AsyncClient):
    jwt = await register_and_login(client, email="ind2@example.com")
    created = await create_api_token(client, jwt)

    res = await client.get(
        "/api/v1/external/market/industries?period=2y",
        headers=api_auth(created["token"]),
    )
    assert res.status_code == 422


async def test_industries_cache_hit_reuses_result(client: AsyncClient):
    jwt = await register_and_login(client, email="ind3@example.com")
    created = await create_api_token(client, jwt)

    mock = AsyncMock(return_value=_MOCK_RESPONSE)
    with patch("api.external_v1.get_latest_industries", new=mock):
        r1 = await client.get(
            "/api/v1/external/market/industries?period=1m&top=5",
            headers=api_auth(created["token"]),
        )
        r2 = await client.get(
            "/api/v1/external/market/industries?period=1m&top=5",
            headers=api_auth(created["token"]),
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert mock.await_count == 1


async def test_industries_end_to_end_with_db_snapshot(client: AsyncClient, db):
    """Real service → DB path (no mock). Seeds 3 rows, asks for top=2 by YTD."""
    now = datetime(2026, 4, 22, 0, 0, 0)
    db.add(MarketIndustry(slug="semis", name="Semiconductors", scraped_at=now,
                          perf_ytd=Decimal("40")))
    db.add(MarketIndustry(slug="utilities", name="Utilities", scraped_at=now,
                          perf_ytd=Decimal("5")))
    db.add(MarketIndustry(slug="energy", name="Energy", scraped_at=now,
                          perf_ytd=Decimal("25")))
    await db.commit()

    jwt = await register_and_login(client, email="ind4@example.com")
    created = await create_api_token(client, jwt)
    res = await client.get(
        "/api/v1/external/market/industries?period=ytd&top=2",
        headers=api_auth(created["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert [r["slug"] for r in body["rows"]] == ["semis", "energy"]


_MOCK_MEMBERS = [
    {"ticker": "XOM", "name": "Exxon Mobil Corporation", "exchange": "NYSE",
     "change_pct": -0.24, "perf_1w": 1.2, "perf_1m": 3.4, "perf_3m": 8.9,
     "perf_6m": 15.1, "perf_ytd": 29.0, "perf_1y": 12.7,
     "market_cap": 642135222801.0},
    {"ticker": "CVX", "name": "Chevron Corporation", "exchange": "NYSE",
     "change_pct": 0.22, "perf_1w": 0.9, "perf_1m": 2.1, "perf_3m": 6.0,
     "perf_6m": 11.0, "perf_ytd": 25.8, "perf_1y": 8.0,
     "market_cap": 381251548117.0},
]


async def test_industry_members_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/market/industries/integrated-oil/members")
    assert res.status_code == 401


async def test_industry_members_unknown_slug_returns_404(client: AsyncClient, db):
    db.add(MarketIndustry(slug="semis", name="Semiconductors",
                          scraped_at=datetime(2026, 4, 22), perf_ytd=Decimal("40")))
    await db.commit()

    jwt = await register_and_login(client, email="mem1@example.com")
    created = await create_api_token(client, jwt)
    res = await client.get(
        "/api/v1/external/market/industries/does-not-exist/members",
        headers=api_auth(created["token"]),
    )
    assert res.status_code == 404


async def test_industry_members_returns_200_with_mock(client: AsyncClient, db):
    db.add(MarketIndustry(slug="integrated-oil", name="Integrated Oil",
                          scraped_at=datetime(2026, 4, 22), perf_ytd=Decimal("29")))
    await db.commit()

    jwt = await register_and_login(client, email="mem2@example.com")
    created = await create_api_token(client, jwt)

    with patch(
        "api.external_v1.fetch_industry_members",
        new=AsyncMock(return_value=_MOCK_MEMBERS),
    ) as mock:
        res = await client.get(
            "/api/v1/external/market/industries/integrated-oil/members?limit=5",
            headers=api_auth(created["token"]),
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["slug"] == "integrated-oil"
    assert body["name"] == "Integrated Oil"
    assert body["count"] == 2
    assert body["members"][0]["ticker"] == "XOM"
    # Slug is resolved to the display name before hitting the scanner.
    mock.assert_awaited_once_with("Integrated Oil", limit=5)


async def test_industry_members_scanner_failure_returns_502(client: AsyncClient, db):
    db.add(MarketIndustry(slug="integrated-oil", name="Integrated Oil",
                          scraped_at=datetime(2026, 4, 22), perf_ytd=Decimal("29")))
    await db.commit()

    jwt = await register_and_login(client, email="mem3@example.com")
    created = await create_api_token(client, jwt)

    with patch(
        "api.external_v1.fetch_industry_members",
        new=AsyncMock(side_effect=RuntimeError("scanner down")),
    ):
        res = await client.get(
            "/api/v1/external/market/industries/integrated-oil/members",
            headers=api_auth(created["token"]),
        )
    assert res.status_code == 502
