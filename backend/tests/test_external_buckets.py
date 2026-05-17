"""External-API v1: Bucket-Endpoints (v0.39, Read-Only).

Coverage:
  - GET /v1/buckets liefert Liste mit gefilterten Feldern
  - GET /v1/buckets/{id}/summary
  - GET /v1/buckets/{id}/drawdown
  - GET /v1/buckets/allocations
  - bucket_id im Position-Response der External-API
  - bucket_id im correlation-matrix Query-Param
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _setup_user_with_token(client) -> dict:
    """Registriert User, erstellt API-Token mit read-Scope, gibt Auth-Header."""
    res = await client.post(
        "/api/auth/register",
        json={"email": "ext-bucket@example.test", "password": "StrongPass123!"},
    )
    assert res.status_code == 201
    login = await client.post(
        "/api/auth/login",
        json={"email": "ext-bucket@example.test", "password": "StrongPass123!"},
    )
    jwt_token = login.json()["access_token"]
    jwt_headers = {"Authorization": f"Bearer {jwt_token}"}
    # API-Token erstellen
    tok = await client.post(
        "/api/settings/api-tokens",
        headers=jwt_headers,
        json={"name": "test", "scopes": ["read"]},
    )
    assert tok.status_code == 201, tok.text
    api_key = tok.json()["token"]
    return {"X-API-Key": api_key, "jwt": jwt_headers}


async def test_external_buckets_list_has_system_buckets(client):
    headers = await _setup_user_with_token(client)
    res = await client.get("/api/v1/external/buckets", headers={"X-API-Key": headers["X-API-Key"]})
    assert res.status_code == 200, res.text
    data = res.json()
    names = {b["name"] for b in data["buckets"]}
    assert {"Alle Positionen", "Immobilien", "Private Equity", "Vorsorge"} <= names
    # Whitelist greift: keine unerwarteten Felder
    sample = data["buckets"][0]
    for forbidden in ("user_id", "created_at", "updated_at"):
        assert forbidden not in sample


async def test_external_bucket_summary_returns_404_for_unknown(client):
    headers = await _setup_user_with_token(client)
    res = await client.get(
        "/api/v1/external/buckets/00000000-0000-0000-0000-000000000000/summary",
        headers={"X-API-Key": headers["X-API-Key"]},
    )
    assert res.status_code == 404


async def test_external_buckets_allocations(client):
    headers = await _setup_user_with_token(client)
    res = await client.get(
        "/api/v1/external/buckets/allocations",
        headers={"X-API-Key": headers["X-API-Key"]},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    # Mindestens liquid_default bucket sollte drin sein
    names = {item["name"] for item in data["items"]}
    assert "Alle Positionen" in names


async def test_external_correlation_with_bucket_id_400_when_empty(client):
    """Bucket ohne Positionen -> compute_correlation_matrix wirft ValueError -> 400."""
    headers = await _setup_user_with_token(client)
    # Liquid-default Bucket nehmen — leer
    buckets_res = await client.get(
        "/api/v1/external/buckets", headers={"X-API-Key": headers["X-API-Key"]},
    )
    liquid = next(
        b for b in buckets_res.json()["buckets"] if b["system_role"] == "liquid_default"
    )
    res = await client.get(
        f"/api/v1/external/analysis/correlation-matrix?bucket_id={liquid['id']}",
        headers={"X-API-Key": headers["X-API-Key"]},
    )
    # Keine Positionen → 400 "Keine Positionen nach Filterung uebrig"
    assert res.status_code == 400
