"""Integration-Tests fuer api/buckets.py.

Coverage: List, Create, Templates, Wechsel-Preview, Migration-Rollback.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _register(client, email="bucketuser@example.test", password="StrongPass123!"):
    res = await client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert res.status_code == 201, res.text
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_list_buckets_returns_system_buckets_for_new_user(client):
    h = await _register(client)
    res = await client.get("/api/portfolio/buckets", headers=h)
    assert res.status_code == 200
    data = res.json()
    names = {b["name"] for b in data["buckets"]}
    assert {"Alle Positionen", "Immobilien", "Private Equity", "Vorsorge"} <= names
    assert data["active_user_buckets"] == 0
    assert data["limit"] == 15
    # Neu-User: kein Modal
    assert data["show_onboarding_modal"] is False


async def test_create_user_bucket(client):
    h = await _register(client)
    res = await client.post(
        "/api/portfolio/buckets",
        headers=h,
        json={"name": "Core", "color": "#3b82f6", "benchmark": "URTH"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Core"
    assert body["kind"] == "user"

    listing = await client.get("/api/portfolio/buckets", headers=h)
    assert listing.json()["active_user_buckets"] == 1


async def test_template_creates_two_buckets_atomar(client):
    h = await _register(client)
    res = await client.post(
        "/api/portfolio/buckets/from-template",
        headers=h,
        json={"template_key": "core_satellite"},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["count"] == 2
    names = {b["name"] for b in data["created"]}
    assert names == {"Core", "Satellite"}


async def test_template_conflict_then_replace(client):
    """Zweites Template-Apply: ohne replace → 409, mit replace → ok."""
    h = await _register(client, email="switcher@example.test")
    first = await client.post(
        "/api/portfolio/buckets/from-template",
        headers=h,
        json={"template_key": "core_satellite"},
    )
    assert first.status_code == 201

    # FIRE-Template hat andere Namen → kein Conflict, plus 2 weitere Buckets
    second = await client.post(
        "/api/portfolio/buckets/from-template",
        headers=h,
        json={"template_key": "fire_spielgeld"},
    )
    assert second.status_code == 201

    # Nochmal core_satellite — Conflict
    third = await client.post(
        "/api/portfolio/buckets/from-template",
        headers=h,
        json={"template_key": "core_satellite"},
    )
    assert third.status_code == 409
    detail = third.json()["detail"]
    assert detail["error"] == "bucket_name_conflict"
    assert detail["can_replace"] is True

    # Mit replace_existing → success, alte Core/Satellite werden soft-deletet
    fourth = await client.post(
        "/api/portfolio/buckets/from-template",
        headers=h,
        json={"template_key": "core_satellite", "replace_existing": True},
    )
    assert fourth.status_code == 201, fourth.text

    # Listing zeigt FIRE + Spielgeld + 2 neue Core + 2 neue Satellite = 4 user-buckets
    listing = await client.get("/api/portfolio/buckets", headers=h)
    assert listing.json()["active_user_buckets"] == 4


async def test_template_unknown_returns_400(client):
    h = await _register(client)
    res = await client.post(
        "/api/portfolio/buckets/from-template",
        headers=h,
        json={"template_key": "doesnotexist"},
    )
    assert res.status_code == 400


async def test_migration_rollback_clears_user_buckets(client):
    h = await _register(client)
    # 1 Template setzen — analog Migration-Effekt
    await client.post(
        "/api/portfolio/buckets/from-template",
        headers=h,
        json={"template_key": "core_satellite"},
    )

    res = await client.post(
        "/api/portfolio/buckets/migration-rollback", headers=h
    )
    assert res.status_code == 200
    result = res.json()
    assert result["buckets_deleted"] == 2

    listing = await client.get("/api/portfolio/buckets", headers=h)
    assert listing.json()["active_user_buckets"] == 0


async def test_delete_system_bucket_400(client):
    h = await _register(client)
    listing = await client.get("/api/portfolio/buckets", headers=h)
    system = next(
        b for b in listing.json()["buckets"] if b["system_role"] == "liquid_default"
    )
    res = await client.delete(
        f"/api/portfolio/buckets/{system['id']}", headers=h
    )
    assert res.status_code == 400


async def test_bucket_target_xor_via_api(client):
    h = await _register(client)
    res = await client.post(
        "/api/portfolio/buckets",
        headers=h,
        json={"name": "X", "target_pct": 30.0, "target_chf": 50000},
    )
    assert res.status_code == 400


async def test_update_bucket_via_patch(client):
    h = await _register(client)
    created = await client.post(
        "/api/portfolio/buckets",
        headers=h,
        json={"name": "Trading", "color": "#ef4444"},
    )
    bid = created.json()["id"]
    res = await client.patch(
        f"/api/portfolio/buckets/{bid}",
        headers=h,
        json={"benchmark": "^GSPC", "color": "#10b981"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["benchmark"] == "^GSPC"
    assert body["color"] == "#10b981"


async def test_onboarding_dismiss(client):
    h = await _register(client)
    res = await client.post(
        "/api/portfolio/buckets/onboarding-dismiss", headers=h
    )
    assert res.status_code == 200
    assert res.json()["noticed_buckets_migration"] is True


async def test_get_bucket_templates(client):
    h = await _register(client)
    res = await client.get("/api/portfolio/buckets/templates", headers=h)
    assert res.status_code == 200
    tpls = res.json()["templates"]
    keys = {t["key"] for t in tpls}
    assert {"core_satellite", "fire_spielgeld"} <= keys
