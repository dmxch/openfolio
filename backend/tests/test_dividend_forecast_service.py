"""Dividenden-Forecast: Aggregation pro aktueller Position (Run-Rate),
Eligibility, Sortierung, und der Cache-Lese-Pfad der API."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

import services.dividend_forecast_service as fc
from models.position import AssetType, Position, PriceSource
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket

pytestmark = pytest.mark.asyncio


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await create_system_buckets(db, user.id)
    await get_liquid_default_bucket(db, user.id)
    await db.commit()
    return user


async def _pos(db, user, *, ticker, typ=AssetType.stock, shares="10", count_as_cash=False):
    liquid = await get_liquid_default_bucket(db, user.id)
    p = Position(
        user_id=user.id, bucket_id=liquid.id, ticker=ticker, name=f"{ticker} Inc",
        type=typ, currency="USD", price_source=PriceSource.yahoo,
        shares=Decimal(shares), cost_basis_chf=Decimal("1000"), count_as_cash=count_as_cash,
    )
    db.add(p)
    await db.commit()


def _fake_fetch(mapping):
    def _f(ticker, since_date, shares, currency="USD"):
        return mapping.get(ticker, [])
    return _f


async def test_compute_forecast_aggregates_per_holding(db, monkeypatch):
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    user = await _make_user(db)
    await _pos(db, user, ticker="AAPL")
    await _pos(db, user, ticker="KO")
    await _pos(db, user, ticker="NOPAY")
    monkeypatch.setattr(fc, "fetch_dividends", _fake_fetch({
        "AAPL": [{"total_chf": 25.0, "dividend_per_share": 0.25} for _ in range(4)],  # 100
        "KO": [{"total_chf": 50.0, "dividend_per_share": 0.5}],                        # 50
        "NOPAY": [],
    }))

    res = await fc.compute_dividend_forecast(db, user.id)
    assert res["has_data"] is True
    assert res["forecast_12m_chf"] == 150.0
    assert res["eligible_count"] == 3      # alle drei stock-Holdings zaehlbar
    assert res["payer_count"] == 2         # NOPAY hat keine Dividende
    # nach Betrag absteigend sortiert
    assert [h["ticker"] for h in res["by_holding"]] == ["AAPL", "KO"]
    aapl = res["by_holding"][0]
    assert aapl["forecast_chf"] == 100.0
    assert aapl["payments"] == 4
    assert aapl["dps_12m"] == 1.0


async def test_compute_forecast_by_month_distribution(db, monkeypatch):
    """by_month verteilt jeden realen Zahltag auf seinen Kalendermonat (1-12),
    immer 12 Eintraege, und die Summe == forecast_12m_chf (keine erfundenen oder
    verlorenen Betraege)."""
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    user = await _make_user(db)
    await _pos(db, user, ticker="AAPL")
    await _pos(db, user, ticker="KO")
    monkeypatch.setattr(fc, "fetch_dividends", _fake_fetch({
        # AAPL quartalsweise: Aug/Nov/Feb/Mai je 25
        "AAPL": [
            {"date": "2025-08-15", "total_chf": 25.0, "dividend_per_share": 0.25},
            {"date": "2025-11-15", "total_chf": 25.0, "dividend_per_share": 0.25},
            {"date": "2026-02-15", "total_chf": 25.0, "dividend_per_share": 0.25},
            {"date": "2026-05-15", "total_chf": 25.0, "dividend_per_share": 0.25},
        ],
        # KO halbjaehrlich: Sep/Maerz je 30
        "KO": [
            {"date": "2025-09-01", "total_chf": 30.0, "dividend_per_share": 0.3},
            {"date": "2026-03-01", "total_chf": 30.0, "dividend_per_share": 0.3},
        ],
    }))

    res = await fc.compute_dividend_forecast(db, user.id)
    by_month = res["by_month"]
    assert len(by_month) == 12
    assert [m["month"] for m in by_month] == list(range(1, 13))
    chf = {m["month"]: m["chf"] for m in by_month}
    assert chf[2] == 25.0 and chf[5] == 25.0 and chf[8] == 25.0 and chf[11] == 25.0  # AAPL
    assert chf[3] == 30.0 and chf[9] == 30.0                                          # KO
    assert chf[1] == 0.0 and chf[12] == 0.0                                           # zahlungsfreie Monate
    # Summen-Invariante: by_month rekonstruiert genau den 12M-Forecast
    assert round(sum(m["chf"] for m in by_month), 2) == res["forecast_12m_chf"] == 160.0
    # Internfeld _months ist aus by_holding entfernt (schlanke Form)
    assert all("_months" not in h for h in res["by_holding"])


async def test_compute_forecast_eligibility(db, monkeypatch):
    """count_as_cash, Nicht-stock/etf/bond und shares=0 zaehlen nicht.

    Der count_as_cash-Fall ist hier bewusst ein CHF-Geldmarktfonds und nicht mehr
    IB01: ein Anleihen-ETF laeuft jetzt als type="bond" und ist damit eligible
    (siehe test_compute_forecast_includes_bond). count_as_cash bleibt der
    Ausschluss fuer bewusst als Cash gefuehrte Geldmarkt-Instrumente.
    """
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    user = await _make_user(db)
    await _pos(db, user, ticker="AAPL")                              # zaehlt
    await _pos(db, user, ticker="CSBGC0.SW", typ=AssetType.etf, count_as_cash=True)  # raus (cash)
    await _pos(db, user, ticker="BTC", typ=AssetType.crypto)         # raus (typ)
    await _pos(db, user, ticker="ZERO", shares="0")                  # raus (shares=0)
    monkeypatch.setattr(fc, "fetch_dividends", _fake_fetch({
        "AAPL": [{"total_chf": 40.0, "dividend_per_share": 0.4}],
    }))
    res = await fc.compute_dividend_forecast(db, user.id)
    assert res["eligible_count"] == 1
    assert res["forecast_12m_chf"] == 40.0


async def test_compute_forecast_includes_bond(db, monkeypatch):
    """Anleihen schuetten aus — der Forecast muss sie enthalten.

    Das ist die Neumodellierung von IB01: frueher etf + count_as_cash (und damit
    aus dem Forecast ausgeschlossen), jetzt type="bond" und voll zaehlend. Faellt
    bond aus dem Typ-Filter, fehlt die Ausschuettung still im 12M-Forecast.

    Herleitung: AAPL 40 + IB01 4 x 15 = 60 -> Forecast 100.
    """
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    user = await _make_user(db)
    await _pos(db, user, ticker="AAPL")
    await _pos(db, user, ticker="IB01.L", typ=AssetType.bond)
    monkeypatch.setattr(fc, "fetch_dividends", _fake_fetch({
        "AAPL": [{"total_chf": 40.0, "dividend_per_share": 0.4}],
        "IB01.L": [{"total_chf": 15.0, "dividend_per_share": 0.15} for _ in range(4)],
    }))
    res = await fc.compute_dividend_forecast(db, user.id)
    assert res["eligible_count"] == 2
    assert res["payer_count"] == 2
    assert res["forecast_12m_chf"] == 100.0
    by_ticker = {h["ticker"]: h for h in res["by_holding"]}
    assert by_ticker["IB01.L"]["forecast_chf"] == 60.0
    assert by_ticker["IB01.L"]["payments"] == 4


async def test_refresh_picks_up_bond_only_user(db, monkeypatch):
    """Der Worker-Entry-Point sammelt die User ueber denselben Typ-Filter. Ein
    Nutzer mit AUSSCHLIESSLICH Anleihen darf dabei nicht durchs Raster fallen —
    sonst bekaeme er nie einen Forecast."""
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    user = await _make_user(db)
    await _pos(db, user, ticker="IB01.L", typ=AssetType.bond)
    monkeypatch.setattr(fc, "fetch_dividends", _fake_fetch({
        "IB01.L": [{"total_chf": 25.0, "dividend_per_share": 0.25}],
    }))
    res = await fc.refresh_dividend_forecasts(db)
    assert res["users"] == 1
    assert res["ok"] == 1


async def test_compute_forecast_user_scoped(db, monkeypatch):
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    monkeypatch.setattr(fc, "fetch_dividends", _fake_fetch({
        "AAPL": [{"total_chf": 10.0, "dividend_per_share": 0.1}],
    }))
    a = await _make_user(db)
    b = await _make_user(db)
    await _pos(db, a, ticker="AAPL")
    res_b = await fc.compute_dividend_forecast(db, b.id)
    assert res_b["eligible_count"] == 0
    assert res_b["forecast_12m_chf"] == 0.0
    assert res_b["has_data"] is True       # leer, aber berechnet


async def test_compute_forecast_fetch_error_is_best_effort(db, monkeypatch):
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    user = await _make_user(db)
    await _pos(db, user, ticker="AAPL")
    await _pos(db, user, ticker="BOOM")

    def _f(ticker, since_date, shares, currency="USD"):
        if ticker == "BOOM":
            raise RuntimeError("yfinance 429")
        return [{"total_chf": 30.0, "dividend_per_share": 0.3}]
    monkeypatch.setattr(fc, "fetch_dividends", _f)

    res = await fc.compute_dividend_forecast(db, user.id)   # darf nicht werfen
    assert res["forecast_12m_chf"] == 30.0
    assert res["payer_count"] == 1


# --- API-Pfad liest NUR den Cache ---------------------------------------

async def test_get_forecast_reads_cache(db, monkeypatch):
    user = await _make_user(db)
    payload = {"has_data": True, "forecast_12m_chf": 99.0, "as_of": "2026-06-28",
               "eligible_count": 1, "payer_count": 1, "by_holding": []}
    monkeypatch.setattr(fc.cache, "get", lambda k: payload)
    res = await fc.get_dividend_forecast(db, user.id)
    assert res["forecast_12m_chf"] == 99.0


async def test_get_forecast_cold_cache_has_no_data(db, monkeypatch):
    user = await _make_user(db)
    monkeypatch.setattr(fc.cache, "get", lambda k: None)
    res = await fc.get_dividend_forecast(db, user.id)
    assert res["has_data"] is False
    assert res["forecast_12m_chf"] == 0.0


async def test_refresh_continues_and_rolls_back_after_user_error(db, monkeypatch):
    """Faellt compute fuer einen User, wird die Session bereinigt (rollback) und
    die uebrigen User laufen weiter — kein Cascading-Failure."""
    monkeypatch.setattr(fc.cache, "set", lambda *a, **k: None)
    a = await _make_user(db)
    b = await _make_user(db)
    await _pos(db, a, ticker="AAPL")
    await _pos(db, b, ticker="KO")
    monkeypatch.setattr(fc, "fetch_dividends", _fake_fetch({
        "AAPL": [{"total_chf": 10.0, "dividend_per_share": 0.1}],
        "KO": [{"total_chf": 20.0, "dividend_per_share": 0.2}],
    }))

    real = fc.compute_dividend_forecast
    calls = {"n": 0}

    async def flaky(_db, uid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient DB error")
        return await real(_db, uid)
    monkeypatch.setattr(fc, "compute_dividend_forecast", flaky)

    rollbacks = {"n": 0}
    orig_rb = db.rollback

    async def spy_rb():
        rollbacks["n"] += 1
        return await orig_rb()
    monkeypatch.setattr(db, "rollback", spy_rb)

    res = await fc.refresh_dividend_forecasts(db)
    assert res["users"] == 2
    assert res["ok"] == 1          # einer fiel, der andere lief weiter
    assert rollbacks["n"] == 1     # Session nach dem Fehler bereinigt
