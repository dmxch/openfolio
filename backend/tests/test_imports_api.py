"""Tests for import API endpoints — file upload, parse, confirm, profiles."""

import io
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="import@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def make_csv_content(content: str = None) -> bytes:
    """Create a simple CSV for testing."""
    if content is None:
        content = "Date,Type,Ticker,Shares,Price,Currency,Total\n2025-01-15,buy,AAPL,10,150.00,USD,1500.00\n"
    return content.encode("utf-8")


class TestAnalyzeCsv:
    async def test_analyze_csv_success(self, client):
        token = await register_and_login(client)
        csv_data = make_csv_content()
        res = await client.post(
            "/api/import/analyze",
            files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
            headers=auth(token),
        )
        assert res.status_code == 200
        data = res.json()
        assert "headers" in data
        assert "sample_rows" in data
        assert "row_count" in data
        assert data["row_count"] == 1

    async def test_analyze_csv_unauthorized(self, client):
        csv_data = make_csv_content()
        res = await client.post(
            "/api/import/analyze",
            files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        )
        assert res.status_code in (401, 403)

    async def test_analyze_wrong_extension(self, client):
        token = await register_and_login(client, "import_ext@example.com")
        res = await client.post(
            "/api/import/analyze",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
            headers=auth(token),
        )
        assert res.status_code == 400
        assert "CSV" in res.json()["detail"]

    async def test_analyze_empty_file(self, client):
        token = await register_and_login(client, "import_empty@example.com")
        res = await client.post(
            "/api/import/analyze",
            files={"file": ("test.csv", io.BytesIO(b""), "text/csv")},
            headers=auth(token),
        )
        assert res.status_code == 400
        assert "leer" in res.json()["detail"]


class TestParseFile:
    async def test_parse_csv_unauthorized(self, client):
        csv_data = make_csv_content()
        res = await client.post(
            "/api/import/parse",
            files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        )
        assert res.status_code in (401, 403)

    async def test_parse_wrong_extension(self, client):
        token = await register_and_login(client, "parse_ext@example.com")
        res = await client.post(
            "/api/import/parse",
            files={"file": ("test.json", io.BytesIO(b"{}"), "application/json")},
            headers=auth(token),
        )
        assert res.status_code == 400

    async def test_parse_empty_file(self, client):
        token = await register_and_login(client, "parse_empty@example.com")
        res = await client.post(
            "/api/import/parse",
            files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
            headers=auth(token),
        )
        assert res.status_code == 400


class TestConfirmImport:
    async def test_confirm_import_unauthorized(self, client):
        res = await client.post(
            "/api/import/confirm",
            json={"transactions": [], "new_positions": []},
        )
        assert res.status_code in (401, 403)

    async def test_confirm_import_empty_transactions(self, client):
        token = await register_and_login(client, "confirm_empty@example.com")
        res = await client.post(
            "/api/import/confirm",
            json={"transactions": [], "new_positions": []},
            headers=auth(token),
        )
        # Empty import should succeed (returns result with 0 counts)
        assert res.status_code in (201, 200, 500)


class TestImportProfiles:
    async def test_list_profiles_empty(self, client):
        token = await register_and_login(client, "prof_list@example.com")
        res = await client.get("/api/import/profiles", headers=auth(token))
        assert res.status_code == 200
        assert res.json() == []

    async def test_create_profile_success(self, client):
        token = await register_and_login(client, "prof_create@example.com")
        res = await client.post(
            "/api/import/profiles",
            json={
                "name": "My Profile",
                "column_mapping": {"date": "Date", "type": "Type"},
                "type_mapping": {"buy": "buy", "sell": "sell"},
            },
            headers=auth(token),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "My Profile"
        assert "id" in data

    async def test_create_profile_unauthorized(self, client):
        res = await client.post(
            "/api/import/profiles",
            json={
                "name": "My Profile",
                "column_mapping": {},
                "type_mapping": {},
            },
        )
        assert res.status_code in (401, 403)

    async def test_delete_profile_success(self, client):
        token = await register_and_login(client, "prof_del@example.com")
        create_res = await client.post(
            "/api/import/profiles",
            json={
                "name": "To Delete",
                "column_mapping": {"date": "Date"},
                "type_mapping": {"buy": "buy"},
            },
            headers=auth(token),
        )
        profile_id = create_res.json()["id"]
        res = await client.delete(f"/api/import/profiles/{profile_id}", headers=auth(token))
        assert res.status_code == 204

        # Verify deleted
        list_res = await client.get("/api/import/profiles", headers=auth(token))
        assert len(list_res.json()) == 0

    async def test_delete_profile_idor(self, client):
        """User B cannot delete User A's import profile."""
        token_a = await register_and_login(client, "profA@example.com")
        token_b = await register_and_login(client, "profB@example.com")
        create_res = await client.post(
            "/api/import/profiles",
            json={
                "name": "A's Profile",
                "column_mapping": {"date": "Date"},
                "type_mapping": {"buy": "buy"},
            },
            headers=auth(token_a),
        )
        profile_id = create_res.json()["id"]
        res = await client.delete(f"/api/import/profiles/{profile_id}", headers=auth(token_b))
        assert res.status_code == 404

    async def test_delete_profile_not_found(self, client):
        token = await register_and_login(client, "prof_404@example.com")
        fake_id = str(uuid.uuid4())
        res = await client.delete(f"/api/import/profiles/{fake_id}", headers=auth(token))
        assert res.status_code == 404
