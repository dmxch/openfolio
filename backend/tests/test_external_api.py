"""Tests for the external read-only REST API (/api/v1/external/*).

Covers:
- X-API-Key auth (missing / invalid / revoked / valid)
- Token-Management endpoints (create / list / revoke)
- Smoke tests for representative read endpoints
- Sensitive fields (bank_name, iban) MUST NOT appear in responses
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str = "ext@example.com") -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def jwt_auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def api_auth(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def create_api_token(client: AsyncClient, jwt: str, name: str = "test") -> dict:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": name},
        headers=jwt_auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- Token Management ---

class TestTokenManagement:
    async def test_create_token_returns_plaintext_once(self, client):
        jwt = await register_and_login(client)
        data = await create_api_token(client, jwt, "Claude Code")
        assert "token" in data
        assert data["token"].startswith("ofk_")
        assert data["prefix"].startswith("ofk_")
        assert len(data["prefix"]) <= 16
        assert data["name"] == "Claude Code"

    async def test_list_tokens_excludes_plaintext(self, client):
        jwt = await register_and_login(client)
        await create_api_token(client, jwt, "Token A")
        res = await client.get("/api/settings/api-tokens", headers=jwt_auth(jwt))
        assert res.status_code == 200
        tokens = res.json()
        assert len(tokens) == 1
        assert "token" not in tokens[0]
        assert "token_hash" not in tokens[0]
        assert tokens[0]["name"] == "Token A"

    async def test_create_token_unauthenticated(self, client):
        res = await client.post("/api/settings/api-tokens", json={"name": "x"})
        assert res.status_code in (401, 403)

    async def test_revoke_token(self, client):
        jwt = await register_and_login(client)
        created = await create_api_token(client, jwt)
        token_id = created["id"]
        plaintext = created["token"]

        res = await client.delete(f"/api/settings/api-tokens/{token_id}", headers=jwt_auth(jwt))
        assert res.status_code == 204

        # External API should now reject this token
        res = await client.get("/api/v1/external/portfolio/summary", headers=api_auth(plaintext))
        assert res.status_code == 401


# --- External Auth ---

class TestExternalAuth:
    async def test_health_no_auth(self, client):
        res = await client.get("/api/v1/external/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    async def test_missing_api_key(self, client):
        res = await client.get("/api/v1/external/portfolio/summary")
        assert res.status_code == 401

    async def test_invalid_api_key(self, client):
        res = await client.get(
            "/api/v1/external/portfolio/summary",
            headers=api_auth("ofk_invalid_token_value_xyz"),
        )
        assert res.status_code == 401

    async def test_malformed_api_key(self, client):
        res = await client.get(
            "/api/v1/external/portfolio/summary",
            headers=api_auth("not-a-valid-token"),
        )
        assert res.status_code == 401

    async def test_valid_api_key(self, client):
        jwt = await register_and_login(client)
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/portfolio/summary",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200


# --- Smoke + Sensitive Field Filtering ---

class TestExternalEndpoints:
    async def test_portfolio_summary_no_sensitive_fields(self, client):
        jwt = await register_and_login(client)
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/portfolio/summary",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        # Top-level expected keys
        for key in ("total_invested_chf", "total_market_value_chf", "positions", "allocations"):
            assert key in body
        # No bank_name / iban anywhere in serialised body
        raw = res.text
        assert "bank_name" not in raw
        assert "iban" not in raw

    async def test_positions_list(self, client):
        jwt = await register_and_login(client)
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/positions",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        assert "positions" in body
        assert "bank_name" not in res.text
        assert "iban" not in res.text

    async def test_screening_latest_empty(self, client):
        jwt = await register_and_login(client)
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/screening/latest",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 0
        assert body["results"] == []

    async def test_position_not_found(self, client):
        jwt = await register_and_login(client)
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/positions/NOTFOUND",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 404
