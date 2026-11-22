"""Vollreview 11/2026, Fixer «pricecache»: Kurs-Refresh, Preis-Cache, Positionen, Worker.

Abgedeckt: K019 (Krypto-Kurse im eigenen Namensraum), K017 (ungültige Zeilen
brechen den UPSERT nicht), K101/K109 (Positions-Update nur über den wirksamen
Ticker, manuelle Kurse bleiben), K163 (Fehlertext ohne Details), K117
(change_pct None im DB-Rückgriff), K058/X16 (Yahoo in Blöcken, kein zweiter
Download-Thread), K133 (SARON-Alter), K049 (FX mit 8 Stellen), K023 (nur
geprüfte Symbole als Liste), X12/K108 (Regen-Datum), K149, K009, K141, X41.
"""

import asyncio
import json
import threading
import types
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import HTTPException
from limits import parse as parse_limit
from sqlalchemy import select

import services.cache_service as cs
import worker
from constants.limits import RL_HEAVY
from dateutils import utcnow
from models.app_config import AppConfig
from models.bucket import Bucket
from models.position import AssetType, Position, PriceSource, PricingMode
from models.price_cache import PriceCache
from models.transaction import Transaction, TransactionType
from models.user import User
from models.watchlist import WatchlistItem
from services import cache, price_service
from services.bucket_service import create_system_buckets
from services.worker_health_service import compute_stale, get_all_health, record_job_run

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
TODAY = date.today()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_module_state():
    cache._mem_clear()
    cs._yahoo_block_cursor = 0
    cs._warned_invalid_symbols.clear()
    worker._reported_failures.clear()
    yield
    cache._mem_clear()
    cs._yahoo_block_cursor = 0
    worker._reported_failures.clear()


# Von Hand gepflegter Kurs: Modus UND Preisquelle manual (models.position.has_manual_price).
MANUAL_PRICE = dict(pricing_mode=PricingMode.manual, price_source=PriceSource.manual)


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await create_system_buckets(db, user.id)
    await db.commit()
    return user


async def _make_position(db, user, ticker="AAPL", **kwargs) -> Position:
    bucket_id = (
        await db.execute(select(Bucket.id).where(Bucket.user_id == user.id).limit(1))
    ).scalar()
    values = dict(
        bucket_id=bucket_id,
        user_id=user.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="USD",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("1"),
        cost_basis_chf=Decimal("1000"),
        current_price=Decimal("100"),
    )
    values.update(kwargs)
    pos = Position(**values)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


def _quote(price: float, currency: str = "USD") -> dict:
    return {"price": price, "currency": currency, "change_pct": 1.0}


async def _price_rows(db, ticker: str) -> list[PriceCache]:
    # populate_existing: die Zeilen entstehen und ändern sich über Core-Statements.
    stmt = select(PriceCache).where(PriceCache.ticker == ticker).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalars().all()


def _mock_providers(monkeypatch, yahoo: dict, crypto: dict | None = None) -> dict:
    """Ersetzt alle Provider von refresh_cache. Liefert die aufgezeichneten Aufrufe."""
    calls: dict = {"yahoo": [], "crypto": [], "saved": []}

    def fake_yahoo(tickers):
        calls["yahoo"].append(list(tickers))
        return {t: dict(yahoo[t]) for t in tickers if t in yahoo}

    async def fake_crypto(ids):
        calls["crypto"].append(list(ids))
        return {i: dict((crypto or {})[i]) for i in ids if i in (crypto or {})}

    async def fake_save(state):
        calls["saved"].append(state)

    saron = AsyncMock(return_value=None)
    calls["saron"] = saron
    monkeypatch.setattr(cs, "_download_yahoo_batch", fake_yahoo)
    monkeypatch.setattr(cs, "_fetch_crypto_batch", fake_crypto)
    monkeypatch.setattr(cs, "_fetch_metals", lambda spot_tickers: {})
    monkeypatch.setattr("services.property_service.fetch_saron_rate", saron)
    monkeypatch.setattr(cs, "_load_refresh_state_from_db", AsyncMock(return_value={}))
    monkeypatch.setattr(cs, "_save_refresh_state_to_db", fake_save)
    return calls


