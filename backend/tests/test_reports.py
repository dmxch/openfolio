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

    # a.md + c.md existieren noch, b.md wurde geloescht/umbenannt → archiviert
    res = await _prune(client, key, ["a.md", "c.md"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["archived"] == 1
    assert body["kept"] == 2

    # B verschwindet aus der aktiven Liste, lebt aber im Archiv weiter.
    listed = await client.get("/api/reports", headers=jwt_auth(jwt))
    assert {r["title"] for r in listed.json()["results"]} == {"A", "C"}
    arch = await client.get("/api/reports?archived=true", headers=jwt_auth(jwt))
    assert {r["title"] for r in arch.json()["results"]} == {"B"}


async def test_prune_empty_list_is_noop(client):
    """KRITISCH: leere source_paths darf NICHT den ganzen Vault loeschen."""
    jwt = await register_and_login(client, "rvp2@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md")
    await _upload(client, key, source_path="b.md")

    res = await _prune(client, key, [])
    assert res.status_code == 200
    body = res.json()
    assert body["archived"] == 0
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
    assert res.json()["archived"] == 1  # nur a.md

    listed = await client.get("/api/reports", headers=jwt_auth(jwt))
    titles = {r["title"] for r in listed.json()["results"]}
    assert titles == {"OTHER"}  # andere source unberuehrt, cf-Waise weg


async def test_prune_idempotent(client):
    jwt = await register_and_login(client, "rvp4@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md")
    await _upload(client, key, source_path="b.md")

    first = await _prune(client, key, ["a.md"])
    assert first.json()["archived"] == 1
    second = await _prune(client, key, ["a.md"])
    assert second.json()["archived"] == 0
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


# --- External CRUD per report_id (X-API-Key) ---
#
# Voll-CRUD ueber den Token statt JWT: GET = read-Scope, PATCH/DELETE = write.

async def test_external_list_and_get_by_id(client):
    jwt = await register_and_login(client, "ex1@test.local")
    write_key = await create_token(client, jwt, write=True)
    read_key = await create_token(client, jwt, name="r", write=False)
    rid = (await _upload(client, write_key, body="# Brief\n\nlesbar")).json()["id"]

    # Liste ueber den (read-)Token, liefert die id
    listed = await client.get("/api/v1/external/reports", headers=api_auth(read_key))
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["results"][0]["id"] == rid

    # Detail mit Body ueber read-Token
    got = await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(read_key))
    assert got.status_code == 200
    assert "lesbar" in got.json()["body"]


async def test_external_list_filters(client):
    jwt = await register_and_login(client, "ex2@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md", category="daily_brief", title="A", body="alpha apple")
    await _upload(client, key, source_path="b.md", category="trade", title="B", body="beta banana")

    res = await client.get("/api/v1/external/reports?category=trade", headers=api_auth(key))
    assert res.json()["total"] == 1
    res = await client.get("/api/v1/external/reports?q=apple", headers=api_auth(key))
    assert {r["title"] for r in res.json()["results"]} == {"A"}
    res = await client.get("/api/v1/external/reports?source=claude-finance", headers=api_auth(key))
    assert res.json()["total"] == 2


async def test_external_patch_body_recomputes_hash(client):
    jwt = await register_and_login(client, "ex3@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    res = await client.patch(
        f"/api/v1/external/reports/{rid}",
        json={"body": "# Brief v2\n\nper PATCH geaendert", "title": "Neuer Titel"},
        headers=api_auth(key),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "updated"
    assert res.json()["title"] == "Neuer Titel"

    got = await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key))
    assert "per PATCH geaendert" in got.json()["body"]

    # content_hash neu berechnet → erneuter Upload mit altem Body zaehlt als update,
    # ein Upload mit dem PATCH-Body zaehlt als unchanged.
    same = await _upload(client, key, body="# Brief v2\n\nper PATCH geaendert")
    assert same.json()["status"] == "unchanged"
    assert same.json()["id"] == rid


