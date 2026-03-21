"""Tests for XIRR and Modified Dietz calculations."""
from datetime import date

import pytest

from services.performance_history_service import xirr, deannualize_xirr


class TestXIRR:
    def test_simple_positive_return(self):
        """Invest 1000, get back 1100 after 1 year = 10%."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2025, 1, 1), 1100),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert abs(result - 0.10) < 0.01

    def test_simple_negative_return(self):
        """Invest 1000, get back 900 after 1 year = -10%."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2025, 1, 1), 900),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert abs(result - (-0.10)) < 0.01

    def test_with_intermediate_cashflows(self):
        """Invest 1000, add 500 mid-year, get back 1600."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2024, 7, 1), -500),
            (date(2025, 1, 1), 1600),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert result > 0  # Should be positive (gained 100 on 1500 invested)

    def test_with_withdrawal(self):
        """Invest 1000, withdraw 200 mid-year, end with 900."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2024, 7, 1), 200),
            (date(2025, 1, 1), 900),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert result > 0  # Gained 100 on effectively 800 invested

    def test_zero_return(self):
        """Invest 1000, get back 1000 = 0%."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2025, 1, 1), 1000),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert abs(result) < 0.01

    def test_empty_cashflows(self):
        result = xirr([])
        assert result is None

    def test_single_cashflow(self):
        result = xirr([(date(2024, 1, 1), -1000)])
        assert result is None

    def test_large_positive_return(self):
        """100% return."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2025, 1, 1), 2000),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert abs(result - 1.0) < 0.02

    def test_large_loss(self):
        """90% loss."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2025, 1, 1), 100),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert result < -0.8


class TestDeannualize:
    def test_full_year(self):
        """Full year = same as annualized."""
        result = deannualize_xirr(10.0, 365)
        assert abs(result - 10.0) < 0.01

    def test_half_year(self):
        """Half year at 10% annual ≈ 4.88%."""
        result = deannualize_xirr(10.0, 182)
        assert 4.5 < result < 5.5

    def test_zero_days(self):
        result = deannualize_xirr(10.0, 0)
        assert result == 0.0

    def test_negative_return(self):
        result = deannualize_xirr(-20.0, 365)
        assert abs(result - (-20.0)) < 0.01