async def _register(client, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _position_payload(**overrides) -> dict:
    base = {"ticker": "AAPL", "name": "Apple Inc.", "type": "stock", "currency": "USD", "shares": 0, "cost_basis_chf": 0}
    base.update(overrides)
    return base


@pytest.fixture
def regen(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr("api.positions.trigger_snapshot_regen", mock)
    return mock


# ---------------------------------------------------------------------------
# K019 — Krypto-Kurse im eigenen Namensraum
# ---------------------------------------------------------------------------

async def test_crypto_position_with_foreign_ticker_leaves_shared_price_alone(db, monkeypatch):
    """Abnahmetest: A hält AAPL, B legt «AAPL» mit coingecko_id bitcoin an."""
    user_a = await _make_user(db)
    user_b = await _make_user(db)
    pos_a = await _make_position(db, user_a, ticker="AAPL")
    pos_b = await _make_position(
        db, user_b, ticker="AAPL", type=AssetType.crypto, coingecko_id="bitcoin",
        currency="CHF", price_source=PriceSource.coingecko,
    )
    calls = _mock_providers(
        monkeypatch,
        yahoo={"AAPL": _quote(190.0), "USDCHF=X": _quote(0.88, "FX")},
        crypto={"bitcoin": {"price": 57000.0, "currency": "CHF", "change_pct": 2.0, "source": "coingecko"}},
    )

    result = await cs.refresh_cache(db)

    assert result["status"] == "ok", result
    assert calls["crypto"] == [["bitcoin"]]
    aapl = await _price_rows(db, "AAPL")
    assert [(float(r.close), r.source, r.currency) for r in aapl] == [(190.0, "yahoo", "USD")]
    btc = await _price_rows(db, "CG:bitcoin")
    assert [(float(r.close), r.source, r.currency) for r in btc] == [(57000.0, "coingecko", "CHF")]

    await db.refresh(pos_a)
    await db.refresh(pos_b)
    assert float(pos_a.current_price) == pytest.approx(190.0)
    assert float(pos_b.current_price) == pytest.approx(57000.0)
    assert cache.get("price:AAPL")["price"] == 190.0
    assert cache.get("crypto:bitcoin")["price"] == 57000.0


async def test_coingecko_id_on_non_crypto_position_is_ignored(db, monkeypatch):
    """Altbestand: type=stock mit coingecko_id läuft über Yahoo, nicht über CoinGecko."""
    user_a = await _make_user(db)
    user_b = await _make_user(db)
    pos_a = await _make_position(db, user_a, ticker="AAPL")
    pos_b = await _make_position(db, user_b, ticker="AAPL", coingecko_id="bitcoin")
    calls = _mock_providers(
        monkeypatch,
        yahoo={"AAPL": _quote(190.0)},
        crypto={"bitcoin": {"price": 57000.0, "currency": "CHF", "change_pct": 2.0, "source": "coingecko"}},
    )

    await cs.refresh_cache(db)

    assert calls["crypto"] == [[]]
    assert await _price_rows(db, "CG:bitcoin") == []
    await db.refresh(pos_a)
    await db.refresh(pos_b)
    assert float(pos_a.current_price) == pytest.approx(190.0)
    assert float(pos_b.current_price) == pytest.approx(190.0)


async def test_collect_all_tickers_keys_crypto_by_coingecko_id(db):
    user = await _make_user(db)
    await _make_position(db, user, ticker="BTC-USD", type=AssetType.crypto, coingecko_id="bitcoin")
    other = await _make_user(db)
    await _make_position(db, other, ticker="XBT", type=AssetType.crypto, coingecko_id="bitcoin")
    await _make_position(db, other, ticker="ETHX", type=AssetType.crypto, coingecko_id="Not A Valid Id")
    await _make_position(db, other, ticker="NOID", type=AssetType.crypto)
    await _make_position(db, other, ticker="MSFT", coingecko_id="ethereum")
    await _make_position(db, other, ticker="MAN", **MANUAL_PRICE)
    await _make_position(db, other, ticker="LEGACY", pricing_mode=PricingMode.manual)
    await _make_position(db, other, ticker="AA,AB AC")
    db.add(WatchlistItem(user_id=user.id, ticker="NVDA", name="Nvidia"))
    db.add(WatchlistItem(user_id=other.id, ticker="X Y,Z", name="Unsinn"))
    await db.commit()

    info = await cs.collect_all_tickers(db)

    assert info["crypto"] == ["bitcoin"]  # dedupliziert, nur type=crypto, nur gültige IDs
    yahoo = set(info["yahoo_tickers"])
    # LEGACY: Modus manual, Preisquelle yahoo. Der Worker lädt den Kurs weiter.
    assert {"MSFT", "NVDA", "LEGACY"} <= yahoo
    # Krypto-Anzeige-Ticker, manuelle Position und Mehrfach-Symbole gehen nicht an Yahoo.
    assert not {"BTC-USD", "XBT", "ETHX", "NOID", "MAN", "AA,AB AC", "X Y,Z"} & yahoo


async def test_seed_position_price_writes_crypto_under_coingecko_key(db, monkeypatch):
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="AAPL", type=AssetType.crypto, coingecko_id="bitcoin")

    async def fake_crypto(ids):
        return {"bitcoin": {"price": 57000.0, "currency": "CHF", "change_pct": 2.0, "source": "coingecko"}}
    monkeypatch.setattr(cs, "_fetch_crypto_batch", fake_crypto)

    assert await cs.seed_position_price(db, pos) is True

    assert await _price_rows(db, "AAPL") == []
    assert [float(r.close) for r in await _price_rows(db, "CG:bitcoin")] == [57000.0]
    assert cache.get("price:AAPL") is None
    assert cache.get("crypto:bitcoin")["price"] == 57000.0


async def test_seed_position_price_skips_manual_and_invalid_symbols(db, monkeypatch):
    user = await _make_user(db)
    manual = await _make_position(db, user, ticker="MAN", **MANUAL_PRICE)
    weird = await _make_position(db, user, ticker="AA,AB AC")
    download = MagicMock(return_value={})
    monkeypatch.setattr(cs, "_download_yahoo_batch", download)

    assert await cs.seed_position_price(db, manual) is False
    assert await cs.seed_position_price(db, weird) is False
    download.assert_not_called()


class TestPositionSchemaGuards:
    async def test_create_rejects_coingecko_id_on_other_types(self, client, regen):
        headers = await _register(client, "cg-create@test.local")
        res = await client.post(
            "/api/portfolio/positions", headers=headers,
            json=_position_payload(coingecko_id="bitcoin"),
        )
        assert res.status_code == 422, res.text
        assert "CoinGecko-ID" in res.json()["detail"]

    @pytest.mark.parametrize("bad_id", ["Bitcoin", "bit coin", "bitcoin,ethereum", "a" * 61])
    async def test_create_rejects_malformed_coingecko_id(self, client, regen, bad_id):
        headers = await _register(client, "cg-pattern@test.local")
        res = await client.post(
            "/api/portfolio/positions", headers=headers,
            json=_position_payload(ticker="BTC-USD", type="crypto", coingecko_id=bad_id),
        )
        assert res.status_code == 422, res.text

    async def test_create_accepts_crypto_with_coingecko_id(self, client, regen):
        headers = await _register(client, "cg-ok@test.local")
        res = await client.post(
            "/api/portfolio/positions", headers=headers,
            json=_position_payload(ticker="BTC-USD", type="crypto", coingecko_id="bitcoin", yfinance_ticker=""),
        )
        assert res.status_code == 201, res.text
        assert res.json()["coingecko_id"] == "bitcoin"
        assert res.json()["yfinance_ticker"] is None  # leere Zeichenkette wird nicht gespeichert

    @pytest.mark.parametrize("payload", [
        {"ticker": "AA,AB"},
        {"ticker": "AA AB"},
        {"ticker": "CG:bitcoin"},
        {"ticker": "A" * 31},
        {"yfinance_ticker": "PAAS.TO MSFT"},
    ])
    async def test_create_rejects_symbols_yahoo_would_split(self, client, regen, payload):
        headers = await _register(client, "ticker-pattern@test.local")
        res = await client.post("/api/portfolio/positions", headers=headers, json=_position_payload(**payload))
        assert res.status_code == 422, res.text

    async def test_free_text_ticker_stays_allowed_for_cash(self, client, regen):
        headers = await _register(client, "cash-ticker@test.local")
        res = await client.post(
            "/api/portfolio/positions", headers=headers,
            json=_position_payload(ticker="CASH_ZKB LOHN, CHF", name="Lohnkonto", type="cash", currency="CHF", shares=1),
        )
        assert res.status_code == 201, res.text

    async def test_yfinance_ticker_and_stop_method_follow_column_width(self, client, regen):
        """K149: 31 Zeichen passen nicht in String(30) — 422 statt Datenbankfehler."""
        headers = await _register(client, "width@test.local")
        res = await client.post(
            "/api/portfolio/positions", headers=headers,
            json=_position_payload(yfinance_ticker="A" * 31),
        )
        assert res.status_code == 422, res.text
        created = await client.post("/api/portfolio/positions", headers=headers, json=_position_payload())
        res = await client.put(
            f"/api/portfolio/positions/{created.json()['id']}", headers=headers,
            json={"stop_loss_method": "x" * 31},
        )
        assert res.status_code == 422, res.text

    async def test_schema_lengths_fit_the_columns(self):
        """K149: kein Feld darf länger sein als seine Spalte (SQLite prüft das nicht)."""
        from api.positions import PositionCreate, PositionUpdate

        checked = 0
        for model in (PositionCreate, PositionUpdate):
            for name, field in model.model_fields.items():
                column = Position.__table__.c.get(name)
                length = getattr(getattr(column, "type", None), "length", None)
                max_len = next((m.max_length for m in field.metadata if hasattr(m, "max_length")), None)
                if length is None or max_len is None:
                    continue
                checked += 1
                assert max_len <= length, f"{model.__name__}.{name}: {max_len} > Spalte {length}"
        assert checked >= 10

    async def test_update_rejects_new_coingecko_id_on_stock(self, client, regen):
        headers = await _register(client, "cg-update@test.local")
        created = await client.post("/api/portfolio/positions", headers=headers, json=_position_payload())
        res = await client.put(
            f"/api/portfolio/positions/{created.json()['id']}", headers=headers,
            json={"coingecko_id": "bitcoin"},
        )
        assert res.status_code == 422, res.text

    async def test_update_keeps_legacy_position_editable(self, client, db, regen):
        """Altdaten: unveränderte Felder blockieren den Edit nicht; ein Typwechsel prüft neu."""
        headers = await _register(client, "cg-legacy@test.local")
        created = await client.post("/api/portfolio/positions", headers=headers, json=_position_payload())
        pos_id = created.json()["id"]
        pos = await db.get(Position, uuid.UUID(pos_id))
        pos.coingecko_id = "bitcoin"  # vor der Prüfung gespeichert
        await db.commit()

        same = {"ticker": "AAPL", "type": "stock", "coingecko_id": "bitcoin", "notes": "neu"}
        res = await client.put(f"/api/portfolio/positions/{pos_id}", headers=headers, json=same)
        assert res.status_code == 200, res.text

        res = await client.put(
            f"/api/portfolio/positions/{pos_id}", headers=headers,
            json={"type": "etf", "coingecko_id": "bitcoin"},
        )
        assert res.status_code == 422, res.text

        res = await client.put(
            f"/api/portfolio/positions/{pos_id}", headers=headers,
            json={"type": "etf", "coingecko_id": None},
        )
        assert res.status_code == 200, res.text

    async def test_core_rejects_with_http_422_for_the_external_api(self, db, regen):
        """Die externe API baut PositionCreate im Handler: die Ablehnung muss ein HTTPException sein."""
        from api.positions import PositionCreate, create_position_core

        user = await _make_user(db)
        data = PositionCreate(ticker="AAPL", name="Apple", type="stock", coingecko_id="bitcoin")
        with pytest.raises(HTTPException) as exc:
            await create_position_core(db, user, data)
        assert exc.value.status_code == 422

    async def test_test_price_rejects_symbol_lists(self, client, regen, monkeypatch):
        headers = await _register(client, "test-price@test.local")
        created = await client.post("/api/portfolio/positions", headers=headers, json=_position_payload())
        lookup = MagicMock(return_value=None)
        monkeypatch.setattr("api.positions.get_stock_price", lookup)
        res = await client.get(
            f"/api/portfolio/positions/{created.json()['id']}/test-price",
            headers=headers, params={"yfinance_ticker": "AAPL,MSFT GOOG"},
        )
        assert res.status_code == 422, res.text
        lookup.assert_not_called()


# ---------------------------------------------------------------------------
# K017 — ungültige Zeilen und Coins
# ---------------------------------------------------------------------------

async def test_upsert_skips_rows_that_would_break_the_statement(db):
    rows = [
        {"ticker": "GOOD", "date": TODAY, "close": 12.5, "currency": "USD", "source": "yahoo"},
        {"ticker": "X" * (cs._PRICE_KEY_MAX_LEN + 1), "date": TODAY, "close": 1.0, "currency": "USD", "source": "yahoo"},
        {"ticker": "NAN", "date": TODAY, "close": float("nan"), "currency": "USD", "source": "yahoo"},
        {"ticker": "INF", "date": TODAY, "close": float("inf"), "currency": "USD", "source": "yahoo"},
        {"ticker": "HUGE", "date": TODAY, "close": 1e10, "currency": "USD", "source": "yahoo"},
        {"ticker": "NONE", "date": TODAY, "close": None, "currency": "USD", "source": "yahoo"},
    ]

    assert await cs._upsert_price_rows(db, rows) == 1
    await db.commit()

    stored = (await db.execute(select(PriceCache.ticker))).scalars().all()
    assert stored == ["GOOD"]

    # Zweiter Lauf am selben Tag aktualisiert die Zeile, statt zu scheitern.
    rows[0]["close"] = 13.0
    assert await cs._upsert_price_rows(db, rows[:1]) == 1
    await db.commit()
    assert [float(r.close) for r in await _price_rows(db, "GOOD")] == [13.0]


async def test_refresh_drops_non_finite_prices_before_they_reach_positions(db, monkeypatch):
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="NANCO")
    _mock_providers(monkeypatch, yahoo={"NANCO": _quote(float("nan")), "USDCHF=X": _quote(0.88, "FX")})

    result = await cs.refresh_cache(db)

    assert result["status"] == "ok", result
    await db.refresh(pos)
    assert float(pos.current_price) == pytest.approx(100)
    assert await _price_rows(db, "NANCO") == []
    assert cache.get("price:NANCO") is None


