"""Tests for market API endpoints — climate, sectors, VIX, FX, precious metals, crypto."""

import uuid
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def register_and_login(client: AsyncClient, email="market@example.com"):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


class TestMarketClimate:
    @patch("services.macro_indicators_service.fetch_all_indicators", new_callable=AsyncMock, return_value={
        "overall_status": "green", "indicators": []
    })
    @patch("services.macro_indicators_service.fetch_extra_indicators", new_callable=AsyncMock, return_value={})
    @patch("services.market_analyzer.get_market_climate", return_value={
        "checks": {
            "price_above_ma200": True, "price_above_ma150": True,
            "price_above_ma50": True, "ma50_above_ma150": True,
        },
        "sp500_price": 5500.0,
    })
    @patch("services.macro_gate_service.calculate_macro_gate", return_value={
        "passed": True, "score": 7, "max_score": 9, "checks": []
    })
    async def test_climate_success(self, mock_gate, mock_climate, mock_extra, mock_indicators, client):
        token = await register_and_login(client)
        res = await client.get("/api/market/climate", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert "combined_status" in data
        assert "combined_label" in data
        assert "gate" in data
        assert "tech_checks" in data

    async def test_climate_unauthorized(self, client):
        res = await client.get("/api/market/climate")
        assert res.status_code in (401, 403)


class TestSectors:
    @patch("api.market.get_sector_rotation", return_value=[
        {"etf": "XLK", "name": "Technology", "performance_1m": 5.2}
    ])
    async def test_sectors_success(self, mock_rotation, client):
        token = await register_and_login(client, "sectors@example.com")
        res = await client.get("/api/market/sectors", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)

    async def test_sectors_unauthorized(self, client):
        res = await client.get("/api/market/sectors")
        assert res.status_code in (401, 403)


class TestVix:
    @patch("api.market.get_vix", return_value={"price": 18.5, "change_pct": -2.1})
    async def test_vix_success(self, mock_vix, client):
        token = await register_and_login(client, "vix@example.com")
        res = await client.get("/api/market/vix", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert "price" in data

    async def test_vix_unauthorized(self, client):
        res = await client.get("/api/market/vix")
        assert res.status_code in (401, 403)


class TestFxRate:
    @patch("services.utils.get_fx_rate", return_value=0.88)
    async def test_fx_rate_success(self, mock_fx, client):
        token = await register_and_login(client, "fx@example.com")
        res = await client.get("/api/market/fx/USD?to_currency=CHF", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["from"] == "USD"
        assert data["to"] == "CHF"
        assert data["rate"] == 0.88

    async def test_fx_rate_unauthorized(self, client):
        res = await client.get("/api/market/fx/USD")
        assert res.status_code in (401, 403)


class TestPreciousMetals:
    @patch("api.market.get_gold_price_chf", return_value=62000.0)
    @patch("api.market.get_stock_price", side_effect=[
        {"price": 2050.0, "currency": "USD", "change_pct": 0.5},
        {"price": 25.5, "currency": "USD", "change_pct": -0.3},
    ])
    async def test_precious_metals_success(self, mock_stock, mock_gold, client):
        token = await register_and_login(client, "metals@example.com")
        res = await client.get("/api/market/precious-metals", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert "gold_spot_chf" in data
        assert "gold_comex_usd" in data
        assert "silver_comex_usd" in data
        assert "gold_silver_ratio" in data
        assert data["gold_silver_ratio"] == round(2050.0 / 25.5, 1)

    async def test_precious_metals_unauthorized(self, client):
        res = await client.get("/api/market/precious-metals")
        assert res.status_code in (401, 403)


class TestMacroIndicators:
    @patch("services.macro_indicators_service.fetch_all_indicators", new_callable=AsyncMock, return_value={
        "overall_status": "green", "indicators": []
    })
    @patch("services.macro_gate_service.calculate_macro_gate", return_value={
        "passed": True, "score": 7, "max_score": 9, "checks": []
    })
    async def test_macro_indicators_success(self, mock_gate, mock_indicators, client):
        token = await register_and_login(client, "macro@example.com")
        res = await client.get("/api/market/macro-indicators", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert "gate_passed" in data
        assert "gate" in data

    async def test_macro_indicators_unauthorized(self, client):
        res = await client.get("/api/market/macro-indicators")
        assert res.status_code in (401, 403)


class TestCryptoMetrics:
    @patch("api.market.fetch_json", new_callable=AsyncMock, side_effect=[
        {"data": {"market_cap_percentage": {"btc": 55.2}}},  # _fetch_global
        {"data": [{"value": "50", "value_classification": "Neutral"}]},  # _fetch_fng
        {"market_data": {"ath": {"chf": 100000}, "current_price": {"chf": 95000}}},  # _fetch_btc_ath
    ])
    @patch("api.market.get_stock_price", return_value={"price": 104.5, "change_pct": -0.2})
    async def test_crypto_metrics_success(self, mock_stock, mock_fetch, client):
        token = await register_and_login(client, "crypto@example.com")
        # Clear any cached result
        from services import cache
        cache.delete("crypto_metrics")
        res = await client.get("/api/market/crypto-metrics", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert "tier1" in data
        assert "tier2" in data

    async def test_crypto_metrics_unauthorized(self, client):
        res = await client.get("/api/market/crypto-metrics")
        assert res.status_code in (401, 403)
