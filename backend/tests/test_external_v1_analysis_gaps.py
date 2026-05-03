"""Tests for the external API gap-closing changes.

Deckt:
- /api/v1/external/analysis/score liefert `concentration` + `liquid_portfolio_chf`
  (v0.28/v0.29 Konzentrations-Block in der externen API).
- /api/v1/external/analysis/heartbeat existiert und liefert das Wyckoff-Sub-Dict
  (v0.29.1).
- /api/v1/external/analysis/breakouts existiert (Konsistenz mit Internal).
- /api/v1/external/market/industries akzeptiert den `min_mcap`-Filter.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.test_external_api import api_auth, create_api_token, register_and_login

pytestmark = pytest.mark.asyncio


# --- Score: concentration + liquid_portfolio_chf -----------------------------


@patch("services.scoring_service.assess_ticker", return_value={
    "ticker": "AAPL", "score": 14, "max_score": 18, "price": 180.0,
    "signal": "BEOBACHTUNGSLISTE", "quality": "STARK",
})
async def test_external_score_includes_concentration_block(
    _mock_score, client: AsyncClient,
):
    jwt = await register_and_login(client, email="extscore1@example.com")
    created = await create_api_token(client, jwt)

    res = await client.get(
        "/api/v1/external/analysis/score/AAPL",
        headers=api_auth(created["token"]),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # Setup-Felder unverändert
    assert body["score"] == 14
    # Phase 1.1: concentration-Block + liquid_portfolio_chf vorhanden
    assert "concentration" in body
    assert "single_name" in body["concentration"]
    assert "sector" in body["concentration"]
    assert "liquid_portfolio_chf" in body
    # Portfolio-weiter HHI / effective_n
    portfolio = body["concentration"].get("portfolio")
    assert portfolio is not None
    for key in ("hhi", "effective_n", "nominal_count", "classification"):
        assert key in portfolio


@patch("services.scoring_service.assess_ticker", return_value={
    "max_score": 0, "price": None,
})
async def test_external_score_404_for_unknown_ticker(_mock_score, client: AsyncClient):
    jwt = await register_and_login(client, email="extscore2@example.com")
    created = await create_api_token(client, jwt)

    res = await client.get(
        "/api/v1/external/analysis/score/INVALID",
        headers=api_auth(created["token"]),
    )
    assert res.status_code == 404


async def test_external_score_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/analysis/score/AAPL")
    assert res.status_code == 401


# --- Heartbeat ---------------------------------------------------------------


_HEARTBEAT_MOCK = {
    "detected": True,
    "score": 2,
    "atr_compression_ratio": 0.42,
    "wyckoff": {
        "score": 1,
        "label": "bestätigt",
        "spring_detected": False,
        "volume_slope_pct_per_day": -0.8,
    },
}


async def test_external_heartbeat_returns_wyckoff_subdict(client: AsyncClient):
    jwt = await register_and_login(client, email="exthb1@example.com")
    created = await create_api_token(client, jwt)

    with patch(
        "services.chart_service.get_heartbeat_pattern",
        return_value=_HEARTBEAT_MOCK,
    ):
        res = await client.get(
            "/api/v1/external/analysis/heartbeat/AAPL",
            headers=api_auth(created["token"]),
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["detected"] is True
    assert "wyckoff" in body
    assert body["wyckoff"]["label"] == "bestätigt"


async def test_external_heartbeat_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/analysis/heartbeat/AAPL")
    assert res.status_code == 401


# --- Breakouts ---------------------------------------------------------------


async def test_external_breakouts_empty_list(client: AsyncClient):
    jwt = await register_and_login(client, email="extbrk1@example.com")
    created = await create_api_token(client, jwt)

    with patch("services.chart_service.get_breakout_events", return_value=[]):
        res = await client.get(
            "/api/v1/external/analysis/breakouts/AAPL",
            headers=api_auth(created["token"]),
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ticker"] == "AAPL"
    assert body["breakouts"] == []


async def test_external_breakouts_requires_api_key(client: AsyncClient):
    res = await client.get("/api/v1/external/analysis/breakouts/AAPL")
    assert res.status_code == 401


# --- Industries: min_mcap-Filter --------------------------------------------


_INDUSTRIES_MOCK = {
    "scraped_at": "2026-04-23T00:00:00+00:00",
    "period": "ytd",
    "count": 1,
    "rows": [
        {"slug": "semis", "name": "Semiconductors", "perf_ytd": 40.0,
         "market_cap": 3_000_000_000_000.0},
    ],
}


async def test_external_industries_min_mcap_forwarded(client: AsyncClient):
    jwt = await register_and_login(client, email="extind_mcap@example.com")
    created = await create_api_token(client, jwt)

    mock = AsyncMock(return_value=_INDUSTRIES_MOCK)
    with patch("api.external_v1.get_latest_industries", new=mock):
        res = await client.get(
            "/api/v1/external/market/industries?period=ytd&min_mcap=1000000000",
            headers=api_auth(created["token"]),
        )
    assert res.status_code == 200, res.text
    # Service wurde mit min_mcap aufgerufen
    assert mock.await_count == 1
    kwargs = mock.await_args.kwargs
    assert kwargs.get("min_mcap") == 1_000_000_000.0


async def test_external_industries_min_mcap_negative_returns_422(client: AsyncClient):
    jwt = await register_and_login(client, email="extind_mcap2@example.com")
    created = await create_api_token(client, jwt)

    res = await client.get(
        "/api/v1/external/market/industries?min_mcap=-1",
        headers=api_auth(created["token"]),
    )
    assert res.status_code == 422
