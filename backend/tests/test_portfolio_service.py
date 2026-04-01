"""Tests for portfolio_service — MA status, MRS, market value, allocations.

Tests the helper functions that compute MA status badges, market value
calculation (with FX), and allocation bucketing. These are critical for
the portfolio dashboard and must NEVER change without maintainer approval.
"""

from unittest.mock import MagicMock, patch

import pytest

from models.position import AssetType, PricingMode
from services.portfolio_service import (
    _compute_market_value,
    _get_ma_status,
    _get_mrs,
    _to_allocation_list,
    SKIP_TICKERS,
)


# ---------------------------------------------------------------------------
# _get_ma_status
# ---------------------------------------------------------------------------

class TestGetMaStatus:
    """Tests MA status badge logic: GESUND / WARNUNG / KRITISCH / None."""

    @patch("services.portfolio_service.compute_moving_averages")
    def test_all_above_returns_gesund(self, mock_ma):
        mock_ma.return_value = {"current": 200, "ma50": 180, "ma150": 160, "ma200": 140}
        result = _get_ma_status("AAPL")
        assert result["ma_status"] == "GESUND"
        assert result["ma_detail"]["above_ma50"] is True
        assert result["ma_detail"]["above_ma150"] is True
        assert result["ma_detail"]["above_ma200"] is True

    @patch("services.portfolio_service.compute_moving_averages")
    def test_two_of_three_returns_warnung(self, mock_ma):
        """Above MA50 and MA150 but below MA200 → WARNUNG (2/3 passed, >= half)."""
        mock_ma.return_value = {"current": 170, "ma50": 160, "ma150": 150, "ma200": 180}
        result = _get_ma_status("AAPL")
        assert result["ma_status"] == "WARNUNG"

    @patch("services.portfolio_service.compute_moving_averages")
    def test_one_of_three_returns_kritisch(self, mock_ma):
        """Only above MA50, below MA150 and MA200 → KRITISCH (1/3 < half)."""
        mock_ma.return_value = {"current": 155, "ma50": 150, "ma150": 160, "ma200": 180}
        result = _get_ma_status("AAPL")
        assert result["ma_status"] == "KRITISCH"

    @patch("services.portfolio_service.compute_moving_averages")
    def test_none_above_returns_kritisch(self, mock_ma):
        mock_ma.return_value = {"current": 100, "ma50": 150, "ma150": 160, "ma200": 180}
        result = _get_ma_status("AAPL")
        assert result["ma_status"] == "KRITISCH"

    @patch("services.portfolio_service.compute_moving_averages")
    def test_missing_current_returns_none(self, mock_ma):
        mock_ma.return_value = {"current": None, "ma50": 150, "ma150": 160, "ma200": None}
        result = _get_ma_status("AAPL")
        assert result["ma_status"] is None
        assert result["ma_detail"] is None

    @patch("services.portfolio_service.compute_moving_averages")
    def test_missing_ma200_returns_none(self, mock_ma):
        """ma200 is None → early return None."""
        mock_ma.return_value = {"current": 200, "ma50": 150, "ma150": 160, "ma200": None}
        result = _get_ma_status("AAPL")
        assert result["ma_status"] is None

    @patch("services.portfolio_service.compute_moving_averages")
    def test_partial_ma_data(self, mock_ma):
        """Only MA200 available (MA50/MA150 None) → checks based on what's available."""
        mock_ma.return_value = {"current": 200, "ma50": None, "ma150": None, "ma200": 180}
        result = _get_ma_status("AAPL")
        # Only 1 check possible (above_200), and it passes → GESUND
        assert result["ma_status"] == "GESUND"

    def test_cash_ticker_skipped(self):
        result = _get_ma_status("CASH_CHF")
        assert result["ma_status"] is None

    def test_skip_tickers(self):
        for ticker in SKIP_TICKERS:
            result = _get_ma_status(ticker)
            assert result["ma_status"] is None

    @patch("services.portfolio_service.compute_moving_averages", side_effect=Exception("boom"))
    def test_exception_returns_none(self, mock_ma):
        result = _get_ma_status("AAPL")
        assert result["ma_status"] is None


