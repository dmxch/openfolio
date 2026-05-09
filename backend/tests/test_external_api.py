"""Tests for the external REST API (/api/v1/external/*).

Covers:
- X-API-Key auth (missing / invalid / revoked / valid)
- Token-Management endpoints (create / list / revoke)
- PII-Sichtbarkeit: ``bank_name``/``address``/``notes``/``tenant`` als Klartext,
  ``iban`` ausschliesslich maskiert (v0.38+ — Token-Eigentümer darf eigene
  Daten lesen, IBAN bleibt aus Sicherheitsgründen identisch zum UI maskiert
  über ``decrypt_and_mask_iban``).
- Smoke tests für read endpoints inkl. Marker-Konsistenz (notes_last_api_*)
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


# --- Smoke + PII-Sichtbarkeit (v0.38+) ---

class TestExternalEndpoints:
    async def test_portfolio_summary_response_shape(self, client):
        jwt = await register_and_login(client)
        created = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/portfolio/summary",
            headers=api_auth(created["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        for key in ("total_invested_chf", "total_market_value_chf", "positions", "allocations"):
            assert key in body

    async def test_portfolio_summary_pii_visible_iban_masked(self, client):
        """v0.38+: bank_name als Klartext, IBAN nur maskiert (••••...1234)."""
        jwt = await register_and_login(client, email="pii-summary@example.com")
        # Cash-Position mit Bank-Daten anlegen
        await client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "CASH-CHF",
                "name": "CHF Konto UBS",
                "type": "cash",
                "currency": "CHF",
                "shares": 1,
                "cost_basis_chf": 50000,
                "bank_name": "UBS Switzerland AG",
                "iban": "CH9300762011623852957",
            },
            headers=jwt_auth(jwt),
        )
        token = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/portfolio/summary",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        # Klartext-IBAN darf NIE auftauchen
        assert "CH9300762011623852957" not in res.text
        # bank_name als Klartext sichtbar (Token-Eigentümer)
        positions = res.json()["positions"]
        cash = next((p for p in positions if p["ticker"] == "CASH-CHF"), None)
        assert cash is not None
        assert cash.get("bank_name") == "UBS Switzerland AG"
        # IBAN maskiert: letzte 4 Stellen + Bullet-Padding
        assert cash.get("iban", "").endswith("2957")
        assert "•" in cash.get("iban", "")

    async def test_positions_list_pii_visible(self, client):
        jwt = await register_and_login(client, email="pii-positions@example.com")
        await client.post(
            "/api/portfolio/positions",
            json={
                "ticker": "CASH-USD", "name": "USD Konto",
                "type": "cash", "currency": "USD",
                "shares": 1, "cost_basis_chf": 1000,
                "bank_name": "Sample Bank",
                "iban": "CH5604835012345678901",
            },
            headers=jwt_auth(jwt),
        )
        token = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/positions",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        assert "positions" in body
        cash = next((p for p in body["positions"] if p["ticker"] == "CASH-USD"), None)
        assert cash is not None
        assert cash.get("bank_name") == "Sample Bank"
        assert cash.get("iban", "").endswith("8901")
        # Klartext der IBAN niemals
        assert "CH5604835012345678901" not in res.text

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
    async def test_immobilien_list_includes_pii(self, client):
        """v0.38+: address/notes/bank werden ausgeliefert (Token-Eigentümer)."""
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
        assert prop["name"] == "Testhaus"
        assert "ltv" in prop
        assert prop.get("address") == "Musterstrasse 1"
        assert prop.get("notes") == "geheime Notiz"
        assert "mortgages" in prop and len(prop["mortgages"]) == 1
        assert prop["mortgages"][0].get("bank") == "GeheimBank AG"

    async def test_immobilie_detail_includes_pii(self, client):
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
        assert body.get("address") == "Musterstrasse 1"
        assert "mortgages" in body
        assert body["mortgages"][0].get("bank") == "GeheimBank AG"

    async def test_hypotheken_list_includes_bank(self, client):
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
        assert m.get("bank") == "GeheimBank AG"

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
    async def test_vorsorge_list_includes_pii_iban_masked(self, client):
        """v0.38+: bank_name/notes als Klartext, IBAN maskiert."""
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
        assert acc.get("bank_name") == "GeheimBank Vorsorge"
        assert acc.get("notes") == "interne Notiz"
        # IBAN maskiert: nicht im Klartext, aber endet auf letzte 4 Stellen
        assert "CH9300762011623852957" not in res.text
        assert acc.get("iban", "").endswith("2957")
        assert "•" in acc.get("iban", "")

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

    async def test_read_only_get_watchlist_includes_notes_and_markers(self, client):
        """v0.38+: read-only Tokens sehen Notes UND die API-Provenienz-Marker.

        Der ``/watchlist``-Skill nutzt ``notes_last_api_write_at`` und
        ``notes_last_api_token_name`` als Manuell-vs-via-API-Indikator —
        ohne sie geht die Sync-Logik kaputt.
        """
        jwt = await register_and_login(client, email="notes-marker@example.com")
        await add_to_watchlist(client, jwt, ticker="AMD", name="AMD")
        wt = await create_api_token_with_scope(client, jwt, name="writer", write=True)
        await client.patch(
            "/api/v1/external/watchlist/AMD/notes",
            json={"content": "via api", "mode": "replace"},
            headers=api_auth(wt["token"]),
        )
        rt = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.get(
            "/api/v1/external/watchlist", headers=api_auth(rt["token"])
        )
        amd = next(i for i in res.json()["items"] if i["ticker"] == "AMD")
        assert amd.get("notes") == "via api"
        assert amd.get("notes_last_api_write_at") is not None
        assert amd.get("notes_last_api_token_name") == "writer"

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


# --- Schreib-API: Watchlist Add/Remove ---

class TestExternalWatchlistAddRemove:
    async def test_read_only_token_cannot_add(self, client):
        jwt = await register_and_login(client, email="wladd-r@example.com")
        token = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.post(
            "/api/v1/external/watchlist",
            json={"ticker": "AAPL", "name": "Apple Inc."},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 403

    async def test_write_token_adds_ticker(self, client):
        jwt = await register_and_login(client, email="wladd-w@example.com")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.post(
            "/api/v1/external/watchlist",
            json={"ticker": "msft", "name": "Microsoft", "sector": "Technology"},
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 201
        body = res.json()
        # Ticker normalized to uppercase
        assert body["ticker"] == "MSFT"
        assert body["name"] == "Microsoft"
        assert body["sector"] == "Technology"
        assert "id" in body
        # Visible in GET
        get = await client.get(
            "/api/v1/external/watchlist", headers=api_auth(token["token"])
        )
        tickers = [i["ticker"] for i in get.json()["items"]]
        assert "MSFT" in tickers

    async def test_duplicate_ticker_returns_409(self, client):
        jwt = await register_and_login(client, email="wldup@example.com")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        await client.post(
            "/api/v1/external/watchlist",
            json={"ticker": "AAPL", "name": "Apple"},
            headers=api_auth(token["token"]),
        )
        dup = await client.post(
            "/api/v1/external/watchlist",
            json={"ticker": "AAPL", "name": "Apple"},
            headers=api_auth(token["token"]),
        )
        assert dup.status_code == 409
        assert "Watchlist" in (dup.json().get("detail") or "")

    async def test_read_only_token_cannot_delete(self, client):
        jwt = await register_and_login(client, email="wldel-r@example.com")
        await add_to_watchlist(client, jwt, ticker="AAPL", name="Apple")
        token = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.delete(
            "/api/v1/external/watchlist/AAPL",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 403

    async def test_delete_existing_ticker(self, client):
        jwt = await register_and_login(client, email="wldel-w@example.com")
        await add_to_watchlist(client, jwt, ticker="AAPL", name="Apple")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        d = await client.delete(
            "/api/v1/external/watchlist/AAPL",
            headers=api_auth(token["token"]),
        )
        assert d.status_code == 204
        get = await client.get(
            "/api/v1/external/watchlist", headers=api_auth(token["token"])
        )
        tickers = [i["ticker"] for i in get.json()["items"]]
        assert "AAPL" not in tickers

    async def test_delete_unknown_ticker_returns_404(self, client):
        jwt = await register_and_login(client, email="wldel-404@example.com")
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        res = await client.delete(
            "/api/v1/external/watchlist/ZZZZZ",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 404

    async def test_delete_keeps_alert_when_position_active(self, client):
        """External DELETE /watchlist/{ticker} respects the same Cascade-Korrektur:
        Stop-Loss-Alarme auf aktiven Positionen ueberleben."""
        from db import async_session as test_async_session
        from models.position import Position, AssetType
        import uuid as _uuid
        from sqlalchemy import select as _select
        from models.user import User as _User

        jwt = await register_and_login(client, email="wldel-keep@example.com")
        await add_to_watchlist(client, jwt, ticker="DUAL2", name="Dual Holding 2")
        # Insert active position directly
        async with test_async_session() as db:
            user_q = await db.execute(_select(_User).where(_User.email == "wldel-keep@example.com"))
            u = user_q.scalar_one()
            db.add(Position(
                id=_uuid.uuid4(),
                user_id=u.id,
                ticker="DUAL2",
                name="Dual Holding 2",
                type=AssetType.stock,
                currency="USD",
                shares=10,
                cost_basis_chf=1000,
                is_active=True,
            ))
            await db.commit()
        # Create an alert
        await client.post(
            "/api/price-alerts",
            json={"ticker": "DUAL2", "alert_type": "price_below", "target_value": 50},
            headers=jwt_auth(jwt),
        )
        # External DELETE
        token = await create_api_token_with_scope(client, jwt, name="w", write=True)
        d = await client.delete(
            "/api/v1/external/watchlist/DUAL2",
            headers=api_auth(token["token"]),
        )
        assert d.status_code == 204
        # Alert survives
        post = await client.get("/api/price-alerts", headers=jwt_auth(jwt))
        assert len(post.json()) == 1


# --- Stop-Loss (Read + Write) ---

async def _seed_stock_with_buy(client, jwt: str, ticker: str = "AAPL", price: float = 150.0):
    """Lege eine Stock-Position + Buy-Transaction an, damit Stop-Loss-Endpoints
    eine echte tradable Position haben. Returns (position_id, txn_id)."""
    pos = await client.post(
        "/api/portfolio/positions",
        json={
            "ticker": ticker, "name": f"{ticker} Inc.",
            "type": "stock", "currency": "USD",
            "shares": 0, "cost_basis_chf": 0,
        },
        headers=jwt_auth(jwt),
    )
    assert pos.status_code in (200, 201), pos.text
    position_id = pos.json()["id"]
    txn = await client.post(
        "/api/transactions",
        json={
            "position_id": position_id,
            "type": "buy",
            "date": "2025-01-15",
            "shares": 10,
            "price_per_share": price,
            "currency": "USD",
            "fx_rate_to_chf": 0.88,
            "total_chf": 10 * price * 0.88,
        },
        headers=jwt_auth(jwt),
    )
    assert txn.status_code in (200, 201), txn.text
    return position_id, txn.json()["id"]


class TestExternalStopLoss:
    async def test_read_only_token_can_read_stop_loss_status(self, client):
        jwt = await register_and_login(client, email="sl-read@example.com")
        await _seed_stock_with_buy(client, jwt, "AAPL")
        rt = await create_api_token_with_scope(client, jwt, name="r")

        res = await client.get(
            "/api/v1/external/portfolio/stop-loss-status",
            headers=api_auth(rt["token"]),
        )
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    async def test_read_only_token_cannot_patch_stop_loss(self, client):
        jwt = await register_and_login(client, email="sl-rdeny@example.com")
        position_id, _ = await _seed_stock_with_buy(client, jwt, "MSFT")
        rt = await create_api_token_with_scope(client, jwt, name="r")

        res = await client.patch(
            f"/api/v1/external/positions/by-id/{position_id}/stop-loss",
            json={"stop_loss_price": 140.0},
            headers=api_auth(rt["token"]),
        )
        assert res.status_code == 403

    async def test_write_token_patches_stop_loss_default_not_confirmed(self, client):
        """v0.38+ Vertrag: confirmed_at_broker MUSS ohne Feld False sein."""
        jwt = await register_and_login(client, email="sl-default@example.com")
        position_id, _ = await _seed_stock_with_buy(client, jwt, "GOOG", price=130.0)
        wt = await create_api_token_with_scope(client, jwt, name="w", write=True)

        res = await client.patch(
            f"/api/v1/external/positions/by-id/{position_id}/stop-loss",
            json={"stop_loss_price": 110.0, "method": "manual"},
            headers=api_auth(wt["token"]),
        )
        assert res.status_code == 200
        # Persistenz prüfen — confirmed_at_broker MUSS False sein
        check = await client.get(
            f"/api/v1/external/positions/by-id/{position_id}",
            headers=api_auth(wt["token"]),
        )
        assert check.status_code == 200
        body = check.json()
        assert body["stop_loss_price"] == 110.0
        assert body["stop_loss_method"] == "manual"
        assert body["stop_loss_confirmed_at_broker"] is False

    async def test_write_token_patches_stop_loss_explicit_confirmed(self, client):
        jwt = await register_and_login(client, email="sl-conf@example.com")
        position_id, _ = await _seed_stock_with_buy(client, jwt, "TSLA", price=200.0)
        wt = await create_api_token_with_scope(client, jwt, name="w", write=True)

        res = await client.patch(
            f"/api/v1/external/positions/by-id/{position_id}/stop-loss",
            json={
                "stop_loss_price": 180.0,
                "method": "atr",
                "confirmed_at_broker": True,
            },
            headers=api_auth(wt["token"]),
        )
        assert res.status_code == 200
        check = await client.get(
            f"/api/v1/external/positions/by-id/{position_id}",
            headers=api_auth(wt["token"]),
        )
        body = check.json()
        assert body["stop_loss_price"] == 180.0
        assert body["stop_loss_confirmed_at_broker"] is True

    async def test_audit_log_records_stop_loss_update(self, client, db):
        from sqlalchemy import select as _select
        jwt = await register_and_login(client, email="sl-audit@example.com")
        position_id, _ = await _seed_stock_with_buy(client, jwt, "NVDA", price=400.0)
        wt = await create_api_token_with_scope(client, jwt, name="w", write=True)
        await client.patch(
            f"/api/v1/external/positions/by-id/{position_id}/stop-loss",
            json={"stop_loss_price": 350.0},
            headers=api_auth(wt["token"]),
        )
        from models.api_write_log import ApiWriteLog
        rows = (await db.execute(_select(ApiWriteLog))).scalars().all()
        assert any(r.action == "stop_loss_update" for r in rows)


class TestExternalStopLossBatch:
    async def test_batch_cap_rejects_more_than_max_items(self, client):
        """v0.38+ Cap: max. 100 Items pro Batch (verhindert Skript-Loops)."""
        jwt = await register_and_login(client, email="sl-cap@example.com")
        wt = await create_api_token_with_scope(client, jwt, name="w", write=True)
        items = [
            {"ticker": f"T{i}", "stop_loss_price": 50.0}
            for i in range(101)
        ]
        res = await client.post(
            "/api/v1/external/portfolio/stop-loss/batch",
            json={"items": items},
            headers=api_auth(wt["token"]),
        )
        assert res.status_code == 422

    async def test_read_only_token_cannot_batch(self, client):
        jwt = await register_and_login(client, email="sl-batch-rdeny@example.com")
        rt = await create_api_token_with_scope(client, jwt, name="r")
        res = await client.post(
            "/api/v1/external/portfolio/stop-loss/batch",
            json={"items": [{"ticker": "AAPL", "stop_loss_price": 140.0}]},
            headers=api_auth(rt["token"]),
        )
        assert res.status_code == 403


# --- Transactions (Read) ---

class TestExternalTransactions:
    async def test_list_transactions_returns_seeded_buy(self, client):
        jwt = await register_and_login(client, email="txn-list@example.com")
        await _seed_stock_with_buy(client, jwt, "AAPL", price=150.0)
        token = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/transactions",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["total"] >= 1
        assert any(t["type"] == "buy" and t["ticker"] == "AAPL" for t in body["items"])

    async def test_filter_by_type(self, client):
        jwt = await register_and_login(client, email="txn-type@example.com")
        await _seed_stock_with_buy(client, jwt, "MSFT", price=300.0)
        token = await create_api_token(client, jwt)
        # Filter type=sell sollte 0 ergeben (nur Buy gesetzt)
        res = await client.get(
            "/api/v1/external/transactions?type=sell",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        assert res.json()["total"] == 0

    async def test_invalid_type_returns_422(self, client):
        jwt = await register_and_login(client, email="txn-inv@example.com")
        token = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/transactions?type=bogus",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 422

    async def test_unauthenticated(self, client):
        res = await client.get("/api/v1/external/transactions")
        assert res.status_code == 401


# --- Settings (Secrets maskiert) ---

class TestExternalSettings:
    async def test_settings_includes_safe_fields(self, client):
        jwt = await register_and_login(client, email="settings-safe@example.com")
        token = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/settings",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        body = res.json()
        # Safe Felder vorhanden
        assert "base_currency" in body or "broker" in body

    async def test_settings_secrets_masked(self, client):
        """Klartext-API-Keys dürfen NIE in der Response stehen."""
        jwt = await register_and_login(client, email="settings-key@example.com")
        # Setze einen FRED-Key über die interne API
        await client.put(
            "/api/settings/fred-api-key",
            json={"api_key": "fred-secret-12345"},
            headers=jwt_auth(jwt),
        )
        token = await create_api_token(client, jwt)
        res = await client.get(
            "/api/v1/external/settings",
            headers=api_auth(token["token"]),
        )
        assert res.status_code == 200
        # Key-Klartext darf nicht auftauchen
        assert "fred-secret-12345" not in res.text
        # Aber das Boolean / der Indicator schon (interne API liefert has_fred_api_key=True)
        body = res.json()
        assert body.get("has_fred_api_key") is True
