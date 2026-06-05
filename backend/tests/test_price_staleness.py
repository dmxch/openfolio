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
from services.price_staleness_service import (
    STALE_THRESHOLD_DAYS,
    check_price_staleness,
)

pytestmark = pytest.mark.asyncio

REFERENCE = date(2026, 6, 5)


def _pos(ticker, *, yf=None, type=AssetType.stock, coingecko_id=None, gold_org=False, active=True):
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
    )


def _price(ticker, d, close=100.0):
    return PriceCache(ticker=ticker, date=d, close=close, currency="CHF", source="yahoo")


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


async def test_yfinance_ticker_used_for_lookup(db):
    # Position display=ROG.SW aber yfinance_ticker=ROP.SW → Lookup muss ROP.SW nutzen.
    db.add(_pos("ROG.SW", yf="ROP.SW"))
    db.add(_price("ROP.SW", REFERENCE))
    await db.commit()
    r = await check_price_staleness(db)
    assert r["stale_count"] == 0  # ROP.SW ist frisch → nicht geflaggt
