"""Tests for performance API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="perf@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestPortfolioHistory:
    async def test_history_unauthorized(self, client):
        res = await client.get("/api/portfolio/history")
        assert res.status_code in (401, 403)

    async def test_history_success(self, client):
        token = await register_and_login(client)
        with patch("api.performance.get_portfolio_history", new_callable=AsyncMock) as mock_hist:
            mock_hist.return_value = {"dates": [], "values": [], "benchmark": []}
            res = await client.get("/api/portfolio/history", headers=auth(token))
            assert res.status_code == 200
            mock_hist.assert_called_once()

    async def test_history_with_params(self, client):
        token = await register_and_login(client)
        with patch("api.performance.get_portfolio_history", new_callable=AsyncMock) as mock_hist:
            mock_hist.return_value = {"dates": [], "values": []}
            res = await client.get(
                "/api/portfolio/history?start=2025-01-01&end=2025-12-31&benchmark=^SSMI",
                headers=auth(token),
            )
            assert res.status_code == 200


class TestMonthlyReturns:
    async def test_monthly_returns_unauthorized(self, client):
        res = await client.get("/api/portfolio/monthly-returns")
        assert res.status_code in (401, 403)

    async def test_monthly_returns_success(self, client):
        token = await register_and_login(client)
        with patch("services.performance_history_service.get_monthly_returns", new_callable=AsyncMock) as mock_mr:
            mock_mr.return_value = {"years": []}
            res = await client.get("/api/portfolio/monthly-returns", headers=auth(token))
            assert res.status_code == 200


class TestTotalReturn:
    async def test_total_return_unauthorized(self, client):
        res = await client.get("/api/portfolio/total-return")
        assert res.status_code in (401, 403)

    async def test_total_return_success(self, client):
        token = await register_and_login(client)
        with patch("services.total_return_service.get_total_return", new_callable=AsyncMock) as mock_tr:
            mock_tr.return_value = {"total_return_chf": 0, "total_return_pct": 0}
            res = await client.get("/api/portfolio/total-return", headers=auth(token))
            assert res.status_code == 200


class TestRecalculate:
    async def test_recalculate_unauthorized(self, client):
        res = await client.post("/api/portfolio/recalculate")
        assert res.status_code in (401, 403)

    async def test_recalculate_all_success(self, client):
        token = await register_and_login(client)
        with patch("services.recalculate_service.recalculate_all_positions", new_callable=AsyncMock) as mock_recalc:
            mock_recalc.return_value = []
            res = await client.post("/api/portfolio/recalculate", headers=auth(token))
            assert res.status_code == 200
            data = res.json()
            assert "recalculated" in data
            assert "positions" in data


class TestCoreSatelliteAllocation:
    async def test_allocation_unauthorized(self, client):
        res = await client.get("/api/portfolio/allocation/core-satellite")
        assert res.status_code in (401, 403)

    async def test_allocation_empty(self, client):
        token = await register_and_login(client)
        with patch("services.utils.get_fx_rates_batch", return_value={"USD": 0.88}):
            res = await client.get("/api/portfolio/allocation/core-satellite", headers=auth(token))
            assert res.status_code == 200
            data = res.json()
            assert "core" in data
            assert "satellite" in data
            assert "unassigned" in data
            assert data["core"]["value_chf"] == 0
            assert data["satellite"]["value_chf"] == 0


class TestDailyChange:
    async def test_daily_change_unauthorized(self, client):
        res = await client.get("/api/portfolio/daily-change")
        assert res.status_code in (401, 403)

    async def test_daily_change_success(self, client):
        token = await register_and_login(client)
        with patch("services.performance_service.calculate_daily_change", new_callable=AsyncMock) as mock_dc:
            mock_dc.return_value = {"change_chf": 0, "change_pct": 0}
            res = await client.get("/api/portfolio/daily-change", headers=auth(token))
            assert res.status_code == 200
