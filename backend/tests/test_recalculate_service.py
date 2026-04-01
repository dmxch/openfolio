"""Tests for recalculate_service — the holy grail of position calculation.

Tests the weighted-average cost basis, realized P&L, and share tracking
logic that must NEVER change without explicit maintainer approval.
"""

import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest

from models.position import AssetType, PricingMode
from models.transaction import TransactionType
from services.recalculate_service import (
    ADDITIVE_TYPES,
    REDUCTIVE_TYPES,
    _calculate_position_values,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_txn(
    txn_type: TransactionType,
    shares: float,
    total_chf: float,
    fees_chf: float = 0.0,
    fx_rate: float = 1.0,
) -> MagicMock:
    """Create a minimal mock transaction for _calculate_position_values."""
    txn = MagicMock()
    txn.type = txn_type
    txn.shares = shares
    txn.total_chf = total_chf
    txn.fees_chf = fees_chf
    txn.fx_rate_to_chf = fx_rate
    # Writable attrs for realized P&L
    txn.cost_basis_at_sale = None
    txn.realized_pnl_chf = None
    txn.realized_pnl = None
    return txn


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_additive_types(self):
        assert TransactionType.buy in ADDITIVE_TYPES
        assert TransactionType.delivery_in in ADDITIVE_TYPES
        assert len(ADDITIVE_TYPES) == 2

    def test_reductive_types(self):
        assert TransactionType.sell in REDUCTIVE_TYPES
        assert TransactionType.delivery_out in REDUCTIVE_TYPES
        assert len(REDUCTIVE_TYPES) == 2

    def test_no_overlap(self):
        assert ADDITIVE_TYPES & REDUCTIVE_TYPES == set()


# ---------------------------------------------------------------------------
# _calculate_position_values — the core algorithm
# ---------------------------------------------------------------------------

class TestCalculatePositionValues:
    """Tests for the weighted-average cost basis + realized P&L algorithm."""

    def test_single_buy(self):
        txns = [_make_txn(TransactionType.buy, 10, 1000.0)]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == 10.0
        assert cost == 1000.0
        assert realized == 0.0

    def test_multiple_buys(self):
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),
            _make_txn(TransactionType.buy, 5, 600.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == 15.0
        assert cost == 1600.0
        assert realized == 0.0

    def test_buy_then_sell_partial(self):
        """Sell 5 of 10 shares at a profit. Avg cost = 100 CHF/share."""
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),              # 10 @ 100
            _make_txn(TransactionType.sell, 5, 750.0, fees_chf=10),  # sell 5 for 750, fee 10
        ]
        shares, cost, realized = _calculate_position_values(txns)

        assert shares == 5.0
        # Cost basis reduced proportionally: 1000 * (1 - 5/10) = 500
        assert cost == 500.0
        # Realized = proceeds - allocated_cost - fees = 750 - 500 - 10 = 240
        assert realized == 240.0

    def test_buy_then_sell_all(self):
        """Sell all shares."""
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),
            _make_txn(TransactionType.sell, 10, 1200.0, fees_chf=5),
        ]
        shares, cost, realized = _calculate_position_values(txns)

        assert shares == 0.0
        assert abs(cost) < 0.01  # cost basis zeroed out
        # Realized = 1200 - 1000 - 5 = 195
        assert realized == 195.0

    def test_sell_at_loss(self):
        """Sell at a loss."""
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),
            _make_txn(TransactionType.sell, 10, 800.0, fees_chf=10),
        ]
        shares, cost, realized = _calculate_position_values(txns)

        assert shares == 0.0
        # Realized = 800 - 1000 - 10 = -210
        assert realized == -210.0

    def test_multiple_buys_then_partial_sell(self):
        """Two buys at different prices, then partial sell → weighted average."""
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),  # 10 @ 100
            _make_txn(TransactionType.buy, 10, 2000.0),   # 10 @ 200
            _make_txn(TransactionType.sell, 5, 900.0, fees_chf=5),
        ]
        shares, cost, realized = _calculate_position_values(txns)

        assert shares == 15.0
        # Avg cost = 3000/20 = 150 CHF/share
        # Allocated cost for 5 shares = 5 * 150 = 750
        # Remaining cost = 3000 * (1 - 5/20) = 3000 * 0.75 = 2250
        assert abs(cost - 2250.0) < 0.01
        # Realized = 900 - 750 - 5 = 145
        assert abs(realized - 145.0) < 0.01

    def test_delivery_in_adds_shares(self):
        """delivery_in acts like buy."""
        txns = [_make_txn(TransactionType.delivery_in, 20, 500.0)]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == 20.0
        assert cost == 500.0

    def test_delivery_out_reduces_shares(self):
        """delivery_out acts like sell."""
        txns = [
            _make_txn(TransactionType.buy, 20, 2000.0),
            _make_txn(TransactionType.delivery_out, 10, 1500.0, fees_chf=0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == 10.0
        # Cost reduced by 50%: 2000 * 0.5 = 1000
        assert abs(cost - 1000.0) < 0.01

    def test_sell_writes_realized_pnl_on_txn(self):
        """Verify that realized P&L is stored back on the transaction mock."""
        sell_txn = _make_txn(TransactionType.sell, 5, 750.0, fees_chf=10, fx_rate=0.88)
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),
            sell_txn,
        ]
        _calculate_position_values(txns)

        # cost_basis_at_sale = avg_cost * shares = 100 * 5 = 500
        assert sell_txn.cost_basis_at_sale == 500.0
        # realized_pnl_chf = 750 - 500 - 10 = 240
        assert sell_txn.realized_pnl_chf == 240.0
        # realized_pnl (in original currency) = 240 / 0.88 ≈ 272.73
        assert abs(sell_txn.realized_pnl - round(240.0 / 0.88, 2)) < 0.01

    def test_sell_zero_fx_rate_fallback(self):
        """If fx_rate is 0, fallback to 1.0 for realized_pnl calc."""
        sell_txn = _make_txn(TransactionType.sell, 5, 750.0, fees_chf=0, fx_rate=0.0)
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),
            sell_txn,
        ]
        _calculate_position_values(txns)
        # With fx=0 → fallback 1.0, so realized_pnl == realized_pnl_chf
        assert sell_txn.realized_pnl == sell_txn.realized_pnl_chf

    def test_sell_more_than_held(self):
        """Selling more shares than held — shares clamped to 0."""
        txns = [
            _make_txn(TransactionType.buy, 5, 500.0),
            _make_txn(TransactionType.sell, 10, 1000.0, fees_chf=0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == 0.0

    def test_sell_when_zero_shares(self):
        """Selling with 0 shares — edge case, realized = 0."""
        sell_txn = _make_txn(TransactionType.sell, 5, 500.0)
        txns = [sell_txn]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == 0.0
        assert realized == 0.0
        assert sell_txn.cost_basis_at_sale == 0
        assert sell_txn.realized_pnl_chf == 0

    def test_empty_transactions(self):
        shares, cost, realized = _calculate_position_values([])
        assert shares == 0.0
        assert cost == 0.0
        assert realized == 0.0

    def test_non_trade_types_ignored(self):
        """Dividend, fee, tax etc. don't affect shares or cost_basis."""
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),
            _make_txn(TransactionType.dividend, 0, 50.0),
            _make_txn(TransactionType.fee, 0, 5.0),
            _make_txn(TransactionType.tax, 0, 10.0),
        ]
        shares, cost, realized = _calculate_position_values(txns)
        assert shares == 10.0
        assert cost == 1000.0
        assert realized == 0.0

    def test_buy_sell_buy_sell_sequence(self):
        """Complex sequence: buy, partial sell, buy more, sell all."""
        txns = [
            _make_txn(TransactionType.buy, 10, 1000.0),              # 10 shares, cost 1000
            _make_txn(TransactionType.sell, 5, 600.0, fees_chf=5),   # sell 5 for 600
            _make_txn(TransactionType.buy, 20, 3000.0),              # buy 20 more
            _make_txn(TransactionType.sell, 25, 5000.0, fees_chf=10),# sell all 25
        ]
        shares, cost, realized = _calculate_position_values(txns)

        # After first buy: 10 shares, 1000 cost
        # After first sell: 5 shares, 500 cost. Realized = 600 - 500 - 5 = 95
        # After second buy: 25 shares, 3500 cost
        # Avg cost = 3500/25 = 140/share. Allocated = 140*25 = 3500
        # After second sell: 0 shares. Realized = 5000 - 3500 - 10 = 1490
        # Total realized = 95 + 1490 = 1585

        assert shares == 0.0
        assert abs(cost) < 0.01
        assert abs(realized - 1585.0) < 0.01

    def test_fractional_shares(self):
        """Crypto-like fractional share quantities."""
        txns = [
            _make_txn(TransactionType.buy, 0.5, 25000.0),
            _make_txn(TransactionType.sell, 0.1, 6000.0, fees_chf=2),
        ]
        shares, cost, realized = _calculate_position_values(txns)

        assert abs(shares - 0.4) < 1e-8
        # Avg cost = 25000/0.5 = 50000/BTC
        # Allocated = 50000 * 0.1 = 5000
        # Remaining cost = 25000 * (1 - 0.1/0.5) = 25000 * 0.8 = 20000
        assert abs(cost - 20000.0) < 0.01
        # Realized = 6000 - 5000 - 2 = 998
        assert abs(realized - 998.0) < 0.01