async def test_fetch_crypto_batch_parses_each_coin_on_its_own(monkeypatch):
    requested = []

    async def fake_fetch(url, params=None, timeout=15):
        requested.append(params["ids"])
        return {
            "bitcoin": {"chf": 57000.0, "chf_24h_change": 2.344},
            "broken-coin": {"usd": 1.0},                      # kein chf
            "null-change": {"chf": 3.5, "chf_24h_change": None},
            "ethereum": {"chf": 2100.0, "chf_24h_change": -1.0},
        }
    monkeypatch.setattr("services.api_utils.fetch_json_coingecko", fake_fetch)

    ids = ["ethereum", "bitcoin", "bitcoin", "broken-coin", "null-change", "missing", "Bad Id"]
    results = await cs._fetch_crypto_batch(ids)

    assert requested == ["bitcoin,broken-coin,ethereum,missing,null-change"]  # dedupliziert, ohne ungültige ID
    assert set(results) == {"bitcoin", "ethereum", "null-change"}
    assert results["bitcoin"] == {"price": 57000.0, "currency": "CHF", "change_pct": 2.34, "source": "coingecko"}
    assert results["null-change"]["change_pct"] == 0


async def test_fetch_crypto_batch_sends_ids_in_blocks(monkeypatch):
    requested = []

    async def fake_fetch(url, params=None, timeout=15):
        chunk = params["ids"].split(",")
        requested.append(chunk)
        if "coin-000" in chunk:
            raise RuntimeError("414 URI Too Long")
        return {cg_id: {"chf": 1.0} for cg_id in chunk}
    monkeypatch.setattr("services.api_utils.fetch_json_coingecko", fake_fetch)

    ids = [f"coin-{i:03d}" for i in range(cs._COINGECKO_IDS_PER_REQUEST + 5)]
    results = await cs._fetch_crypto_batch(ids)

    assert [len(chunk) for chunk in requested] == [cs._COINGECKO_IDS_PER_REQUEST, 5]
    assert len(results) == 5  # der gescheiterte Block reisst den zweiten nicht mit


# ---------------------------------------------------------------------------
# K101 / K109 — Positions-Update
# ---------------------------------------------------------------------------

async def test_batch_price_update_matches_only_the_effective_ticker(db):
    """A hält «CFR» mit yfinance_ticker «CFR.SW»; ein Kurs für «CFR» gehört einem anderen Titel."""
    user = await _make_user(db)
    richemont = await _make_position(db, user, ticker="CFR", yfinance_ticker="CFR.SW")
    empty_yf = await _make_position(db, user, ticker="NESN", yfinance_ticker="")

    await cs._update_position_prices_batch(db, [("CFR", 140.0), ("NESN", 80.0)])
    await db.commit()
    await db.refresh(richemont)
    await db.refresh(empty_yf)
    assert float(richemont.current_price) == pytest.approx(100)  # nicht der Kurs von Cullen/Frost
    assert float(empty_yf.current_price) == pytest.approx(80.0)  # '' zählt wie kein yfinance_ticker

    await cs._update_position_prices_batch(db, [("CFR.SW", 155.5)])
    await db.commit()
    await db.refresh(richemont)
    assert float(richemont.current_price) == pytest.approx(155.5)


