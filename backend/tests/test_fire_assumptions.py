"""FIRE-Annahmen: serverseitige Persistenz (intern + externe API).

Deckt ab:
  - neuer User -> Defaults (GET)
  - PUT speichert + GET liest dieselben Werte zurueck (Round-Trip)
  - capital_base "net_worth" wird auf "with_pension" migriert
  - interner PUT klemmt out-of-bounds (kein 422), Frontend-freundlich
  - externer PUT ist write-gated (read-Token -> 403) und strikt (out-of-bounds 422)
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def _jwt(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    return (await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})).json()["access_token"]


async def _token(client: AsyncClient, jwt: str, write: bool) -> str:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "w" if write else "r", "write_access": write},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert res.status_code == 201, res.text
    return res.json()["token"]


async def test_new_user_gets_defaults(client):
    jwt = await _jwt(client, "fire-defaults@test.local")
    res = await client.get("/api/analysis/fire-assumptions", headers={"Authorization": f"Bearer {jwt}"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["capital_base"] == "with_pension"
    assert body["withdrawal_rate_pct"] == 4.0
    assert body["target_annual_spending_chf"] == 80000.0


async def test_put_then_get_roundtrip(client):
    jwt = await _jwt(client, "fire-roundtrip@test.local")
    payload = {
        "capital_base": "liquid",
        "annual_return_pct": 6.5,
        "annual_savings_chf": 25000,
        "withdrawal_rate_pct": 3.5,
        "target_annual_spending_chf": 60000,
    }
    put = await client.put("/api/analysis/fire-assumptions", json=payload, headers={"Authorization": f"Bearer {jwt}"})
    assert put.status_code == 200, put.text
    got = (await client.get("/api/analysis/fire-assumptions", headers={"Authorization": f"Bearer {jwt}"})).json()
    assert got["capital_base"] == "liquid"
    assert got["annual_return_pct"] == 6.5
    assert got["withdrawal_rate_pct"] == 3.5
    assert got["target_annual_spending_chf"] == 60000.0


async def test_net_worth_base_is_migrated(client):
    """Die entfernte Basis "net_worth" (ueberzeichnete FIRE) -> with_pension."""
    jwt = await _jwt(client, "fire-migrate@test.local")
    # Intern erlaubt freie Strings; das Service migriert net_worth.
    put = await client.put(
        "/api/analysis/fire-assumptions",
        json={"capital_base": "net_worth", "annual_return_pct": 5, "annual_savings_chf": 40000,
              "withdrawal_rate_pct": 4, "target_annual_spending_chf": 80000},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["capital_base"] == "with_pension"


async def test_internal_put_clamps_out_of_bounds(client):
    """Interner PUT klemmt (statt 422) — stale/extreme Werte werden gebogen."""
    jwt = await _jwt(client, "fire-clamp@test.local")
    put = await client.put(
        "/api/analysis/fire-assumptions",
        json={"capital_base": "liquid", "annual_return_pct": 999, "annual_savings_chf": 40000,
              "withdrawal_rate_pct": 4, "target_annual_spending_chf": 80000},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["annual_return_pct"] == 30.0  # auf obere Bound geklemmt


async def test_external_put_requires_write(client):
    jwt = await _jwt(client, "fire-ext-read@test.local")
    read_token = await _token(client, jwt, write=False)
    res = await client.put(
        "/api/v1/external/analysis/fire-assumptions",
        json={"capital_base": "liquid", "annual_return_pct": 5, "annual_savings_chf": 40000,
              "withdrawal_rate_pct": 4, "target_annual_spending_chf": 80000},
        headers={"X-API-Key": read_token},
    )
    assert res.status_code == 403, res.text


async def test_external_put_write_persists(client):
    jwt = await _jwt(client, "fire-ext-write@test.local")
    write_token = await _token(client, jwt, write=True)
    res = await client.put(
        "/api/v1/external/analysis/fire-assumptions",
        json={"capital_base": "liquid", "annual_return_pct": 7, "annual_savings_chf": 30000,
              "withdrawal_rate_pct": 3, "target_annual_spending_chf": 50000},
        headers={"X-API-Key": write_token},
    )
    assert res.status_code == 200, res.text
    # Read via internem GET (selber User) -> persistiert.
    got = (await client.get("/api/analysis/fire-assumptions", headers={"Authorization": f"Bearer {jwt}"})).json()
    assert got["annual_return_pct"] == 7.0
    assert got["capital_base"] == "liquid"


async def test_external_put_strict_rejects_out_of_bounds(client):
    """Externe Schreib-Schemas sind strikt: out-of-bounds -> 422 (nicht klemmen)."""
    jwt = await _jwt(client, "fire-ext-strict@test.local")
    write_token = await _token(client, jwt, write=True)
    res = await client.put(
        "/api/v1/external/analysis/fire-assumptions",
        json={"capital_base": "liquid", "annual_return_pct": 999, "annual_savings_chf": 40000,
              "withdrawal_rate_pct": 4, "target_annual_spending_chf": 80000},
        headers={"X-API-Key": write_token},
    )
    assert res.status_code == 422, res.text
