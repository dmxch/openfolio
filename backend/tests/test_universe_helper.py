"""Tests fuer services.screening.universe.resolve_equity_universe.

Pre-Deploy-Audit-Gate (siehe docs/research/diagnose_universe_audit_2026-05-21.md):
- Junk-Tickers (Cash, Crypto, ETF, Multi-Listing-Format) muessen rausfallen
- US-Stocks (type=stock) muessen drinbleiben
- Watchlist-Active-Filter respektiert
- Dedup ueber Positions/Watchlist-Overlap
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from models.position import AssetType, Position, PriceSource, PricingMode
from models.user import User, UserSettings
from models.watchlist import WatchlistItem
from services.bucket_service import create_system_buckets, list_buckets
from services.screening.universe import classify_ticker_format, resolve_equity_universe

# pytest-asyncio laeuft in Mode.AUTO (siehe pytest.ini) — async-Tests werden
# automatisch erkannt; kein modulweites pytest.mark.asyncio noetig (das wuerde
# nur den sync-Klassifizierer-Test faelschlich markieren).


async def _make_user(db) -> tuple[User, "uuid.UUID"]:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await create_system_buckets(db, user.id)
    await db.commit()
    buckets = await list_buckets(db, user.id)
    # "Alle Positionen" ist der Default-Bucket fuer normale Stocks
    default_bucket = next(b for b in buckets if b.name == "Alle Positionen")
    return user, default_bucket.id


async def _add_position(db, user, bucket_id, *, ticker: str, type_: AssetType, currency: str = "USD"):
    pos = Position(
        user_id=user.id,
        bucket_id=bucket_id,
        ticker=ticker,
        name=f"{ticker} test",
        type=type_,
        currency=currency,
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("1"),
        cost_basis_chf=Decimal("100"),
        current_price=Decimal("100"),
    )
    db.add(pos)
    await db.commit()


async def _add_watchlist(db, user, *, ticker: str, is_active: bool = True, type_=None):
    wl = WatchlistItem(user_id=user.id, ticker=ticker, name=ticker, is_active=is_active, type=type_)
    db.add(wl)
    await db.commit()


async def test_keeps_us_stocks_drops_junk(db):
    """type=stock bleibt, ETF/Crypto/Cash/Commodity raus."""
    user, bucket = await _make_user(db)
    await _add_position(db, user, bucket, ticker="AAPL", type_=AssetType.stock)
    await _add_position(db, user, bucket, ticker="MSFT", type_=AssetType.stock)
    await _add_position(db, user, bucket, ticker="VWRL", type_=AssetType.etf)
    await _add_position(db, user, bucket, ticker="BTC-USD", type_=AssetType.crypto)
    await _add_position(db, user, bucket, ticker="CASH_CHF", type_=AssetType.cash, currency="CHF")
    await _add_position(db, user, bucket, ticker="GLD", type_=AssetType.commodity)

    result = await resolve_equity_universe(db)

    assert result == ["AAPL", "MSFT"]


async def test_drops_multi_listing_format(db):
    """Format-Filter: . und : sind Multi-Listing-Suffixe."""
    user, bucket = await _make_user(db)
    await _add_position(db, user, bucket, ticker="AAPL", type_=AssetType.stock)
    await _add_position(db, user, bucket, ticker="ROG.SW", type_=AssetType.stock)
    await _add_position(db, user, bucket, ticker="ICHN.L", type_=AssetType.stock)
    await _add_position(db, user, bucket, ticker="SSV.TO", type_=AssetType.stock)
    await _add_position(db, user, bucket, ticker="ABC:US", type_=AssetType.stock)

    result = await resolve_equity_universe(db)

    assert result == ["AAPL"]


async def test_includes_active_watchlist(db):
    """is_active=true Watchlist-Tickers drin, is_active=false raus."""
    user, bucket = await _make_user(db)
    await _add_position(db, user, bucket, ticker="AAPL", type_=AssetType.stock)
    await _add_watchlist(db, user, ticker="NVDA", is_active=True)
    await _add_watchlist(db, user, ticker="GOOG", is_active=True)
    await _add_watchlist(db, user, ticker="OLDX", is_active=False)

    result = await resolve_equity_universe(db)

    assert result == ["AAPL", "GOOG", "NVDA"]


async def test_watchlist_format_filter(db):
    """Watchlist hat keinen type, aber Format-Filter greift."""
    user, _ = await _make_user(db)
    await _add_watchlist(db, user, ticker="NVDA", is_active=True)
    await _add_watchlist(db, user, ticker="NESN.SW", is_active=True)
    await _add_watchlist(db, user, ticker="VOD.L", is_active=True)

    result = await resolve_equity_universe(db)

    assert result == ["NVDA"]


async def test_dedup_position_watchlist_overlap(db):
    """Ein Ticker in Position UND Watchlist erscheint nur einmal."""
    user, bucket = await _make_user(db)
    await _add_position(db, user, bucket, ticker="MSFT", type_=AssetType.stock)
    await _add_watchlist(db, user, ticker="MSFT", is_active=True)

    result = await resolve_equity_universe(db)

    assert result == ["MSFT"]


async def test_normalizes_case_and_whitespace(db):
    """Ticker werden upper-cased und getrimmt; Duplikate dedupliziert."""
    user, bucket = await _make_user(db)
    await _add_position(db, user, bucket, ticker="aapl", type_=AssetType.stock)
    await _add_watchlist(db, user, ticker="AAPL ", is_active=True)
    await _add_watchlist(db, user, ticker=" msft", is_active=True)

    result = await resolve_equity_universe(db)

    assert result == ["AAPL", "MSFT"]


async def test_empty_returns_empty_list(db):
    """Keine Positionen, keine Watchlist → leere Liste."""
    result = await resolve_equity_universe(db)
    assert result == []


async def test_multi_user_universe_is_global(db):
    """Universum aggregiert ueber alle User (FMP-Pulls sind global, nicht per-User)."""
    user_a, bucket_a = await _make_user(db)
    user_b, bucket_b = await _make_user(db)
    await _add_position(db, user_a, bucket_a, ticker="AAPL", type_=AssetType.stock)
    await _add_position(db, user_b, bucket_b, ticker="GOOG", type_=AssetType.stock)
    await _add_watchlist(db, user_a, ticker="NVDA", is_active=True)

    result = await resolve_equity_universe(db)

    assert result == ["AAPL", "GOOG", "NVDA"]


async def test_watchlist_typed_crypto_excluded(db):
    """Watchlist-Eintrag mit type=crypto faellt raus, type=stock/NULL bleibt."""
    user, _ = await _make_user(db)
    await _add_watchlist(db, user, ticker="NVDA", type_=AssetType.stock)
    await _add_watchlist(db, user, ticker="GOOG", type_=None)
    await _add_watchlist(db, user, ticker="SOLANA", type_=AssetType.crypto)

    result = await resolve_equity_universe(db)

    assert result == ["GOOG", "NVDA"]


async def test_watchlist_typed_etf_excluded(db):
    """Explizit als ETF getaggter Watchlist-Eintrag faellt raus (auch ohne Format-Suffix)."""
    user, _ = await _make_user(db)
    await _add_watchlist(db, user, ticker="NVDA", type_=AssetType.stock)
    await _add_watchlist(db, user, ticker="SPY", type_=AssetType.etf)

    result = await resolve_equity_universe(db)

    assert result == ["NVDA"]


async def test_crypto_pair_suffix_dropped_even_when_untyped(db):
    """Legacy-NULL-Row mit Crypto-Pair-Suffix faellt durch Format-Backstop raus."""
    user, _ = await _make_user(db)
    await _add_watchlist(db, user, ticker="NVDA", type_=None)
    await _add_watchlist(db, user, ticker="ETH-USD", type_=None)
    await _add_watchlist(db, user, ticker="BTC-EUR", type_=None)

    result = await resolve_equity_universe(db)

    assert result == ["NVDA"]


async def test_b_shares_with_hyphen_kept(db):
    """US-B-Shares (BRK-B, BF-B) haben Bindestrich, sind aber Equities → drin."""
    user, bucket = await _make_user(db)
    await _add_position(db, user, bucket, ticker="BRK-B", type_=AssetType.stock)
    await _add_position(db, user, bucket, ticker="BF-B", type_=AssetType.stock)

    result = await resolve_equity_universe(db)

    assert result == ["BF-B", "BRK-B"]


@pytest.mark.parametrize(
    "ticker,expected",
    [
        ("BTC-USD", AssetType.crypto),
        ("eth-eur", AssetType.crypto),
        ("SOL-USDT", AssetType.crypto),
        ("BRK-B", None),
        ("BF-B", None),
        ("AAPL", None),
        ("ROG.SW", None),
        ("", None),
    ],
)
def test_classify_ticker_format(ticker, expected):
    assert classify_ticker_format(ticker) == expected
