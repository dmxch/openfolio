"""Vollreview 11/2026, Welle 3, Fixer «misc»: main.py, Markt, Buckets, ETF-Durchsicht.

K163 (Refresh-Fehler nur für Admins), K060 (Alerts lesen die Summary über den
geteilten Cache), K005 (Symbolsuche ohne Wiederholung), K139 (Krypto-Metriken
intern), GF05 (Benchmark und Ziel leeren), K094 verfeinert (fehlende ISIN ist
kein Konflikt), K095 (FMP-Key für den ETF-Refresh), PurchaseDate in
api/validation, Annotated-Falle bei Query- und Path-Parametern.
"""

from __future__ import annotations

import asyncio
import inspect
import typing
import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import APIRouter, Query
from fastapi import params as fastapi_params
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from sqlalchemy import select, update
from starlette.requests import Request as StarletteRequest

import api.buckets as buckets_api
import api.imports as imports_api
import api.market as market_api
import services.etf_holdings_service as eh
from api.auth import limiter
from api.validation import PURCHASE_DATE_ERROR, MarketTicker, PurchaseDate
from dateutils import utcnow
from models.bucket import Bucket
from models.position import AssetType, Position, PriceSource
from models.user import User, UserSettings
from services import api_utils, cache
from services.auth_service import encrypt_value
from services.bucket_service import create_bucket, create_system_buckets, update_bucket

TEST_PASSWORD = "TestPassw0rd!2026"


async def _login(client, email: str) -> dict[str, str]:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _request() -> StarletteRequest:
    return StarletteRequest({
        "type": "http", "method": "GET", "path": "/", "headers": [], "client": ("10.0.0.9", 1234),
    })


async def _make_user(db, *, is_admin: bool = False) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x", is_admin=is_admin)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await create_system_buckets(db, user.id)
    await db.commit()
    return user


async def _add_etf(db, user_id, ticker: str, *, name: str, isin: str | None = None) -> Position:
    bucket = (await db.execute(
        select(Bucket).where(Bucket.user_id == user_id).order_by(Bucket.sort_order)
    )).scalars().first()
    pos = Position(
        user_id=user_id, bucket_id=bucket.id, ticker=ticker, name=name, type=AssetType.etf,
        currency="USD", price_source=PriceSource.yahoo, isin=isin,
        shares=Decimal("10"), cost_basis_chf=Decimal("1500"),
    )
    db.add(pos)
    await db.commit()
    return pos


# --- K163: Refresh-Status -----------------------------------------------------


