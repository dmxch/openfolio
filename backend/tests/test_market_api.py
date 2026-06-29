"""Tests for market API endpoints — climate, sectors, VIX, FX, precious metals, crypto."""

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient

from models.market_industry import MarketIndustry

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

    @patch("services.macro_indicators_service.fetch_all_indicators", new_callable=AsyncMock, return_value={
        "overall_status": "green", "risk_status": "green", "overall_label": "Risk On",
        "green_count": 4, "yellow_count": 0, "red_count": 0,
        "indicators": [
            {"name": "shiller_pe", "status": "red", "group": "valuation"},
            {"name": "buffett_indicator", "status": "red", "group": "valuation"},
            {"name": "vix", "status": "green", "group": "risk"},
        ],
        "valuation_status": "red", "valuation_label": "Stark überbewertet",
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
    async def test_valuation_does_not_force_risk_off(self, mock_gate, mock_climate, mock_extra, mock_indicators, client):
        # Trend bullish + Risk-Treiber gruen -> Risk On, trotz extremer Bewertung (CAPE/Buffett rot).
        token = await register_and_login(client, email="climate2@example.com")
        res = await client.get("/api/market/climate", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["combined_label"] == "Risk On"
        assert data["combined_status"] == "green"
        # Bewertung als separates Kontext-Signal durchgereicht (kippt das Klima nicht)
        assert data["valuation_status"] == "red"
        assert data["valuation_label"] == "Stark überbewertet"

    @patch("services.macro_indicators_service.fetch_all_indicators", new_callable=AsyncMock, return_value={
        "overall_status": "red", "risk_status": "red", "overall_label": "Risk Off",
        "green_count": 1, "yellow_count": 0, "red_count": 2,
        "indicators": [{"name": "vix", "status": "red", "group": "risk"}, {"name": "credit_spread", "status": "red", "group": "risk"}],
        "valuation_status": "green", "valuation_label": "Fair bewertet",
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
    async def test_risk_drivers_red_triggers_risk_off(self, mock_gate, mock_climate, mock_extra, mock_indicators, client):
        # Echte Risk-Treiber rot (VIX+Credit) -> Risk Off, auch bei intaktem Trend.
        token = await register_and_login(client, email="climate3@example.com")
        res = await client.get("/api/market/climate", headers=auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["combined_label"] == "Risk Off"
        assert data["combined_status"] == "red"

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


_MOCK_MEMBERS = [
    {"ticker": "XOM", "name": "Exxon Mobil Corporation", "exchange": "NYSE",
     "change_pct": -0.24, "perf_1w": 1.2, "perf_1m": 3.4, "perf_3m": 8.9,
     "perf_6m": 15.1, "perf_ytd": 29.0, "perf_1y": 12.7,
     "market_cap": 642135222801.0},
    {"ticker": "CVX", "name": "Chevron Corporation", "exchange": "NYSE",
     "change_pct": 0.22, "perf_1w": 0.9, "perf_1m": 2.1, "perf_3m": 6.0,
     "perf_6m": 11.0, "perf_ytd": 25.8, "perf_1y": 8.0,
     "market_cap": 381251548117.0},
]


class TestIndustryMembers:
    """Drill-down: GET /api/market/industries/{slug}/members (JWT-Auth)."""

    @staticmethod
    def _clear_cache(slug, limit):
        from services import cache
        cache.delete(f"market:industry_members:{slug}:l{limit}:v1")

    async def test_members_unauthorized(self, client):
        res = await client.get("/api/market/industries/integrated-oil/members")
        assert res.status_code in (401, 403)

    async def test_members_unknown_slug_returns_404(self, client, db):
        db.add(MarketIndustry(slug="semis", name="Semiconductors",
                              scraped_at=datetime(2026, 4, 22), perf_ytd=Decimal("40")))
        await db.commit()
        token = await register_and_login(client, "members1@example.com")
        res = await client.get(
            "/api/market/industries/does-not-exist/members", headers=auth(token),
        )
        assert res.status_code == 404

    async def test_members_returns_200_with_mock(self, client, db):
        self._clear_cache("integrated-oil", 5)
        db.add(MarketIndustry(slug="integrated-oil", name="Integrated Oil",
                              scraped_at=datetime(2026, 4, 22), perf_ytd=Decimal("29")))
        await db.commit()
        token = await register_and_login(client, "members2@example.com")

        with patch("api.market.fetch_industry_members",
                   new=AsyncMock(return_value=_MOCK_MEMBERS)) as mock:
            res = await client.get(
                "/api/market/industries/integrated-oil/members?limit=5",
                headers=auth(token),
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["slug"] == "integrated-oil"
        assert body["name"] == "Integrated Oil"
        assert body["count"] == 2
        assert body["members"][0]["ticker"] == "XOM"
        # Slug wird vor dem Scanner-Call zum Anzeigenamen aufgelöst.
        mock.assert_awaited_once_with("Integrated Oil", limit=5)

    async def test_members_scanner_failure_returns_502(self, client, db):
        self._clear_cache("integrated-oil", 50)
        db.add(MarketIndustry(slug="integrated-oil", name="Integrated Oil",
                              scraped_at=datetime(2026, 4, 22), perf_ytd=Decimal("29")))
        await db.commit()
        token = await register_and_login(client, "members3@example.com")

        with patch("api.market.fetch_industry_members",
                   new=AsyncMock(side_effect=RuntimeError("scanner down"))):
            res = await client.get(
                "/api/market/industries/integrated-oil/members", headers=auth(token),
            )
        assert res.status_code == 502
