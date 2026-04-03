"""Tests for portfolio_service — _compute_market_value and _to_allocation_list."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.portfolio_service import _compute_market_value, _to_allocation_list


def make_pos(**kwargs):
    defaults = {
        "id": "test-id", "ticker": "AAPL", "name": "Apple",
        "type": SimpleNamespace(value="stock"), "currency": "USD",
        "shares": 10, "cost_basis_chf": 5000, "current_price": 150,
        "yfinance_ticker": "AAPL", "coingecko_id": None,
        "gold_org": False, "pricing_mode": SimpleNamespace(value="yahoo"),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestComputeMarketValue:
    def test_cash_returns_cost_basis(self):
        from models.position import AssetType
        pos = make_pos(type=AssetType.cash, cost_basis_chf=10000)
        mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 10000
        assert price is None
        assert stale == {}

    def test_pension_returns_cost_basis(self):
        from models.position import AssetType
        pos = make_pos(type=AssetType.pension, cost_basis_chf=50000)
        mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 50000

    @patch("services.portfolio_service.get_stock_price")
    def test_stock_with_chf(self, mock_price):
        from models.position import AssetType
        mock_price.return_value = {"price": 100.0, "currency": "CHF"}
        pos = make_pos(type=AssetType.stock, shares=10, currency="CHF")
        mv, price, ccy, stale = _compute_market_value(pos, {"CHF": 1.0})
        assert mv == 1000.0
        assert price == 100.0
        assert stale == {}

    @patch("services.portfolio_service.get_stock_price")
    def test_stock_with_usd_fx(self, mock_price):
        from models.position import AssetType
        mock_price.return_value = {"price": 200.0, "currency": "USD"}
        pos = make_pos(type=AssetType.stock, shares=5, currency="USD")
        mv, price, ccy, stale = _compute_market_value(pos, {"USD": 0.88})
        assert mv == 5 * 200.0 * 0.88

    @patch("services.portfolio_service.get_stock_price")
    def test_no_fx_rate_stale(self, mock_price):
        from models.position import AssetType
        mock_price.return_value = {"price": 50.0}
        pos = make_pos(type=AssetType.stock, shares=100, currency="GBP")
        with patch("services.cache_service.get_cached_price_sync", return_value=None):
            mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 0
        assert stale["is_stale"] is True

    @patch("services.portfolio_service.get_stock_price")
    def test_no_price_fallback(self, mock_price):
        from models.position import AssetType
        mock_price.return_value = None
        pos = make_pos(type=AssetType.stock, cost_basis_chf=3000)
        mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 3000
        assert stale["price_source"] == "cost_basis_fallback"

    @patch("services.portfolio_service.get_crypto_price_chf")
    def test_crypto(self, mock_crypto):
        from models.position import AssetType
        mock_crypto.return_value = {"price": 95000.0}
        pos = make_pos(type=AssetType.crypto, shares=0.5, coingecko_id="bitcoin")
        mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 0.5 * 95000.0
        assert ccy == "CHF"

    @patch("services.portfolio_service.get_gold_price_chf")
    def test_gold(self, mock_gold):
        from models.position import AssetType
        mock_gold.return_value = {"price": 2200.0}
        pos = make_pos(type=AssetType.stock, gold_org=True, shares=2)
        mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 4400.0

    def test_manual_pricing(self):
        from models.position import AssetType, PricingMode
        pos = make_pos(type=AssetType.stock, pricing_mode=PricingMode.manual,
                       current_price=75.0, shares=20, currency="CHF")
        mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 1500.0


class TestToAllocationList:
    def test_basic(self):
        result = _to_allocation_list({"stock": 7000, "etf": 3000}, 10000)
        assert result[0]["name"] == "stock"
        assert result[0]["pct"] == 70.0

    def test_sorted_desc(self):
        result = _to_allocation_list({"s": 100, "b": 900, "m": 500}, 1500)
        assert result[0]["name"] == "b"

    def test_zero_total(self):
        result = _to_allocation_list({"a": 100}, 0)
        assert result[0]["pct"] == 0

    def test_empty(self):
        assert _to_allocation_list({}, 10000) == []

    def test_single_100pct(self):
        result = _to_allocation_list({"only": 5000}, 5000)
        assert result[0]["pct"] == 100.0
