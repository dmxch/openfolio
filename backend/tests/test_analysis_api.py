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

    async def test_delete_watchlist_cascades_price_alerts(self, client):
        """Removing a watchlist item must drop its price alerts so they don't
        survive as invisible orphans (they're typically created via the
        watchlist row's bell popover and unmanageable from the UI otherwise)."""
        token = await register_and_login(client, "cascade@example.com")
        # Add ticker to watchlist
        wl_res = await client.post(
            "/api/analysis/watchlist",
            json={"ticker": "AVAV", "name": "AeroVironment"},
            headers=auth(token),
        )
        item_id = wl_res.json()["id"]

        # Create two price alerts for the same ticker, plus one for an unrelated ticker
        for target in (200, 281):
            await client.post(
                "/api/price-alerts",
                json={"ticker": "AVAV", "alert_type": "price_above", "target_value": target},
                headers=auth(token),
            )
        await client.post(
            "/api/price-alerts",
            json={"ticker": "MSFT", "alert_type": "price_below", "target_value": 350},
            headers=auth(token),
        )

        # Verify pre-state: 3 alerts total
        pre = await client.get("/api/price-alerts", headers=auth(token))
        assert len(pre.json()) == 3

        # Remove watchlist item — should cascade-delete the 2 AVAV alerts
        res = await client.delete(f"/api/analysis/watchlist/{item_id}", headers=auth(token))
        assert res.status_code == 204

        post = await client.get("/api/price-alerts", headers=auth(token))
        remaining = post.json()
        assert len(remaining) == 1, f"expected only MSFT alert to survive, got {remaining}"
        assert remaining[0]["ticker"] == "MSFT"

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


class TestScoreBondNotApplicable:
    """Anleihen bekommen kein Aktien-Setup — ueber den ECHTEN Endpoint geprueft.

    assess_ticker ist hier bewusst NICHT gemockt: der bond-Guard greift vor Cache
    und score_stock, es gibt also keinen Netzwerk-Zugriff. Nur so faengt der Test
    beide Haelften des Defekts — den nie durchgereichten asset_type UND die
    404-Kollision (_not_applicable_assessment liefert max_score=0/price=None,
    exakt die Signatur, mit der der Endpoint "Ticker nicht gefunden" wirft).
    """

    async def _bond_position(self, client, token):
        res = await client.post(
            "/api/portfolio/positions",
            headers=auth(token),
            json={
                "ticker": "IB01.L",
                "name": "iShares $ Treasury Bond 0-1yr UCITS ETF",
                "type": "bond",
                "currency": "USD",
                "shares": 330,
                "cost_basis_chf": 32000,
                "yfinance_ticker": "IB01.L",
            },
        )
        assert res.status_code in (200, 201), res.text
        return res

    async def test_bond_position_score_is_not_applicable_not_404(self, client):
        token = await register_and_login(client, "bondscore@example.com")
        await self._bond_position(client, token)

        res = await client.get("/api/analysis/score/IB01.L", headers=auth(token))

        assert res.status_code == 200, "Anleihe darf nicht als 'Ticker nicht gefunden' enden"
        data = res.json()
        assert data["not_applicable"] is True
        assert data["signal"] == "NICHT_ANWENDBAR"
        assert data["mansfield_rs"] is None

    @patch("services.scoring_service.cache")
    @patch("services.scoring_service.score_stock")
    async def test_stock_position_still_scored(self, mock_score, mock_cache, client):
        """Gegenprobe: der Guard darf nur Anleihen treffen."""
        mock_cache.get.return_value = None
        mock_score.return_value = {
            "ticker": "AAPL", "price": 180.0, "signal": "WATCHLIST",
            "signal_label": "Warten", "criteria": [], "score": 14, "max_score": 18,
        }
        token = await register_and_login(client, "stockscore@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            headers=auth(token),
            json={"ticker": "AAPL", "name": "Apple", "type": "stock",
                  "currency": "USD", "shares": 10, "cost_basis_chf": 1800},
        )
        assert res.status_code in (200, 201), res.text

        res = await client.get("/api/analysis/score/AAPL", headers=auth(token))
        assert res.status_code == 200
        assert not res.json().get("not_applicable")
