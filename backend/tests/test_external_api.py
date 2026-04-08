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


# --- Immobilien (Real Estate) ---

async def _seed_property_with_mortgage(client, jwt: str) -> str:
    """Create a Property + Mortgage via the internal CRUD API. Returns property_id."""
    res = await client.post(
        "/api/properties",
        json={
            "name": "Testhaus",
            "address": "Musterstrasse 1",
            "property_type": "efh",
            "purchase_date": "2020-06-01",
            "purchase_price": 1200000,
            "estimated_value": 1350000,
            "canton": "ZH",
            "notes": "geheime Notiz",
        },
        headers=jwt_auth(jwt),
    )
    assert res.status_code in (200, 201), res.text
    pid = res.json()["id"]

    res = await client.post(
        f"/api/properties/{pid}/mortgages",
        json={
            "name": "Tranche A",
            "type": "saron",
            "amount": 800000,
            "interest_rate": 1.2,
            "margin_rate": 0.85,
            "start_date": "2020-06-01",
            "end_date": "2025-06-01",
            "monthly_payment": 800,
            "amortization_monthly": 200,
            "amortization_annual": 2400,
            "bank": "GeheimBank AG",
        },
        headers=jwt_auth(jwt),
    )
    assert res.status_code in (200, 201), res.text
    return pid


class TestExternalImmobilien:
    async def test_immobilien_list_no_sensitive_fields(self, client):
        jwt = await register_and_login(client, email="immo@example.com")
        await _seed_property_with_mortgage(client, jwt)
        created = await create_api_token(client, jwt)

        res = await client.get(
            "/api/v1/external/immobilien",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        for key in ("total_value_chf", "total_mortgage_chf", "total_equity_chf", "properties"):
            assert key in body
        assert len(body["properties"]) == 1
        prop = body["properties"][0]
        # Whitelisted fields present
        assert prop["name"] == "Testhaus"
        assert "ltv" in prop
        assert "mortgages" in prop and len(prop["mortgages"]) == 1
        # Sensitive fields filtered
        raw = res.text
        assert '"address"' not in raw
        assert '"notes"' not in raw
        assert '"bank"' not in raw
        assert "GeheimBank" not in raw
        assert "Musterstrasse" not in raw

    async def test_immobilie_detail(self, client):
        jwt = await register_and_login(client, email="immo2@example.com")
        pid = await _seed_property_with_mortgage(client, jwt)
        created = await create_api_token(client, jwt)

        res = await client.get(
            f"/api/v1/external/immobilien/{pid}",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == pid
        assert "mortgages" in body
        assert '"bank"' not in res.text
        assert "GeheimBank" not in res.text

    async def test_hypotheken_list(self, client):
        jwt = await register_and_login(client, email="immo3@example.com")
        pid = await _seed_property_with_mortgage(client, jwt)
        created = await create_api_token(client, jwt)

        res = await client.get(
            f"/api/v1/external/immobilien/{pid}/hypotheken",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["property_id"] == pid
        assert len(body["mortgages"]) == 1
        m = body["mortgages"][0]
        assert m["name"] == "Tranche A"
        assert "effective_rate" in m
        assert "bank" not in m

    async def test_immobilien_unauthenticated(self, client):
        res = await client.get("/api/v1/external/immobilien")
        assert res.status_code == 401

    async def test_immobilie_not_found(self, client):
        jwt = await register_and_login(client, email="immo4@example.com")
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/immobilien/00000000-0000-0000-0000-000000000000",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 404


# --- Vorsorge (Pension / Saeule 3a) ---

async def _seed_pension(client, jwt: str) -> str:
    """Create a pension Position via the internal API. Returns position id."""
    res = await client.post(
        "/api/portfolio/positions",
        json={
            "ticker": "VORSORGE-VIAC",
            "name": "VIAC 3a Konto",
            "type": "pension",
            "currency": "CHF",
            "shares": 1,
            "cost_basis_chf": 25000,
            "bank_name": "GeheimBank Vorsorge",
            "iban": "CH9300762011623852957",
            "notes": "interne Notiz",
        },
        headers=jwt_auth(jwt),
    )
    assert res.status_code in (200, 201), res.text
    return res.json().get("id")


class TestExternalVorsorge:
    async def test_vorsorge_list_no_sensitive_fields(self, client):
        jwt = await register_and_login(client, email="vorsorge@example.com")
        await _seed_pension(client, jwt)
        created = await create_api_token(client, jwt)

        res = await client.get(
            "/api/v1/external/vorsorge",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert "total_value_chf" in body
        assert "accounts" in body
        assert len(body["accounts"]) == 1
        acc = body["accounts"][0]
        assert acc["ticker"] == "VORSORGE-VIAC"
        assert acc["market_value_chf"] == 25000.0
        assert body["total_value_chf"] == 25000.0
        # Sensitive fields filtered
        raw = res.text
        assert '"bank_name"' not in raw
        assert '"iban"' not in raw
        assert '"notes"' not in raw
        assert "GeheimBank" not in raw
        assert "CH9300762011623852957" not in raw

    async def test_vorsorge_unauthenticated(self, client):
        res = await client.get("/api/v1/external/vorsorge")
        assert res.status_code == 401

    async def test_vorsorge_not_found(self, client):
        jwt = await register_and_login(client, email="vorsorge2@example.com")
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/vorsorge/00000000-0000-0000-0000-000000000000",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 404
