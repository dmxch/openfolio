"""Tests für den Price-Staleness-Guard (services/price_staleness_service.py).

Deckt ab:
- stale Ticker (latest älter als Schwelle ggü. frischestem Peer)
- no-data Ticker (keine price_cache-Zeile) → gilt als stale
- frische Ticker werden nicht geflaggt
- nicht-yahoo Positionen (cash/pension/PE/crypto/gold) werden übersprungen
- Referenz = frischester Peer (absorbiert Wochenenden/Feiertage)
"""
import uuid
from datetime import date, timedelta

import pytest

from models.position import AssetType, Position
from models.price_cache import PriceCache
from models.watchlist import WatchlistItem
from services.price_staleness_service import (
    STALE_THRESHOLD_DAYS,
    check_price_staleness,
)

pytestmark = pytest.mark.asyncio

REFERENCE = date(2026, 6, 5)


def _pos(ticker, *, yf=None, type=AssetType.stock, coingecko_id=None, gold_org=False, active=True, shares=1.0):
    return Position(
        user_id=uuid.uuid4(),
        bucket_id=uuid.uuid4(),
        ticker=ticker,
        name=ticker,
        type=type,
        yfinance_ticker=yf,
        coingecko_id=coingecko_id,
        gold_org=gold_org,
        is_active=active,
        shares=shares,
    )


def _price(ticker, d, close=100.0):
    return PriceCache(ticker=ticker, date=d, close=close, currency="CHF", source="yahoo")


def _wl(ticker, *, type=None, active=True):
    return WatchlistItem(
        user_id=uuid.uuid4(), ticker=ticker, name=ticker, type=type, is_active=active
    )


async def test_flags_stale_and_missing_skips_fresh_and_nonyahoo(db):
    db.add_all([
        _pos("NOVN.SW"),                       # fresh
        _pos("ROG.SW", yf="ROG.SW"),           # stale 17d
        _pos("XNJP.L"),                        # no price_cache row at all
        _pos("CASH", type=AssetType.cash),     # skip: cash
        _pos("BTC", type=AssetType.crypto, coingecko_id="bitcoin"),  # skip: crypto
    ])
    db.add_all([
        _price("NOVN.SW", REFERENCE),
        _price("ROG.SW", date(2026, 5, 19)),   # 17 days before reference
    ])
    await db.commit()

    r = await check_price_staleness(db)

    assert r["reference_date"] == REFERENCE.isoformat()
    assert r["total_monitored"] == 3  # cash + crypto skipped
    by_ticker = {s["ticker"]: s for s in r["stale"]}
    assert set(by_ticker) == {"ROG.SW", "XNJP.L"}
    assert by_ticker["ROG.SW"]["days_stale"] == 17
    assert by_ticker["XNJP.L"]["latest"] is None
    # NOVN.SW (fresh) nicht geflaggt
    assert "NOVN.SW" not in by_ticker


async def test_within_threshold_not_flagged(db):
    db.add_all([_pos("AAA"), _pos("BBB")])
    db.add_all([
        _price("AAA", REFERENCE),
        _price("BBB", REFERENCE - timedelta(days=STALE_THRESHOLD_DAYS)),  # genau an der Schwelle
    ])
    await db.commit()

    r = await check_price_staleness(db)
    assert r["stale_count"] == 0


async def test_missing_first_then_most_stale(db):
    db.add_all([_pos("FRESH"), _pos("OLD"), _pos("GONE")])
    db.add_all([
        _price("FRESH", REFERENCE),
        _price("OLD", date(2026, 5, 25)),  # 11d
    ])
    await db.commit()

    r = await check_price_staleness(db)
    order = [s["ticker"] for s in r["stale"]]
    assert order[0] == "GONE"  # no-data zuerst
    assert order[1] == "OLD"


async def test_no_data_at_all(db):
    db.add(_pos("AAA"))
    await db.commit()
    r = await check_price_staleness(db)
    assert r.get("no_data") is True
    assert r["stale_count"] == 0


async def test_zero_share_position_skipped(db):
    # Geschlossene Position (shares=0, is_active=true) mit totem Symbol darf NICHT
    # alarmieren — sonst taegliche Fehlalarme auf verkaufte Titel.
    db.add_all([
        _pos("HELD"),                       # shares=1 → ueberwacht
        _pos("CLOSED", yf="DEAD.SW", shares=0),  # shares=0 → uebersprungen, keine price_cache
    ])
    db.add(_price("HELD", REFERENCE))
    await db.commit()

    r = await check_price_staleness(db)
    assert r["total_monitored"] == 1  # nur HELD
    assert r["stale_count"] == 0      # CLOSED ignoriert trotz totem Symbol


async def test_watchlist_item_with_dead_symbol_flagged(db):
    # Watchlist-Symbol ohne price_cache-Zeile (z.B. BRK.B statt BRK-B) → geflaggt.
    db.add_all([_pos("HELD"), _wl("BRK.B")])
    db.add(_price("HELD", REFERENCE))
    await db.commit()

    r = await check_price_staleness(db)
    by_ticker = {s["ticker"]: s for s in r["stale"]}
    assert "BRK.B" in by_ticker
    assert by_ticker["BRK.B"]["latest"] is None
    assert by_ticker["BRK.B"]["display"] == ["BRK.B (Watchlist)"]


async def test_watchlist_crypto_skipped(db):
    # Crypto-Watchlist-Item wird via CoinGecko bepreist → nicht im price_cache,
    # darf nicht fälschlich als stale gelten.
    db.add_all([_pos("HELD"), _wl("DOGE", type=AssetType.crypto)])
    db.add(_price("HELD", REFERENCE))
    await db.commit()

    r = await check_price_staleness(db)
    assert all(s["ticker"] != "DOGE" for s in r["stale"])


async def test_yfinance_ticker_used_for_lookup(db):
    # Position display=ROG.SW aber yfinance_ticker=ROP.SW → Lookup muss ROP.SW nutzen.
    db.add(_pos("ROG.SW", yf="ROP.SW"))
    db.add(_price("ROP.SW", REFERENCE))
    await db.commit()
    r = await check_price_staleness(db)
    assert r["stale_count"] == 0  # ROP.SW ist frisch → nicht geflaggt
