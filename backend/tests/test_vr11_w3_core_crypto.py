"""Vollreview 11/2026, Welle 3, Fixer «core»: Leser der Krypto-Kurse nach K019.

Seit K019 liegen CoinGecko-Kurse in price_cache unter «CG:<coingecko_id>» (CHF),
nie unter dem frei wählbaren Ticker der Position. Die coingecko_id zählt nur
beim Typ crypto; bei jedem anderen Typ ist sie ein Altbestand und die Position
läuft über Yahoo. Je Leser belegt ein Test beide Richtungen.

B2: Pending Orders auf den Ticker einer eigenen Krypto-Position.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from models.pending_order import PendingOrder
from models.position import AssetType, Position
from models.price_cache import PriceCache
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services import cache as app_cache
from services import history_service, snapshot_service
from services.bucket_service import create_bucket, create_system_buckets
from services.cache_service import crypto_price_key
from services.pending_order_service import get_digest_buckets, get_pending_orders
from services.performance_service import calculate_daily_change
from services.price_staleness_service import check_price_staleness

pytestmark = pytest.mark.asyncio


def _pos(user_id, ticker, *, type=AssetType.stock, coingecko_id=None, yf=None,
         currency="USD", shares="2"):
    return Position(
        user_id=user_id, bucket_id=uuid.uuid4(), ticker=ticker, name=ticker, type=type,
        coingecko_id=coingecko_id, yfinance_ticker=yf, currency=currency,
        shares=Decimal(shares), cost_basis_chf=Decimal("1000"), is_active=True,
    )


def _price(ticker, d, close, currency="CHF", source="coingecko"):
    return PriceCache(ticker=ticker, date=d, close=close, currency=currency, source=source)


@pytest.fixture
def cache_keys():
    """Setzt Schlüssel im App-Cache und räumt sie nach dem Test wieder ab."""
    keys: list[str] = []

    def _set(key, value):
        keys.append(key)
        app_cache.set(key, value)

    yield _set
    for key in keys:
        app_cache.delete(key)


# --- performance_service: Tagesveränderung ------------------------------------


async def test_daily_change_reads_crypto_from_coingecko_key(db):
    uid = uuid.uuid4()
    today, prev = date.today(), date.today() - timedelta(days=1)
    db.add(_pos(uid, "BTC", type=AssetType.crypto, coingecko_id="bitcoin"))
    db.add_all([
        _price(crypto_price_key("bitcoin"), prev, 50000),
        _price(crypto_price_key("bitcoin"), today, 51000),
        # Yahoo «BTC» ist ein anderes Instrument und darf nicht zählen.
        _price("BTC", prev, 40, "USD", "yahoo"),
        _price("BTC", today, 20, "USD", "yahoo"),
        _price("USDCHF=X", today, 0.9, "CHF", "yahoo"),
    ])
    await db.commit()

    res = await calculate_daily_change(db, uid)

    assert res["positions_valued"] == 1
    # 2 Stück × (51000 − 50000) CHF; die Zeile trägt CHF, also ohne FX.
    assert res["daily_change_chf"] == 2000.0
    assert res["daily_change_pct"] == 2.0


async def test_daily_change_legacy_coingecko_id_uses_yahoo_ticker(db):
    uid = uuid.uuid4()
    today, prev = date.today(), date.today() - timedelta(days=1)
    db.add(_pos(uid, "AAPL", type=AssetType.stock, coingecko_id="bitcoin"))
    db.add_all([
        _price(crypto_price_key("bitcoin"), prev, 50000),
        _price(crypto_price_key("bitcoin"), today, 51000),
        _price("AAPL", prev, 100, "USD", "yahoo"),
        _price("AAPL", today, 110, "USD", "yahoo"),
        _price("USDCHF=X", today, 0.9, "CHF", "yahoo"),
    ])
    await db.commit()

    res = await calculate_daily_change(db, uid)

    assert res["positions_valued"] == 1
    assert res["daily_change_chf"] == 18.0  # 2 × 10 USD × 0.9


# --- snapshot_service: Tages-Snapshot -----------------------------------------


async def test_snapshot_values_crypto_with_coingecko_price(db, monkeypatch, cache_keys):
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"USD": 0.9})
    uid = uuid.uuid4()
    crypto = _pos(uid, "W3SOL", type=AssetType.crypto, coingecko_id="w3-solana")
    db.add(crypto)
    await db.commit()
    cache_keys("crypto:w3-solana", {"price": 150.0, "currency": "CHF", "change_pct": 1.0})
    # Ein Yahoo-Kurs unter dem Anzeige-Ticker gehört nicht zur Krypto-Position.
    cache_keys("price:W3SOL", {"price": 7.0, "currency": "USD", "change_pct": 0.0})

    total, cash = await snapshot_service._calc_portfolio_value_fast(db, uid)

    assert total == pytest.approx(300.0)  # 2 × 150 CHF, ohne FX
    assert cash == 0.0
    assert await snapshot_service._calc_position_value_chf(crypto, {"USD": 0.9}) == pytest.approx(300.0)


async def test_snapshot_values_legacy_coingecko_id_with_yahoo_price(db, monkeypatch, cache_keys):
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"USD": 0.9})
    uid = uuid.uuid4()
    legacy = _pos(uid, "W3AAPL", type=AssetType.stock, coingecko_id="w3-bitcoin")
    db.add(legacy)
    await db.commit()
    cache_keys("crypto:w3-bitcoin", {"price": 50000.0, "currency": "CHF", "change_pct": 1.0})
    cache_keys("price:W3AAPL", {"price": 100.0, "currency": "USD", "change_pct": 0.0})

    total, _cash = await snapshot_service._calc_portfolio_value_fast(db, uid)

    assert total == pytest.approx(180.0)  # 2 × 100 USD × 0.9, nicht 2 × 50000
    assert await snapshot_service._calc_position_value_chf(legacy, {"USD": 0.9}) == pytest.approx(180.0)


# --- history_service: Rückgriff ohne Yahoo-Bars --------------------------------


def test_crypto_seed_keys_only_for_pure_crypto_tickers():
    tradable = {
        "p1": {"ticker": "BTC-USD", "coingecko_id": "bitcoin"},
        "p2": {"ticker": "ETH-USD", "coingecko_id": "ethereum"},
        "p3": {"ticker": "ETH-USD", "coingecko_id": None},      # auch als Nicht-Krypto gehalten
        "p4": {"ticker": "DOT-USD", "coingecko_id": "polkadot"},
        "p5": {"ticker": "DOT-USD", "coingecko_id": "other-dot"},  # zwei Coins, ein Ticker
        "p6": {"ticker": "NESN.SW", "coingecko_id": None},
    }
    keys = history_service._crypto_seed_keys(
        tradable, ["BTC-USD", "ETH-USD", "DOT-USD", "NESN.SW", "UNKNOWN"]
    )
    assert keys == {"BTC-USD": "CG:bitcoin"}


async def _history_user(db, *, type, coingecko_id):
    user = User(email=f"w3{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await db.refresh(user)
    await create_system_buckets(db, user.id)
    await db.commit()
    bucket = await create_bucket(db, user.id, name="Core")
    await db.commit()
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="BTC-USD", name="Bitcoin",
        type=type, coingecko_id=coingecko_id, currency="USD",
        shares=Decimal("2"), cost_basis_chf=Decimal("10000"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    db.add(Transaction(
        user_id=user.id, position_id=pos.id, type=TransactionType.buy,
        date=date.today() - timedelta(days=40), shares=Decimal("2"),
        price_per_share=Decimal("5000"), currency="USD", total_chf=Decimal("10000"),
    ))
    await db.commit()
    return user


def _patch_history(monkeypatch, db_rows):
    """Yahoo liefert für BTC-USD keine Bars, für USDCHF=X konstant 0.9."""
    def _yf(all_tickers, **kwargs):
        cal = pd.date_range(kwargs["start"], kwargs["end"], freq="D")
        cols = {
            ("Close", t): np.full(len(cal), 0.9 if t == "USDCHF=X" else np.nan)
            for t in all_tickers
        }
        df = pd.DataFrame(cols, index=cal)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    requested: list[list[str]] = []

    def _db_prices(tickers, fallback_days=5):
        requested.append(list(tickers))
        return {t: db_rows[t] for t in tickers if t in db_rows}

    monkeypatch.setattr("services.history_service.yf_download", _yf)
    monkeypatch.setattr("services.history_service.get_fx_rates_batch", lambda: {"USD": 0.9})
    monkeypatch.setattr("services.benchmark_service.benchmark_quote_currency", lambda t: "CHF")
    monkeypatch.setattr("services.cache_service.get_cached_prices_batch_sync", _db_prices)
    return requested


async def test_history_seeds_crypto_from_coingecko_key(db, monkeypatch):
    user = await _history_user(db, type=AssetType.crypto, coingecko_id="bitcoin")
    requested = _patch_history(monkeypatch, {
        "CG:bitcoin": {"price": 45000.0, "currency": "CHF"},
    })
    today = date.today()

    hist = await history_service.get_portfolio_history(
        db, today - timedelta(days=10), today, benchmark="", user_id=user.id
    )

    assert "CG:bitcoin" in requested[0]
    # 45000 CHF ÷ 0.9 = 50000 USD; der Replay rechnet 2 × 50000 USD × 0.9.
    assert hist["data"][-1]["value"] == pytest.approx(90000.0)


async def test_history_legacy_coingecko_id_keeps_yahoo_key(db, monkeypatch):
    user = await _history_user(db, type=AssetType.stock, coingecko_id="bitcoin")
    requested = _patch_history(monkeypatch, {
        "CG:bitcoin": {"price": 45000.0, "currency": "CHF"},
        "BTC-USD": {"price": 100.0, "currency": "USD"},
    })
    today = date.today()

    hist = await history_service.get_portfolio_history(
        db, today - timedelta(days=10), today, benchmark="", user_id=user.id
    )

    assert requested[0] == ["BTC-USD"]
    assert hist["data"][-1]["value"] == pytest.approx(180.0)  # 2 × 100 USD × 0.9


# --- price_staleness_service ---------------------------------------------------


async def test_staleness_monitors_legacy_coingecko_id_and_skips_crypto(db):
    today = date.today()
    db.add_all([
        _pos(uuid.uuid4(), "NOVN.SW"),
        _pos(uuid.uuid4(), "AAPL", type=AssetType.stock, coingecko_id="bitcoin"),
        _pos(uuid.uuid4(), "BTC", type=AssetType.crypto, coingecko_id="bitcoin"),
    ])
    db.add_all([
        _price("NOVN.SW", today, 100, "CHF", "yahoo"),
        _price("AAPL", today - timedelta(days=20), 100, "USD", "yahoo"),
    ])
    await db.commit()

    report = await check_price_staleness(db)

    assert report["total_monitored"] == 2  # Krypto läuft nie über Yahoo
    assert [s["ticker"] for s in report["stale"]] == ["AAPL"]
    assert report["stale"][0]["days_stale"] == 20


# --- api/portfolio: 24-Stunden-Änderung ----------------------------------------


async def test_enrich_summary_takes_24h_change_from_the_right_namespace(monkeypatch):
    from api import portfolio as portfolio_api

    def _row(pid, ticker, type_):
        return SimpleNamespace(
            id=pid, bank_name=None, iban=None, notes=None, type=type_,
            coingecko_id="bitcoin", yfinance_ticker=None, ticker=ticker,
        )

    rows = [_row("p-crypto", "BTC", AssetType.crypto), _row("p-legacy", "MSFT", AssetType.stock)]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[rows, SimpleNamespace(all=lambda: [])])
    requested: list[list[str]] = []

    def _get_many(keys):
        requested.append(list(keys))
        return {
            "crypto:bitcoin": {"change_pct": 4.2},
            "price:MSFT": {"change_pct": -1.5},
            "price:BTC": {"change_pct": 99.0},  # Yahoo «BTC»: anderes Instrument
        }

    monkeypatch.setattr("services.cache.get_many", _get_many)
    summary = {"positions": [
        {"id": "p-crypto", "ticker": "BTC"},
        {"id": "p-legacy", "ticker": "MSFT"},
    ]}

    enriched = await portfolio_api._enrich_summary(db, SimpleNamespace(id=uuid.uuid4()), summary)

    assert requested == [["crypto:bitcoin", "price:MSFT"]]
    by_ticker = {p["ticker"]: p for p in enriched["positions"]}
    assert by_ticker["BTC"]["change_pct_24h"] == 4.2     # CoinGecko
    assert by_ticker["MSFT"]["change_pct_24h"] == -1.5   # Yahoo, nicht der Coin
    # Die Abfrage lädt den Typ mit, sonst lässt sich der Altbestand nicht erkennen.
    assert "positions.type" in str(db.execute.await_args_list[0].args[0])


# --- scripts/backfill_price_history --------------------------------------------


def test_backfill_collects_legacy_coingecko_id_and_skips_crypto():
    from scripts.backfill_price_history import collect_backfill_tickers

    uid = uuid.uuid4()
    positions = [
        _pos(uid, "NESN.SW"),
        _pos(uid, "AAPL", type=AssetType.stock, coingecko_id="bitcoin"),
        _pos(uid, "ROG", yf="ROG.SW"),
        _pos(uid, "BTC", type=AssetType.crypto, coingecko_id="bitcoin"),
        _pos(uid, "CASH", type=AssetType.cash),
        _pos(uid, "NESN.SW"),  # doppelt
    ]

    assert collect_backfill_tickers(positions) == ["NESN.SW", "AAPL", "ROG.SW"]


# --- B2: Pending Orders auf Krypto-Ticker --------------------------------------


def _order(user_id, ticker, *, currency="CHF", limit="40000", side="buy"):
    return PendingOrder(
        user_id=user_id, ticker=ticker, side=side, shares=Decimal("1"),
        limit_price=Decimal(limit), currency=currency,
    )


async def test_pending_order_on_own_crypto_ticker_gets_coingecko_quote(db):
    uid = uuid.uuid4()
    db.add(_pos(uid, "W3ADA", type=AssetType.crypto, coingecko_id="w3-cardano"))
    db.add(_order(uid, "w3ada"))  # Zuordnung ohne Rücksicht auf Gross-/Kleinschreibung
    db.add(_price(crypto_price_key("w3-cardano"), date.today() - timedelta(days=1), 50000))
    await db.commit()

    res = await get_pending_orders(db, uid)

    item = res["items"][0]
    assert item["current_price"] == 50000.0
    assert item["quote_currency"] == "CHF"
    assert item["distance_pct"] == pytest.approx(0.2)  # (50000 − 40000) / 50000


async def test_pending_order_prefers_cached_coingecko_price(db, cache_keys):
    uid = uuid.uuid4()
    db.add(_pos(uid, "W3XRP", type=AssetType.crypto, coingecko_id="w3-ripple"))
    db.add(_order(uid, "W3XRP", limit="41000"))
    db.add(_price(crypto_price_key("w3-ripple"), date.today(), 50000))
    await db.commit()
    cache_keys("crypto:w3-ripple", {"price": 40000.0, "currency": "CHF", "change_pct": 0.0})
    # Yahoo führt unter demselben Symbol ein anderes Instrument.
    cache_keys("price:W3XRP", {"price": 12.0, "currency": "USD", "change_pct": 0.0})

    digest = await get_digest_buckets(db, uid)

    assert [o["ticker"] for o in digest["breached"]] == ["W3XRP"]
    assert digest["breached"][0]["current_price"] == 40000.0


async def test_pending_order_ignores_crypto_positions_of_other_users(db):
    uid, other = uuid.uuid4(), uuid.uuid4()
    db.add(_pos(other, "W3DOT", type=AssetType.crypto, coingecko_id="w3-polkadot"))
    db.add(_order(uid, "W3DOT", currency="USD", limit="90"))
    db.add_all([
        _price(crypto_price_key("w3-polkadot"), date.today(), 50000),
        _price("W3DOT", date.today(), 100, "USD", "yahoo"),
    ])
    await db.commit()

    res = await get_pending_orders(db, uid)

    item = res["items"][0]
    assert item["current_price"] == 100.0  # Yahoo-Zeile unter dem Order-Ticker
    assert item["quote_currency"] == "USD"
    assert item["distance_pct"] == pytest.approx(0.1)


async def test_pending_order_without_price_stays_without_quote(db):
    uid = uuid.uuid4()
    db.add(_pos(uid, "W3LTC", type=AssetType.crypto, coingecko_id="w3-litecoin"))
    db.add(_order(uid, "W3LTC"))
    await db.commit()

    res = await get_pending_orders(db, uid)

    assert res["items"][0]["current_price"] is None
    assert res["items"][0]["distance_pct"] is None