class TestCacheStatus:
    STATE = {
        "refreshing": False, "status": "error", "last_refresh": "2026-11-13T10:00:00Z",
        "errors": ["yahoo: HTTPStatusError", "db: DBAPIError"],
    }

    async def test_errors_are_hidden_from_normal_users(self, client, monkeypatch):
        monkeypatch.setattr("services.cache_service.get_refresh_state", AsyncMock(return_value=dict(self.STATE)))
        headers = await _login(client, "status-user@example.com")
        res = await client.get("/api/cache/status", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["errors"] == []
        assert body["status"] == "error"  # der Zustand selbst bleibt sichtbar
        assert isinstance(body["age_minutes"], int)

    async def test_admin_sees_the_errors(self, client, db, monkeypatch):
        monkeypatch.setattr("services.cache_service.get_refresh_state", AsyncMock(return_value=dict(self.STATE)))
        headers = await _login(client, "status-admin@example.com")
        await db.execute(update(User).where(User.email == "status-admin@example.com").values(is_admin=True))
        await db.commit()
        res = await client.get("/api/cache/status", headers=headers)
        assert res.json()["errors"] == self.STATE["errors"]

    async def test_state_without_errors_gets_an_empty_list(self, client, monkeypatch):
        monkeypatch.setattr(
            "services.cache_service.get_refresh_state", AsyncMock(return_value={"refreshing": False}),
        )
        headers = await _login(client, "status-empty@example.com")
        assert (await client.get("/api/cache/status", headers=headers)).json()["errors"] == []


# --- K060: Alerts lesen über den geteilten Summary-Cache ----------------------


class TestAlertsSummary:
    async def test_alerts_route_uses_the_cached_summary(self, client, db, monkeypatch):
        cached = AsyncMock(return_value={"positions": []})
        raw = AsyncMock(return_value={"positions": []})
        monkeypatch.setattr("services.portfolio_service.get_portfolio_summary_cached", cached)
        monkeypatch.setattr("services.portfolio_service.get_portfolio_summary", raw)
        monkeypatch.setattr("services.market_analyzer.get_market_climate", lambda: {"status": "bullish"})
        monkeypatch.setattr(
            "services.bucket_performance_service.get_allocations_by_bucket", AsyncMock(return_value=[]),
        )
        headers = await _login(client, "alerts-cache@example.com")

        res = await client.get("/api/alerts", headers=headers)

        assert res.status_code == 200, res.text
        assert cached.await_count == 1
        raw.assert_not_awaited()  # kein zweiter Schreiber neben get_portfolio_summary_cached

    def test_main_no_longer_carries_its_own_cache_block(self):
        import main

        source = inspect.getsource(main.get_alerts)
        assert "_SUMMARY_TTL" not in source
        assert "app_cache.set" not in source


# --- K005: Abruf ohne Wiederholung --------------------------------------------


class _FailingClient:
    def __init__(self, status: int):
        self.status = status
        self.calls = 0

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        request = httpx.Request("GET", url)
        return httpx.Response(self.status, request=request, json={"ok": self.status == 200})


class TestFetchJsonOnce:
    @pytest.mark.parametrize("status", [429, 500, 503])
    async def test_transient_error_is_not_retried(self, monkeypatch, status):
        """fetch_json wiederholt 429 und 5xx bis dreimal und hielt so einen Yahoo-Slot besetzt."""
        client = _FailingClient(status)
        monkeypatch.setattr(api_utils, "get_async_client", lambda: client)
        with pytest.raises(httpx.HTTPStatusError):
            await api_utils.fetch_json_once("https://example.org/x")
        assert client.calls == 1

    async def test_success_returns_the_json(self, monkeypatch):
        client = _FailingClient(200)
        monkeypatch.setattr(api_utils, "get_async_client", lambda: client)
        assert await api_utils.fetch_json_once("https://example.org/x", params={"q": "a"}) == {"ok": True}

    def test_symbol_search_uses_the_single_attempt(self):
        import main

        source = inspect.getsource(main.search_symbols)
        assert "fetch_json_once(" in source
        assert "await fetch_json(" not in source


# --- K139: Krypto-Metriken intern ----------------------------------------------


@pytest.fixture
def crypto_sources(monkeypatch):
    cache.delete("crypto_metrics")
    cache._key_locks.pop("crypto_metrics", None)
    coingecko = AsyncMock()
    plain = AsyncMock(return_value={"data": [{"value": "61", "value_classification": "Greed"}]})

    async def _coingecko(url, params=None, timeout=15):
        await asyncio.sleep(0.01)  # der erste Request hält die Sperre, während die anderen ankommen
        await coingecko(url)
        if url.endswith("/global"):
            return {"data": {"market_cap_percentage": {"btc": 56.44}}}
        return {"market_data": {"ath": {"chf": 100000.0}, "current_price": {"chf": 80000.0}}}

    monkeypatch.setattr("services.api_utils.fetch_json_coingecko", _coingecko)
    monkeypatch.setattr("services.api_utils.fetch_json", plain)
    monkeypatch.setattr(
        "services.price_service.get_stock_price", lambda ticker: {"price": 104.2, "change_pct": 0.3},
    )
    ttls: list[int] = []
    real_set = cache.set

    def _spy(key, value, ttl=cache.DEFAULT_TTL):
        if key == "crypto_metrics":
            ttls.append(ttl)
        return real_set(key, value, ttl)

    monkeypatch.setattr(cache, "set", _spy)
    monkeypatch.setattr(limiter, "enabled", False)
    yield SimpleNamespace(coingecko=coingecko, plain=plain, ttls=ttls)
    cache.delete("crypto_metrics")
    cache._key_locks.pop("crypto_metrics", None)


class TestInternalCryptoMetrics:
    async def test_cold_cache_fetches_once_for_parallel_requests(self, crypto_sources):
        results = await asyncio.gather(*[
            market_api.crypto_metrics(request=_request(), user=None) for _ in range(8)
        ])
        assert crypto_sources.coingecko.await_count == 2  # /global und /coins/bitcoin, je einmal
        assert crypto_sources.plain.await_count == 1
        assert all(r == results[0] for r in results)
        assert results[0]["tier1"]["btc_dominance"] == 56.4
        assert results[0]["tier2"]["btc_ath_distance_pct"] == -20.0
        assert crypto_sources.ttls == [900]

    async def test_coingecko_goes_through_the_rate_limited_fetch(self, crypto_sources):
        await market_api.crypto_metrics(request=_request(), user=None)
        plain_urls = [call.args[0] for call in crypto_sources.plain.await_args_list]
        assert plain_urls == ["https://api.alternative.me/fng/?limit=1"]

    async def test_partial_result_is_cached_only_briefly(self, crypto_sources, monkeypatch):
        async def _failing(url, params=None, timeout=15):
            raise RuntimeError("429 Too Many Requests")

        monkeypatch.setattr("services.api_utils.fetch_json_coingecko", _failing)
        result = await market_api.crypto_metrics(request=_request(), user=None)
        assert crypto_sources.ttls == [60]
        assert "btc_dominance" not in result["tier1"]
        assert result["tier1"]["fear_greed_value"] == 61

    async def test_empty_fear_and_greed_list_is_no_error(self, crypto_sources):
        """fng_data.get("data", [{}])[0] warf bei leerer Liste IndexError (500)."""
        crypto_sources.plain.return_value = {"data": []}
        result = await market_api.crypto_metrics(request=_request(), user=None)
        assert "fear_greed_value" not in result["tier1"]
        assert result["tier1"]["btc_dominance"] == 56.4

    async def test_internal_and_external_route_share_one_entry(self, crypto_sources):
        import api.external_v1 as ext

        internal = await market_api.crypto_metrics(request=_request(), user=None)
        external = await ext.market_crypto_metrics_external(request=_request(), _user=None)
        assert external == internal
        assert crypto_sources.coingecko.await_count == 2  # der zweite Aufruf kam aus dem Cache


# --- GF05: Benchmark und Ziel leeren ------------------------------------------


class TestBucketClearing:
    async def _bucket(self, client, headers, **fields) -> dict:
        res = await client.post("/api/portfolio/buckets", json={"name": "Wachstum", **fields}, headers=headers)
        assert res.status_code == 201, res.text
        return res.json()

    async def test_patch_clears_benchmark_and_target(self, client):
        headers = await _login(client, "gf05a@example.com")
        bucket = await self._bucket(client, headers, benchmark="^GSPC", target_pct=40)
        assert bucket["benchmark"] == "^GSPC" and bucket["target_pct"] == 40

        res = await client.patch(
            f"/api/portfolio/buckets/{bucket['id']}",
            json={"benchmark": "", "target_pct": None, "target_chf": None},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["benchmark"] is None
        assert body["target_pct"] is None
        assert body["target_chf"] is None

        stored = (await client.get(f"/api/portfolio/buckets/{bucket['id']}", headers=headers)).json()
        assert (stored["benchmark"], stored["target_pct"], stored["target_chf"]) == (None, None, None)

    async def test_patch_clears_a_chf_target(self, client):
        headers = await _login(client, "gf05b@example.com")
        bucket = await self._bucket(client, headers, target_chf=25000)
        res = await client.patch(
            f"/api/portfolio/buckets/{bucket['id']}",
            json={"target_pct": None, "target_chf": None}, headers=headers,
        )
        assert res.json()["target_chf"] is None

    async def test_omitted_or_single_null_fields_change_nothing(self, client):
        """None bleibt «nicht ändern»: nur beide Zielfelder ausdrücklich als null leeren das Ziel."""
        headers = await _login(client, "gf05c@example.com")
        bucket = await self._bucket(client, headers, benchmark="^GSPC", target_pct=40)
        url = f"/api/portfolio/buckets/{bucket['id']}"

        for payload in ({"name": "Umbenannt"}, {"target_pct": None}, {"target_chf": None}, {"benchmark": None}):
            res = await client.patch(url, json=payload, headers=headers)
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["benchmark"] == "^GSPC"
            assert body["target_pct"] == 40

    async def test_switching_the_target_type_still_works(self, client):
        headers = await _login(client, "gf05d@example.com")
        bucket = await self._bucket(client, headers, target_pct=40)
        res = await client.patch(
            f"/api/portfolio/buckets/{bucket['id']}",
            json={"target_pct": None, "target_chf": 10000}, headers=headers,
        )
        body = res.json()
        assert body["target_pct"] is None and body["target_chf"] == 10000

    async def test_unknown_benchmark_is_still_rejected(self, client):
        headers = await _login(client, "gf05e@example.com")
        bucket = await self._bucket(client, headers)
        res = await client.patch(
            f"/api/portfolio/buckets/{bucket['id']}", json={"benchmark": "NOPE"}, headers=headers,
        )
        assert res.status_code == 400

    async def test_service_clear_target(self, db):
        user = await _make_user(db)
        bucket = await create_bucket(db, user.id, name="Ziel", target_chf=5000, benchmark="^GSPC")
        await db.commit()

        await update_bucket(db, user.id, bucket.id, clear_target=True)
        assert bucket.target_chf is None and bucket.target_pct is None
        assert bucket.benchmark == "^GSPC"

        await update_bucket(db, user.id, bucket.id, benchmark="")
        assert bucket.benchmark is None

        await update_bucket(db, user.id, bucket.id, target_pct=30)
        await update_bucket(db, user.id, bucket.id)  # ohne Argumente: nichts ändert sich
        assert float(bucket.target_pct) == 30


# --- K094 verfeinert: fehlende ISIN ist kein Konflikt -------------------------


class TestEtfRefIsinInheritance:
    ISIN = "IE00BJ0KDQ92"

    async def test_missing_isin_of_one_user_takes_the_existing_one(self, db):
        """Vorher: ein Nutzer ohne ISIN, und alle sahen veraltete Holdings."""
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, a.id, "XDWD.DE", name="Xtrackers MSCI World", isin=self.ISIN)
        await _add_etf(db, b.id, "XDWD.DE", name="XTRACKERS MSCI WORLD UCITS ETF 1C")

        with patch.object(eh.logger, "warning") as warn:
            refs = await eh._get_active_etf_refs(db)

        assert [r.ticker for r in refs] == ["XDWD.DE"]
        # Egal welcher Nutzer zuerst sortiert: der Ref trägt die ISIN für den Abruf.
        assert refs[0].isin_valid == self.ISIN
        assert eh.get_adapter(refs[0]).name == eh.get_adapter(
            eh.EtfRef("XDWD.DE", self.ISIN, "Xtrackers MSCI World")
        ).name
        warn.assert_not_called()

    async def test_ref_carries_the_isin_whoever_sorts_first(self, db):
        users = [await _make_user(db) for _ in range(2)]
        first, second = sorted(users, key=lambda u: str(u.id))
        # Der Nutzer OHNE ISIN sortiert zuerst.
        await _add_etf(db, first.id, "XDWD.DE", name="Xtrackers MSCI World")
        await _add_etf(db, second.id, "XDWD.DE", name="Xtrackers MSCI World", isin=self.ISIN)
        refs = await eh._get_active_etf_refs(db)
        assert len(refs) == 1 and refs[0].isin_valid == self.ISIN

    async def test_two_different_isins_stay_a_conflict(self, db):
        """Welle 5: der Konflikt bleibt gemeldet, die älteste ISIN gewinnt aber."""
        a, b, c = [await _make_user(db) for _ in range(3)]
        await _add_etf(db, a.id, "XDWD.DE", name="Xtrackers MSCI World", isin=self.ISIN)
        await _add_etf(db, b.id, "XDWD.DE", name="Xtrackers MSCI World", isin="LU0274209740")
        await _add_etf(db, c.id, "XDWD.DE", name="Xtrackers MSCI World")
        with patch.object(eh.logger, "warning") as warn:
            refs = await eh._get_active_etf_refs(db)
        assert [r.isin_valid for r in refs] == [self.ISIN]
        assert warn.call_count == 1

    async def test_different_adapter_stays_a_conflict_despite_inherited_isin(self, db):
        """Die geerbte ISIN ändert nichts daran, dass die Namen verschiedene Quellen wählen.

        Welle 5: die ältere Position gewinnt. Die ISIN der jüngeren gehört zu
        einem anderen Anbieter und wird deshalb nicht für den Abruf übernommen.
        """
        victim = await _make_user(db)
        attacker = await _make_user(db)
        await _add_etf(db, victim.id, "LYX0.DE", name="Amundi MSCI World")
        await _add_etf(db, attacker.id, "LYX0.DE", name="Xtrackers MSCI Japan", isin="LU0274209740")
        refs, conflicts = await eh._resolve_active_etf_refs(db)
        assert [(r.name, r.isin) for r in refs] == [("Amundi MSCI World", None)]
        assert eh.get_adapter(refs[0]) is None
        assert conflicts == [{
            "etf_ticker": "LYX0.DE", "positions": 2,
            "chosen": {"source": "Amundi", "isin": None},
            "rejected": [{"source": "Xtrackers", "isin": "LU0274209740"}],
        }]

    async def test_position_without_isin_and_brand_does_not_block_the_ticker(self, db):
        """Welle 5, Zwischenregel: eine Position ohne ISIN und ohne Markennamen eines
        Adapters zählt nicht mit. Der Ticker fällt deshalb nicht aus.

        Restrisiko (K094): trägt noch niemand eine ISIN, bestimmt die erste
        Position mit ISIN die Quelle für alle ohne ISIN.
        """
        first = await _make_user(db)
        second = await _make_user(db)
        await _add_etf(db, first.id, "VWRA.L", name="Vanguard FTSE All-World")
        await _add_etf(db, second.id, "VWRA.L", name="Xtrackers MSCI Japan", isin="LU0274209740")
        refs, conflicts = await eh._resolve_active_etf_refs(db)
        assert [(r.ticker, r.isin) for r in refs] == [("VWRA.L", "LU0274209740")]
        assert conflicts == []

    async def test_no_isin_anywhere_is_unchanged(self, db):
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, a.id, "VOO", name="Vanguard S&P 500")
        await _add_etf(db, b.id, "VOO", name="VANGUARD S&P 500 ETF")
        refs = await eh._get_active_etf_refs(db)
        assert [(r.ticker, r.isin) for r in refs] == [("VOO", None)]


