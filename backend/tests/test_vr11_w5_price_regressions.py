"""Vollreview 11/2026, Welle 5, Fixer «price»: Fehler aus den Fixes der Wellen 1–4.

R-pricecache-2 / R-smtpreports-3  Staleness-Guard überwacht keine manuell bepreisten Positionen
R-pricecache-3 / R-smtpreports-1  Krypto-Schlüssel im Preis-Alarm nur beim Typ crypto
R-smtpreports-2                   Alarm aus der Watchlist gegen den Kurs in seiner Währung
R-pricecache-4                    Typwechsel weg von Cash/Vorsorge stellt auf Live-Kurs um
R-pricecache-5                    coingecko_id passt mit Präfix in price_cache.ticker
R-yfanalysis-3                    .L-Ticker ohne bekannte Kurswährung bekommt keinen Kurs
R-extapi-1 (Zusatz)               Recalculate aller Positionen leert den Summary-Cache
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select

import services.cache_service as cs
from models.position import AssetType, Position, PriceSource, PricingMode
from models.price_alert import PriceAlert
from models.price_cache import PriceCache
from models.user import User
from models.watchlist import WatchlistItem
from services import cache
from services.price_staleness_service import check_price_staleness

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
REFERENCE = date(2026, 11, 13)


@pytest.fixture(autouse=True)
def clean_cache():
    cache._mem_clear()
    yield
    cache._mem_clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Von Hand gepflegter Kurs: Modus UND Preisquelle manual (models.position.has_manual_price).
MANUAL_PRICE = dict(pricing_mode=PricingMode.manual, price_source=PriceSource.manual)


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x", is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_position(db, user_id, ticker, **kwargs) -> Position:
    values = dict(
        user_id=user_id,
        bucket_id=uuid.uuid4(),
        ticker=ticker,
        name=ticker,
        type=AssetType.stock,
        currency="USD",
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
        shares=Decimal("1"),
        cost_basis_chf=Decimal("1000"),
        is_active=True,
    )
    values.update(kwargs)
    pos = Position(**values)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


async def _make_alert(db, user, ticker, alert_type, target, currency) -> PriceAlert:
    alert = PriceAlert(
        user_id=user.id,
        ticker=ticker,
        alert_type=alert_type,
        target_value=Decimal(target),
        currency=currency,
    )
    db.add(alert)
    await db.commit()
    return alert


def _install_prices(monkeypatch, prices: dict[str, tuple[float, str]]) -> list[list[str]]:
    """Ersetzt cache.get_many durch Einträge, wie der Worker sie schreibt.

    Liefert die Liste der MGET-Aufrufe.
    """
    payloads = {
        key: {"price": price, "currency": currency, "change_pct": 0}
        for key, (price, currency) in prices.items()
    }
    calls: list[list[str]] = []

    def get_many(keys):
        calls.append(list(keys))
        return {k: payloads[k] for k in keys if k in payloads}

    monkeypatch.setattr(cache, "get_many", get_many)
    return calls


async def _register(client, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _user_id(db, email: str) -> uuid.UUID:
    return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


def _yahoo_frame(closes: dict[str, list[float]]) -> pd.DataFrame:
    index = pd.date_range("2026-11-11", periods=2)
    frame = pd.DataFrame({(ticker, "Close"): values for ticker, values in closes.items()}, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


# ---------------------------------------------------------------------------
# R-pricecache-2 / R-smtpreports-3 — Staleness ohne manuelle Positionen
# ---------------------------------------------------------------------------

async def test_staleness_skips_manually_priced_position(db):
    """NESN.SW manuell, letzter Kurs 9 Tage alt, NOVN.SW frisch: kein Alarm."""
    await _make_position(db, uuid.uuid4(), "NESN.SW", **MANUAL_PRICE)
    await _make_position(db, uuid.uuid4(), "NOVN.SW")
    db.add_all([
        PriceCache(ticker="NESN.SW", date=REFERENCE - timedelta(days=9), close=80, currency="CHF", source="yahoo"),
        PriceCache(ticker="NOVN.SW", date=REFERENCE, close=90, currency="CHF", source="yahoo"),
    ])
    await db.commit()

    report = await check_price_staleness(db, today=REFERENCE)

    assert report["stale_count"] == 0
    assert report["total_monitored"] == 1  # nur NOVN.SW
    # Der Worker lädt den Ticker nicht: gleiche Menge wie die Überwachung.
    assert "NESN.SW" not in (await cs.collect_all_tickers(db))["yahoo_tickers"]


async def test_staleness_reports_no_outage_when_only_manual_positions_exist(db):
    await _make_position(db, uuid.uuid4(), "NESN.SW", **MANUAL_PRICE)
    db.add(PriceCache(ticker="NESN.SW", date=REFERENCE - timedelta(days=30), close=80, currency="CHF", source="yahoo"))
    await db.commit()

    report = await check_price_staleness(db, today=REFERENCE)

    assert report["total_monitored"] == 0
    assert report["stale"] == []
    assert not report.get("feed_outage")


async def test_staleness_still_monitors_manual_ticker_held_auto_or_watched(db):
    """Führt ein anderer Nutzer den Ticker mit Live-Kurs, bleibt er überwacht."""
    await _make_position(db, uuid.uuid4(), "NESN.SW", **MANUAL_PRICE)
    await _make_position(db, uuid.uuid4(), "NESN.SW")
    await _make_position(db, uuid.uuid4(), "NOVN.SW")
    db.add(WatchlistItem(user_id=uuid.uuid4(), ticker="ROG.SW", name="Roche", is_active=True))
    db.add_all([
        PriceCache(ticker="NESN.SW", date=REFERENCE - timedelta(days=9), close=80, currency="CHF", source="yahoo"),
        PriceCache(ticker="NOVN.SW", date=REFERENCE, close=90, currency="CHF", source="yahoo"),
    ])
    await db.commit()

    report = await check_price_staleness(db, today=REFERENCE)

    assert {s["ticker"] for s in report["stale"]} == {"NESN.SW", "ROG.SW"}
    assert report["total_monitored"] == 3


# ---------------------------------------------------------------------------
# R-pricecache-3 / R-smtpreports-1 — Krypto-Schlüssel nur beim Typ crypto
# ---------------------------------------------------------------------------

async def test_alert_on_stock_with_legacy_coingecko_id_ignores_crypto_price(db, monkeypatch):
    """Altbestand: Aktie AAPL mit coingecko_id bitcoin, Alarm «AAPL über 300»."""
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user.id, "AAPL", coingecko_id="bitcoin")
    alert = await _make_alert(db, user, "AAPL", "price_above", "300", "USD")
    # Ein anderer Nutzer hält Bitcoin: crypto:bitcoin steht im Cache.
    calls = _install_prices(monkeypatch, {"crypto:bitcoin": (57000.0, "CHF"), "price:AAPL": (250.0, "USD")})

    assert await check_price_alerts(db) == []

    assert calls == [["price:AAPL"]]
    await db.refresh(alert)
    assert alert.is_triggered is False
    assert alert.is_active is True


async def test_alert_on_stock_with_legacy_coingecko_id_fires_on_yahoo_price(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user.id, "ETHE", coingecko_id="ethereum", yfinance_ticker="ETHE")
    await _make_alert(db, user, "ETHE", "price_above", "30", "USD")
    # Hält niemand Ethereum, fehlt crypto:ethereum. Der Yahoo-Kurs liegt über dem Ziel.
    _install_prices(monkeypatch, {"price:ETHE": (35.0, "USD")})

    triggered = await check_price_alerts(db)

    assert [t["trigger_price"] for t in triggered] == [35.0]


async def test_alert_on_crypto_position_keeps_the_crypto_key(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _make_user(db)
    await _make_position(db, user.id, "BTC", type=AssetType.crypto, coingecko_id="bitcoin", currency="CHF")
    await _make_alert(db, user, "BTC", "price_above", "50000", "CHF")
    calls = _install_prices(monkeypatch, {"crypto:bitcoin": (90000.0, "CHF"), "price:BTC": (1.0, "USD")})

    triggered = await check_price_alerts(db)

    assert [t["trigger_price"] for t in triggered] == [90000.0]
    assert calls == [["crypto:bitcoin"]]


# ---------------------------------------------------------------------------
# R-smtpreports-2 — Ticker in Position und Watchlist
# ---------------------------------------------------------------------------

async def _holder_with_btc_position_and_watchlist(db) -> User:
    user = await _make_user(db)
    await _make_position(db, user.id, "BTC-USD", type=AssetType.crypto, coingecko_id="bitcoin")
    db.add(WatchlistItem(user_id=user.id, ticker="BTC-USD", name="Bitcoin"))
    await db.commit()
    return user


# Yahoo: 100000 USD. CoinGecko: 80000 CHF.
BTC_PRICES = {"price:BTC-USD": (100000.0, "USD"), "crypto:bitcoin": (80000.0, "CHF")}


async def test_usd_alert_from_watchlist_is_not_compared_with_chf_position_price(db, monkeypatch):
    """«Kurs unter 90000 USD» löst bei 100000 USD nicht aus, auch wenn CoinGecko 80000 CHF meldet."""
    from services.price_alert_service import check_price_alerts

    user = await _holder_with_btc_position_and_watchlist(db)
    alert = await _make_alert(db, user, "BTC-USD", "price_below", "90000", "USD")
    calls = _install_prices(monkeypatch, BTC_PRICES)

    assert await check_price_alerts(db) == []

    await db.refresh(alert)
    assert alert.is_triggered is False
    # Beide Schlüssel in einem MGET (K132).
    assert calls == [["crypto:bitcoin", "price:BTC-USD"]]


async def test_usd_alert_from_watchlist_fires_on_the_usd_price(db, monkeypatch):
    from services.price_alert_service import check_price_alerts

    user = await _holder_with_btc_position_and_watchlist(db)
    await _make_alert(db, user, "BTC-USD", "price_above", "95000", "USD")
    _install_prices(monkeypatch, BTC_PRICES)

    triggered = await check_price_alerts(db)

    assert [(t["currency"], t["trigger_price"]) for t in triggered] == [("USD", 100000.0)]


async def test_chf_alert_from_portfolio_keeps_the_position_price(db, monkeypatch):
    """Die Portfolio-Tabelle legt den Alarm in der Kurswährung der Position an (CHF)."""
    from services.price_alert_service import check_price_alerts

    user = await _holder_with_btc_position_and_watchlist(db)
    await _make_alert(db, user, "BTC-USD", "price_below", "90000", "CHF")
    _install_prices(monkeypatch, BTC_PRICES)

    triggered = await check_price_alerts(db)

    assert [(t["currency"], t["trigger_price"]) for t in triggered] == [("CHF", 80000.0)]


async def test_position_price_stays_default_without_a_currency_match(db, monkeypatch):
    """Ohne Währung (pct_change_day) und bei fehlendem Positions-Kurs gilt der Positions-Schlüssel."""
    from services.price_alert_service import check_price_alerts

    user = await _holder_with_btc_position_and_watchlist(db)
    pct = await _make_alert(db, user, "BTC-USD", "pct_change_day", "5", None)
    payloads = {
        "price:BTC-USD": {"price": 100000.0, "currency": "USD", "change_pct": 9.0},
        "crypto:bitcoin": {"price": 80000.0, "currency": "CHF", "change_pct": 1.0},
    }
    monkeypatch.setattr(cache, "get_many", lambda keys: {k: payloads[k] for k in keys if k in payloads})

    assert await check_price_alerts(db) == []  # 1 % der Position, nicht 9 % der Watchlist
    await db.refresh(pct)
    assert pct.is_triggered is False

    # Override-Position ohne Kurs im Cache: der Kurs unter dem Anzeige-Ticker
    # gehört zu einem anderen Symbol und bleibt aussen vor (X09).
    other = await _make_user(db)
    await _make_position(db, other.id, "ROG.SW", yfinance_ticker="ROP.SW", currency="CHF")
    db.add(WatchlistItem(user_id=other.id, ticker="ROG.SW", name="Roche"))
    await db.commit()
    await _make_alert(db, other, "ROG.SW", "price_above", "200", "CHF")
    _install_prices(monkeypatch, {"price:ROG.SW": (250.0, "CHF"), "crypto:bitcoin": (80000.0, "CHF")})

    assert await check_price_alerts(db) == []


# ---------------------------------------------------------------------------
# R-pricecache-4 — Typwechsel weg von Cash/Vorsorge
# ---------------------------------------------------------------------------

async def _legacy_cash_etf(db, user_id) -> Position:
    """Altbestand: T-Bill-ETF als Cash-Konto, manuell bepreist."""
    return await _make_position(
        db, user_id, "IB01.L",
        type=AssetType.cash,
        pricing_mode=PricingMode.manual,
        price_source=PriceSource.manual,
        shares=Decimal("496"),
        current_price=Decimal("60185"),
    )


async def test_cash_to_bond_migration_switches_to_live_pricing(client, db):
    """Der Knopf «Als Anleihe führen (live bepreisen)» sendet nur type und count_as_cash.

    Der Modus bleibt manual: die Position hat keine Kauf-Buchung, und im Modus
    auto setzte «Neu berechnen» ihren Bestand auf 0. Die Preisquelle wird yahoo,
    damit der Worker den Kurs lädt.
    """
    from services.recalculate_service import recalculate_position

    headers = await _register(client, "w5-migrate@test.local")
    pos = await _legacy_cash_etf(db, await _user_id(db, "w5-migrate@test.local"))

    res = await client.put(
        f"/api/portfolio/positions/{pos.id}", headers=headers,
        json={"type": "bond", "count_as_cash": False},
    )

    assert res.status_code == 200, res.text
    assert res.json()["type"] == "bond"
    assert res.json()["pricing_mode"] == "manual"
    assert res.json()["price_source"] == "yahoo"
    # Der Worker lädt den Kurs und schreibt ihn auf die Position.
    assert "IB01.L" in (await cs.collect_all_tickers(db))["yahoo_tickers"]
    await cs._update_position_prices_batch(db, [("IB01.L", 98.07)])
    await db.commit()
    await db.refresh(pos)
    assert float(pos.current_price) == 98.07
    # «Neu berechnen» lässt den Bestand ohne Kauf-Buchung stehen.
    result = await recalculate_position(db, pos.id)
    await db.commit()
    await db.refresh(pos)
    assert result.get("skipped")
    assert float(pos.shares) == 496


async def test_type_change_respects_an_explicit_pricing_mode(client, db):
    headers = await _register(client, "w5-explicit@test.local")
    pos = await _legacy_cash_etf(db, await _user_id(db, "w5-explicit@test.local"))

    res = await client.put(
        f"/api/portfolio/positions/{pos.id}", headers=headers,
        json={"type": "bond", "count_as_cash": False, "pricing_mode": "manual"},
    )

    assert res.status_code == 200, res.text
    assert res.json()["pricing_mode"] == "manual"
    # Der Modus war schon manual: kein Wechsel, also Live-Kurs für den neuen Typ.
    assert res.json()["price_source"] == "yahoo"


async def test_type_change_respects_an_explicit_price_source(client, db):
    """Wer den Kurs der Anleihe von Hand pflegen will, nennt die Preisquelle."""
    headers = await _register(client, "w5-explicit-src@test.local")
    pos = await _legacy_cash_etf(db, await _user_id(db, "w5-explicit-src@test.local"))

    res = await client.put(
        f"/api/portfolio/positions/{pos.id}", headers=headers,
        json={"type": "bond", "count_as_cash": False, "price_source": "manual"},
    )

    assert res.status_code == 200, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "manual")
    assert "IB01.L" not in (await cs.collect_all_tickers(db))["yahoo_tickers"]


# ---------------------------------------------------------------------------
# Abnahme Fixlauf — Altbestand: Modus manual, Preisquelle nicht manual
# ---------------------------------------------------------------------------

async def test_legacy_manual_mode_with_yahoo_source_keeps_the_worker_price(db):
    """Früheres Cash-Konto, als Anleihe geführt: Modus manual, Preisquelle yahoo.

    Vor dem Vollreview lud der Worker den Kurs ohne Blick auf den Modus. Das
    bleibt so: sonst stünde der Kurs nach dem Deploy still.
    """
    pos = await _make_position(
        db, uuid.uuid4(), "IB01.L", type=AssetType.bond,
        pricing_mode=PricingMode.manual, price_source=PriceSource.yahoo,
        shares=Decimal("330"), current_price=Decimal("118"),
    )
    db.add(PriceCache(ticker="IB01.L", date=REFERENCE, close=118, currency="USD", source="yahoo"))
    await db.commit()

    assert "IB01.L" in (await cs.collect_all_tickers(db))["yahoo_tickers"]
    await cs._update_position_prices_batch(db, [("IB01.L", 122.58)])
    await db.commit()
    await db.refresh(pos)
    assert float(pos.current_price) == 122.58
    # Der Worker lädt den Ticker, also bleibt er überwacht.
    assert (await check_price_staleness(db, today=REFERENCE))["total_monitored"] == 1


async def test_legacy_manual_mode_keeps_crypto_and_metal_prices(db):
    """Modus manual mit Preisquelle coingecko oder gold_org: der Worker schreibt weiter."""
    uid = uuid.uuid4()
    btc = await _make_position(
        db, uid, "BTC-USD", type=AssetType.crypto, coingecko_id="bitcoin",
        pricing_mode=PricingMode.manual, price_source=PriceSource.coingecko,
    )
    gold = await _make_position(
        db, uid, "XAUCHF=X", type=AssetType.commodity, gold_org=True,
        pricing_mode=PricingMode.manual, price_source=PriceSource.gold_org,
    )

    info = await cs.collect_all_tickers(db)
    assert info["crypto"] == ["bitcoin"]
    assert info["metal_spot_tickers"] == ["XAUCHF=X"]
    await cs._update_crypto_position_prices(db, [("bitcoin", 57000.0)])
    await db.commit()
    await db.refresh(btc)
    await db.refresh(gold)
    assert float(btc.current_price) == 57000.0


async def test_own_price_source_beats_a_manual_price(client, db):
    """Nachabnahme: Edelmetall und Krypto mit coingecko_id haben eine eigene
    Kursquelle. Summary, Tages-Snapshot und Regen bewerten sie zuerst damit. Liesse
    der Worker den Kurs bei Modus und Preisquelle manual stehen, hinge der Wert
    davon ab, ob gerade ein Kurs im Cache liegt."""
    from models.position import has_manual_price

    headers = await _register(client, "w5-ownsource@test.local")
    uid = await _user_id(db, "w5-ownsource@test.local")
    btc = await _make_position(
        db, uid, "BTC-USD", type=AssetType.crypto, coingecko_id="bitcoin",
        price_source=PriceSource.coingecko,
    )
    gold = await _make_position(db, uid, "XAUCHF=X", type=AssetType.commodity, gold_org=True, **MANUAL_PRICE)
    token = await _make_position(db, uid, "MYTOKEN", type=AssetType.crypto, **MANUAL_PRICE)

    assert not has_manual_price(gold)
    assert has_manual_price(token)  # Krypto ohne coingecko_id: der Handkurs gilt

    # Modus manual auf einer Krypto-Position mit ID: die Preisquelle bleibt.
    res = await client.put(
        f"/api/portfolio/positions/{btc.id}", headers=headers,
        json={"pricing_mode": "manual", "current_price": 40000},
    )
    assert res.status_code == 200, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "coingecko")

    info = await cs.collect_all_tickers(db)
    assert info["crypto"] == ["bitcoin"]
    assert info["metal_spot_tickers"] == ["XAUCHF=X"]
    await cs._update_crypto_position_prices(db, [("bitcoin", 57000.0)])
    await db.commit()
    await db.refresh(btc)
    assert float(btc.current_price) == 57000.0


async def test_manual_mode_with_a_price_sets_the_manual_source_on_legacy_positions(client, db):
    """Nachabnahme: Modus manual und ein Kurs im selben Request heissen Handkurs,
    auch wenn der Modus schon manual war (Altbestand mit Preisquelle yahoo)."""
    headers = await _register(client, "w5-legacyprice@test.local")
    uid = await _user_id(db, "w5-legacyprice@test.local")
    pos = await _make_position(
        db, uid, "IB01.L", type=AssetType.bond,
        pricing_mode=PricingMode.manual, price_source=PriceSource.yahoo,
    )

    res = await client.put(
        f"/api/portfolio/positions/{pos.id}", headers=headers,
        json={"pricing_mode": "manual", "current_price": 50},
    )

    assert res.status_code == 200, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "manual")
    await cs._update_position_prices_batch(db, [("IB01.L", 122.58)])
    await db.commit()
    await db.refresh(pos)
    assert float(pos.current_price) == 50


async def test_switch_to_manual_mode_sets_the_manual_price_source(client, db):
    """K109: Wer den Modus auf manual stellt, pflegt den Kurs selbst."""
    headers = await _register(client, "w5-tomanual@test.local")
    uid = await _user_id(db, "w5-tomanual@test.local")
    pos = await _make_position(db, uid, "NESN.SW", currency="CHF", current_price=Decimal("90"))

    res = await client.put(
        f"/api/portfolio/positions/{pos.id}", headers=headers,
        json={"pricing_mode": "manual", "current_price": 50},
    )

    assert res.status_code == 200, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "manual")
    assert "NESN.SW" not in (await cs.collect_all_tickers(db))["yahoo_tickers"]
    await cs._update_position_prices_batch(db, [("NESN.SW", 92.0)])
    await db.commit()
    await db.refresh(pos)
    assert float(pos.current_price) == 50

    # Zurück auf auto: die Preisquelle des Typs gilt wieder.
    res = await client.put(
        f"/api/portfolio/positions/{pos.id}", headers=headers, json={"pricing_mode": "auto"},
    )
    assert res.status_code == 200, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("auto", "yahoo")
    assert "NESN.SW" in (await cs.collect_all_tickers(db))["yahoo_tickers"]


async def test_unrelated_edit_leaves_a_legacy_manual_position_live_priced(client, db):
    """Der Bearbeiten-Dialog sendet Modus und Preisquelle unverändert mit."""
    headers = await _register(client, "w5-legacyedit@test.local")
    uid = await _user_id(db, "w5-legacyedit@test.local")
    pos = await _make_position(
        db, uid, "IB01.L", type=AssetType.bond,
        pricing_mode=PricingMode.manual, price_source=PriceSource.yahoo,
    )

    res = await client.put(
        f"/api/portfolio/positions/{pos.id}", headers=headers,
        json={"name": "Treasury 0-1yr", "pricing_mode": "manual", "price_source": "yahoo"},
    )

    assert res.status_code == 200, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "yahoo")
    assert "IB01.L" in (await cs.collect_all_tickers(db))["yahoo_tickers"]


async def test_create_with_manual_mode_sets_the_manual_price_source(client, db):
    headers = await _register(client, "w5-createmanual@test.local")
    base = {
        "name": "Privatplatzierung", "type": "stock", "currency": "CHF",
        "shares": 10, "cost_basis_chf": 1000, "current_price": 100, "pricing_mode": "manual",
    }

    res = await client.post("/api/portfolio/positions", headers=headers, json={**base, "ticker": "PRIV1"})
    assert res.status_code == 201, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "manual")

    # Ausdrücklich genannte Preisquelle gilt: Bestand von Hand, Kurs vom Worker.
    res = await client.post(
        "/api/portfolio/positions", headers=headers,
        json={**base, "ticker": "PRIV2", "price_source": "yahoo"},
    )
    assert res.status_code == 201, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "yahoo")


async def test_type_change_keeps_manual_where_no_live_price_exists(client, db):
    headers = await _register(client, "w5-keep@test.local")
    uid = await _user_id(db, "w5-keep@test.local")
    konto = await _make_position(
        db, uid, "CASH_Sparkonto", type=AssetType.cash,
        pricing_mode=PricingMode.manual, price_source=PriceSource.manual, currency="CHF",
    )
    aktie = await _make_position(db, uid, "NESN.SW", currency="CHF", **MANUAL_PRICE)

    # Cash zu Vorsorge: beide Typen führen ihren Saldo manuell.
    res = await client.put(f"/api/portfolio/positions/{konto.id}", headers=headers, json={"type": "pension"})
    assert res.status_code == 200, res.text
    assert res.json()["pricing_mode"] == "manual"

    # Aktie zu ETF: der manuelle Kurs ist eine Wahl des Nutzers (K109).
    res = await client.put(f"/api/portfolio/positions/{aktie.id}", headers=headers, json={"type": "etf"})
    assert res.status_code == 200, res.text
    assert (res.json()["pricing_mode"], res.json()["price_source"]) == ("manual", "manual")


# ---------------------------------------------------------------------------
# R-pricecache-5 — Länge der coingecko_id
# ---------------------------------------------------------------------------

async def test_longest_accepted_coingecko_id_gets_a_price_cache_row(db):
    column_len = PriceCache.__table__.c.ticker.type.length
    assert cs.COINGECKO_ID_MAX_LEN == column_len - len(cs.CRYPTO_PRICE_KEY_PREFIX) == 57

    longest = "a" * cs.COINGECKO_ID_MAX_LEN
    assert cs.is_coingecko_id(longest) is True
    assert cs.is_coingecko_id(longest + "a") is False
    assert len(cs.crypto_price_key(longest)) == column_len

    written = await cs._upsert_price_rows(db, [{
        "ticker": cs.crypto_price_key(longest), "date": date.today(),
        "close": 1.5, "currency": "CHF", "source": "coingecko",
    }])
    await db.commit()

    assert written == 1


async def test_create_rejects_coingecko_id_that_would_get_no_price_row(client, db):
    headers = await _register(client, "w5-cgid@test.local")
    payload = {"ticker": "BTC-USD", "name": "Coin", "type": "crypto", "currency": "USD", "shares": 0, "cost_basis_chf": 0}

    res = await client.post("/api/portfolio/positions", headers=headers, json={**payload, "coingecko_id": "a" * 58})
    assert res.status_code == 422, res.text
    assert "höchstens 57 Zeichen" in res.json()["detail"]

    res = await client.post("/api/portfolio/positions", headers=headers, json={**payload, "coingecko_id": "a" * 57})
    assert res.status_code == 201, res.text


# ---------------------------------------------------------------------------
# R-yfanalysis-3 — .L-Ticker ohne bekannte Kurswährung
# ---------------------------------------------------------------------------

async def test_download_skips_lse_ticker_with_unknown_quote_currency(monkeypatch):
    """Ticker-Lock länger als die Frist belegt: yf_quote_currency liefert None."""
    monkeypatch.setattr(cs, "yf_download", lambda tickers, **kw: _yahoo_frame(
        {"SHEL.L": [2490.0, 2500.0], "AAPL": [189.0, 190.0]}
    ))
    monkeypatch.setattr(cs, "yf_quote_currency", lambda ticker: None)

    results = cs._download_yahoo_batch(["SHEL.L", "AAPL"])

    # Kein Kurs statt 2500 «GBP» (100-fach zu hoch). Andere Ticker bleiben.
    assert "SHEL.L" not in results
    assert results["AAPL"]["price"] == 190.0


async def test_download_converts_pence_and_keeps_other_lse_currencies(monkeypatch):
    monkeypatch.setattr(cs, "yf_download", lambda tickers, **kw: _yahoo_frame(
        {"SHEL.L": [2490.0, 2500.0], "EIMI.L": [39.0, 40.0]}
    ))
    monkeypatch.setattr(cs, "yf_quote_currency", lambda ticker: {"SHEL.L": "GBp", "EIMI.L": "USD"}[ticker])

    results = cs._download_yahoo_batch(["SHEL.L", "EIMI.L"])

    assert (results["SHEL.L"]["price"], results["SHEL.L"]["currency"]) == (25.0, "GBP")
    assert (results["EIMI.L"]["price"], results["EIMI.L"]["currency"]) == (40.0, "USD")


async def test_backfill_skips_lse_ticker_with_unknown_quote_currency(db, monkeypatch):
    index = pd.date_range("2026-11-11", periods=2)
    monkeypatch.setattr(cs, "yf_download", lambda tickers, **kw: pd.DataFrame({"Close": [2490.0, 2500.0]}, index=index))
    executed = []
    real_execute = db.execute

    async def recording_execute(stmt, *args, **kwargs):
        executed.append(stmt)
        return await real_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db, "execute", recording_execute)

    # Kurswährung unbekannt: nichts schreiben. on_conflict_do_nothing korrigierte
    # eine Pence-Zeile unter dem Label GBP später nie.
    monkeypatch.setattr(cs, "yf_quote_currency", lambda ticker: None)
    assert await cs.backfill_price_history(db, "SHEL.L") == 0
    assert executed == []

    # Gegenprobe: mit bekannter Kurswährung schreibt derselbe Aufruf Pfund-Kurse.
    monkeypatch.setattr(cs, "yf_quote_currency", lambda ticker: "GBp")
    assert await cs.backfill_price_history(db, "SHEL.L") == 2
    rows = (await real_execute(select(PriceCache).where(PriceCache.ticker == "SHEL.L"))).scalars().all()
    assert sorted((float(r.close), r.currency) for r in rows) == [(24.9, "GBP"), (25.0, "GBP")]


# ---------------------------------------------------------------------------
# R-extapi-1 (Zusatz) — Recalculate leert den Summary-Cache
# ---------------------------------------------------------------------------

async def test_recalculate_all_invalidates_the_summary_cache(client, db):
    from services.portfolio_service import portfolio_cache_version

    headers = await _register(client, "w5-recalc@test.local")
    uid = str(await _user_id(db, "w5-recalc@test.local"))
    cache.set(f"portfolio_summary:{uid}", {"positions": [], "stale": True})
    version_before = portfolio_cache_version(uid)

    res = await client.post("/api/portfolio/positions/recalculate", headers=headers)

    assert res.status_code == 200, res.text
    assert cache.get(f"portfolio_summary:{uid}") is None
    assert portfolio_cache_version(uid) != version_before
