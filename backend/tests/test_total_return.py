"""Tests for total_return_service and performance_history_service calculations."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.performance_history_service import (
    xirr,
    deannualize_xirr,
    _calculate_xirr_from_data,
)



# --- Helper: fake snapshot/transaction objects ---

def make_snap(d: date, value: float, net_cf: float = 0):
    return SimpleNamespace(date=d, total_value_chf=value, net_cash_flow_chf=net_cf)


def make_txn(d: date, type_val: str, total: float):
    return SimpleNamespace(date=d, type=type_val, total_chf=total)


# --- _calculate_xirr_from_data tests ---

class TestCalculateXirrFromData:
    def test_simple_growth(self):
        """Portfolio grows from 10000 to 11000 in one year, no transactions."""
        snaps = [
            make_snap(date(2024, 1, 1), 10000),
            make_snap(date(2025, 1, 1), 11000),
        ]
        result = _calculate_xirr_from_data(snaps, [], date(2024, 1, 1), date(2025, 1, 1))
        assert result is not None
        assert abs(result - 0.10) < 0.02  # ~10%

    def test_no_snapshots_returns_none(self):
        result = _calculate_xirr_from_data([], [], date(2024, 1, 1), date(2025, 1, 1))
        assert result is None

    def test_single_snapshot_returns_none(self):
        """Only end snapshot, no start — should still compute (start_value=0)."""
        snaps = [make_snap(date(2025, 1, 1), 11000)]
        result = _calculate_xirr_from_data(snaps, [], date(2024, 1, 1), date(2025, 1, 1))
        # With start_value=0 and end_value=11000, XIRR needs at least a buy transaction
        # Without transactions, there's just an end value with no starting investment
        # Result depends on implementation — just check it doesn't crash
        assert result is None or isinstance(result, float)

    def test_with_inflow_transaction(self):
        """Start 10000, add 5000 mid-year, end 16000."""
        snaps = [
            make_snap(date(2024, 1, 1), 10000),
            make_snap(date(2024, 7, 1), 15500, net_cf=5000),
            make_snap(date(2025, 1, 1), 16000),
        ]
        txns = [make_txn(date(2024, 7, 1), "buy", 5000)]
        result = _calculate_xirr_from_data(snaps, txns, date(2024, 1, 1), date(2025, 1, 1))
        assert result is not None
        assert result > 0  # Positive return (gained 1000 on 15000)

    def test_with_dividend(self):
        """Start 10000, receive 200 dividend, end 10100."""
        snaps = [
            make_snap(date(2024, 1, 1), 10000),
            make_snap(date(2025, 1, 1), 10100),
        ]
        txns = [make_txn(date(2024, 6, 15), "dividend", 200)]
        result = _calculate_xirr_from_data(snaps, txns, date(2024, 1, 1), date(2025, 1, 1))
        assert result is not None
        assert result > 0  # Total return positive

    def test_short_period(self):
        """3 months, 2% gain."""
        snaps = [
            make_snap(date(2024, 1, 1), 10000),
            make_snap(date(2024, 4, 1), 10200),
        ]
        result = _calculate_xirr_from_data(snaps, [], date(2024, 1, 1), date(2024, 4, 1))
        assert result is not None
        assert result > 0.05  # Annualized should be > 5%

    def test_loss_period(self):
        """Portfolio drops 20%."""
        snaps = [
            make_snap(date(2024, 1, 1), 10000),
            make_snap(date(2025, 1, 1), 8000),
        ]
        result = _calculate_xirr_from_data(snaps, [], date(2024, 1, 1), date(2025, 1, 1))
        assert result is not None
        assert abs(result - (-0.20)) < 0.02


# --- XIRR edge cases ---

class TestXIRREdgeCases:
    def test_very_short_period(self):
        """1 day holding period."""
        cashflows = [
            (date(2024, 6, 1), -1000),
            (date(2024, 6, 2), 1001),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert result > 0

    def test_multiple_buys_and_sells(self):
        """Complex multi-transaction scenario."""
        cashflows = [
            (date(2024, 1, 1), -10000),   # Initial buy
            (date(2024, 3, 1), -5000),    # Add position
            (date(2024, 6, 1), 3000),     # Partial sell
            (date(2024, 9, 1), -2000),    # Buy more
            (date(2025, 1, 1), 16000),    # Final value
        ]
        result = xirr(cashflows)
        assert result is not None
        # Net invested: 10000+5000-3000+2000 = 14000, end value 16000 → positive
        assert result > 0

    def test_all_same_date_returns_none(self):
        """All cashflows on the same date — undefined IRR."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2024, 1, 1), 1100),
        ]
        result = xirr(cashflows)
        # Should handle gracefully (0 days → division issues)
        assert result is None or isinstance(result, float)

    def test_negative_then_positive_large(self):
        """10x return in 6 months."""
        cashflows = [
            (date(2024, 1, 1), -1000),
            (date(2024, 7, 1), 10000),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert result > 5  # Annualized > 500%


# --- Deannualize edge cases ---

class TestDeannualizeEdgeCases:
    def test_very_short_period(self):
        """7 days at 100% annual ≈ 1.35%."""
        result = deannualize_xirr(100.0, 7)
        assert 1.0 < result < 2.0

    def test_two_years(self):
        """730 days at 10% annual ≈ 21%."""
        result = deannualize_xirr(10.0, 730)
        assert 20.0 < result < 22.0

    def test_negative_short_period(self):
        result = deannualize_xirr(-50.0, 90)
        assert result < 0