# --- K095: FMP-Key für den ETF-Refresh -----------------------------------------


class TestEtfRefreshKey:
    async def test_key_of_a_normal_user_never_feeds_the_global_refresh(self, db, monkeypatch):
        monkeypatch.setattr("config.settings.fmp_system_api_key", "")
        user = await _make_user(db)
        await db.execute(
            update(UserSettings).where(UserSettings.user_id == user.id)
            .values(fmp_api_key=encrypt_value("user-key"))
        )
        await db.commit()
        assert await eh._get_any_user_fmp_key(db) is None

    async def test_admin_key_is_used_without_a_system_key(self, db, monkeypatch):
        monkeypatch.setattr("config.settings.fmp_system_api_key", "")
        admin = await _make_user(db, is_admin=True)
        await db.execute(
            update(UserSettings).where(UserSettings.user_id == admin.id)
            .values(fmp_api_key=encrypt_value("admin-key"))
        )
        await db.commit()
        assert await eh._get_any_user_fmp_key(db) == "admin-key"

    async def test_system_key_wins(self, db, monkeypatch):
        monkeypatch.setattr("config.settings.fmp_system_api_key", "system-key")
        admin = await _make_user(db, is_admin=True)
        await db.execute(
            update(UserSettings).where(UserSettings.user_id == admin.id)
            .values(fmp_api_key=encrypt_value("admin-key"))
        )
        await db.commit()
        assert await eh._get_any_user_fmp_key(db) == "system-key"