async def test_batch_price_update_leaves_manual_cash_and_crypto_alone(db):
    user = await _make_user(db)
    manual = await _make_position(db, user, ticker="MAN", current_price=Decimal("50"), **MANUAL_PRICE)
    cash = await _make_position(db, user, ticker="USD", type=AssetType.cash)
    crypto = await _make_position(db, user, ticker="BTC-USD", type=AssetType.crypto, coingecko_id="bitcoin")
    auto = await _make_position(db, user, ticker="AUTO")

    await cs._update_position_prices_batch(
        db, [("MAN", 77.0), ("USD", 33.0), ("BTC-USD", 66000.0), ("AUTO", 12.0)]
    )
    await db.commit()

    for pos in (manual, cash, crypto, auto):
        await db.refresh(pos)
    assert float(manual.current_price) == pytest.approx(50)
    assert float(cash.current_price) == pytest.approx(100)
    assert float(crypto.current_price) == pytest.approx(100)
    assert float(auto.current_price) == pytest.approx(12.0)


async def test_crypto_price_update_goes_by_coingecko_id_only(db):
    user = await _make_user(db)
    btc = await _make_position(db, user, ticker="AAPL", type=AssetType.crypto, coingecko_id="bitcoin")
    manual = await _make_position(
        db, user, ticker="BTC2", type=AssetType.crypto, coingecko_id="bitcoin", **MANUAL_PRICE,
    )
    stock = await _make_position(db, user, ticker="MSFT", coingecko_id="bitcoin")
    inactive = await _make_position(
        db, user, ticker="OLD", type=AssetType.crypto, coingecko_id="bitcoin", is_active=False,
    )

    await cs._update_crypto_position_prices(db, [("bitcoin", 57000.0), ("ethereum", 2100.0)])
    await db.commit()

    for pos in (btc, manual, stock, inactive):
        await db.refresh(pos)
    assert float(btc.current_price) == pytest.approx(57000.0)
    # Krypto mit coingecko_id hat eine eigene Kursquelle. Sie geht dem manuellen
    # Kurs vor, wie in Summary, Tages-Snapshot und Regen (has_own_price_source).
    assert float(manual.current_price) == pytest.approx(57000.0)
    assert float(stock.current_price) == pytest.approx(100)
    assert float(inactive.current_price) == pytest.approx(100)


async def test_refresh_does_not_overwrite_manual_price(db, monkeypatch):
    """K109: Yahoo kennt den Ticker (über die Watchlist), der manuelle Kurs bleibt."""
    user = await _make_user(db)
    manual = await _make_position(db, user, ticker="NESN.SW", current_price=Decimal("50"), **MANUAL_PRICE)
    db.add(WatchlistItem(user_id=user.id, ticker="NESN.SW", name="Nestlé"))
    await db.commit()
    _mock_providers(monkeypatch, yahoo={"NESN.SW": _quote(92.0, "CHF")})

    await cs.refresh_cache(db)

    await db.refresh(manual)
    assert float(manual.current_price) == pytest.approx(50)
    assert cache.get("price:NESN.SW")["price"] == 92.0  # der geteilte Kurs wird trotzdem gepflegt


# ---------------------------------------------------------------------------
# K163 — Fehlertext ohne Details
# ---------------------------------------------------------------------------

async def test_refresh_error_status_carries_no_statement_details(db, monkeypatch):
    user = await _make_user(db)
    await _make_position(db, user, ticker="AAPL")
    calls = _mock_providers(monkeypatch, yahoo={"AAPL": _quote(190.0)})

    async def boom(db, rows):
        raise RuntimeError("[SQL: INSERT INTO price_cache ...] [parameters: ('SECRETTICKER', 123.45)]")
    monkeypatch.setattr(cs, "_upsert_price_rows", boom)

    result = await cs.refresh_cache(db)

    assert result == {"status": "error", "error": "Refresh fehlgeschlagen (RuntimeError)"}
    assert calls["saved"][-1]["status"] == "error"
    assert calls["saved"][-1]["errors"] == ["Refresh fehlgeschlagen (RuntimeError)"]
    assert "SECRETTICKER" not in json.dumps(calls["saved"])


async def test_provider_error_is_reported_by_class_only(db, monkeypatch):
    calls = _mock_providers(monkeypatch, yahoo={"USDCHF=X": _quote(0.88, "FX")})

    async def failing_crypto(ids):
        raise ValueError("https://api.example/simple/price?ids=secret-coin&key=TOPSECRET")
    monkeypatch.setattr(cs, "_fetch_crypto_batch", failing_crypto)

    result = await cs.refresh_cache(db)

    assert result["status"] == "ok"
    assert result["errors"] == ["Crypto: Abruf fehlgeschlagen (ValueError)"]
    assert "TOPSECRET" not in json.dumps(calls["saved"])


# ---------------------------------------------------------------------------
# K117 — DB-Rückgriff ohne erfundene Tagesänderung
# ---------------------------------------------------------------------------

class TestDbFallbackChangePct:
    def test_single_price_fallback_has_no_change(self, monkeypatch):
        written = {}
        monkeypatch.setattr(price_service.cache, "get", lambda key: None)
        monkeypatch.setattr(price_service.cache, "set", lambda key, value, ttl=900: written.update({key: value}))
        monkeypatch.setattr(
            cs, "get_cached_price_sync",
            lambda ticker, fallback_days=2: {"price": 148.0, "currency": "USD", "stale": True},
        )
        monkeypatch.setattr(price_service, "_in_event_loop", lambda: True)

        result = price_service.get_stock_price("AAPL")

        assert result == {"price": 148.0, "currency": "USD", "change_pct": None}
        assert written["price:AAPL"]["change_pct"] is None

    def test_today_row_has_no_change_either(self, monkeypatch):
        monkeypatch.setattr(price_service.cache, "get", lambda key: None)
        monkeypatch.setattr(price_service.cache, "set", lambda key, value, ttl=900: None)
        monkeypatch.setattr(
            cs, "get_cached_price_sync",
            lambda ticker, fallback_days=2: {"price": 149.0, "currency": "USD", "stale": False},
        )
        assert price_service.get_stock_price("AAPL")["change_pct"] is None

    def test_bulk_fallback_has_no_change(self, monkeypatch):
        monkeypatch.setattr(price_service.cache, "get", lambda key: None)
        monkeypatch.setattr(price_service.cache, "set", lambda key, value, ttl=900: None)
        monkeypatch.setattr(
            cs, "get_cached_prices_batch_sync",
            lambda tickers, fallback_days=5: {"AAPL": {"price": 148.0, "currency": "USD", "stale": True}},
        )
        assert price_service.get_stock_prices_bulk(["AAPL"])["AAPL"]["change_pct"] is None

    def test_crypto_falls_back_to_the_coingecko_key(self, monkeypatch):
        """Ohne Rückgriff auf «CG:<id>» fehlte ausserhalb der Worker-Zeiten jeder Krypto-Kurs."""
        asked = []

        def fake_db(ticker, fallback_days=2):
            asked.append((ticker, fallback_days))
            return {"price": 57000.0, "currency": "CHF", "stale": True}
        monkeypatch.setattr(price_service.cache, "get", lambda key: None)
        monkeypatch.setattr(price_service.cache, "set", lambda key, value, ttl=900: None)
        monkeypatch.setattr(cs, "get_cached_price_sync", fake_db)
        monkeypatch.setattr(price_service, "_in_event_loop", lambda: True)

        result = price_service.get_crypto_price_chf("bitcoin")

        assert asked == [("CG:bitcoin", 5)]
        assert result == {"price": 57000.0, "currency": "CHF", "change_pct": None}

    def test_crypto_fallback_ignores_price_rounded_to_zero(self, monkeypatch):
        monkeypatch.setattr(price_service.cache, "get", lambda key: None)
        monkeypatch.setattr(cs, "get_cached_price_sync", lambda ticker, fallback_days=2: {"price": 0.0, "currency": "CHF"})
        monkeypatch.setattr(price_service, "_in_event_loop", lambda: True)
        assert price_service.get_crypto_price_chf("shiba-inu") is None