# ---------------------------------------------------------------------------
# _get_mrs
# ---------------------------------------------------------------------------

class TestGetMrs:
    @patch("services.portfolio_service.compute_mansfield_rs")
    def test_normal_ticker(self, mock_mrs):
        mock_mrs.return_value = 0.75
        result = _get_mrs("AAPL")
        assert result == 0.75

    def test_cash_skipped(self):
        assert _get_mrs("CASH_USD") is None

    def test_skip_tickers(self):
        for ticker in SKIP_TICKERS:
            assert _get_mrs(ticker) is None

    @patch("services.portfolio_service.compute_mansfield_rs", side_effect=Exception("fail"))
    def test_exception_returns_none(self, mock_mrs):
        assert _get_mrs("AAPL") is None


# ---------------------------------------------------------------------------
# _compute_market_value
# ---------------------------------------------------------------------------

class TestComputeMarketValue:
    """Tests the market value resolution for all asset types."""

    def _make_position(self, **kwargs):
        pos = MagicMock()
        pos.type = kwargs.get("type", AssetType.stock)
        pos.shares = kwargs.get("shares", 10)
        pos.cost_basis_chf = kwargs.get("cost_basis_chf", 1000)
        pos.currency = kwargs.get("currency", "USD")
        pos.ticker = kwargs.get("ticker", "AAPL")
        pos.yfinance_ticker = kwargs.get("yfinance_ticker", None)
        pos.coingecko_id = kwargs.get("coingecko_id", None)
        pos.gold_org = kwargs.get("gold_org", False)
        pos.pricing_mode = MagicMock()
        pos.pricing_mode.value = kwargs.get("pricing_mode", "auto")
        pos.current_price = kwargs.get("current_price", None)
        return pos

    def test_cash_returns_cost_basis(self):
        """Cash positions: market_value = cost_basis, no price needed."""
        pos = self._make_position(type=AssetType.cash, cost_basis_chf=5000)
        mv, price, currency, stale = _compute_market_value(pos, {})
        assert mv == 5000.0
        assert price is None
        assert currency is None

    def test_pension_returns_cost_basis(self):
        pos = self._make_position(type=AssetType.pension, cost_basis_chf=80000)
        mv, price, currency, stale = _compute_market_value(pos, {})
        assert mv == 80000.0

    @patch("services.portfolio_service.get_crypto_price_chf")
    def test_crypto_with_coingecko(self, mock_crypto):
        """Crypto positions with coingecko_id → direct CHF price."""
        mock_crypto.return_value = {"price": 95000.0}
        pos = self._make_position(
            type=AssetType.crypto, coingecko_id="bitcoin", shares=0.5
        )
        mv, price, currency, stale = _compute_market_value(pos, {})
        assert mv == 47500.0
        assert price == 95000.0
        assert currency == "CHF"

    @patch("services.portfolio_service.get_gold_price_chf")
    def test_gold_org_position(self, mock_gold):
        """Gold.org priced positions → CHF direct."""
        mock_gold.return_value = {"price": 2400.0}
        pos = self._make_position(gold_org=True, shares=3)
        mv, price, currency, stale = _compute_market_value(pos, {})
        assert mv == 7200.0
        assert price == 2400.0

    def test_manual_pricing(self):
        """Manual positions use current_price directly, no FX."""
        pos = self._make_position(pricing_mode="manual", current_price=50.0, shares=20)
        mv, price, currency, stale = _compute_market_value(pos, {})
        assert mv == 1000.0
        assert price == 50.0

    def test_manual_pricing_no_current_price(self):
        """Manual position with no current_price → 0 value."""
        pos = self._make_position(pricing_mode="manual", current_price=None, shares=20)
        mv, price, currency, stale = _compute_market_value(pos, {})
        assert mv == 0.0

    @patch("services.portfolio_service.get_stock_price")
    def test_stock_with_fx(self, mock_price):
        """Stock position: price × shares × fx_rate."""
        mock_price.return_value = {"price": 150.0, "currency": "USD"}
        pos = self._make_position(shares=10, currency="USD")
        fx_rates = {"USD": 0.88, "EUR": 0.95}
        mv, price, currency, stale = _compute_market_value(pos, fx_rates)
        assert mv == 10 * 150.0 * 0.88
        assert price == 150.0
        assert currency == "USD"

    @patch("services.portfolio_service.get_stock_price")
    def test_stock_chf_fx_rate_1(self, mock_price):
        """CHF stock: fx_rate should be 1.0 (from fx_rates dict)."""
        mock_price.return_value = {"price": 100.0, "currency": "CHF"}
        pos = self._make_position(shares=5, currency="CHF")
        fx_rates = {"CHF": 1.0, "USD": 0.88}
        mv, price, currency, stale = _compute_market_value(pos, fx_rates)
        assert mv == 500.0

    @patch("services.portfolio_service.get_stock_price")
    def test_stock_no_fx_rate_stale(self, mock_price):
        """Missing FX rate with no DB fallback → stale marker."""
        mock_price.return_value = {"price": 100.0, "currency": "USD"}
        pos = self._make_position(shares=10, currency="JPY", ticker="7203.T")
        fx_rates = {"USD": 0.88}  # no JPY

        with patch("services.cache_service.get_cached_price_sync") as mock_db:
            mock_db.return_value = None  # no stale FX either
            mv, price, currency, stale = _compute_market_value(pos, fx_rates)
            assert mv == 0
            assert stale["is_stale"] is True
            assert "Kein FX-Kurs" in stale["stale_reason"]

    @patch("services.portfolio_service.get_stock_price")
    def test_no_price_falls_to_cost_basis(self, mock_price):
        """No price at all → fallback to cost_basis_chf."""
        mock_price.return_value = None
        pos = self._make_position(cost_basis_chf=2000)
        mv, price, currency, stale = _compute_market_value(pos, {})
        assert mv == 2000.0
        assert stale["is_stale"] is True
        assert stale["price_source"] == "cost_basis_fallback"

    @patch("services.portfolio_service.get_stock_price")
    def test_uses_yfinance_ticker_when_set(self, mock_price):
        """Position with yfinance_ticker uses that for price lookup."""
        mock_price.return_value = {"price": 50.0, "currency": "CHF"}
        pos = self._make_position(
            ticker="NESN", yfinance_ticker="NESN.SW", shares=10, currency="CHF"
        )
        fx_rates = {"CHF": 1.0}
        _compute_market_value(pos, fx_rates)
        mock_price.assert_called_once_with("NESN.SW")


# ---------------------------------------------------------------------------
# _to_allocation_list
# ---------------------------------------------------------------------------

class TestToAllocationList:
    def test_basic_allocation(self):
        alloc = {"stock": 7000.0, "etf": 3000.0}
        result = _to_allocation_list(alloc, 10000.0)
        assert len(result) == 2
        # Sorted by value descending
        assert result[0]["name"] == "stock"
        assert result[0]["value_chf"] == 7000.0
        assert result[0]["pct"] == 70.0
        assert result[1]["name"] == "etf"
        assert result[1]["pct"] == 30.0

    def test_zero_total(self):
        alloc = {"stock": 0.0}
        result = _to_allocation_list(alloc, 0.0)
        assert result[0]["pct"] == 0

    def test_empty_dict(self):
        result = _to_allocation_list({}, 10000.0)
        assert result == []

    def test_rounding(self):
        alloc = {"a": 333.33, "b": 666.67}
        result = _to_allocation_list(alloc, 1000.0)
        assert result[0]["pct"] == 66.67
        assert result[1]["pct"] == 33.33

    def test_single_entry_100pct(self):
        alloc = {"core": 50000.0}
        result = _to_allocation_list(alloc, 50000.0)
        assert result[0]["pct"] == 100.0