# --- PurchaseDate in api/validation ---------------------------------------------


class _Purchase(BaseModel):
    d: PurchaseDate


class TestPurchaseDate:
    def test_bounds(self):
        today = utcnow().date()
        assert _Purchase(d=date(1900, 1, 1)).d == date(1900, 1, 1)
        assert _Purchase(d="1955-06-30").d == date(1955, 6, 30)  # vor 1970 erlaubt, anders als BookingDate
        assert _Purchase(d=today + timedelta(days=1)).d == today + timedelta(days=1)
        for bad in (date(1899, 12, 31), today + timedelta(days=2)):
            with pytest.raises(ValidationError) as exc:
                _Purchase(d=bad)
            assert PURCHASE_DATE_ERROR in str(exc.value)

    def test_same_bounds_and_text_as_the_definition_in_real_estate(self):
        import api.real_estate as real_estate
        import api.validation as validation

        assert validation.MIN_PURCHASE_DATE == real_estate.MIN_PURCHASE_DATE
        assert validation.PURCHASE_DATE_ERROR == real_estate.PURCHASE_DATE_ERROR


# --- Annotated-Falle -------------------------------------------------------------


def _annotated_trap_offenders(routes) -> list[str]:
    """Parameter der Form «x: Annotated[T, Constraint] = Query(...)».

    FastAPI setzt bei einem FieldInfo als Default die Annotation auf den
    Basistyp: die Einschränkung aus dem Annotated-Alias (MarketTicker,
    CurrencyCode, BookingDate, PurchaseDate) fiele still weg.
    """
    offenders = []
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        hints = typing.get_type_hints(route.endpoint, include_extras=True)
        for name, param in inspect.signature(route.endpoint).parameters.items():
            annotation = hints.get(name)
            if typing.get_origin(annotation) is not typing.Annotated:
                continue
            if not isinstance(param.default, FieldInfo) or isinstance(param.default, fastapi_params.Depends):
                continue
            extras = typing.get_args(annotation)[1:]
            if any(not isinstance(m, (FieldInfo, fastapi_params.Depends)) for m in extras):
                offenders.append(f"{route.endpoint.__module__}.{route.endpoint.__name__}({name})")
    return offenders


