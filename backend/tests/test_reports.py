"""Tests fuer den Report-Vault.

Upload (Token, write-Scope, idempotent) via /api/v1/external/reports,
Read/List/Tag/Export/Delete (JWT) via /api/reports. Plus User-Scoping.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def jwt_auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def api_auth(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def create_token(client, jwt, name="t", write=False) -> str:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": name, "write_access": write},
        headers=jwt_auth(jwt),
    )
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _report(**over) -> dict:
    base = {
        "category": "daily_brief",
        "title": "Daily Brief 2026-05-25",
        "report_date": "2026-05-25",
        "body": "# Brief\n\nSome **markdown** content.",
        "source": "claude-finance",
        "source_path": "Output/2026-05-25_daily_brief.md",
    }
    base.update(over)
    return base


async def _upload(client, key, **over):
    return await client.post("/api/v1/external/reports", json=_report(**over), headers=api_auth(key))


# --- Upload / Idempotenz ---

async def test_upload_created_then_unchanged_then_updated(client):
    jwt = await register_and_login(client, "rv1@test.local")
    key = await create_token(client, jwt, write=True)

    res = await _upload(client, key)
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "created"
    rid = res.json()["id"]

    # gleicher source_path + gleicher body → unchanged
    res2 = await _upload(client, key)
    assert res2.json()["status"] == "unchanged"
    assert res2.json()["id"] == rid

    # gleicher source_path, neuer body → updated
    res3 = await _upload(client, key, body="# Brief v2\n\nUpdated.")
    assert res3.json()["status"] == "updated"
    assert res3.json()["id"] == rid

    # Read bestaetigt neuen Body
    got = await client.get(f"/api/reports/{rid}", headers=jwt_auth(jwt))
    assert got.status_code == 200
    assert "Updated." in got.json()["body"]


async def test_upload_requires_write_scope(client):
    jwt = await register_and_login(client, "rv2@test.local")
    read_key = await create_token(client, jwt, write=False)
    res = await _upload(client, read_key)
    assert res.status_code == 403


async def test_update_preserves_user_tags(client):
    jwt = await register_and_login(client, "rv3@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    # User taggt im UI
    await client.patch(f"/api/reports/{rid}", json={"tags": ["wichtig", "silber"]}, headers=jwt_auth(jwt))

    # Sync pusht geaenderten Body → tags muessen erhalten bleiben
    await _upload(client, key, body="# Brief geaendert")
    got = await client.get(f"/api/reports/{rid}", headers=jwt_auth(jwt))
    assert got.json()["tags"] == ["wichtig", "silber"]


# --- List / Filter ---

async def test_list_filters_and_facets(client):
    jwt = await register_and_login(client, "rv4@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md", category="daily_brief", title="A", body="alpha apple")
    await _upload(client, key, source_path="b.md", category="trade", title="B", body="beta banana")
    await _upload(client, key, source_path="c.md", category="trade", title="C", body="gamma apple")

    # Kein Filter → alle 3, Facetten vollstaendig
    res = await client.get("/api/reports", headers=jwt_auth(jwt))
    body = res.json()
    assert body["total"] == 3
    assert set(body["categories"]) == {"daily_brief", "trade"}

    # category-Filter
    res = await client.get("/api/reports?category=trade", headers=jwt_auth(jwt))
    assert res.json()["total"] == 2
    # Facetten bleiben vollstaendig trotz Filter
    assert set(res.json()["categories"]) == {"daily_brief", "trade"}

    # Volltextsuche (title + body)
    res = await client.get("/api/reports?q=apple", headers=jwt_auth(jwt))
    titles = {r["title"] for r in res.json()["results"]}
    assert titles == {"A", "C"}


async def test_list_tag_filter_and_pagination(client):
    jwt = await register_and_login(client, "rv5@test.local")
    key = await create_token(client, jwt, write=True)
    for i in range(5):
        await _upload(client, key, source_path=f"p{i}.md", title=f"R{i}",
                      report_date=f"2026-05-{20 + i:02d}")

    res = await client.get("/api/reports?per_page=2&page=1", headers=jwt_auth(jwt))
    body = res.json()
    assert body["total"] == 5
    assert len(body["results"]) == 2
    # Neuestes Datum zuerst
    assert body["results"][0]["title"] == "R4"

    res2 = await client.get("/api/reports?per_page=2&page=3", headers=jwt_auth(jwt))
    assert len(res2.json()["results"]) == 1


async def test_tag_filter(client):
    jwt = await register_and_login(client, "rv6@test.local")
    key = await create_token(client, jwt, write=True)
    r1 = (await _upload(client, key, source_path="x.md", title="X")).json()["id"]
    await _upload(client, key, source_path="y.md", title="Y")
    await client.patch(f"/api/reports/{r1}", json={"tags": ["macro"]}, headers=jwt_auth(jwt))

    res = await client.get("/api/reports?tag=macro", headers=jwt_auth(jwt))
    assert res.json()["total"] == 1
    assert res.json()["results"][0]["title"] == "X"
    assert "macro" in res.json()["all_tags"]


# --- User-Scoping ---

async def test_user_cannot_see_other_users_report(client):
    jwt_a = await register_and_login(client, "rva@test.local")
    key_a = await create_token(client, jwt_a, write=True)
    rid = (await _upload(client, key_a)).json()["id"]

    jwt_b = await register_and_login(client, "rvb@test.local")
    # B sieht A's Report nicht in der Liste
    res = await client.get("/api/reports", headers=jwt_auth(jwt_b))
    assert res.json()["total"] == 0
    # und kann ihn nicht direkt lesen
    got = await client.get(f"/api/reports/{rid}", headers=jwt_auth(jwt_b))
    assert got.status_code == 404


# --- Tags-Update ---

async def test_tag_update_dedups_and_limits(client):
    jwt = await register_and_login(client, "rv7@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    res = await client.patch(
        f"/api/reports/{rid}", json={"tags": ["a", "a", " b ", "b"]}, headers=jwt_auth(jwt)
    )
    assert res.status_code == 200
    assert res.json()["tags"] == ["a", "b"]

    # Limit
    res2 = await client.patch(
        f"/api/reports/{rid}", json={"tags": [f"t{i}" for i in range(25)]}, headers=jwt_auth(jwt)
    )
    assert res2.status_code == 422


# --- Export ---

async def test_export_returns_markdown_attachment(client):
    jwt = await register_and_login(client, "rv8@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key, body="# Title\n\nbody")).json()["id"]

    res = await client.get(f"/api/reports/{rid}/export", headers=jwt_auth(jwt))
    assert res.status_code == 200
    assert "text/markdown" in res.headers["content-type"]
    assert "attachment" in res.headers["content-disposition"]
    assert res.text == "# Title\n\nbody"


# --- Prune (Reconciliation) ---

async def _prune(client, key, source_paths, source="claude-finance"):
    return await client.post(
        "/api/v1/external/reports/prune",
        json={"source": source, "source_paths": source_paths},
        headers=api_auth(key),
    )


async def test_prune_removes_orphans_keeps_current(client):
    jwt = await register_and_login(client, "rvp1@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md", title="A")
    await _upload(client, key, source_path="b.md", title="B")
    await _upload(client, key, source_path="c.md", title="C")

    # a.md + c.md existieren noch, b.md wurde geloescht/umbenannt
    res = await _prune(client, key, ["a.md", "c.md"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["deleted"] == 1
    assert body["kept"] == 2

    listed = await client.get("/api/reports", headers=jwt_auth(jwt))
    titles = {r["title"] for r in listed.json()["results"]}
    assert titles == {"A", "C"}


async def test_prune_empty_list_is_noop(client):
    """KRITISCH: leere source_paths darf NICHT den ganzen Vault loeschen."""
    jwt = await register_and_login(client, "rvp2@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md")
    await _upload(client, key, source_path="b.md")

    res = await _prune(client, key, [])
    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] == 0
    assert body["kept"] == 2
    assert body["warning"] == "empty_source_paths_skipped"

    listed = await client.get("/api/reports", headers=jwt_auth(jwt))
    assert listed.json()["total"] == 2


async def test_prune_scoped_to_source(client):
    """Prune trifft nur die eigene source — fremde/andere bleiben."""
    jwt = await register_and_login(client, "rvp3@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md", source="claude-finance", title="A-CF")
    await _upload(client, key, source_path="other.md", source="some-other-tool", title="OTHER")

    # Prune mit claude-finance + Liste ohne a.md → a.md (cf) wird geloescht,
    # OTHER (andere source) bleibt unberuehrt.
    res = await _prune(client, key, ["zzz.md"], source="claude-finance")
    assert res.json()["deleted"] == 1  # nur a.md

    listed = await client.get("/api/reports", headers=jwt_auth(jwt))
    titles = {r["title"] for r in listed.json()["results"]}
    assert titles == {"OTHER"}  # andere source unberuehrt, cf-Waise weg


async def test_prune_idempotent(client):
    jwt = await register_and_login(client, "rvp4@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md")
    await _upload(client, key, source_path="b.md")

    first = await _prune(client, key, ["a.md"])
    assert first.json()["deleted"] == 1
    second = await _prune(client, key, ["a.md"])
    assert second.json()["deleted"] == 0
    assert second.json()["kept"] == 1


async def test_prune_requires_write_scope(client):
    jwt = await register_and_login(client, "rvp5@test.local")
    read_key = await create_token(client, jwt, write=False)
    res = await _prune(client, read_key, ["a.md"])
    assert res.status_code == 403


async def test_prune_user_scoped(client):
    """Prune von User A laesst User Bs Reports unberuehrt."""
    jwt_a = await register_and_login(client, "rvpa@test.local")
    key_a = await create_token(client, jwt_a, write=True)
    await _upload(client, key_a, source_path="a.md")

    jwt_b = await register_and_login(client, "rvpb@test.local")
    key_b = await create_token(client, jwt_b, write=True)
    await _upload(client, key_b, source_path="a.md", title="B-owned")

    # A pruned alles (leere-ausser-fremde Liste) → nur As a.md weg
    await _prune(client, key_a, ["zzz.md"])

    listed_b = await client.get("/api/reports", headers=jwt_auth(jwt_b))
    assert listed_b.json()["total"] == 1
    assert listed_b.json()["results"][0]["title"] == "B-owned"


# --- Delete ---

async def test_delete_report(client):
    jwt = await register_and_login(client, "rv9@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    res = await client.delete(f"/api/reports/{rid}", headers=jwt_auth(jwt))
    assert res.status_code == 204

    got = await client.get(f"/api/reports/{rid}", headers=jwt_auth(jwt))
    assert got.status_code == 404