# ---------------------------------------------------------------------------
# K058 / X16 — Yahoo in Blöcken
# ---------------------------------------------------------------------------

def test_plan_yahoo_blocks_puts_fx_first_and_rotates():
    tickers = [f"T{i:03d}" for i in range(120)] + cs.FX_PAIRS + ["^VIX"]

    blocks, rotating = cs._plan_yahoo_blocks(tickers)

    assert rotating == 3
    assert set(blocks[0]) == set(cs.FX_PAIRS) | {"^VIX"}
    assert [len(b) for b in blocks[1:]] == [50, 50, 20]
    assert blocks[1][0] == "T000"

    cs._yahoo_block_cursor = 2
    rotated, _ = cs._plan_yahoo_blocks(tickers)
    assert set(rotated[0]) == set(blocks[0])  # FX bleibt vorn
    assert rotated[1][0] == "T100" and rotated[2][0] == "T000"


async def test_refresh_downloads_in_blocks_and_stores_every_ticker(db, monkeypatch):
    user = await _make_user(db)
    tickers = [f"T{i:03d}" for i in range(120)]
    for t in tickers:
        db.add(WatchlistItem(user_id=user.id, ticker=t, name=t))
    await db.commit()
    calls = _mock_providers(monkeypatch, yahoo={t: _quote(10.0) for t in tickers} | {"USDCHF=X": _quote(0.88, "FX")})

    result = await cs.refresh_cache(db)

    assert result["yahoo_error"] is None
    assert max(len(block) for block in calls["yahoo"]) <= cs._YAHOO_BLOCK_SIZE
    assert len(calls["yahoo"]) >= 4
    stored = set((await db.execute(select(PriceCache.ticker))).scalars().all())
    assert set(tickers) <= stored
    assert cache.get("fx_rates")["USD"] == 0.88


async def test_timed_out_block_keeps_earlier_blocks_and_blocks_a_second_thread(db, monkeypatch):
    release = threading.Event()
    started: list[list[str]] = []

    def fake_yahoo(tickers):
        started.append(list(tickers))
        if "SLOW" in tickers:
            release.wait(10)
            return {}
        return {t: _quote(5.0) for t in tickers}
    monkeypatch.setattr(cs, "_download_yahoo_batch", fake_yahoo)
    monkeypatch.setattr(cs, "_YAHOO_BLOCK_SIZE", 1)
    tickers = ["USDCHF=X", "AAA", "SLOW"]

    try:
        results, upserted, error = await cs._refresh_yahoo_blocks(db, tickers, 0.5, TODAY, set())

        assert error == "TimeoutError"
        assert set(results) == {"USDCHF=X", "AAA"} and upserted == 2
        # Die fertigen Blöcke sind gespeichert, obwohl der dritte hängt.
        assert [float(r.close) for r in await _price_rows(db, "AAA")] == [5.0]
        assert cs._yahoo_download_lock.locked()

        # Zweiter Lauf, während der alte Thread noch lädt: kein neuer Download.
        before = len(started)
        _, _, error = await cs._refresh_yahoo_blocks(db, tickers, 0.5, TODAY, set())
        assert error == "DownloadStillRunning"
        assert len(started) == before
    finally:
        release.set()
        for _ in range(100):
            if not cs._yahoo_download_lock.locked():
                break
            await asyncio.sleep(0.05)
    assert not cs._yahoo_download_lock.locked()

    # Der nächste Lauf beginnt beim Block, der zuletzt nicht fertig wurde.
    started.clear()
    monkeypatch.setattr(cs, "_download_yahoo_batch", lambda tickers: started.append(list(tickers)) or {})
    await cs._refresh_yahoo_blocks(db, tickers, 5, TODAY, set())
    assert started == [["USDCHF=X"], ["SLOW"], ["AAA"]]


async def test_empty_yahoo_answer_counts_as_error(db, monkeypatch):
    """Bei einer IP-Sperre liefert Yahoo leere Daten statt eines Fehlers."""
    monkeypatch.setattr(cs, "_download_yahoo_batch", lambda tickers: {})
    results, upserted, error = await cs._refresh_yahoo_blocks(db, ["USDCHF=X", "AAPL"], 5, TODAY, set())
    assert (results, upserted, error) == ({}, 0, "NoData")


# ---------------------------------------------------------------------------
# K133 — SARON nur bei altem Wert laden
# ---------------------------------------------------------------------------

async def test_saron_is_fetched_only_when_stored_value_is_old(db, monkeypatch):
    assert await cs._saron_due(db) is True  # kein Wert gespeichert

    row = AppConfig(key="saron_rate", value="{}", updated_at=datetime.now(timezone.utc) - timedelta(hours=7))
    db.add(row)
    await db.commit()
    assert await cs._saron_due(db) is True

    calls = _mock_providers(monkeypatch, yahoo={"USDCHF=X": _quote(0.88, "FX")})
    await cs.refresh_cache(db)
    assert calls["saron"].await_count == 1

    row.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()
    assert await cs._saron_due(db) is False
    await cs.refresh_cache(db)
    assert calls["saron"].await_count == 1  # kein zweiter Abruf


# ---------------------------------------------------------------------------
# K049 / K023 — Rundung der FX-Paare, Symbole als Liste
# ---------------------------------------------------------------------------