class TestAnnotatedParams:
    def test_helper_detects_the_trap(self):
        router = APIRouter()

        @router.get("/bad")
        async def bad(ticker: MarketTicker = Query(...)):
            return ticker

        @router.get("/good")
        async def good(ticker: typing.Annotated[MarketTicker, Query()], plain: str = Query("", max_length=3)):
            return ticker

        offenders = _annotated_trap_offenders(router.routes)
        assert len(offenders) == 1 and offenders[0].endswith("bad(ticker)")

    def test_no_route_of_the_four_modules_loses_its_constraint(self):
        import main

        routes = [
            *market_api.router.routes,
            *imports_api.router.routes,
            *buckets_api.router.routes,
            *[r for r in main.app.routes if isinstance(r, APIRoute) and r.endpoint.__module__ == "main"],
        ]
        assert len(routes) > 30
        assert _annotated_trap_offenders(routes) == []

    @pytest.mark.parametrize("path", [
        "/api/market/fx/us1", "/api/market/fx/USDX", "/api/market/fx/USD?to_currency=c1f",
        "/api/market/fx/USD?to_currency=CHFX",
    ])
    async def test_currency_constraint_applies_to_path_and_query(self, client, monkeypatch, path):
        called = []
        monkeypatch.setattr("services.utils.get_fx_rate", lambda a, b: called.append((a, b)) or 1.0)
        headers = await _login(client, f"fx-{uuid.uuid4().hex[:6]}@example.com")
        res = await client.get(path, headers=headers)
        assert res.status_code == 422
        assert called == []

    async def test_valid_currency_is_uppercased(self, client, monkeypatch):
        called = []
        monkeypatch.setattr("services.utils.get_fx_rate", lambda a, b: called.append((a, b)) or 0.9)
        headers = await _login(client, "fx-ok@example.com")
        res = await client.get("/api/market/fx/usd?to_currency=chf", headers=headers)
        assert res.status_code == 200
        assert called == [("USD", "CHF")]
