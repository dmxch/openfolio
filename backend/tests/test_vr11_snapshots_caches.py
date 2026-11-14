"""Vollreview 11/2026: Caches rund um Summary, Renditen und Earnings.

K013  Earnings-Vorschau mit Abruffehler nur 5 Minuten cachen
K016  Summary gibt die DB-Connection vor der Thread-Phase zurück
K039  Versionsmarke je Nutzer in den abgeleiteten Cache-Schlüsseln
K060  get_portfolio_summary_cached
K061  Total-Return lädt Snapshots und Transaktionen einmal und cacht das Ergebnis
K064  24h-Änderung gebündelt über get_many
K130  keine Abfrage über die Transaktionen aller Nutzer bei leerem Depot
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from db import async_session, engine as test_engine
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position
from models.transaction import Transaction, TransactionType
from services import cache
from services import portfolio_service as ps
from services.portfolio_service import (
    bump_portfolio_cache_version,
    get_portfolio_summary,
    get_portfolio_summary_cached,
    portfolio_cache_version,
    single_flight,
)

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"

SUMMARY = {
    "total_pnl_chf": 100.0,
    "total_invested_chf": 1000.0,
    "positions": [
        {"type": "stock", "cost_basis_chf": 1000.0, "market_value_chf": 1100.0, "pnl_chf": 100.0},
    ],
}


@contextmanager
def capture_sql():
    statements: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _before)


def _touching(statements: list[str], table: str) -> list[str]:
    return [s for s in statements if f"FROM {table}" in s]


def _snap(uid, d: date, value, cf=0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        user_id=uid, date=d, total_value_chf=Decimal(str(value)),
        cash_chf=Decimal("0"), net_cash_flow_chf=Decimal(str(cf)),
    )


def _txn(uid, ttype, d: date, total, **extra) -> Transaction:
    return Transaction(
        user_id=uid, position_id=uuid.uuid4(), type=ttype, date=d,
        shares=Decimal("0"), price_per_share=Decimal("0"), currency="CHF",
        total_chf=Decimal(str(total)), **{k: Decimal(str(v)) for k, v in extra.items()},
    )


# --- K039 -------------------------------------------------------------------


async def test_k039_version_changes_on_bump_and_invalidate():
    from api.portfolio import invalidate_portfolio_cache

    uid = uuid.uuid4()
    other = uuid.uuid4()
    assert portfolio_cache_version(uid) == "0"

    bump_portfolio_cache_version(uid)
    first = portfolio_cache_version(uid)
    assert first != "0"
    assert portfolio_cache_version(other) == "0"  # je Nutzer

    cache.set(f"portfolio_summary:{uid}", {"positions": []}, ttl=60)
    invalidate_portfolio_cache(str(uid))
    assert cache.get(f"portfolio_summary:{uid}") is None
    assert portfolio_cache_version(uid) not in ("0", first)


async def test_k039_monthly_returns_are_recomputed_after_invalidation(db):
    """Vorher blieb monthly_returns_m:{user} nach einer Buchung 15 Minuten stehen."""
    from api.portfolio import invalidate_portfolio_cache
    from services.performance_history_service import get_monthly_returns

    uid = uuid.uuid4()
    today = date.today()
    month_start = today.replace(day=1)
    prev_end = month_start - timedelta(days=1)
    db.add(_txn(uid, TransactionType.buy, prev_end.replace(day=1), 1000))
    last = _snap(uid, today, 1100)
    db.add_all([_snap(uid, prev_end.replace(day=1), 1000), _snap(uid, prev_end, 1000), last])
    await db.commit()

    def _this_month(result):
        return next(m["return_pct"] for m in result["months"]
                    if (m["year"], m["month"]) == (today.year, today.month))

    assert _this_month(await get_monthly_returns(db, user_id=uid)) == 10.0

    last.total_value_chf = Decimal("1200")
    await db.commit()
    # Ohne Invalidierung: Cache-Treffer mit dem alten Wert.
    assert _this_month(await get_monthly_returns(db, user_id=uid)) == 10.0

    invalidate_portfolio_cache(str(uid))
    assert _this_month(await get_monthly_returns(db, user_id=uid)) == 20.0


async def test_k039_version_is_part_of_the_derived_cache_keys(db, monkeypatch):
    """Historie, Faktor-Zerlegung, Korrelation und Earnings-Vorschau tragen die
    Marke im Schlüssel."""
    from services import factor_decomposition_service as fds

    uid = uuid.uuid4()
    bump_portfolio_cache_version(uid)
    marker = f":v{portfolio_cache_version(uid)}:"
    keys = []
    real_get = cache.get

    def spy_get(key):
        keys.append(key)
        return real_get(key)

    monkeypatch.setattr("services.cache.get", spy_get)
    monkeypatch.setattr(fds, "get_portfolio_history", AsyncMock(return_value={"data": []}))
    await fds.factor_decomposition(db, date(2025, 1, 1), date(2025, 6, 30), user_id=uid)

    db.add(Position(
        user_id=uid, bucket_id=uuid.uuid4(), ticker="CASH_CHF", name="Konto",
        type=AssetType.cash, currency="CHF", shares=Decimal("1"),
        cost_basis_chf=Decimal("500"), is_active=True,
    ))
    await db.commit()
    from services.history_service import get_portfolio_history
    await get_portfolio_history(db, date(2025, 1, 1), date.today(), benchmark="", user_id=uid)

    for prefix in ("factor_decomp:", "portfolio_history:"):
        matching = [k for k in keys if k.startswith(prefix)]
        assert matching and all(marker in k for k in matching), prefix


async def test_k039_route_cache_keys_carry_the_version(client, db, monkeypatch):
    from sqlalchemy import select

    from models.user import User

    await client.post("/api/auth/register", json={"email": "k039@example.com", "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": "k039@example.com", "password": TEST_PASSWORD})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    uid = (await db.execute(select(User.id).where(User.email == "k039@example.com"))).scalar_one()
    bump_portfolio_cache_version(uid)
    marker = f":v{portfolio_cache_version(uid)}:"

    written = []
    real_set = cache.set

    def spy_set(key, value, ttl=900):
        written.append(key)
        return real_set(key, value, ttl)

    monkeypatch.setattr("services.cache.set", spy_set)
    monkeypatch.setattr("api.portfolio.compute_correlation_matrix", AsyncMock(return_value={"tickers": []}))
    monkeypatch.setattr("api.portfolio.result_cache_ttl", lambda data: 60)
    monkeypatch.setattr("api.portfolio.compute_bucket_correlation_matrix", AsyncMock(return_value={"buckets": []}))
    monkeypatch.setattr(
        "api.portfolio.get_upcoming_earnings_for_portfolio",
        AsyncMock(return_value={"earnings": [], "warnings": []}),
    )

    for path in ("correlation-matrix", "buckets/correlation-matrix", "upcoming-earnings"):
        assert (await client.get(f"/api/portfolio/{path}", headers=headers)).status_code == 200

    for prefix in ("external:correlation:", "buckets:correlation:", "external:upcoming_earnings:"):
        matching = [k for k in written if k.startswith(prefix)]
        assert matching and all(marker in k for k in matching), prefix


# --- K060 -------------------------------------------------------------------


async def test_k060_cached_summary_computes_once(db, monkeypatch):
    from api.portfolio import invalidate_portfolio_cache

    uid = uuid.uuid4()
    compute = AsyncMock(side_effect=lambda db, user_id=None: {"positions": [], "n": compute.await_count})
    monkeypatch.setattr(ps, "get_portfolio_summary", compute)

    first = await get_portfolio_summary_cached(db, uid)
    second = await get_portfolio_summary_cached(db, uid)
    assert compute.await_count == 1
    assert first == second == {"positions": [], "n": 1}
    # Derselbe Schlüssel wie /api/portfolio/summary und /api/alerts.
    assert cache.get(f"portfolio_summary:{uid}") == first

    invalidate_portfolio_cache(str(uid))
    assert (await get_portfolio_summary_cached(db, uid))["n"] == 2


async def test_k060_concurrent_misses_compute_once(db, monkeypatch):
    uid = uuid.uuid4()
    calls = 0

    async def slow_summary(db, user_id=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"positions": [], "n": calls}

    monkeypatch.setattr(ps, "get_portfolio_summary", slow_summary)

    results = await asyncio.gather(*[get_portfolio_summary_cached(db, uid) for _ in range(5)])

    assert calls == 1
    assert all(r == {"positions": [], "n": 1} for r in results)


async def test_k060_result_computed_across_a_write_is_not_cached(db, monkeypatch):
    """Eine Buchung während der Berechnung: das Ergebnis kennt sie vielleicht
    nicht und darf nicht für 60 s in den Cache."""
    uid = uuid.uuid4()
    calls = 0

    async def summary_with_write(db, user_id=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            bump_portfolio_cache_version(uid)
        return {"positions": [], "n": calls}

    monkeypatch.setattr(ps, "get_portfolio_summary", summary_with_write)

    assert (await get_portfolio_summary_cached(db, uid))["n"] == 1
    assert cache.get(f"portfolio_summary:{uid}") is None
    assert (await get_portfolio_summary_cached(db, uid))["n"] == 2
    assert (await get_portfolio_summary_cached(db, uid))["n"] == 2


async def test_single_flight_propagates_errors_and_recovers():
    key = f"sf:{uuid.uuid4()}"
    attempts = 0

    async def failing():
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.02)
        raise ValueError("boom")

    results = await asyncio.gather(
        *[single_flight(key, failing) for _ in range(3)], return_exceptions=True
    )
    assert attempts == 1
    assert all(isinstance(r, ValueError) for r in results)
    assert key not in ps._inflight

    async def ok():
        return 42

    assert await single_flight(key, ok) == 42


async def test_single_flight_follower_takes_over_when_leader_is_cancelled():
    key = f"sf:{uuid.uuid4()}"
    started = asyncio.Event()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await asyncio.sleep(30)
        return calls

    leader = asyncio.create_task(single_flight(key, compute))
    await asyncio.wait_for(started.wait(), timeout=5)
    follower = asyncio.create_task(single_flight(key, compute))
    await asyncio.sleep(0)
    leader.cancel()

    assert await asyncio.wait_for(follower, timeout=5) == 2
    with pytest.raises(asyncio.CancelledError):
        await leader
    assert key not in ps._inflight


# --- K016 / K130 ------------------------------------------------------------


async def test_k130_empty_depot_does_not_scan_transactions(db, monkeypatch):
    """Ohne Positionen entfiel der Filter position_id IN (...): die Abfrage
    gruppierte die Kauf-Transaktionen aller Nutzer."""
    monkeypatch.setattr(ps, "get_fx_rates_batch", lambda: {})
    other = uuid.uuid4()
    db.add(_txn(other, TransactionType.buy, date(2025, 1, 6), 1000))
    await db.commit()

    with capture_sql() as statements:
        summary = await get_portfolio_summary(db, uuid.uuid4())

    assert summary["positions"] == []
    assert _touching(statements, "transactions") == []


async def test_k130_first_buy_date_still_reported(db, monkeypatch):
    monkeypatch.setattr(ps, "get_fx_rates_batch", lambda: {})
    monkeypatch.setattr(ps, "prefetch_close_series", lambda tickers: None)
    monkeypatch.setattr(ps, "_get_ma_status", lambda t: {"ma_status": None, "ma_detail": None})
    monkeypatch.setattr(ps, "_get_mrs", lambda t: None)
    monkeypatch.setattr(ps, "get_stock_prices_bulk", lambda tickers: {})
    uid = uuid.uuid4()
    pos = Position(
        user_id=uid, bucket_id=uuid.uuid4(), ticker="AAA", name="AAA", type=AssetType.stock,
        currency="CHF", shares=Decimal("10"), cost_basis_chf=Decimal("1000"), is_active=True,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    for d in (date(2025, 3, 3), date(2025, 1, 6)):
        txn = _txn(uid, TransactionType.buy, d, 500)
        txn.position_id = pos.id
        db.add(txn)
    await db.commit()

    summary = await get_portfolio_summary(db, uid)

    assert summary["positions"][0]["buy_date"] == "2025-01-06"


async def test_k016_summary_releases_connection_before_thread_phase(db, monkeypatch):
    seen = []
    monkeypatch.setattr(ps, "get_fx_rates_batch", lambda: {"CHF": 1.0})
    monkeypatch.setattr(ps, "prefetch_close_series", lambda tickers: seen.append(db.in_transaction()))
    monkeypatch.setattr(ps, "_get_ma_status", lambda t: {"ma_status": None, "ma_detail": None})
    monkeypatch.setattr(ps, "_get_mrs", lambda t: None)
    monkeypatch.setattr(
        ps, "get_stock_prices_bulk",
        lambda tickers: {"AAA": {"price": 110.0, "currency": "CHF", "change_pct": 0}},
    )
    uid = uuid.uuid4()
    db.add(Position(
        user_id=uid, bucket_id=uuid.uuid4(), ticker="AAA", name="AAA", type=AssetType.stock,
        currency="CHF", shares=Decimal("10"), cost_basis_chf=Decimal("1000"), is_active=True,
    ))
    await db.commit()

    summary = await get_portfolio_summary(db, uid)

    assert seen == [False]
    assert summary["total_market_value_chf"] == 1100.0


async def test_k064_skip_tickers_are_priced_through_the_bulk_lookup(db, monkeypatch):
    """GC=F steht in SKIP_TICKERS (kein MA/MRS), braucht aber einen Kurs. Ohne
    Einzel-Fallback muss der Ticker im Bulk-Lookup stehen."""
    bulk_calls = []

    def fake_bulk(tickers):
        bulk_calls.append(set(tickers))
        return {"GC=F": {"price": 2000.0, "currency": "CHF", "change_pct": 0}}

    def no_single(*args, **kwargs):
        raise AssertionError("get_stock_price darf im Summary-Pfad nicht laufen")

    monkeypatch.setattr(ps, "get_fx_rates_batch", lambda: {"CHF": 1.0})
    monkeypatch.setattr(ps, "get_stock_prices_bulk", fake_bulk)
    monkeypatch.setattr(ps, "get_stock_price", no_single)
    uid = uuid.uuid4()
    db.add_all([
        Position(
            user_id=uid, bucket_id=uuid.uuid4(), ticker="GC=F", name="Gold-Future",
            type=AssetType.commodity, currency="CHF", shares=Decimal("2"),
            cost_basis_chf=Decimal("3000"), is_active=True,
        ),
        Position(
            user_id=uid, bucket_id=uuid.uuid4(), ticker="CASH_CHF", name="Konto",
            type=AssetType.cash, currency="CHF", shares=Decimal("1"),
            cost_basis_chf=Decimal("500"), is_active=True,
        ),
    ])
    await db.commit()

    summary = await get_portfolio_summary(db, uid)

    assert bulk_calls == [{"GC=F"}]
    values = {p["ticker"]: p["market_value_chf"] for p in summary["positions"]}
    assert values == {"GC=F": 4000.0, "CASH_CHF": 500.0}


# --- K064 -------------------------------------------------------------------


async def test_k064_enrich_reads_all_price_keys_in_one_call(monkeypatch):
    from api import portfolio as portfolio_api

    positions = [{"id": f"pos-{i}", "ticker": f"T{i}"} for i in range(4)]
    rows = [
        SimpleNamespace(id="pos-0", bank_name=None, iban=None, notes=None, type=AssetType.stock,
                        coingecko_id=None, yfinance_ticker=None, ticker="T0"),
        SimpleNamespace(id="pos-1", bank_name=None, iban=None, notes=None, type=AssetType.stock,
                        coingecko_id=None, yfinance_ticker="T1.SW", ticker="T1"),
        # K019: die coingecko_id zählt nur beim Typ crypto.
        SimpleNamespace(id="pos-2", bank_name=None, iban=None, notes=None, type=AssetType.crypto,
                        coingecko_id="bitcoin", yfinance_ticker="BTC-USD", ticker="T2"),
        SimpleNamespace(id="pos-3", bank_name=None, iban=None, notes=None, type=AssetType.stock,
                        coingecko_id=None, yfinance_ticker=None, ticker="T3"),
    ]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[rows, SimpleNamespace(all=lambda: [])])
    many_calls = []

    def fake_get_many(keys):
        many_calls.append(list(keys))
        return {
            "price:T0": {"change_pct": 1.0},
            "price:T1.SW": {"change_pct": -2.0},
            "crypto:bitcoin": {"change_pct": 3.0},
        }

    def no_single_get(key):
        raise AssertionError(f"Einzel-GET für {key}")

    monkeypatch.setattr("services.cache.get_many", fake_get_many)
    monkeypatch.setattr("services.cache.get", no_single_get)
    monkeypatch.setattr(portfolio_api, "decrypt_field", lambda v: v)
    monkeypatch.setattr(portfolio_api, "decrypt_and_mask_iban", lambda v: v)

    enriched = await portfolio_api._enrich_summary(
        db, SimpleNamespace(id=uuid.uuid4()), {"positions": positions}
    )

    assert many_calls == [["price:T0", "price:T1.SW", "crypto:bitcoin", "price:T3"]]
    assert [p["change_pct_24h"] for p in enriched["positions"]] == [1.0, -2.0, 3.0, None]


# --- K061 -------------------------------------------------------------------


async def _returns_user(db) -> uuid.UUID:
    uid = uuid.uuid4()
    today = date.today()
    year_start = date(today.year, 1, 1)
    db.add_all([
        _snap(uid, year_start - timedelta(days=400), 1000),
        _snap(uid, year_start - timedelta(days=1), 1100),
        _snap(uid, today, 1250),
        _txn(uid, TransactionType.buy, year_start - timedelta(days=400), 1000),
        _txn(uid, TransactionType.sell, year_start - timedelta(days=30), 300,
             realized_pnl_chf=40, fees_chf=3),
        _txn(uid, TransactionType.dividend, year_start - timedelta(days=20), 12,
             gross_amount=20, tax_amount=5, fx_rate_to_chf=0.8),
        _txn(uid, TransactionType.dividend, today, 9),
        _txn(uid, TransactionType.sell, today, 100, realized_pnl_chf=-15, fees_chf=2),
        _txn(uid, TransactionType.fee, today, -7),
        _txn(uid, TransactionType.interest, today, 4),
        _txn(uid, TransactionType.capital_gain, today, 6),
    ])
    await db.commit()
    return uid


async def test_k061_total_return_loads_history_once(db):
    """Vorher: vier Abfragen auf portfolio_snapshots und zehn auf transactions,
    zwei davon je ein vollständiges Laden als ORM-Objekte."""
    from services.total_return_service import get_total_return

    uid = await _returns_user(db)

    with capture_sql() as statements:
        res = await get_total_return(db, user_id=uid, summary=SUMMARY)

    assert len(_touching(statements, "portfolio_snapshots")) == 1
    assert len(_touching(statements, "transactions")) == 2  # Summen + Ledger
    # Das Ledger kommt als Spaltenauswahl, nicht als ganze Zeile.
    ledger = [s for s in _touching(statements, "transactions") if "sum(" not in s.lower()]
    assert len(ledger) == 1 and "transactions.notes" not in ledger[0]

    assert res["realized_pnl_chf"] == 25.0          # 40 - 15
    assert res["dividends_net_chf"] == 21.0         # 12 + 9
    assert res["dividends_gross_chf"] == 25.0       # 20 x 0.8 + 9 (ohne gross: netto)
    assert res["dividends_tax_chf"] == 4.0          # 5 x 0.8
    assert res["capital_gains_dist_chf"] == 6.0
    assert res["interest_chf"] == 4.0
    assert res["trading_fees_chf"] == 5.0
    assert res["other_fees_chf"] == 7.0
    assert res["total_return_chf"] == 149.0         # 100 + 25 + 21 + 6 + 4 - 7
    assert res["ytd_realized_chf"] == -15.0
    assert res["ytd_dividends_chf"] == 9.0
    assert res["ytd_chf"] == 150.0                  # 1250 - 1100, keine Snapshot-Cashflows
    assert res["ytd_pct"] is not None
    assert res["total_return_pct"] != 0


async def test_k061_calc_ytd_without_preloaded_data_matches(db):
    """_calc_ytd lädt ohne Vorgaben selbst und liefert dasselbe wie mit."""
    from services.total_return_service import _calc_ytd, get_total_return

    uid = await _returns_user(db)
    full = await get_total_return(db, user_id=uid, summary=SUMMARY)
    alone = await _calc_ytd(db, uid, 100.0)

    assert alone == {k: full[k] for k in alone}


async def test_k061_total_return_result_is_cached_until_invalidated(db, monkeypatch):
    from api.portfolio import invalidate_portfolio_cache
    from services import total_return_service as trs

    uid = await _returns_user(db)
    summary_calls = AsyncMock(return_value=SUMMARY)
    monkeypatch.setattr(trs, "get_portfolio_summary_cached", summary_calls)

    first = await trs.get_total_return(db, user_id=uid)
    with capture_sql() as statements:
        second = await trs.get_total_return(db, user_id=uid)
    assert second == first
    assert statements == []
    assert summary_calls.await_count == 1

    db.add(_txn(uid, TransactionType.interest, date.today(), 50))
    await db.commit()
    invalidate_portfolio_cache(str(uid))

    third = await trs.get_total_return(db, user_id=uid)
    assert third["interest_chf"] == first["interest_chf"] + 50
    assert summary_calls.await_count == 2


async def test_k061_concurrent_total_return_calls_compute_once(db, monkeypatch):
    from services import total_return_service as trs

    uid = await _returns_user(db)
    calls = 0

    async def slow_summary(session, user_id):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return SUMMARY

    monkeypatch.setattr(trs, "get_portfolio_summary_cached", slow_summary)

    async def _call():
        async with async_session() as session:
            return await trs.get_total_return(session, user_id=uid)

    results = await asyncio.gather(_call(), _call())

    assert calls == 1
    assert results[0] == results[1]


async def test_k061_monthly_returns_load_history_once(db):
    from services.performance_history_service import get_monthly_returns

    uid = await _returns_user(db)

    with capture_sql() as statements:
        result = await get_monthly_returns(db, user_id=uid)

    assert result["months"]
    assert len(_touching(statements, "portfolio_snapshots")) == 1
    assert len(_touching(statements, "transactions")) == 2  # min(date) + Ledger


# --- K013 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "warnings, expected_ttl",
    [(["earnings_fetch_failed:BROKEN"], 300), ([], 43200), (["no_earnings_source:ETF"], 43200)],
)
async def test_k013_failed_earnings_fetch_is_cached_only_briefly(
    client, monkeypatch, warnings, expected_ttl,
):
    email = f"k013{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    monkeypatch.setattr(
        "api.portfolio.get_upcoming_earnings_for_portfolio",
        AsyncMock(return_value={"earnings": [], "warnings": warnings}),
    )
    ttls = []
    real_set = cache.set

    def spy_set(key, value, ttl=900):
        if key.startswith("external:upcoming_earnings:"):
            ttls.append(ttl)
        return real_set(key, value, ttl)

    monkeypatch.setattr("services.cache.set", spy_set)

    res = await client.get("/api/portfolio/upcoming-earnings", headers=headers)

    assert res.status_code == 200
    assert ttls == [expected_ttl]
