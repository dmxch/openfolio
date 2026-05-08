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


# --- Schreib-API: Token-Scopes ---

async def create_api_token_with_scope(
    client: AsyncClient, jwt: str, name: str = "test", write: bool = False
) -> dict:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": name, "write_access": write},
        headers=jwt_auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def add_to_watchlist(client: AsyncClient, jwt: str, ticker: str = "AAPL", name: str = "Apple Inc.") -> dict:
    res = await client.post(
        "/api/analysis/watchlist",
        json={"ticker": ticker, "name": name},
        headers=jwt_auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()


class TestScopes:
    async def test_default_token_is_read_only(self, client):
        jwt = await register_and_login(client, email="scope-default@example.com")
        token = await create_api_token_with_scope(client, jwt, name="readonly")
        assert token.get("scopes") == ["read"]

    async def test_write_token_has_read_and_write_scopes(self, client):
        jwt = await register_and_login(client, email="scope-write@example.com")
        token = await create_api_token_with_scope(client, jwt, name="rw", write=True)
        assert "read" in token.get("scopes", [])
        assert "write" in token.get("scopes", [])

    async def test_list_tokens_includes_scopes(self, client):
        jwt = await register_and_login(client, email="scope-list@example.com")
        await create_api_token_with_scope(client, jwt, name="rw", write=True)
        res = await client.get("/api/settings/api-tokens", headers=jwt_auth(jwt))
        assert res.status_code == 200
        tokens = res.json()
        assert "scopes" in tokens[0]
        assert "write" in tokens[0]["scopes"]


# --- Schreib-API: Watchlist-Notizen ---

class TestExternalNotes:
    async def test_read_only_token_cannot_patch_notes(self, client):
        jwt = await register_and_login(client, email="notes-r@example.com")
        await add_to_watchlist(client, jwt, ticker="AAPL", name="Apple")
        token = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.patch(
            "/api/v1/external/watchlist/AAPL/notes",
            json={"content": "x", "mode": "replace"},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 403
        assert "write" in (res.json().get("detail") or "")

    async def test_write_token_replace_roundtrip(self, client):
        jwt = await register_and_login(client, email="notes-rt@example.com")
        await add_to_watchlist(client, jwt, ticker="MSFT", name="Microsoft")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.patch(
            "/api/v1/external/watchlist/MSFT/notes",
            json={"content": "Hallo Welt", "mode": "replace"},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["ticker"] == "MSFT"
        assert body["char_count"] == 10

        res2 = await client.get(
            "/api/v1/external/watchlist", headers=api_auth(token["token"])
        )
        assert res2.status_code == 200
        msft = next(i for i in res2.json()["items"] if i["ticker"] == "MSFT")
        assert msft["notes"] == "Hallo Welt"
        assert msft["notes_last_api_token_name"] == "w"

    async def test_append_concatenates_with_separator(self, client):
        jwt = await register_and_login(client, email="notes-app@example.com")
        await add_to_watchlist(client, jwt, ticker="GOOG", name="Alphabet")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        await client.patch(
            "/api/v1/external/watchlist/GOOG/notes",
            json={"content": "a", "mode": "replace"},
            headers=api_auth(token["token"]),
        )
        await client.patch(
            "/api/v1/external/watchlist/GOOG/notes",
            json={"content": "b", "mode": "append"},
            headers=api_auth(token["token"]),
        )
        res = await client.get(
            "/api/v1/external/watchlist", headers=api_auth(token["token"])
        )
        goog = next(i for i in res.json()["items"] if i["ticker"] == "GOOG")
        assert goog["notes"] == "a\n\n---\nb"

    async def test_pydantic_rejects_above_10000(self, client):
        jwt = await register_and_login(client, email="notes-len@example.com")
        await add_to_watchlist(client, jwt, ticker="NVDA", name="Nvidia")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.patch(
            "/api/v1/external/watchlist/NVDA/notes",
            json={"content": "x" * 10_001, "mode": "replace"},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 422

    async def test_append_overflow_combined_limit(self, client):
        jwt = await register_and_login(client, email="notes-ovf@example.com")
        await add_to_watchlist(client, jwt, ticker="TSLA", name="Tesla")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        # Existing 9500 chars
        await client.patch(
            "/api/v1/external/watchlist/TSLA/notes",
            json={"content": "a" * 9500, "mode": "replace"},
            headers=api_auth(token["token"]),
        )
        # Append 1000 chars; combined > 10000 (incl. separator) should 422
        res = await client.patch(
            "/api/v1/external/watchlist/TSLA/notes",
            json={"content": "b" * 1000, "mode": "append"},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 422
        # Content unchanged
        get = await client.get(
            "/api/v1/external/watchlist", headers=api_auth(token["token"])
        )
        tsla = next(i for i in get.json()["items"] if i["ticker"] == "TSLA")
        assert tsla["notes"] == "a" * 9500

    async def test_unknown_ticker_returns_404(self, client):
        jwt = await register_and_login(client, email="notes-404@example.com")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.patch(
            "/api/v1/external/watchlist/ZZZZ/notes",
            json={"content": "x", "mode": "replace"},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 404

    async def test_read_only_get_watchlist_strips_notes(self, client):
        jwt = await register_and_login(client, email="notes-strip@example.com")
        await add_to_watchlist(client, jwt, ticker="AMD", name="AMD")
        # Set a note via the write-token flow first
        wt = await create_api_token_with_scope(client, jwt, name="w", write=True)
        await client.patch(
            "/api/v1/external/watchlist/AMD/notes",
            json={"content": "secret", "mode": "replace"},
            headers=api_auth(wt["token"]),
        )
        # Read-only token should not see the note
        rt = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.get(
            "/api/v1/external/watchlist", headers=api_auth(rt["token"])
        )
        amd = next(i for i in res.json()["items"] if i["ticker"] == "AMD")
        assert "notes" not in amd
        assert "notes_last_api_write_at" not in amd

    async def test_audit_log_does_not_persist_content(self, client):
        # We assert via the API response shape: audit metadata fields
        # are present on the response, but the content itself is not echoed
        # outside the watchlist GET. (Direct DB inspection is covered by
        # the Postgres smoke test in the plan; here we ensure the contract
        # of the PATCH response.)
        jwt = await register_and_login(client, email="audit@example.com")
        await add_to_watchlist(client, jwt, ticker="SHOP", name="Shopify")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.patch(
            "/api/v1/external/watchlist/SHOP/notes",
            json={"content": "secret-audit", "mode": "replace"},
            headers=api_auth(token["token"]),
        )
        body = res.json()
        # The PATCH response must not echo the note content.
        assert "content" not in body
        assert "notes" not in body
        assert body["char_count"] == len("secret-audit")


# --- Schreib-API: Preis-Alarme ---

class TestExternalAlerts:
    async def test_create_alert_requires_scope(self, client):
        jwt = await register_and_login(client, email="alert-scope@example.com")
        await add_to_watchlist(client, jwt, ticker="AAPL", name="Apple")
        token = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.post(
            "/api/v1/external/alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 200.0},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 403

    async def test_create_alert_requires_watchlist_or_position(self, client):
        jwt = await register_and_login(client, email="alert-nowl@example.com")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.post(
            "/api/v1/external/alerts",
            json={"ticker": "ZZZZZ", "alert_type": "price_above", "target_value": 50.0},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 400
        assert "Watchlist" in (res.json().get("detail") or "")

    async def test_create_alert_via_watchlist_ticker(self, client):
        jwt = await register_and_login(client, email="alert-wl@example.com")
        await add_to_watchlist(client, jwt, ticker="META", name="Meta")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.post(
            "/api/v1/external/alerts",
            json={"ticker": "META", "alert_type": "price_above", "target_value": 500.0},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 201
        alert = res.json()
        assert alert["ticker"] == "META"
        assert alert["alert_type"] == "price_above"
        assert alert["target_value"] == 500.0

    async def test_alert_limit_100(self, client):
        jwt = await register_and_login(client, email="alert-lim@example.com")
        await add_to_watchlist(client, jwt, ticker="AAPL", name="Apple")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        # Create 100 alerts
        for i in range(100):
            res = await client.post(
                "/api/v1/external/alerts",
                json={"ticker": "AAPL", "alert_type": "price_above", "target_value": float(100 + i)},
                headers=api_auth(token["token"]),
            )
            assert res.status_code == 201, f"#{i}: {res.text}"
        # 101st should be rejected
        res = await client.post(
            "/api/v1/external/alerts",
            json={"ticker": "AAPL", "alert_type": "price_above", "target_value": 999.0},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 400
        assert "Limit" in (res.json().get("detail") or "")

    async def test_alert_update_target_value(self, client):
        jwt = await register_and_login(client, email="alert-up@example.com")
        await add_to_watchlist(client, jwt, ticker="NFLX", name="Netflix")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        created = await client.post(
            "/api/v1/external/alerts",
            json={"ticker": "NFLX", "alert_type": "price_above", "target_value": 600.0},
            headers=api_auth(token["token"]),
        )
        alert_id = created.json()["id"]
        upd = await client.patch(
            f"/api/v1/external/alerts/{alert_id}",
            json={"target_value": 700.0},
            headers=api_auth(token["token"]),
        )
        assert upd.status_code == 200
        out = upd.json()
        assert out["target_value"] == 700.0
        assert out["is_active"] is True
        assert out["is_triggered"] is False

    async def test_alert_delete_then_404(self, client):
        jwt = await register_and_login(client, email="alert-del@example.com")
        await add_to_watchlist(client, jwt, ticker="ORCL", name="Oracle")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        created = await client.post(
            "/api/v1/external/alerts",
            json={"ticker": "ORCL", "alert_type": "price_below", "target_value": 100.0},
            headers=api_auth(token["token"]),
        )
        alert_id = created.json()["id"]
        d1 = await client.delete(
            f"/api/v1/external/alerts/{alert_id}",
            headers=api_auth(token["token"]),
        )
        assert d1.status_code == 204
        d2 = await client.delete(
            f"/api/v1/external/alerts/{alert_id}",
            headers=api_auth(token["token"]),
        )
        assert d2.status_code == 404

    async def test_read_only_token_can_list_alerts(self, client):
        jwt = await register_and_login(client, email="alert-list@example.com")
        await add_to_watchlist(client, jwt, ticker="IBM", name="IBM")
        wt = await create_api_token_with_scope(client, jwt, name="w", write=True)
        await client.post(
            "/api/v1/external/alerts",
            json={"ticker": "IBM", "alert_type": "price_above", "target_value": 250.0},
            headers=api_auth(wt["token"]),
        )
        rt = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.get(
            "/api/v1/external/alerts?ticker=IBM",
            headers=api_auth(rt["token"]),
        )
        assert res.status_code == 200
        alerts = res.json()
        assert len(alerts) == 1
        assert alerts[0]["ticker"] == "IBM"


# --- Cascade-Delete Regression (Phase 1.4) ---

class TestCascadeDeleteOnWatchlistRemove:
    async def test_keeps_alert_when_position_active(self, client):
        """Stop-Loss-Alert auf Portfolio-Ticker ueberlebt Watchlist-Remove."""
        from db import async_session as test_async_session
        from models.position import Position, AssetType
        import uuid as _uuid

        jwt = await register_and_login(client, email="cascade-keep@example.com")
        # Add ticker to both watchlist and an active position
        wl_res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "DUAL", "name": "Dual Holding"},
            headers=jwt_auth(jwt),
        )
        item_id = wl_res.json()["id"]

        # Insert an active Position directly via the test session
        async with test_async_session() as db:
            from sqlalchemy import select as _select
            from models.user import User as _User
            user_q = await db.execute(_select(_User).where(_User.email == "cascade-keep@example.com"))
            u = user_q.scalar_one()
            db.add(Position(
                id=_uuid.uuid4(),
                user_id=u.id,
                ticker="DUAL",
                name="Dual Holding",
                type=AssetType.stock,
                currency="USD",
                shares=10,
                cost_basis_chf=1000,
                is_active=True,
            ))
            await db.commit()

        # Create an alert for the dual ticker
        await client.post(
            "/api/price-alerts",
            json={"ticker": "DUAL", "alert_type": "price_below", "target_value": 50},
            headers=jwt_auth(jwt),
        )
        # Remove from watchlist
        d = await client.delete(f"/api/analysis/watchlist/{item_id}", headers=jwt_auth(jwt))
        assert d.status_code == 204
        # Alert should still exist
        post = await client.get("/api/price-alerts", headers=jwt_auth(jwt))
        assert len(post.json()) == 1, f"alert should survive when position is active: {post.json()}"

    async def test_cascades_alert_when_no_position(self, client):
        """Watchlist-only Ticker → Cascade-Delete bleibt aktiv."""
        jwt = await register_and_login(client, email="cascade-drop@example.com")
        wl_res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "WLON", "name": "Watchlist-Only"},
            headers=jwt_auth(jwt),
        )
        item_id = wl_res.json()["id"]
        await client.post(
            "/api/price-alerts",
            json={"ticker": "WLON", "alert_type": "price_above", "target_value": 100},
            headers=jwt_auth(jwt),
        )
        d = await client.delete(f"/api/analysis/watchlist/{item_id}", headers=jwt_auth(jwt))
        assert d.status_code == 204
        post = await client.get("/api/price-alerts", headers=jwt_auth(jwt))
        assert len(post.json()) == 0, "alert should cascade when no position holds the ticker"
