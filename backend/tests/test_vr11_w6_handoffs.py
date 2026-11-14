"""Regressionstests Welle 6: Übergaben aus Welle 5 (Vollreview vom 13.11.2026).

R-importtx-4     Externe Pending Order nimmt den Ticker einer eigenen Position an
R-marketscreen-3 Wechsel des wirksamen FRED-Keys löscht auch den CH-Makro-Snapshot
R-yfanalysis-3   Regen: .L-Position mit Kauf, aber ohne Yahoo-Kurs am Kauftag
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, update

from config import settings
from models.api_write_log import ApiWriteLog
from models.pending_order import PendingOrder
from models.portfolio_snapshot import PortfolioSnapshot
from models.position import AssetType, Position, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services import cache
from services.bucket_service import create_system_buckets, get_liquid_default_bucket
from services.snapshot_service import regenerate_snapshots

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"
PENDING_ORDERS = "/api/v1/external/pending-orders"


@pytest.fixture(autouse=True)
def no_network():
    """Kein Snapshot-Regen und kein Yahoo-Abruf beim Fill."""
    info = AsyncMock(return_value={"shortName": "Test AG", "currency": "USD"})
    with (
        patch("api.orders.trigger_snapshot_regen"),
        patch("services.ticker_info_service.get_ticker_info_cached", info),
    ):
        yield


# --- Helfer ------------------------------------------------------------------

async def _login(client, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _write_key(client, jwt_headers: dict) -> dict:
    res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "w6", "write_access": True, "current_password": TEST_PASSWORD},
        headers=jwt_headers,
    )
    assert res.status_code == 201, res.text
    return {"X-API-Key": res.json()["token"]}


async def _user_id(db, email: str):
    return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _make_position(db, user_id, *, ticker: str, **over) -> Position:
    liquid = await get_liquid_default_bucket(db, user_id)
    fields = dict(
        user_id=user_id,
        bucket_id=liquid.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="USD",
        price_source=PriceSource.yahoo,
        shares=Decimal("10"),
        cost_basis_chf=Decimal("4000"),
    )
    fields.update(over)
    pos = Position(**fields)
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


def _order(**overrides) -> dict:
    base = {"ticker": "BRK B", "side": "sell", "shares": 2, "limit_price": 400.0,
            "currency": "USD", "expiry_type": "gtc"}
    base.update(overrides)
    return base


async def _create_log_rows(db) -> list[ApiWriteLog]:
    rows = (await db.execute(select(ApiWriteLog))).scalars().all()
    return [r for r in rows if r.action == "pending_order_create"]


# --- R-importtx-4: externe Pending Order --------------------------------------

class TestExternalOrderTicker:
    async def test_display_ticker_of_an_own_position_is_accepted_and_fills_it(self, client, db):
        """IBKR-Import speichert «BRK B». Vorher 422; «BRK-B» füllte eine neue Position."""
        jwt = await _login(client, "w6-order@example.com")
        key = await _write_key(client, jwt)
        user_id = await _user_id(db, "w6-order@example.com")
        pos = await _make_position(db, user_id, ticker="BRK B", yfinance_ticker="BRK-B")
        # Der Fill rechnet den Bestand aus dem Ledger neu: ohne Kauf wäre er 0.
        db.add(Transaction(
            position_id=pos.id, user_id=user_id, type=TransactionType.buy, date=date(2024, 3, 1),
            shares=Decimal("10"), price_per_share=Decimal("400"), currency="USD",
            fx_rate_to_chf=Decimal("1"), total_chf=Decimal("4000"),
        ))
        await db.commit()

        created = await client.post(PENDING_ORDERS, json=_order(ticker=" brk b "), headers=key)

        assert created.status_code == 201, created.text
        assert created.json()["ticker"] == "BRK B"
        assert [r.ticker for r in await _create_log_rows(db)] == ["BRK B"]

        fill = await client.post(
            f"{PENDING_ORDERS}/{created.json()['id']}/fill",
            json={"price_per_share": 410.0, "fill_date": date.today().isoformat(), "fx_rate_to_chf": 1.0},
            headers=key,
        )
        assert fill.status_code == 200, fill.text
        positions = (await db.execute(select(Position).where(Position.user_id == user_id))).scalars().all()
        assert [p.ticker for p in positions] == ["BRK B"]  # keine neue Position «BRK-B»
        await db.refresh(pos)
        assert float(pos.shares) == 8

    @pytest.mark.parametrize("ticker", ["AAPL MSFT", "AA,AB,AC", "AAPL;DROP", "ÄPFEL"])
    async def test_non_market_ticker_without_position_is_rejected(self, client, db, ticker):
        """yfinance zerlegt «AA,AB AC» in drei Abrufe: ohne eigene Position bleibt es bei 422."""
        jwt = await _login(client, "w6-order-bad@example.com")
        key = await _write_key(client, jwt)

        res = await client.post(PENDING_ORDERS, json=_order(ticker=ticker, side="buy"), headers=key)

        assert res.status_code == 422
        assert "Ticker" in res.json()["detail"]
        assert (await db.execute(select(PendingOrder))).scalars().all() == []
        assert await _create_log_rows(db) == []

    async def test_ticker_of_a_foreign_position_is_rejected(self, client, db):
        await _login(client, "w6-order-owner@example.com")
        owner_id = await _user_id(db, "w6-order-owner@example.com")
        await _make_position(db, owner_id, ticker="BRK B")
        jwt = await _login(client, "w6-order-other@example.com")
        key = await _write_key(client, jwt)

        res = await client.post(PENDING_ORDERS, json=_order(), headers=key)

        assert res.status_code == 422
        assert (await db.execute(select(PendingOrder))).scalars().all() == []

    async def test_market_ticker_without_position_is_still_accepted(self, client):
        jwt = await _login(client, "w6-order-ok@example.com")
        key = await _write_key(client, jwt)

        res = await client.post(PENDING_ORDERS, json=_order(ticker=" nesn.sw ", side="buy"), headers=key)

        assert res.status_code == 201, res.text
        assert res.json()["ticker"] == "NESN.SW"

    @pytest.mark.parametrize("ticker", ["", "   ", "A" * 31])
    async def test_empty_and_too_long_ticker_fail_in_the_schema(self, client, ticker):
        jwt = await _login(client, "w6-order-len@example.com")
        key = await _write_key(client, jwt)

        res = await client.post(PENDING_ORDERS, json=_order(ticker=ticker, side="buy"), headers=key)

        assert res.status_code == 422
        assert isinstance(res.json()["detail"], list)  # Pydantic, nicht die Route


# --- R-marketscreen-3: FRED-Key und CH-Makro-Snapshot --------------------------

@pytest.fixture
def mem_cache(monkeypatch):
    """Cache ohne Redis: der Memory-Layer ist die einzige Quelle, je Test frisch."""
    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    cache._mem_clear()
    yield cache
    cache._mem_clear()


@pytest.fixture
def ch_snapshot(monkeypatch):
    """Zählt die Neuberechnungen des CH-Makro-Snapshots; kein Abruf nach aussen."""
    monkeypatch.setattr(settings, "fred_system_api_key", "")
    snapshot = AsyncMock(return_value={"ch_10y": None, "warnings": ["fred_no_api_key"]})
    monkeypatch.setattr("api.market.get_ch_macro_snapshot", snapshot)
    monkeypatch.setattr("api.external_v1.get_ch_macro_snapshot", snapshot)
    return snapshot


class TestChMacroCacheOnFredKeyChange:
    async def _make_admin(self, db, email: str) -> None:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()

    async def test_admin_key_change_recomputes_the_snapshot(self, client, db, mem_cache, ch_snapshot):
        """Ohne Löschen fehlte die CH-10Y-Rendite bis sechs Stunden nach dem Speichern."""
        jwt = await _login(client, "w6-fred-admin@test.local")
        await self._make_admin(db, "w6-fred-admin@test.local")

        assert (await client.get("/api/market/macro/ch", headers=jwt)).status_code == 200
        assert (await client.get("/api/market/macro/ch", headers=jwt)).status_code == 200
        assert ch_snapshot.await_count == 1  # zweiter Aufruf aus dem Cache

        res = await client.put("/api/settings/fred-api-key", json={"api_key": "admin-key"}, headers=jwt)
        assert res.status_code == 200
        await client.get("/api/market/macro/ch", headers=jwt)
        assert ch_snapshot.await_count == 2

        res = await client.delete("/api/settings/fred-api-key", headers=jwt)
        assert res.status_code == 204
        await client.get("/api/market/macro/ch", headers=jwt)
        assert ch_snapshot.await_count == 3

    async def test_external_route_reads_the_same_dropped_key(self, client, db, mem_cache, ch_snapshot):
        jwt = await _login(client, "w6-fred-ext@test.local")
        await self._make_admin(db, "w6-fred-ext@test.local")
        key = await _write_key(client, jwt)

        assert (await client.get("/api/v1/external/macro/ch", headers=key)).status_code == 200
        await client.put("/api/settings/fred-api-key", json={"api_key": "admin-key"}, headers=jwt)
        assert (await client.get("/api/v1/external/macro/ch", headers=key)).status_code == 200

        assert ch_snapshot.await_count == 2

    async def test_plain_user_cannot_clear_the_shared_snapshot(self, client, mem_cache, ch_snapshot):
        """K142 gilt weiter: der Key eines Nutzers ohne Admin-Recht ändert den wirksamen Key nicht."""
        jwt = await _login(client, "w6-fred-user@test.local")
        await client.get("/api/market/macro/ch", headers=jwt)

        await client.put("/api/settings/fred-api-key", json={"api_key": "user-key"}, headers=jwt)
        await client.delete("/api/settings/fred-api-key", headers=jwt)
        await client.get("/api/market/macro/ch", headers=jwt)

        assert ch_snapshot.await_count == 1


# --- R-yfanalysis-3: Regen ohne Referenzpreis am Kauftag ------------------------
#
# Die GBX-Erkennung im Regen vergleicht den ersten Kaufkurs mit dem Yahoo-Kurs
# am Kauftag. Beginnt die Yahoo-Reihe erst nach dem Kauf, fehlt der Vergleich.
# Vorher galt die Reihe dann als Pfund, und niemand fragte die Notierungswährung.

BUY_DAY = date.today() - timedelta(days=20)
SERIES_START = BUY_DAY + timedelta(days=4)


async def _regen_depot(db) -> uuid.UUID:
    """AAA als Anker, dazu VUSA.L: 5 Stück, gekauft zu 80 GBP (Einstand 450 CHF)."""
    user = User(email=f"w6{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await db.commit()
    await create_system_buckets(db, user.id)
    await db.commit()

    anchor = await _make_position(
        db, user.id, ticker="AAA", currency="CHF", cost_basis_chf=Decimal("1000"),
    )
    vusa = await _make_position(
        db, user.id, ticker="VUSA.L", currency="GBP", shares=Decimal("5"),
        cost_basis_chf=Decimal("450"), type=AssetType.etf,
    )
    for pos, shares, price, total in ((anchor, "10", "100", "1000"), (vusa, "5", "80", "450")):
        db.add(Transaction(
            position_id=pos.id, user_id=user.id, type=TransactionType.buy, date=BUY_DAY,
            shares=Decimal(shares), price_per_share=Decimal(price), currency=pos.currency,
            fx_rate_to_chf=Decimal("1"), total_chf=Decimal(total),
        ))
    await db.commit()
    return user.id


def _fake_download(vusa_price: float | None, *, vusa_from: date | None = SERIES_START):
    """Kurs-Frame wie yf_download. VUSA.L hat vor ``vusa_from`` keinen Kurs."""
    def fake(all_tickers, **kwargs):
        cal = pd.date_range(kwargs["start"], kwargs["end"], freq="D")
        prices = {"AAA": 100.0, "VUSA.L": vusa_price, "GBPCHF=X": 1.1}
        df = pd.DataFrame(
            {("Close", t): np.full(len(cal), np.nan if prices[t] is None else prices[t]) for t in all_tickers},
            index=cal,
        )
        if vusa_from is not None:
            df.loc[df.index < pd.Timestamp(vusa_from), ("Close", "VUSA.L")] = np.nan
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df
    return fake


def _patch_regen(monkeypatch, download, quote_currency) -> list[int]:
    """Liefert die Thread-IDs, aus denen die Notierungswährung gefragt wurde."""
    seen: list[int] = []

    def lookup(ticker):
        seen.append(threading.get_ident())
        return quote_currency(ticker)

    monkeypatch.setattr("services.cache_service._quote_currency", lookup)
    monkeypatch.setattr("services.snapshot_service.yf_download", download)
    monkeypatch.setattr("services.utils.get_fx_rates_batch", lambda: {"GBP": 1.1})
    return seen


async def _last_total(db, user_id) -> float:
    rows = (await db.execute(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
        .order_by(PortfolioSnapshot.date)
        .execution_options(populate_existing=True)
    )).scalars().all()
    assert rows
    return float(rows[-1].total_value_chf)


def _raise(ticker):
    raise RuntimeError("ticker lock timeout")


class TestRegenPenceCheckWithoutReferencePrice:
    async def test_pence_series_is_divided_when_yahoo_reports_gbp_pence(self, db, monkeypatch):
        """Vorher: 5 x 8000 x 1.1 = 44'000 statt 440 in der ganzen Historie."""
        user_id = await _regen_depot(db)
        seen = _patch_regen(monkeypatch, _fake_download(8000.0), lambda t: "GBp")

        result = await regenerate_snapshots(db, user_id)

        assert "error" not in result
        assert await _last_total(db, user_id) == pytest.approx(1440.0, abs=0.01)
        # Blockierender Abruf: nie auf dem Event-Loop (K131).
        assert seen and all(t != threading.get_ident() for t in seen)

    @pytest.mark.parametrize("lookup", [lambda t: None, _raise], ids=["none", "raises"])
    async def test_series_is_ignored_when_the_quote_currency_is_unknown(self, db, monkeypatch, lookup):
        """Pence oder Pfund ist offen: Einstandswert statt eines 100-fachen Kurses."""
        user_id = await _regen_depot(db)
        _patch_regen(monkeypatch, _fake_download(8000.0), lookup)

        result = await regenerate_snapshots(db, user_id)

        assert "error" not in result
        assert await _last_total(db, user_id) == pytest.approx(1450.0, abs=0.01)

    async def test_pound_series_keeps_divisor_one(self, db, monkeypatch):
        user_id = await _regen_depot(db)
        _patch_regen(monkeypatch, _fake_download(80.0), lambda t: "GBP")

        await regenerate_snapshots(db, user_id)

        assert await _last_total(db, user_id) == pytest.approx(1440.0, abs=0.01)

    async def test_ratio_check_with_a_reference_price_asks_yahoo_nothing(self, db, monkeypatch):
        """Kontrolle: mit Kurs am Kauftag entscheidet weiter der Ratio-Vergleich."""
        user_id = await _regen_depot(db)
        seen = _patch_regen(monkeypatch, _fake_download(8000.0, vusa_from=None), _raise)

        await regenerate_snapshots(db, user_id)

        assert seen == []
        assert await _last_total(db, user_id) == pytest.approx(1440.0, abs=0.01)

    async def test_ticker_without_any_series_asks_yahoo_nothing(self, db, monkeypatch):
        """Kontrolle: ohne Reihe gibt es nichts zu bewerten, also auch keinen Abruf."""
        user_id = await _regen_depot(db)
        seen = _patch_regen(monkeypatch, _fake_download(None, vusa_from=None), _raise)

        await regenerate_snapshots(db, user_id)

        assert seen == []
        assert await _last_total(db, user_id) == pytest.approx(1450.0, abs=0.01)
