"""Tests fuer per-Bucket total-return + fee-summary.

Verifiziert die Attribution:
  - unrealized: Positionen mit Position.bucket_id (aus summary-Param)
  - realized: Sells via Transaction.bucket_id_at_sale (Snapshot zum Verkauf)
  - Dividenden/Zinsen/Gebuehren: aktueller Bucket der Position (Position.bucket_id)
  - HEILIGE Regel 11: whole-portfolio-Funktion bleibt unberuehrt (separate Funktion).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from models.position import AssetType, Position, PricingMode, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services.bucket_service import create_bucket, create_system_buckets
from services.total_return_service import get_bucket_total_return, get_fee_summary

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    return user


def _make_position(user_id, bucket_id, ticker="AAPL") -> Position:
    return Position(
        user_id=user_id,
        bucket_id=bucket_id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="CHF",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("1"),
        cost_basis_chf=Decimal("0"),
    )


def _dividend(user_id, pos_id, *, net=10, gross=12, tax=2, d=date(2025, 3, 1)) -> Transaction:
    return Transaction(
        user_id=user_id, position_id=pos_id, type=TransactionType.dividend,
        date=d, shares=Decimal("0"), price_per_share=Decimal("0"),
        currency="CHF", fx_rate_to_chf=Decimal("1"),
        fees_chf=Decimal("0"), taxes_chf=Decimal(str(tax)),
        total_chf=Decimal(str(net)),
        gross_amount=Decimal(str(gross)), tax_amount=Decimal(str(tax)),
    )


def _fee(user_id, pos_id, *, amount=3, d=date(2025, 3, 2)) -> Transaction:
    return Transaction(
        user_id=user_id, position_id=pos_id, type=TransactionType.fee,
        date=d, shares=Decimal("0"), price_per_share=Decimal("0"),
        currency="CHF", fx_rate_to_chf=Decimal("1"),
        fees_chf=Decimal("0"), taxes_chf=Decimal("0"),
        total_chf=Decimal(str(-amount)),
    )


def _sell(user_id, pos_id, bucket_at_sale, *, pnl=20, fee=1, d=date(2025, 3, 3)) -> Transaction:
    return Transaction(
        user_id=user_id, position_id=pos_id, type=TransactionType.sell,
        date=d, shares=Decimal("1"), price_per_share=Decimal("100"),
        currency="CHF", fx_rate_to_chf=Decimal("1"),
        fees_chf=Decimal(str(fee)), taxes_chf=Decimal("0"),
        total_chf=Decimal("100"), cost_basis_at_sale=Decimal("80"),
        realized_pnl_chf=Decimal(str(pnl)), realized_pnl=Decimal(str(pnl)),
        bucket_id_at_sale=bucket_at_sale,
    )


async def _setup_two_buckets(db):
    user = await _make_user(db)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket_a = await create_bucket(db, user.id, name="Core")
    bucket_b = await create_bucket(db, user.id, name="Satellite")
    await db.commit()
    pos_a = _make_position(user.id, bucket_a.id, ticker="AAPL")
    pos_b = _make_position(user.id, bucket_b.id, ticker="MSFT")
    db.add_all([pos_a, pos_b])
    await db.commit()
    return user, bucket_a, bucket_b, pos_a, pos_b


def _summary(pos_a, pos_b):
    """Synthetischer get_portfolio_summary-Output (nur was total-return liest).

    invested = market_value_chf - pnl_chf, daher market_value_chf = cost_basis + pnl.
    """
    return {
        "positions": [
            {"bucket_id": str(pos_a.bucket_id), "pnl_chf": 100, "cost_basis_chf": 1000, "market_value_chf": 1100, "type": "stock"},
            {"bucket_id": str(pos_b.bucket_id), "pnl_chf": 50, "cost_basis_chf": 500, "market_value_chf": 550, "type": "stock"},
        ],
    }


async def test_bucket_total_return_attribution(db):
    user, bucket_a, bucket_b, pos_a, pos_b = await _setup_two_buckets(db)
    db.add_all([
        _dividend(user.id, pos_a.id, net=10, gross=12, tax=2),
        _fee(user.id, pos_a.id, amount=3),
        _sell(user.id, pos_a.id, bucket_a.id, pnl=20, fee=1),
        _dividend(user.id, pos_b.id, net=99, gross=99, tax=0),
    ])
    await db.commit()

    res_a = await get_bucket_total_return(db, user.id, bucket_a.id, summary=_summary(pos_a, pos_b))
    assert res_a["unrealized_pnl_chf"] == 100.0
    assert res_a["realized_pnl_chf"] == 20.0
    assert res_a["dividends_net_chf"] == 10.0
    assert res_a["dividends_gross_chf"] == 12.0
    assert res_a["dividends_tax_chf"] == 2.0
    assert res_a["trading_fees_chf"] == 1.0
    assert res_a["other_fees_chf"] == 3.0
    # 100 + 20 + 10 + 0 + 0 - 3 (nur standalone fees)
    assert res_a["total_return_chf"] == 127.0
    assert res_a["total_invested_chf"] == 1000.0
    assert res_a["total_return_pct"] == 12.7
    assert res_a["is_money_weighted"] is False

    res_b = await get_bucket_total_return(db, user.id, bucket_b.id, summary=_summary(pos_a, pos_b))
    assert res_b["unrealized_pnl_chf"] == 50.0
    assert res_b["realized_pnl_chf"] == 0.0  # Sell war in bucket_a
    assert res_b["dividends_net_chf"] == 99.0
    assert res_b["total_invested_chf"] == 500.0


async def test_realized_uses_bucket_id_at_sale_not_current(db):
    """Sell zaehlt zum Bucket-at-sale, auch wenn die Position spaeter umzieht."""
    user, bucket_a, bucket_b, pos_a, pos_b = await _setup_two_buckets(db)
    db.add(_sell(user.id, pos_a.id, bucket_a.id, pnl=20, fee=0))
    await db.commit()
    # Position spaeter nach bucket_b umhaengen
    pos_a.bucket_id = bucket_b.id
    await db.commit()

    res_a = await get_bucket_total_return(db, user.id, bucket_a.id, summary=_summary(pos_a, pos_b))
    assert res_a["realized_pnl_chf"] == 20.0  # bleibt in bucket_a
    res_b = await get_bucket_total_return(db, user.id, bucket_b.id, summary=_summary(pos_a, pos_b))
    assert res_b["realized_pnl_chf"] == 0.0


async def test_fee_summary_bucket_filter(db):
    user, bucket_a, bucket_b, pos_a, pos_b = await _setup_two_buckets(db)
    db.add_all([
        _fee(user.id, pos_a.id, amount=3),
        _sell(user.id, pos_a.id, bucket_a.id, pnl=20, fee=1),  # trading fee 1 auf pos_a
        _fee(user.id, pos_b.id, amount=7),
    ])
    await db.commit()

    fa = await get_fee_summary(db, user_id=user.id, bucket_id=bucket_a.id)
    assert fa["total_other_fees_chf"] == 3.0
    assert fa["total_trading_fees_chf"] == 1.0

    fb = await get_fee_summary(db, user_id=user.id, bucket_id=bucket_b.id)
    assert fb["total_other_fees_chf"] == 7.0
    assert fb["total_trading_fees_chf"] == 0.0

    # Ohne bucket_id: whole-portfolio (unveraendert) = Summe beider
    fall = await get_fee_summary(db, user_id=user.id)
    assert fall["total_other_fees_chf"] == 10.0
    assert fall["total_trading_fees_chf"] == 1.0


async def test_invested_uses_chf_market_value_for_cash(db):
    """Fremdwaehrungs-Cash in einem liquiden Bucket: total_invested muss der
    CHF-Marktwert (market_value_chf) sein, NICHT das rohe cost_basis_chf, das fuer
    Cash ein Fremdwaehrungs-Saldo ist (reference_cash_saldo_manual)."""
    user, bucket_a, bucket_b, pos_a, pos_b = await _setup_two_buckets(db)
    summary = {
        "positions": [
            # USD-Cash-Konto: cost_basis_chf = 10000 (USD-Saldo!), market_value_chf = 8800 (CHF)
            {"bucket_id": str(bucket_a.id), "pnl_chf": 0, "cost_basis_chf": 10000, "market_value_chf": 8800, "type": "cash"},
        ],
    }
    res = await get_bucket_total_return(db, user.id, bucket_a.id, summary=summary)
    assert res["total_invested_chf"] == 8800.0  # CHF-Marktwert, nicht 10000 (USD-Saldo)
    assert res["unrealized_pnl_chf"] == 0.0


async def test_bucket_total_return_user_isolation(db):
    user, bucket_a, bucket_b, pos_a, pos_b = await _setup_two_buckets(db)
    other = await _make_user(db)
    await create_system_buckets(db, other.id)
    await db.commit()
    other_bucket = await create_bucket(db, other.id, name="Core")
    await db.commit()
    other_pos = _make_position(other.id, other_bucket.id, ticker="TSLA")
    db.add(other_pos)
    await db.commit()
    db.add(_dividend(other.id, other_pos.id, net=999, gross=999, tax=0))
    await db.commit()

    # user fragt seinen bucket_a ab — darf die 999-Dividende von other NIE sehen
    res = await get_bucket_total_return(db, user.id, bucket_a.id, summary=_summary(pos_a, pos_b))
    assert res["dividends_net_chf"] == 0.0
