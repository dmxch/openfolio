"""Unit tests for apply_transaction_to_position / reverse_transaction_on_position.

Specifically covers the sell-to-zero deactivation rule that prevents
ghost positions from triggering rule_alert_service stop-loss emails after
a position is fully sold.
"""

import uuid
from datetime import datetime

import pytest

from models.position import AssetType, Position, PriceSource, PricingMode
from models.transaction import TransactionType
from services.transaction_service import (
    apply_transaction_to_position,
    reverse_transaction_on_position,
)


def _make_position(shares: float = 0.0, cost_basis_chf: float = 0.0, **overrides) -> Position:
    base = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        ticker="LHX",
        name="L3Harris",
        type=AssetType.stock,
        currency="USD",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        gold_org=False,
        is_etf=False,
        is_active=True,
        shares=shares,
        cost_basis_chf=cost_basis_chf,
    )
    base.update(overrides)
    return Position(**base)


class TestApplyTransaction:
    def test_buy_increments_shares_and_cost_basis(self):
        pos = _make_position(shares=10, cost_basis_chf=1000)
        apply_transaction_to_position(
            pos, txn_type=TransactionType.buy, shares=5, total_chf=600
        )
        assert float(pos.shares) == 15
        assert float(pos.cost_basis_chf) == 1600
        assert pos.is_active is True

    def test_partial_sell_keeps_position_active(self):
        pos = _make_position(shares=16, cost_basis_chf=4549, stop_loss_price=325)
        apply_transaction_to_position(
            pos, txn_type=TransactionType.sell, shares=8, total_chf=2000
        )
        assert float(pos.shares) == 8
        # cost basis halved (sold 8/16 of position)
        assert abs(float(pos.cost_basis_chf) - 2274.5) < 0.01
        assert pos.is_active is True
        # Stop-loss preserved on partial sell
        assert float(pos.stop_loss_price) == 325

    def test_full_sell_deactivates_position_and_clears_stop_loss(self):
        """The LHX bug: full sell must deactivate + clear stop-loss state."""
        pos = _make_position(
            shares=16,
            cost_basis_chf=4549,
            stop_loss_price=325,
            stop_loss_method="structural",
            stop_loss_confirmed_at_broker=True,
            stop_loss_updated_at=datetime(2026, 3, 5),
        )
        apply_transaction_to_position(
            pos, txn_type=TransactionType.sell, shares=16, total_chf=4104
        )
        assert float(pos.shares) == 0
        assert pos.is_active is False
        assert pos.stop_loss_price is None
        assert pos.stop_loss_method is None
        assert pos.stop_loss_confirmed_at_broker is False
        assert pos.stop_loss_updated_at is None

    def test_oversell_caps_at_zero_and_deactivates(self):
        pos = _make_position(shares=5, cost_basis_chf=1000, stop_loss_price=80)
        apply_transaction_to_position(
            pos, txn_type=TransactionType.sell, shares=10, total_chf=900
        )
        assert float(pos.shares) == 0
        assert pos.is_active is False
        assert pos.stop_loss_price is None

    def test_delivery_out_to_zero_deactivates(self):
        pos = _make_position(shares=3, cost_basis_chf=300, stop_loss_price=50)
        apply_transaction_to_position(
            pos, txn_type=TransactionType.delivery_out, shares=3, total_chf=0
        )
        assert float(pos.shares) == 0
        assert pos.is_active is False
        assert pos.stop_loss_price is None

    def test_buy_reactivates_closed_position(self):
        """Re-buying a previously-closed ticker must re-activate the position."""
        pos = _make_position(shares=0, cost_basis_chf=0, is_active=False)
        apply_transaction_to_position(
            pos, txn_type=TransactionType.buy, shares=10, total_chf=1500
        )
        assert float(pos.shares) == 10
        assert pos.is_active is True


class TestReverseTransaction:
    def test_reverse_full_sell_reactivates_position(self):
        """Deleting the closing sell-transaction must bring the position back."""
        pos = _make_position(shares=0, cost_basis_chf=0, is_active=False)
        reverse_transaction_on_position(
            pos, txn_type=TransactionType.sell, shares=16, total_chf=4104
        )
        assert float(pos.shares) == 16
        assert pos.is_active is True

    def test_reverse_only_buy_deactivates_position(self):
        """Deleting the only buy that ever existed empties the position."""
        pos = _make_position(shares=10, cost_basis_chf=1500, stop_loss_price=120)
        reverse_transaction_on_position(
            pos, txn_type=TransactionType.buy, shares=10, total_chf=1500
        )
        assert float(pos.shares) == 0
        assert pos.is_active is False
        assert pos.stop_loss_price is None
