"""Tests for analysis API endpoints (watchlist, tags, score, MRS, breakouts, levels)."""

import uuid
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="analysis@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestWatchlistCRUD:
    async def test_get_watchlist_empty(self, client):
        token = await register_and_login(client)
        res = await client.get("/api/analysis/watchlist", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["items"] == []
        assert data["active_alerts_count"] == 0

    async def test_add_to_watchlist(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"},
            headers=auth(token),
        )
        assert res.status_code == 201
        data = res.json()
        assert data["ticker"] == "AAPL"
        assert data["name"] == "Apple Inc."

    async def test_add_to_watchlist_unauthorized(self, client):
        res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AAPL", "name": "Apple Inc."},
        )
        assert res.status_code in (401, 403)

    async def test_add_to_watchlist_missing_fields(self, client):
        token = await register_and_login(client)
        res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AAPL"},
            headers=auth(token),
        )
        assert res.status_code == 422

    async def test_delete_watchlist_item(self, client):
        token = await register_and_login(client)
        create_res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AAPL", "name": "Apple Inc."},
            headers=auth(token),
        )
        item_id = create_res.json()["id"]
        res = await client.delete(f"/api/analysis/watchlist/{item_id}", headers=auth(token))
        assert res.status_code == 204

    async def test_delete_watchlist_idor(self, client):
        """User B cannot delete User A's watchlist item."""
        token_a = await register_and_login(client, "wa@example.com")
        token_b = await register_and_login(client, "wb@example.com")
        create_res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AAPL", "name": "Apple Inc."},
            headers=auth(token_a),
        )
        item_id = create_res.json()["id"]
        res = await client.delete(f"/api/analysis/watchlist/{item_id}", headers=auth(token_b))
        assert res.status_code == 404

    async def test_update_watchlist_notes(self, client):
        token = await register_and_login(client)
        create_res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "MSFT", "name": "Microsoft"},
            headers=auth(token),
        )
        item_id = create_res.json()["id"]
        res = await client.patch(
            f"/api/analysis/watchlist/{item_id}",
            json={"notes": "Strong fundamentals"},
            headers=auth(token),
        )
        assert res.status_code == 200

    async def test_update_watchlist_idor(self, client):
        """User B cannot update User A's watchlist item."""
        token_a = await register_and_login(client, "ua@example.com")
        token_b = await register_and_login(client, "ub@example.com")
        create_res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AAPL", "name": "Apple"},
            headers=auth(token_a),
        )
        item_id = create_res.json()["id"]
        res = await client.patch(
            f"/api/analysis/watchlist/{item_id}",
            json={"notes": "Hacked"},
            headers=auth(token_b),
        )
        assert res.status_code == 404

    async def test_delete_nonexistent_watchlist(self, client):
        token = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        res = await client.delete(f"/api/analysis/watchlist/{fake_id}", headers=auth(token))
        assert res.status_code == 404


class TestMRSHistory:
    @patch("services.chart_service.get_mrs_history", return_value=[{"date": "2026-01-01", "mrs": 0.5}])
    async def test_mrs_history_success(self, mock_mrs, client):
        token = await register_and_login(client, "mrs@example.com")
        res = await client.get("/api/analysis/mrs-history/AAPL", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["ticker"] == "AAPL"
        assert "data" in data

    async def test_mrs_history_unauthorized(self, client):
        res = await client.get("/api/analysis/mrs-history/AAPL")
        assert res.status_code in (401, 403)


class TestBreakouts:
    @patch("services.chart_service.get_breakout_events", return_value=[])
    async def test_breakouts_success(self, mock_breakouts, client):
        token = await register_and_login(client, "brk@example.com")
        res = await client.get("/api/analysis/breakouts/AAPL", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["ticker"] == "AAPL"
        assert "breakouts" in data

    async def test_breakouts_unauthorized(self, client):
        res = await client.get("/api/analysis/breakouts/AAPL")
        assert res.status_code in (401, 403)


class TestScore:
    @patch("services.scoring_service.assess_ticker", return_value={
        "ticker": "AAPL", "score": 14, "max_score": 18, "price": 180.0,
        "signal": "BEOBACHTUNGSLISTE", "quality": "STARK",
    })
    async def test_score_success(self, mock_score, client):
        token = await register_and_login(client, "score@example.com")
        res = await client.get("/api/analysis/score/AAPL", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["ticker"] == "AAPL"
        assert data["score"] == 14

    @patch("services.scoring_service.assess_ticker", return_value={
        "max_score": 0, "price": None,
    })
    async def test_score_ticker_not_found(self, mock_score, client):
        token = await register_and_login(client, "score2@example.com")
        res = await client.get("/api/analysis/score/INVALID", headers=auth(token))
        assert res.status_code == 404

    async def test_score_unauthorized(self, client):
        res = await client.get("/api/analysis/score/AAPL")
        assert res.status_code in (401, 403)


class TestLevels:
    @patch("services.chart_service.get_support_resistance_levels", return_value={
        "ticker": "AAPL", "support": 170.0, "resistance": 195.0,
    })
    async def test_levels_success(self, mock_levels, client):
        token = await register_and_login(client, "lvl@example.com")
        res = await client.get("/api/analysis/levels/AAPL", headers=auth(token))
        assert res.status_code == 200

    async def test_levels_unauthorized(self, client):
        res = await client.get("/api/analysis/levels/AAPL")
        assert res.status_code in (401, 403)