def _yahoo_frame(closes: dict[str, list[float]]) -> pd.DataFrame:
    index = pd.date_range("2026-11-11", periods=2)
    frame = pd.DataFrame({(ticker, "Close"): values for ticker, values in closes.items()}, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


def test_download_rounds_fx_to_eight_decimals_and_passes_a_list(monkeypatch):
    received = []

    def fake_download(tickers, **kwargs):
        received.append(tickers)
        return _yahoo_frame({"JPYCHF=X": [0.00521111, 0.00523456], "AAPL": [189.123456, 190.123456]})
    monkeypatch.setattr(cs, "yf_download", fake_download)

    results = cs._download_yahoo_batch(["JPYCHF=X", "AAPL", "AA,AB", "X Y", "AAPL"])

    assert received == [["JPYCHF=X", "AAPL"]]  # Liste, keine verbundene Zeichenkette
    assert results["JPYCHF=X"]["price"] == 0.00523456
    assert results["AAPL"]["price"] == 190.1235


def test_download_without_valid_symbols_does_not_call_yahoo(monkeypatch):
    download = MagicMock()
    monkeypatch.setattr(cs, "yf_download", download)
    assert cs._download_yahoo_batch(["AA,AB", "X Y"]) == {}
    download.assert_not_called()


def test_price_decimals():
    assert cs._price_decimals("JPYCHF=X") == 8
    assert cs._price_decimals("CG:shiba-inu") == 8
    assert cs._price_decimals("AAPL") == 4


async def test_backfill_ignores_invalid_symbols(db, monkeypatch):
    download = MagicMock()
    monkeypatch.setattr(cs, "yf_download", download)
    assert await cs.backfill_price_history(db, "AAPL,MSFT GOOG") == 0
    download.assert_not_called()


# ---------------------------------------------------------------------------
# X12 / K108 — Datum für den Snapshot-Regen
# ---------------------------------------------------------------------------

class TestRegenTrigger:
    async def test_create_with_cost_basis_triggers_regen_before_today(self, client, regen):
        headers = await _register(client, "regen-create@test.local")
        res = await client.post(
            "/api/portfolio/positions", headers=headers,
            json=_position_payload(shares=10, cost_basis_chf=1500),
        )
        assert res.status_code == 201, res.text
        regen.assert_called_once()
        assert regen.call_args.args[1] < date.today()

    async def test_create_without_cost_basis_triggers_nothing(self, client, regen):
        headers = await _register(client, "regen-none@test.local")
        res = await client.post("/api/portfolio/positions", headers=headers, json=_position_payload())
        assert res.status_code == 201, res.text
        regen.assert_not_called()

    async def test_delete_uses_oldest_transaction_date(self, client, db, regen):
        """Heute angelegt, Käufe von 2023: der Regen muss trotzdem laufen."""
        headers = await _register(client, "regen-delete@test.local")
        created = await client.post("/api/portfolio/positions", headers=headers, json=_position_payload())
        pos = await db.get(Position, uuid.UUID(created.json()["id"]))
        for day in (date(2023, 6, 1), date(2023, 3, 1)):
            db.add(Transaction(
                user_id=pos.user_id, position_id=pos.id, type=TransactionType.buy, date=day,
                shares=1, price_per_share=100, currency="USD", total_chf=100,
            ))
        await db.commit()

        res = await client.delete(f"/api/portfolio/positions/{pos.id}", headers=headers)

        assert res.status_code == 204, res.text
        assert regen.call_args.args[1] == date(2023, 3, 1)

    async def test_delete_of_holding_without_transactions_regens_everything(self, client, regen):
        headers = await _register(client, "regen-static@test.local")
        created = await client.post(
            "/api/portfolio/positions", headers=headers,
            json=_position_payload(shares=10, cost_basis_chf=1500),
        )
        regen.reset_mock()

        res = await client.delete(f"/api/portfolio/positions/{created.json()['id']}", headers=headers)

        assert res.status_code == 204, res.text
        assert regen.call_args.args[1] == date.min


# ---------------------------------------------------------------------------
# K009 — Limit auf der Dividenden-Route
# ---------------------------------------------------------------------------

def test_position_dividends_route_has_heavy_limit():
    from api.auth import limiter

    limits = limiter._route_limits.get("api.positions.position_dividends")
    assert limits, "Dividenden-Route ohne eigenes Limit"
    assert [item.limit for item in limits] == [parse_limit(RL_HEAVY)]


# ---------------------------------------------------------------------------
# K141 — abgefangene Fehler erreichen die Job-Health
# ---------------------------------------------------------------------------

@pytest.fixture
def health_records(monkeypatch) -> list:
    records: list = []
    monkeypatch.setattr(worker, "_record_health_async", lambda *args: records.append(args))
    monkeypatch.setattr(worker, "_max_age_for_job", lambda job_id: None)
    return records


async def test_swallowed_job_failure_is_recorded_as_error(health_records):
    async def job():
        try:
            raise ValueError("boom")
        except Exception:
            worker._note_job_failure("step_a")

    await worker._health_tracked(job, "job_a")()
    worker._on_job_executed(types.SimpleNamespace(job_id="job_a"))

    assert health_records[0][1] == "error"
    assert "step_a: ValueError: boom" in health_records[0][3]

    async def healthy():
        return None

    await worker._health_tracked(healthy, "job_a")()
    worker._on_job_executed(types.SimpleNamespace(job_id="job_a"))
    assert health_records[1][1] == "success" and health_records[1][3] is None


async def test_note_outside_a_scheduler_run_is_a_noop():
    worker._note_job_failure("anything", "ignored")
    assert worker._reported_failures == {}


async def test_track_job_health_wraps_registered_jobs():
    async def job():
        worker._note_job_failure("inner", "kaputt")

    scheduler = worker._build_scheduler()
    scheduler.add_job(job, IntervalTrigger(hours=1), id="j1")
    worker._track_job_health(scheduler)

    await scheduler.get_job("j1").func()

    assert worker._reported_failures == {"j1": "inner: kaputt"}


@pytest.mark.parametrize("outcome, expected", [
    ({"status": "error", "error": "Refresh fehlgeschlagen (RuntimeError)"}, "status=error"),
    ({"status": "ok", "tickers_refreshed": 3, "yahoo_error": "TimeoutError"}, "yahoo=TimeoutError"),
    (asyncio.TimeoutError(), "timeout"),
    ({"status": "ok", "tickers_refreshed": 3, "yahoo_error": None}, None),
])
async def test_price_refresh_reports_failed_refresh(monkeypatch, outcome, expected):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_lock(lock_id):
        yield True

    @asynccontextmanager
    async def fake_session():
        yield object()

    async def fake_refresh(*args, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(worker, "is_extended_hours", lambda: True)
    monkeypatch.setattr(worker, "advisory_lock", fake_lock)
    monkeypatch.setattr(worker, "async_session", fake_session)
    monkeypatch.setattr(worker, "refresh_cache", fake_refresh)
    monkeypatch.setattr(worker, "_save_refresh_state_to_db", AsyncMock())
    monkeypatch.setattr(cs, "_load_refresh_state_from_db", AsyncMock(return_value={}))
    monkeypatch.setattr(worker, "_check_alerts", AsyncMock())

    await worker._health_tracked(worker.price_refresh, "intraday_refresh")()

    reported = worker._reported_failures.get("intraday_refresh")
    if expected is None:
        assert reported is None
    else:
        assert expected in reported


async def test_job_helpers_note_their_swallowed_exception(monkeypatch):
    async def failing(db):
        raise RuntimeError("smtp down")
    monkeypatch.setattr("services.price_alert_service.check_price_alerts", failing)

    await worker._health_tracked(worker._check_alerts, "alerts")()

    assert "price_alerts: RuntimeError: smtp down" in worker._reported_failures["alerts"]


# ---------------------------------------------------------------------------
# X41 — verpasste Läufe
# ---------------------------------------------------------------------------

def test_scheduler_gets_a_misfire_grace_of_five_minutes():
    assert worker._build_scheduler()._job_defaults["misfire_grace_time"] == 300


async def test_missed_run_does_not_refresh_last_run_at(db):
    await record_job_run(db, "job_m", "success", runtime_ms=120, max_age_s=660)
    before = {r["job_id"]: r for r in await get_all_health(db)}["job_m"]

    await asyncio.sleep(0.01)
    await record_job_run(db, "job_m", "missed", max_age_s=660)

    after = {r["job_id"]: r for r in await get_all_health(db)}["job_m"]
    assert after["last_status"] == "missed"
    assert after["last_run_at"] == before["last_run_at"]
    assert after["last_runtime_ms"] == 120
    assert after["consecutive_failures"] == 0


async def test_job_that_only_misfires_counts_as_never_ran(db):
    await record_job_run(db, "job_n", "missed", max_age_s=660)
    rows = await get_all_health(db)
    assert rows[0]["last_run_at"] is None

    now = utcnow()
    unhealthy = compute_stale(rows, now, worker_started_at=now - timedelta(hours=2), known_job_ids=["job_n"])

    assert [(u["job_id"], u["reason"]) for u in unhealthy] == [("job_n", "never_ran")]


# ---------------------------------------------------------------------------
# Bereinigungsskript für alte CoinGecko-Zeilen
# ---------------------------------------------------------------------------

async def _seed_legacy_rows(db) -> dict:
    user = await _make_user(db)
    other = await _make_user(db)
    await _make_position(db, user, ticker="BTC-USD", type=AssetType.crypto, coingecko_id="bitcoin")
    await _make_position(db, user, ticker="AAPL")
    await _make_position(db, other, ticker="AAPL", type=AssetType.crypto, coingecko_id="bitcoin")
    await _make_position(db, user, ticker="XYZ", type=AssetType.crypto, coingecko_id="coin-a")
    await _make_position(db, other, ticker="XYZ", type=AssetType.crypto, coingecko_id="coin-b")
    legacy_stock = await _make_position(db, other, ticker="MSFT", coingecko_id="ethereum")
    d1, d2 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    rows = [
        ("BTC-USD", d1, 50000, "CHF", "coingecko"),
        ("BTC-USD", d2, 51000, "CHF", "coingecko"),
        ("CG:bitcoin", d2, 51111, "CHF", "coingecko"),   # neuer Schlüssel hat d2 schon
        ("AAPL", d1, 50500, "CHF", "coingecko"),          # vergiftete Zeile
        ("AAPL", d2, 190, "USD", "yahoo"),                # echter Kurs, bleibt
        ("XYZ", d1, 1, "CHF", "coingecko"),               # zwei coingecko_ids
        ("ORPHAN", d1, 2, "CHF", "coingecko"),            # keine Position
    ]
    for ticker, day, close, currency, source in rows:
        db.add(PriceCache(ticker=ticker, date=day, close=close, currency=currency, source=source))
    await db.commit()
    return {"d1": d1, "d2": d2, "legacy_stock": legacy_stock}


async def _cache_table(db) -> set[tuple]:
    # Spalten statt Entitäten: das Skript ändert die Zeilen an der Session vorbei.
    rows = (await db.execute(select(PriceCache.ticker, PriceCache.date, PriceCache.close, PriceCache.source))).all()
    return {(ticker, day, float(close), source) for ticker, day, close, source in rows}


async def test_cleanup_script_dry_run_changes_nothing(db):
    from scripts.vr11_cleanup_crypto_price_cache import cleanup

    seeded = await _seed_legacy_rows(db)
    before = await _cache_table(db)

    report = await cleanup(db)

    assert await _cache_table(db) == before
    assert {e["ticker"]: e["target"] for e in report["rekeyed"]} == {"AAPL": "CG:bitcoin", "BTC-USD": "CG:bitcoin"}
    assert {e["ticker"] for e in report["unmapped"]} == {"XYZ", "ORPHAN"}
    assert [p["id"] for p in report["non_crypto_positions"]] == [str(seeded["legacy_stock"].id)]


async def test_cleanup_script_apply_rekeys_unambiguous_rows(db):
    from scripts.vr11_cleanup_crypto_price_cache import cleanup

    seeded = await _seed_legacy_rows(db)
    d1, d2 = seeded["d1"], seeded["d2"]

    await cleanup(db, apply=True)

    table = await _cache_table(db)
    assert ("AAPL", d2, 190.0, "yahoo") in table
    assert not any(t == "AAPL" and s == "coingecko" for t, _, _, s in table)
    assert not any(t == "BTC-USD" for t, _, _, _ in table)
    assert ("CG:bitcoin", d2, 51111.0, "coingecko") in table  # vorhandener Kurs gewinnt
    assert len([row for row in table if row[0] == "CG:bitcoin" and row[1] == d1]) == 1
    # Ohne eindeutige Zuordnung bleibt die Zeile stehen, bis der Betreiber sie löscht.
    assert ("XYZ", d1, 1.0, "coingecko") in table
    assert ("ORPHAN", d1, 2.0, "coingecko") in table

    # Idempotent, und --delete-unmapped räumt den Rest.
    report = await cleanup(db, apply=True, delete_unmapped=True)
    assert report["rekeyed"] == []
    table = await _cache_table(db)
    assert not any(t in ("XYZ", "ORPHAN") for t, _, _, _ in table)
    assert ("AAPL", d2, 190.0, "yahoo") in table


# --- Sammel-Seed nach einem Import (Import am Wochenende blieb ohne Kurse) ---

def _import_seed_mocks(monkeypatch, quotes: dict, names: dict | None = None, backfill=None):
    download = MagicMock(return_value=quotes)
    monkeypatch.setattr(cs, "_download_yahoo_batch", download)
    backfill = backfill or AsyncMock(return_value=10)
    monkeypatch.setattr(cs, "backfill_price_history", backfill)

    async def fake_info(ticker):
        if names is None or ticker not in names:
            raise RuntimeError("no info")
        return {"shortName": names[ticker]}
    import services.ticker_info_service as tis
    monkeypatch.setattr(tis, "get_ticker_info_cached", fake_info)
    return download, backfill


async def _seed(db, user, **kwargs):
    return await cs.seed_missing_prices_for_user(db, user.id, pause_s=0, **kwargs)


async def test_import_seed_prices_names_and_history_in_one_batch(db, monkeypatch):
    user = await _make_user(db)
    aapl = await _make_position(db, user, ticker="AAPL", name="AAPL", current_price=None)
    msft = await _make_position(db, user, ticker="MSFT", name="Microsoft Corp", current_price=None)
    closed = await _make_position(db, user, ticker="PEP", name="PEP", current_price=None, shares=Decimal("0"))
    download, backfill = _import_seed_mocks(
        monkeypatch,
        {"AAPL": {"price": 342.5, "currency": "USD"}, "MSFT": {"price": 500.0, "currency": "USD"},
         "PEP": {"price": 150.0, "currency": "USD"}},
        names={"AAPL": "Apple Inc.", "PEP": "PepsiCo, Inc."},
    )
    invalidated = []

    counts = await _seed(db, user, after_prices=lambda: invalidated.append(1))

    assert download.call_count == 1  # EIN Sammelabruf, nie einer je Position
    assert download.call_args.args[0] == ["AAPL", "MSFT", "PEP"]  # gehaltene zuerst
    for pos in (aapl, msft, closed):
        await db.refresh(pos)
    assert float(aapl.current_price) == 342.5 and float(msft.current_price) == 500.0
    assert aapl.name == "Apple Inc." and closed.name == "PepsiCo, Inc."
    assert msft.name == "Microsoft Corp"  # ein vorhandener Name bleibt
    assert [float(r.close) for r in await _price_rows(db, "AAPL")] == [342.5]
    # Historie nur fuer gehaltene Titel.
    assert sorted(c.args[1] for c in backfill.call_args_list) == ["AAPL", "MSFT"]
    assert counts == {"positions": 3, "priced": 3, "named": 2, "history": 2, "skipped": 0}
    assert invalidated == [1]


async def test_import_seed_leaves_priced_manual_old_and_foreign_positions_alone(db, monkeypatch):
    user, other = await _make_user(db), await _make_user(db)
    priced = await _make_position(db, user, ticker="AAPL")  # hat schon einen Kurs
    await _make_position(db, user, ticker="MAN", current_price=None, **MANUAL_PRICE)
    await _make_position(db, user, ticker="AA,AB AC", current_price=None)
    # Seit Tagen ohne Kurs (delistet, falsches Symbol): nicht bei jedem Import neu abfragen.
    await _make_position(db, user, ticker="DEAD", current_price=None,
                         created_at=utcnow() - cs.IMPORT_SEED_WINDOW - timedelta(minutes=1))
    foreign = await _make_position(db, other, ticker="NVDA", current_price=None)
    download, _ = _import_seed_mocks(monkeypatch, {"NVDA": {"price": 1.0, "currency": "USD"}})
    invalidated = []

    counts = await _seed(db, user, after_prices=lambda: invalidated.append(1))

    download.assert_not_called()
    assert counts["positions"] == 0 and invalidated == []
    await db.refresh(priced)
    await db.refresh(foreign)
    assert float(priced.current_price) == 100.0 and foreign.current_price is None


async def test_import_seed_survives_a_ticker_without_quote_and_a_failing_provider(db, monkeypatch):
    user = await _make_user(db)
    known = await _make_position(db, user, ticker="AAPL", name="AAPL", current_price=None)
    unknown = await _make_position(db, user, ticker="SSV.TO", name="SSV.TO", current_price=None)
    _import_seed_mocks(monkeypatch, {"AAPL": {"price": 10.0, "currency": "USD"}})  # keine Namen: Info wirft

    counts = await _seed(db, user)

    await db.refresh(known)
    await db.refresh(unknown)
    assert float(known.current_price) == 10.0 and unknown.current_price is None
    assert known.name == "AAPL" and counts["priced"] == 1 and counts["named"] == 0

    monkeypatch.setattr(cs, "_download_yahoo_batch", MagicMock(side_effect=RuntimeError("yahoo down")))
    assert (await _seed(db, user))["priced"] == 0  # wirft nie


async def test_import_seed_caps_the_batch_and_prefers_held_positions(db, monkeypatch):
    user = await _make_user(db)
    monkeypatch.setattr(cs, "IMPORT_SEED_MAX_TICKERS", 2)
    await _make_position(db, user, ticker="AAA", current_price=None, shares=Decimal("0"))
    await _make_position(db, user, ticker="BBB", current_price=None, shares=Decimal("0"))
    await _make_position(db, user, ticker="YYY", current_price=None)
    await _make_position(db, user, ticker="ZZZ", current_price=None)
    download, backfill = _import_seed_mocks(monkeypatch, {})

    counts = await _seed(db, user)

    assert download.call_args.args[0] == ["YYY", "ZZZ"]  # gehaltene vor geschlossenen
    assert counts["positions"] == 2 and counts["skipped"] == 2
    assert sorted(c.args[1] for c in backfill.call_args_list) == ["YYY", "ZZZ"]  # nie fuer den Rest

async def test_import_seed_history_continues_after_a_rollback_in_backfill(db, monkeypatch):
    """backfill_price_history rollt bei einem Fehler die Session zurueck. Danach duerfen
    keine ORM-Objekte mehr gelesen werden, sonst endet der Lauf mit MissingGreenlet."""
    user = await _make_user(db)
    await _make_position(db, user, ticker="AAPL", current_price=None)
    await _make_position(db, user, ticker="MSFT", current_price=None)
    seen = []

    async def rolling_back(session, ticker, period="2y"):
        seen.append(ticker)
        await session.rollback()
        return 0

    _import_seed_mocks(monkeypatch, {"AAPL": {"price": 1.0, "currency": "USD"},
                                     "MSFT": {"price": 2.0, "currency": "USD"}}, backfill=rolling_back)

    counts = await _seed(db, user)

    assert seen == ["AAPL", "MSFT"]  # der zweite Ticker laeuft trotz Rollback beim ersten
    assert counts["priced"] == 2 and counts["history"] == 0


async def test_import_seed_keeps_a_name_changed_during_the_run(db, monkeypatch):
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="AAPL", name="AAPL", current_price=None)
    _import_seed_mocks(monkeypatch, {"AAPL": {"price": 1.0, "currency": "USD"}})

    async def renaming_info(ticker):
        # Der Nutzer benennt die Position um, waehrend der Lauf den Namen holt.
        from sqlalchemy import update
        await db.execute(update(Position).where(Position.id == pos.id).values(name="Mein Apfel"))
        return {"shortName": "Apple Inc."}
    import services.ticker_info_service as tis
    monkeypatch.setattr(tis, "get_ticker_info_cached", renaming_info)

    counts = await _seed(db, user)

    await db.refresh(pos)
    assert pos.name == "Mein Apfel" and counts["named"] == 0


async def test_import_seed_waits_for_a_busy_download_and_gives_up_cleanly(db, monkeypatch):
    user = await _make_user(db)
    pos = await _make_position(db, user, ticker="AAPL", current_price=None)
    _import_seed_mocks(monkeypatch, {})
    block = MagicMock(return_value=None)  # der Worker laedt gerade: Sperre besetzt
    monkeypatch.setattr(cs, "_download_yahoo_block", block)

    info_calls = []

    async def counting_info(ticker):
        info_calls.append(ticker)
        return {"shortName": "X"}
    import services.ticker_info_service as tis
    monkeypatch.setattr(tis, "get_ticker_info_cached", counting_info)

    counts = await _seed(db, user)

    assert block.call_count == cs._IMPORT_SEED_LOCK_TRIES
    await db.refresh(pos)
    assert pos.current_price is None and counts["priced"] == 0
    # Ohne Sammelabruf auch keine Einzelabrufe fuer Namen und Historie.
    assert info_calls == [] and cs.backfill_price_history.call_count == 0
    assert counts["positions"] == 0 and counts["skipped"] == 1


async def test_import_seed_trigger_runs_once_per_user_and_reruns_after_a_second_import(monkeypatch):
    user_id = uuid.uuid4()
    started = asyncio.Event()
    release = asyncio.Event()
    runs = []

    async def fake_seed(db, uid, **kwargs):
        runs.append(uid)
        started.set()
        await release.wait()
        return {"priced": 0, "named": 0}

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(cs, "seed_missing_prices_for_user", fake_seed)
    monkeypatch.setattr(cs, "async_session", lambda: _Session())
    monkeypatch.setattr(cs, "_seed_run_lock", None)

    cs.trigger_import_price_seed(user_id)
    await started.wait()
    cs.trigger_import_price_seed(user_id)  # zweiter Import waehrend des Laufs
    cs.trigger_import_price_seed(user_id)
    assert len(runs) == 1 and len(cs._seed_tasks) == 1  # kein zweiter Task

    release.set()
    await asyncio.gather(*list(cs._seed_tasks))

    assert len(runs) == 2  # genau eine Wiederholung
    assert user_id not in cs._seed_running_users and user_id not in cs._seed_rerun_users


async def test_import_seed_trigger_releases_user_and_lock_after_a_hanging_run(monkeypatch):
    """Ein haengender Abruf darf weder den Nutzer noch den Einzellaeufer festhalten."""
    first, second = uuid.uuid4(), uuid.uuid4()
    runs = []

    async def fake_seed(db, uid, **kwargs):
        runs.append(uid)
        if uid == first:
            await asyncio.sleep(3600)  # haengt
        return {"priced": 0, "named": 0}

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(cs, "seed_missing_prices_for_user", fake_seed)
    monkeypatch.setattr(cs, "async_session", lambda: _Session())
    monkeypatch.setattr(cs, "_seed_run_lock", None)
    monkeypatch.setattr(cs, "IMPORT_SEED_BUDGET_S", 0.05)

    cs.trigger_import_price_seed(first)
    cs.trigger_import_price_seed(second)  # wartet hinter dem haengenden Lauf
    await asyncio.wait_for(asyncio.gather(*list(cs._seed_tasks)), timeout=5)

    assert runs == [first, second]  # der zweite Nutzer kommt nach der Frist dran
    assert not cs._seed_running_users and not cs._seed_rerun_users
    assert not cs._seed_run_lock.locked()

    cs.trigger_import_price_seed(first)  # und der erste darf spaeter wieder
    await asyncio.wait_for(asyncio.gather(*list(cs._seed_tasks)), timeout=5)
    assert runs.count(first) == 2

