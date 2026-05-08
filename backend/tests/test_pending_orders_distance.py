"""Unit-Tests fuer compute_distance_pct + compute_effective_status."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from services.pending_order_service import (
    compute_distance_pct,
    compute_effective_status,
)


@pytest.mark.parametrize(
    "side,limit,current,oc,qc,expected",
    [
        # BUY: positiv = noch zu erreichen (Spot muss fallen)
        ("buy", Decimal("90"), Decimal("100"), "USD", "USD", Decimal("0.10")),
        # BUY: Spot durchgebrochen (Spot < Limit) -> negativ
        ("buy", Decimal("110"), Decimal("100"), "USD", "USD", Decimal("-0.10")),
        # SELL: positiv = noch zu erreichen (Spot muss steigen)
        ("sell", Decimal("120"), Decimal("100"), "USD", "USD", Decimal("0.20")),
        # SELL: Spot durchgebrochen (Spot > Limit) -> negativ
        ("sell", Decimal("90"), Decimal("100"), "USD", "USD", Decimal("-0.10")),
    ],
)
def test_distance_signs(side, limit, current, oc, qc, expected):
    actual = compute_distance_pct(side, limit, current, oc, qc)
    assert actual is not None
    assert abs(actual - expected) < Decimal("0.0001"), f"got {actual}, want {expected}"


def test_distance_currency_mismatch_returns_none():
    # bewusst kein FX-Convert — siehe GBX/GBP-Memory
    assert (
        compute_distance_pct("buy", Decimal("90"), Decimal("100"), "USD", "CHF")
        is None
    )


def test_distance_no_quote_returns_none():
    assert compute_distance_pct("buy", Decimal("90"), None, "USD", "USD") is None


def test_distance_zero_or_negative_quote_returns_none():
    assert compute_distance_pct("buy", Decimal("90"), Decimal("0"), "USD", "USD") is None


def test_distance_quote_currency_case_insensitive():
    """USD im Limit, usd im Quote — soll matchen."""
    actual = compute_distance_pct("buy", Decimal("90"), Decimal("100"), "USD", "usd")
    assert actual == Decimal("0.10")


def _mk_order(status: str, expiry_type: str = "gtc", expiry_date=None):
    return SimpleNamespace(status=status, expiry_type=expiry_type, expiry_date=expiry_date)


def test_effective_status_open_no_expiry():
    today = date(2026, 5, 8)
    assert compute_effective_status(_mk_order("open"), today) == "open"


def test_effective_status_filled_returns_filled():
    today = date(2026, 5, 8)
    assert compute_effective_status(_mk_order("filled"), today) == "filled"


def test_effective_status_cancelled_returns_cancelled():
    today = date(2026, 5, 8)
    assert compute_effective_status(_mk_order("cancelled"), today) == "cancelled"


def test_effective_status_gtd_in_past_is_expired():
    today = date(2026, 5, 8)
    yesterday = today - timedelta(days=1)
    order = _mk_order("open", "gtd", yesterday)
    assert compute_effective_status(order, today) == "expired"


def test_effective_status_gtd_today_is_open():
    """GTD-Date heute zaehlt noch nicht als expired (nur < today)."""
    today = date(2026, 5, 8)
    order = _mk_order("open", "gtd", today)
    assert compute_effective_status(order, today) == "open"


def test_effective_status_gtd_in_future_is_open():
    today = date(2026, 5, 8)
    tomorrow = today + timedelta(days=1)
    order = _mk_order("open", "gtd", tomorrow)
    assert compute_effective_status(order, today) == "open"


def test_effective_status_gtd_already_filled_stays_filled():
    """Wenn DB-Status filled ist, ueberschreibt expiry-Logik nicht."""
    today = date(2026, 5, 8)
    yesterday = today - timedelta(days=1)
    order = _mk_order("filled", "gtd", yesterday)
    assert compute_effective_status(order, today) == "filled"