async def test_external_patch_empty_is_noop(client):
    jwt = await register_and_login(client, "ex4@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]
    res = await client.patch(f"/api/v1/external/reports/{rid}", json={}, headers=api_auth(key))
    assert res.status_code == 200
    assert res.json()["status"] == "unchanged"


async def test_external_patch_tags_dedups_and_limits(client):
    jwt = await register_and_login(client, "ex5@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    res = await client.patch(
        f"/api/v1/external/reports/{rid}", json={"tags": ["a", "a", " b "]}, headers=api_auth(key)
    )
    assert res.json()["tags"] == ["a", "b"]
    # leere Liste leert die Tags
    res = await client.patch(f"/api/v1/external/reports/{rid}", json={"tags": []}, headers=api_auth(key))
    assert res.json()["tags"] == []
    # Limit
    res = await client.patch(
        f"/api/v1/external/reports/{rid}", json={"tags": [f"t{i}" for i in range(25)]}, headers=api_auth(key)
    )
    assert res.status_code == 422


async def test_external_patch_and_delete_require_write_scope(client):
    jwt = await register_and_login(client, "ex6@test.local")
    write_key = await create_token(client, jwt, write=True)
    read_key = await create_token(client, jwt, name="r", write=False)
    rid = (await _upload(client, write_key)).json()["id"]

    res = await client.patch(f"/api/v1/external/reports/{rid}", json={"title": "X"}, headers=api_auth(read_key))
    assert res.status_code == 403
    res = await client.delete(f"/api/v1/external/reports/{rid}", headers=api_auth(read_key))
    assert res.status_code == 403


async def test_external_delete_by_id(client):
    jwt = await register_and_login(client, "ex7@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    res = await client.delete(f"/api/v1/external/reports/{rid}", headers=api_auth(key))
    assert res.status_code == 204
    got = await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key))
    assert got.status_code == 404


async def test_external_crud_user_scoped(client):
    jwt_a = await register_and_login(client, "exa@test.local")
    key_a = await create_token(client, jwt_a, write=True)
    rid = (await _upload(client, key_a)).json()["id"]

    jwt_b = await register_and_login(client, "exb@test.local")
    key_b = await create_token(client, jwt_b, write=True)

    # B sieht As Report weder in Liste noch per id, und kann ihn nicht aendern/loeschen
    assert (await client.get("/api/v1/external/reports", headers=api_auth(key_b))).json()["total"] == 0
    assert (await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key_b))).status_code == 404
    assert (await client.patch(f"/api/v1/external/reports/{rid}", json={"title": "hack"}, headers=api_auth(key_b))).status_code == 404
    assert (await client.delete(f"/api/v1/external/reports/{rid}", headers=api_auth(key_b))).status_code == 404


# --- Archiv (Soft-Delete neben hartem DELETE) ---

async def test_archive_hides_from_default_shows_in_archive(client):
    jwt = await register_and_login(client, "ar1@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    res = await client.post(f"/api/v1/external/reports/{rid}/archive", headers=api_auth(key))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "archived"
    assert res.json()["archived_at"] is not None

    # Default-Liste leer, Archiv-Liste zeigt den Report
    assert (await client.get("/api/v1/external/reports", headers=api_auth(key))).json()["total"] == 0
    arch = await client.get("/api/v1/external/reports?archived=true", headers=api_auth(key))
    assert arch.json()["total"] == 1
    assert arch.json()["results"][0]["id"] == rid

    # Direkt per id lesbar bleibt er (read-Pfad ignoriert den Archiv-Status)
    assert (await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key))).status_code == 200


