"""External-API-Paritaet: jede neue Analyse-Sicht muss unter /api/v1/external/analysis/*
exakt dasselbe liefern wie der interne /api/analysis/*-Endpoint (read-Scope).

Stehende Regel: alles muss per API erreichbar sein. Dieser Test faengt eine
fehlende externe Spiegelung (oder Shape-Divergenz) sofort.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"

# Endpoints, die unter BEIDEN Praefixen identisch existieren muessen.
ANALYSIS_VIEWS = [
    "net-worth",
    "dividend-yoc",
    "dividend-forecast",
    "rebalancing",
    "position-rebalancing",
    "trade-journal",
    "country-lookthrough",
    "fire-projection",
    "fire-assumptions",
]


async def _setup(client: AsyncClient, email: str):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    jwt = (await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})).json()["access_token"]
    tok_res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "r", "write_access": False},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert tok_res.status_code == 201, tok_res.text
    return jwt, tok_res.json()["token"]


@pytest.mark.parametrize("view", ANALYSIS_VIEWS)
async def test_external_analysis_parity(client, view):
    jwt, token = await _setup(client, f"parity-{view}@test.local")

    ext = await client.get(f"/api/v1/external/analysis/{view}", headers={"X-API-Key": token})
    assert ext.status_code == 200, f"external {view}: {ext.status_code} {ext.text}"

    intern = await client.get(f"/api/analysis/{view}", headers={"Authorization": f"Bearer {jwt}"})
    assert intern.status_code == 200, f"internal {view}: {intern.status_code} {intern.text}"

    assert ext.json() == intern.json(), f"Paritaet verletzt fuer {view}"


async def test_external_analysis_requires_token(client):
    """Ohne Token -> 401/403 (kein offener Zugang zu den Sichten)."""
    res = await client.get("/api/v1/external/analysis/net-worth")
    assert res.status_code in (401, 403)


async def _write_token(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    jwt = (await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})).json()["access_token"]
    tok_res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "w", "write_access": True},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert tok_res.status_code == 201, tok_res.text
    return tok_res.json()["token"]


async def test_external_dividend_forecast_refresh_requires_write(client):
    """POST /dividend-forecast/refresh ist write-gated; read-Token -> 403."""
    _, read_token = await _setup(client, "fc-refresh-read@test.local")
    res = await client.post(
        "/api/v1/external/analysis/dividend-forecast/refresh",
        headers={"X-API-Key": read_token},
    )
    assert res.status_code == 403, res.text


async def test_external_dividend_forecast_refresh_write_ok(client):
    """Write-Token -> 200; leerer User loest keinen yfinance-Call aus (keine Holdings)."""
    write_token = await _write_token(client, "fc-refresh-write@test.local")
    res = await client.post(
        "/api/v1/external/analysis/dividend-forecast/refresh",
        headers={"X-API-Key": write_token},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("has_data") is True
    assert body.get("forecast_12m_chf") == 0