async def test_unarchive_restores(client):
    jwt = await register_and_login(client, "ar2@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    await client.post(f"/api/v1/external/reports/{rid}/archive", headers=api_auth(key))
    res = await client.post(f"/api/v1/external/reports/{rid}/unarchive", headers=api_auth(key))
    assert res.status_code == 200
    assert res.json()["status"] == "active"
    assert res.json()["archived_at"] is None

    assert (await client.get("/api/v1/external/reports", headers=api_auth(key))).json()["total"] == 1
    assert (await client.get("/api/v1/external/reports?archived=true", headers=api_auth(key))).json()["total"] == 0


async def test_archive_is_idempotent(client):
    jwt = await register_and_login(client, "ar3@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    first = await client.post(f"/api/v1/external/reports/{rid}/archive", headers=api_auth(key))
    ts = first.json()["archived_at"]
    second = await client.post(f"/api/v1/external/reports/{rid}/archive", headers=api_auth(key))
    assert second.status_code == 200
    assert second.json()["archived_at"] == ts  # Zeitstempel bleibt unveraendert


async def test_archive_unarchive_require_write_scope(client):
    jwt = await register_and_login(client, "ar4@test.local")
    write_key = await create_token(client, jwt, write=True)
    read_key = await create_token(client, jwt, name="r", write=False)
    rid = (await _upload(client, write_key)).json()["id"]

    assert (await client.post(f"/api/v1/external/reports/{rid}/archive", headers=api_auth(read_key))).status_code == 403
    assert (await client.post(f"/api/v1/external/reports/{rid}/unarchive", headers=api_auth(read_key))).status_code == 403


async def test_reupload_resurrects_archived_report(client):
    """Re-Upload derselben Quelldatei holt einen archivierten/geprunten Report zurueck."""
    jwt = await register_and_login(client, "ar5@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key, source_path="x.md")).json()["id"]

    await client.post(f"/api/v1/external/reports/{rid}/archive", headers=api_auth(key))
    assert (await client.get("/api/v1/external/reports", headers=api_auth(key))).json()["total"] == 0

    # gleicher source_path, unveraenderter Body → unchanged, aber reaktiviert
    again = await _upload(client, key, source_path="x.md")
    assert again.json()["status"] == "unchanged"
    assert again.json()["id"] == rid
    listed = await client.get("/api/v1/external/reports", headers=api_auth(key))
    assert listed.json()["total"] == 1
    assert listed.json()["results"][0]["id"] == rid


async def test_prune_archives_then_reupload_resurrects(client):
    jwt = await register_and_login(client, "ar6@test.local")
    key = await create_token(client, jwt, write=True)
    await _upload(client, key, source_path="a.md", title="A")
    await _upload(client, key, source_path="b.md", title="B")

    # b.md verschwindet aus dem Workspace → prune archiviert
    assert (await _prune(client, key, ["a.md"])).json()["archived"] == 1
    assert (await client.get("/api/v1/external/reports?archived=true", headers=api_auth(key))).json()["total"] == 1

    # b.md taucht wieder auf → Re-Upload reaktiviert (keine Dublette)
    await _upload(client, key, source_path="b.md", title="B")
    active = await client.get("/api/v1/external/reports", headers=api_auth(key))
    assert {r["title"] for r in active.json()["results"]} == {"A", "B"}
    assert (await client.get("/api/v1/external/reports?archived=true", headers=api_auth(key))).json()["total"] == 0


async def test_delete_still_hard_deletes_archived(client):
    """Archiv und hartes DELETE koexistieren: DELETE entfernt auch aus dem Archiv endgueltig."""
    jwt = await register_and_login(client, "ar7@test.local")
    key = await create_token(client, jwt, write=True)
    rid = (await _upload(client, key)).json()["id"]

    await client.post(f"/api/v1/external/reports/{rid}/archive", headers=api_auth(key))
    assert (await client.delete(f"/api/v1/external/reports/{rid}", headers=api_auth(key))).status_code == 204
    # weder aktiv noch im Archiv
    assert (await client.get("/api/v1/external/reports?archived=true", headers=api_auth(key))).json()["total"] == 0
    assert (await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key))).status_code == 404


# --- Trade-Journal Plan->Ist-Link (End-to-End ueber die External-API) ---

def _patch_yf(monkeypatch):
    import yfinance as yf

    class _Fake:
        def __init__(self, *_a, **_kw):
            self.info = {"shortName": "Test Co", "currency": "USD"}

    monkeypatch.setattr(yf, "Ticker", _Fake)


async def _make_txn_id(client, key, ticker="AAPL") -> str:
    """Bucht eine Transaktion via External-API und gibt ihre id zurueck."""
    from datetime import date as _d
    payload = {
        "ticker": ticker, "type": "buy", "date": _d.today().isoformat(),
        "shares": 10, "price_per_share": 150.0, "currency": "USD",
        "fx_rate_to_chf": 0.9, "total_chf": 1350.0,
    }
    res = await client.post("/api/v1/external/transactions", json=payload, headers=api_auth(key))
    assert res.status_code == 201, res.text
    lst = await client.get(f"/api/v1/external/transactions?ticker={ticker}", headers=api_auth(key))
    return lst.json()["items"][0]["id"]


async def test_report_trade_link_create_and_persist(client, monkeypatch):
    _patch_yf(monkeypatch)
    jwt = await register_and_login(client, "tj-create@test.local")
    key = await create_token(client, jwt, write=True)
    txn_id = await _make_txn_id(client, key, "AAPL")

    res = await _upload(
        client, key, category="trade", title="Trade-Plan AAPL",
        source_path="Output/trade_aapl.md",
        ticker="aapl", side="buy", linked_transaction_id=txn_id,
    )
    assert res.status_code == 201, res.text
    rid = res.json()["id"]

    got = (await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key))).json()
    assert got["ticker"] == "AAPL"            # normalisiert (upper)
    assert got["side"] == "buy"
    assert got["linked_transaction_id"] == txn_id


async def test_report_trade_link_rejects_foreign_transaction(client, monkeypatch):
    _patch_yf(monkeypatch)
    # User A bucht eine Transaktion
    jwt_a = await register_and_login(client, "tj-owner@test.local")
    key_a = await create_token(client, jwt_a, write=True)
    txn_a = await _make_txn_id(client, key_a, "AAPL")
    # User B versucht, seinen Plan an A's Transaktion zu haengen -> 404
    jwt_b = await register_and_login(client, "tj-attacker@test.local")
    key_b = await create_token(client, jwt_b, write=True)
    res = await _upload(
        client, key_b, category="trade", title="Trade-Plan AAPL",
        source_path="Output/b_trade.md", ticker="AAPL", side="buy",
        linked_transaction_id=txn_a,
    )
    assert res.status_code == 404, res.text


async def test_report_trade_link_patch_set_and_clear(client, monkeypatch):
    _patch_yf(monkeypatch)
    jwt = await register_and_login(client, "tj-patch@test.local")
    key = await create_token(client, jwt, write=True)
    txn_id = await _make_txn_id(client, key, "AAPL")
    rid = (await _upload(client, key, category="trade", title="Trade-Plan AAPL",
                         source_path="Output/p.md")).json()["id"]

    # Link nachtraeglich per PATCH setzen
    r1 = await client.patch(f"/api/v1/external/reports/{rid}",
                            json={"linked_transaction_id": txn_id, "side": "buy"},
                            headers=api_auth(key))
    assert r1.status_code == 200, r1.text
    assert r1.json()["linked_transaction_id"] == txn_id

    # Feld weglassen aendert den Link NICHT (exclude_unset)
    r2 = await client.patch(f"/api/v1/external/reports/{rid}",
                            json={"title": "Trade-Plan AAPL (rev)"}, headers=api_auth(key))
    assert r2.json()["linked_transaction_id"] == txn_id

    # Leerstring loest den Link
    r3 = await client.patch(f"/api/v1/external/reports/{rid}",
                            json={"linked_transaction_id": ""}, headers=api_auth(key))
    assert r3.json()["linked_transaction_id"] is None


async def test_trade_journal_autolink_on_post_transaction(client, monkeypatch):
    """E2E: ein offener Trade-Plan wird beim Buchen einer passenden Buy-Txn
    server-seitig automatisch verlinkt (create_transaction_core-Hook)."""
    from datetime import date as _d
    _patch_yf(monkeypatch)
    jwt = await register_and_login(client, "tj-autolink@test.local")
    key = await create_token(client, jwt, write=True)

    # Offener Plan (Buy AAPL), report_date heute -> im +/-35d-Fenster, NICHT verlinkt
    rid = (await _upload(
        client, key, category="trade", title="Trade-Plan AAPL",
        source_path="Output/trades/al_aapl.md",
        ticker="AAPL", side="buy", report_date=_d.today().isoformat(),
    )).json()["id"]
    pre = (await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key))).json()
    assert pre["linked_transaction_id"] is None

    # Buy buchen -> Hook verlinkt den Plan automatisch
    txn_id = await _make_txn_id(client, key, "AAPL")
    post = (await client.get(f"/api/v1/external/reports/{rid}", headers=api_auth(key))).json()
    assert post["linked_transaction_id"] == txn_id
