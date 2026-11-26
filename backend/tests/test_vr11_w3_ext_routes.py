"""Vollreview 11/2026, Welle 3, externe API: Übergaben für api/external_v1.py.

K093 (Holdings je Nutzer), K146 und K013 (kurze TTL bei Lücken), K039
(Versionsmarke im Cache-Schlüssel), K060 und K012 (Summary aus dem Cache),
K019 und K125 (24h-Change), K162 (Notizen der Pending Orders), GS11
(Alarm-Limit), K021 (ein Scan zur selben Zeit), K080 (Regen nach Import),
K010 (Import-Vorschau), K059 (Ticker-Pool), GF05 (Bucket-Felder leeren),
K119 (summary der Transaktionsliste), X02 (Limits für ID-Routen) und die
Annotated-Falle bei Pfad- und Query-Parametern.
"""

import asyncio
import typing
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Query
from fastapi.responses import Response
from fastapi.routing import APIRoute
from limits import parse as parse_limit
from sqlalchemy import func, select, update

import api.external_v1 as ext
import api.screening as api_screening
from api.auth import limiter
from api.validation import MARKET_TICKER_PATTERN, MarketTicker
from constants.limits import RL_HEAVY, RL_READ
from models.api_write_log import ApiWriteLog
from models.pending_order import PendingOrder
from models.position import Position
from models.price_alert import PriceAlert
from models.screening import ScreeningScan
from models.transaction import Transaction, TransactionType
from models.user import User
from services import cache
from services.encryption_helpers import decrypt_field
from services.import_service import ImportPreview
from services.screening import screening_service as ss
from tests.test_external_ui_parity import api_auth, jwt_auth, make_token, register_and_login, rw_tokens
from tests.test_external_v1_correlation import _MOCK_RESPONSE as CORRELATION

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/external"
TODAY = date.today().isoformat()


async def _user_id(db, email: str) -> uuid.UUID:
    return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _log_actions(db, email: str) -> list[str]:
    rows = await db.execute(
        select(ApiWriteLog.action).where(ApiWriteLog.user_id == await _user_id(db, email))
    )
    return [r[0] for r in rows]


async def _new_position(client, token: str, ticker: str, **extra) -> str:
    # cost_basis_chf=0: kein Snapshot-Regen im Hintergrund.
    body = {"ticker": ticker, "name": ticker, "type": "stock", "currency": "CHF",
            "shares": 1, "cost_basis_chf": 0, **extra}
    res = await client.post(f"{BASE}/positions", json=body, headers=api_auth(token))
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _summary(*positions: dict) -> dict:
    return {"positions": list(positions), "total_market_value_chf": 0.0, "allocations": {}}


def _external_routes() -> list[APIRoute]:
    return [r for r in ext.router.routes if isinstance(r, APIRoute)]


def _limits_of(func_name: str) -> list:
    return [lim.limit for lim in limiter._route_limits.get(f"api.external_v1.{func_name}", [])]


@pytest.fixture
def cache_sets(monkeypatch):
    """Zeichnet (Schlüssel, TTL) jedes cache.set auf und schreibt weiter in den Cache."""
    calls: list[tuple[str, int]] = []
    real_set = cache.set

    def _set(key, value, ttl=cache.DEFAULT_TTL):
        calls.append((key, ttl))
        real_set(key, value, ttl=ttl)

    monkeypatch.setattr(cache, "set", _set)
    return calls


# --- K093: Sektor-Holdings nur für den Nutzer des Keys ---


class TestSectorHoldings:
    async def test_route_passes_the_token_owner_to_the_service(self, client, db, monkeypatch):
        """Ohne user_id lieferte der Service für in_portfolio und in_watchlist immer False."""
        email = "w3-k093@example.com"
        _, r = await rw_tokens(client, email)
        service = AsyncMock(return_value={"etf": "XLK", "holdings": []})
        monkeypatch.setattr("services.sector_analyzer.get_sector_holdings", service)
        res = await client.get(f"{BASE}/market/sectors/xlk/holdings", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert service.await_args.args[0] == "XLK"
        assert service.await_args.kwargs == {"user_id": await _user_id(db, email)}

    async def test_unknown_etf_is_still_404(self, client, monkeypatch):
        _, r = await rw_tokens(client, "w3-k093-404@example.com")
        monkeypatch.setattr("services.sector_analyzer.get_sector_holdings", AsyncMock(return_value=None))
        res = await client.get(f"{BASE}/market/sectors/NOPE/holdings", headers=api_auth(r))
        assert res.status_code == 404


# --- K146 und K013: unvollständige Resultate bleiben nur kurz im Cache ---


class TestShortTtlForPartialResults:
    @pytest.fixture(autouse=True)
    def _clear_macro(self):
        cache.delete("external:macro:ch:v1")
        yield
        cache.delete("external:macro:ch:v1")

    @pytest.mark.parametrize("snapshot, ttl", [
        ({"snb": {}, "warnings": ["saron_unavailable"]}, 600),
        ({"snb": {}, "warnings": []}, 21600),
    ])
    async def test_ch_macro_snapshot_with_warnings_is_cached_ten_minutes(
        self, client, monkeypatch, cache_sets, snapshot, ttl,
    ):
        """Die Route schrieb unter dem geteilten Schlüssel immer 6 Stunden."""
        _, r = await rw_tokens(client, f"w3-k146-{ttl}@example.com")
        monkeypatch.setattr(ext, "get_ch_macro_snapshot", AsyncMock(return_value=snapshot))
        res = await client.get(f"{BASE}/macro/ch", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert ("external:macro:ch:v1", ttl) in cache_sets

    @pytest.mark.parametrize("warnings, ttl", [
        (["earnings_fetch_failed:AAPL"], 300),
        (["no_earnings_in_window:AAPL"], 43200),
    ])
    async def test_upcoming_earnings_with_failed_fetch_is_cached_five_minutes(
        self, client, monkeypatch, cache_sets, warnings, ttl,
    ):
        _, r = await rw_tokens(client, f"w3-k013-{ttl}@example.com")
        data = {"as_of": TODAY, "window_days": 7, "earnings": [], "warnings": warnings}
        monkeypatch.setattr(ext, "get_upcoming_earnings_for_portfolio", AsyncMock(return_value=data))
        res = await client.get(f"{BASE}/portfolio/upcoming-earnings", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert [t for key, t in cache_sets if key.startswith("external:upcoming_earnings:")] == [ttl]


# --- K039: Versionsmarke im Cache-Schlüssel ---


class TestCacheVersionMarker:
    async def _tokens(self, client, email: str) -> tuple[str, str]:
        jwt = await register_and_login(client, email)
        return jwt, await make_token(client, jwt, name="r", write=False)

    async def test_correlation_is_recomputed_after_a_portfolio_change(self, client, db, monkeypatch):
        """Ohne Marke blieb die Matrix nach einer Buchung bis zu 24 Stunden alt."""
        from api.portfolio import invalidate_portfolio_cache

        email = "w3-k039-corr@example.com"
        _, r = await self._tokens(client, email)
        compute = AsyncMock(return_value=CORRELATION)
        monkeypatch.setattr(ext, "compute_correlation_matrix", compute)
        url = f"{BASE}/analysis/correlation-matrix"
        assert (await client.get(url, headers=api_auth(r))).status_code == 200
        assert (await client.get(url, headers=api_auth(r))).status_code == 200
        assert compute.await_count == 1
        invalidate_portfolio_cache(str(await _user_id(db, email)))
        assert (await client.get(url, headers=api_auth(r))).status_code == 200
        assert compute.await_count == 2

    async def test_correlation_shares_its_entry_with_the_internal_route_again(self, client, monkeypatch):
        """Seit Welle 2 trug nur die interne Route die Marke: beide rechneten getrennt."""
        jwt, r = await self._tokens(client, "w3-k039-shared@example.com")
        compute = AsyncMock(return_value=CORRELATION)
        monkeypatch.setattr(ext, "compute_correlation_matrix", compute)
        monkeypatch.setattr("api.portfolio.compute_correlation_matrix", compute)
        assert (await client.get(f"{BASE}/analysis/correlation-matrix", headers=api_auth(r))).status_code == 200
        res = await client.get("/api/portfolio/correlation-matrix", headers=jwt_auth(jwt))
        assert res.status_code == 200, res.text
        assert compute.await_count == 1

    async def test_upcoming_earnings_shares_its_entry_and_follows_the_marker(self, client, db, monkeypatch):
        from api.portfolio import invalidate_portfolio_cache

        email = "w3-k039-earn@example.com"
        jwt, r = await self._tokens(client, email)
        data = {"as_of": TODAY, "window_days": 7, "earnings": [], "warnings": []}
        fetch = AsyncMock(return_value=data)
        monkeypatch.setattr(ext, "get_upcoming_earnings_for_portfolio", fetch)
        monkeypatch.setattr("api.portfolio.get_upcoming_earnings_for_portfolio", fetch)
        assert (await client.get(f"{BASE}/portfolio/upcoming-earnings", headers=api_auth(r))).status_code == 200
        res = await client.get("/api/portfolio/upcoming-earnings", headers=jwt_auth(jwt))
        assert res.status_code == 200, res.text
        assert fetch.await_count == 1
        invalidate_portfolio_cache(str(await _user_id(db, email)))
        assert (await client.get(f"{BASE}/portfolio/upcoming-earnings", headers=api_auth(r))).status_code == 200
        assert fetch.await_count == 2

    async def test_bucket_correlation_is_recomputed_after_a_portfolio_change(self, client, db, monkeypatch):
        from api.portfolio import invalidate_portfolio_cache

        email = "w3-k039-bucket@example.com"
        _, r = await self._tokens(client, email)
        compute = AsyncMock(return_value={"buckets": [], "matrix": []})
        monkeypatch.setattr(
            "services.bucket_correlation_service.compute_bucket_correlation_matrix", compute,
        )
        url = f"{BASE}/buckets/correlation-matrix"
        assert (await client.get(url, headers=api_auth(r))).status_code == 200
        assert (await client.get(url, headers=api_auth(r))).status_code == 200
        assert compute.await_count == 1
        invalidate_portfolio_cache(str(await _user_id(db, email)))
        assert (await client.get(url, headers=api_auth(r))).status_code == 200
        assert compute.await_count == 2


# --- K060, K012, K019 und K125: Summary und 24h-Change ---


class TestSummaryFromCache:
    async def test_read_routes_use_the_cached_summary_and_leave_it_untouched(self, client, monkeypatch):
        """Die Anreicherung schrieb entschlüsselte PII in das Objekt, das der Cache allen liefert."""
        w, r = await rw_tokens(client, "w3-k060@example.com")
        pid = await _new_position(client, w, "W3PII", notes="geheim", bank_name="Hausbank")
        row = {"id": pid, "ticker": "W3PII", "name": "W3PII", "type": "stock"}
        shared = _summary(row)
        cached = AsyncMock(return_value=shared)
        monkeypatch.setattr(ext, "get_portfolio_summary_cached", cached)

        summary = await client.get(f"{BASE}/portfolio/summary", headers=api_auth(r))
        listing = await client.get(f"{BASE}/positions", headers=api_auth(r))
        single = await client.get(f"{BASE}/positions/w3pii", headers=api_auth(r))
        for res in (summary, listing, single):
            assert res.status_code == 200, res.text
        assert cached.await_count == 3

        for position in (summary.json()["positions"][0], listing.json()["positions"][0], single.json()):
            assert position["notes"] == "geheim"
            assert position["bank_name"] == "Hausbank"
            assert position["active_alerts"] == 0
        assert shared == _summary({"id": pid, "ticker": "W3PII", "name": "W3PII", "type": "stock"})
        assert row == {"id": pid, "ticker": "W3PII", "name": "W3PII", "type": "stock"}

    async def test_score_does_not_compute_a_second_summary(self, client, monkeypatch):
        """K012: Konzentration und Summary kommen aus einem Aufruf."""
        _, r = await rw_tokens(client, "w3-k012@example.com")
        monkeypatch.setattr(
            "services.scoring_service.assess_ticker",
            lambda *a, **kw: {"ticker": "AAPL", "score": 5, "max_score": 10, "price": 190.0},
        )
        combined = AsyncMock(return_value=({"single_name": {}}, {"total_market_value_chf": 1234.5}))
        monkeypatch.setattr("services.concentration_service.get_concentration_with_summary", combined)
        second = AsyncMock(side_effect=AssertionError("zweite Summary berechnet"))
        monkeypatch.setattr(ext, "get_portfolio_summary_cached", second)
        monkeypatch.setattr("services.portfolio_service.get_portfolio_summary", second)
        res = await client.get(f"{BASE}/analysis/score/AAPL", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert res.json()["liquid_portfolio_chf"] == 1234.5
        assert combined.await_count == 1


class TestChange24h:
    @pytest.fixture(autouse=True)
    def _clear_prices(self):
        keys = ("crypto:w3coin", "price:W3STK", "price:W3-USD", "price:W3YF.SW")
        for key in keys:
            cache.delete(key)
        yield
        for key in keys:
            cache.delete(key)

    async def test_coingecko_id_counts_only_for_crypto_positions(self, client, db, monkeypatch):
        """K019: eine coingecko_id auf einer Aktie zeigte die Tagesänderung des Coins."""
        w, r = await rw_tokens(client, "w3-k019@example.com")
        stock = await _new_position(client, w, "W3STK")
        coin = await _new_position(client, w, "W3-USD", type="crypto", coingecko_id="w3coin")
        # Altbestand: das Schema lehnt die ID auf einer Aktie heute ab.
        await db.execute(update(Position).where(Position.id == uuid.UUID(stock)).values(coingecko_id="w3coin"))
        await db.commit()
        cache.set("crypto:w3coin", {"change_pct": 9.9}, ttl=60)
        cache.set("price:W3STK", {"change_pct": 1.1}, ttl=60)
        monkeypatch.setattr(ext, "get_portfolio_summary_cached", AsyncMock(return_value=_summary(
            {"id": stock, "ticker": "W3STK"}, {"id": coin, "ticker": "W3-USD"},
        )))
        res = await client.get(f"{BASE}/positions", headers=api_auth(r))
        assert res.status_code == 200, res.text
        change = {p["ticker"]: p["change_pct_24h"] for p in res.json()["positions"]}
        assert change == {"W3STK": 1.1, "W3-USD": 9.9}

    async def test_prices_come_from_one_bulk_read(self, client, monkeypatch):
        """K125: je Position ein synchrones Redis-GET auf dem Event-Loop."""
        w, r = await rw_tokens(client, "w3-k125@example.com")
        a = await _new_position(client, w, "W3STK")
        b = await _new_position(client, w, "W3YF", yfinance_ticker="W3YF.SW")
        cache.set("price:W3YF.SW", {"change_pct": -2.5}, ttl=60)
        monkeypatch.setattr(ext, "get_portfolio_summary_cached", AsyncMock(return_value=_summary(
            {"id": a, "ticker": "W3STK"}, {"id": b, "ticker": "W3YF"},
        )))
        bulk: list[list[str]] = []
        single: list[str] = []
        real_get_many, real_get = cache.get_many, cache.get

        def _get_many(keys):
            bulk.append(sorted(keys))
            return real_get_many(keys)

        def _get(key):
            single.append(key)
            return real_get(key)

        monkeypatch.setattr(cache, "get_many", _get_many)
        monkeypatch.setattr(cache, "get", _get)
        res = await client.get(f"{BASE}/positions", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert bulk == [["price:W3STK", "price:W3YF.SW"]]
        assert not [k for k in single if k.startswith(("price:", "crypto:"))]
        change = {p["ticker"]: p["change_pct_24h"] for p in res.json()["positions"]}
        assert change == {"W3STK": None, "W3YF": -2.5}


# --- K162: Notizen der Pending Orders ---


class TestPendingOrderNotes:
    _ORDER = {"ticker": "AAPL", "side": "buy", "shares": 1, "limit_price": 100}

    async def _stored(self, db) -> str | None:
        db.expire_all()
        return (await db.execute(select(PendingOrder.notes))).scalar_one()

    async def test_notes_are_stored_encrypted_and_returned_as_plain_text(self, client, db):
        """Die externe Route schrieb Klartext, während die interne schon verschlüsselte."""
        w, r = await rw_tokens(client, "w3-k162@example.com")
        res = await client.post(
            f"{BASE}/pending-orders", json={**self._ORDER, "notes": "Limit nach Earnings"}, headers=api_auth(w),
        )
        assert res.status_code == 201, res.text
        assert res.json()["notes"] == "Limit nach Earnings"
        stored = await self._stored(db)
        assert stored != "Limit nach Earnings"
        assert decrypt_field(stored) == "Limit nach Earnings"

        patched = await client.patch(
            f"{BASE}/pending-orders/{res.json()['id']}", json={"notes": "neu gesetzt"}, headers=api_auth(w),
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["notes"] == "neu gesetzt"
        stored = await self._stored(db)
        assert stored != "neu gesetzt"
        assert decrypt_field(stored) == "neu gesetzt"

        listing = await client.get(f"{BASE}/pending-orders", headers=api_auth(r))
        assert [o["notes"] for o in listing.json()["items"]] == ["neu gesetzt"]

    async def test_cleared_notes_stay_null_and_old_plain_text_stays_readable(self, client, db):
        w, _ = await rw_tokens(client, "w3-k162-legacy@example.com")
        res = await client.post(f"{BASE}/pending-orders", json=self._ORDER, headers=api_auth(w))
        assert res.status_code == 201, res.text
        assert res.json()["notes"] is None
        assert await self._stored(db) is None

        # Zeile aus der Zeit vor der Verschlüsselung.
        await db.execute(update(PendingOrder).values(notes="alter Klartext"))
        await db.commit()
        patched = await client.patch(
            f"{BASE}/pending-orders/{res.json()['id']}", json={"limit_price": 101}, headers=api_auth(w),
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["notes"] == "alter Klartext"

        cleared = await client.patch(
            f"{BASE}/pending-orders/{res.json()['id']}", json={"notes": None}, headers=api_auth(w),
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["notes"] is None
        assert await self._stored(db) is None


# --- GS11: Alarm-Limit über alle Zeilen ---


class TestAlertLimit:
    async def test_triggered_alerts_count_towards_the_total_limit(self, client, db, monkeypatch):
        """Ausgelöste Alarme werden inaktiv und gaben ihren Platz wieder frei."""
        email = "w3-gs11@example.com"
        w, _ = await rw_tokens(client, email)
        monkeypatch.setattr(ext, "MAX_PRICE_ALERTS_PER_USER", 3)
        added = await client.post(f"{BASE}/watchlist", json={"ticker": "NVDA", "name": "Nvidia"}, headers=api_auth(w))
        assert added.status_code == 201, added.text
        user_id = await _user_id(db, email)
        for _ in range(2):
            db.add(PriceAlert(
                user_id=user_id, ticker="NVDA", alert_type="price_above", target_value=1,
                is_active=False, is_triggered=True,
            ))
        await db.commit()
        body = {"ticker": "NVDA", "alert_type": "price_above", "target_value": 500}

        third = await client.post(f"{BASE}/alerts", json=body, headers=api_auth(w))
        assert third.status_code == 201, third.text
        fourth = await client.post(f"{BASE}/alerts", json=body, headers=api_auth(w))
        assert fourth.status_code == 400
        assert fourth.json()["detail"] == (
            "Alarm-Limit erreicht (max. 3 Alarme inklusive ausgelöster). Bitte alte Alarme löschen."
        )
        total = (await db.execute(select(func.count()).select_from(PriceAlert))).scalar()
        assert total == 3

    async def test_limit_text_matches_the_internal_route(self):
        from constants.limits import MAX_PRICE_ALERTS_PER_USER

        assert ext.MAX_PRICE_ALERTS_PER_USER == MAX_PRICE_ALERTS_PER_USER == 500


# --- K021: ein Scan zur selben Zeit ---


class TestScreeningScan:
    @pytest.fixture(autouse=True)
    def _free_scan_lock(self):
        """Die Sperre lebt im Prozess (kein Redis im Test): vor und nach jedem Test frei."""
        ss.release_scan_lock()
        yield
        ss.release_scan_lock()

    async def test_second_start_answers_409_and_writes_no_log(self, client, db, monkeypatch):
        """Die Route legte bei laufendem Scan einen zweiten an; der endete sofort mit status error."""
        started: list[tuple] = []

        async def fake_background(scan_id, lock_held=False):
            started.append((scan_id, lock_held))  # Scan «läuft»: die Sperre bleibt gehalten

        monkeypatch.setattr(api_screening, "_run_scan_background", fake_background)
        email = "w3-k021@example.com"
        w, _ = await rw_tokens(client, email)

        first = await client.post(f"{BASE}/screening/scan", headers=api_auth(w))
        assert first.status_code == 201, first.text
        scan_id = first.json()["scan_id"]
        assert first.json() == {"scan_id": scan_id, "status": "pending"}

        second = await client.post(f"{BASE}/screening/scan", headers=api_auth(w))
        assert second.status_code == 409
        assert second.json() == {"detail": ss.SCAN_BUSY_MESSAGE, "scan_id": scan_id}

        assert started == [(uuid.UUID(scan_id), True)]
        assert (await db.execute(select(func.count()).select_from(ScreeningScan))).scalar() == 1
        assert (await _log_actions(db, email)).count("screening_scan") == 1

    async def test_scan_started_in_the_ui_blocks_the_external_route(self, client, monkeypatch):
        async def fake_background(scan_id, lock_held=False):
            return None

        monkeypatch.setattr(api_screening, "_run_scan_background", fake_background)
        jwt = await register_and_login(client, "w3-k021-ui@example.com")
        w = await make_token(client, jwt, name="w", write=True)
        internal = await client.post("/api/screening/scan", headers=jwt_auth(jwt))
        assert internal.status_code == 200, internal.text
        res = await client.post(f"{BASE}/screening/scan", headers=api_auth(w))
        assert res.status_code == 409
        assert res.json()["scan_id"] == internal.json()["scan_id"]


# --- K080: Snapshot-Regen nach dem Import ---


class TestImportConfirmRegen:
    def _body(self) -> dict:
        row = {"type": "buy", "ticker": "AAPL", "shares": 1, "price_per_share": 10, "total_chf": 10}
        return {"transactions": [
            {**row, "date": "2026-03-02"},
            {**row, "date": "2026-01-15"},
            {**row, "date": "2025-12-01", "is_duplicate": True},
        ]}

    def _patch(self, monkeypatch, created: int) -> tuple[MagicMock, AsyncMock]:
        monkeypatch.setattr(
            "services.import_service.confirm_import",
            AsyncMock(return_value={"created_transactions": created}),
        )
        monkeypatch.setattr("services.recalculate_service.recalculate_all_positions", AsyncMock(return_value=[]))
        trigger = MagicMock()
        direct = AsyncMock(side_effect=AssertionError("regenerate_snapshots direkt gestartet"))
        monkeypatch.setattr("services.snapshot_trigger.trigger_snapshot_regen", trigger)
        monkeypatch.setattr("services.snapshot_service.regenerate_snapshots", direct)
        return trigger, direct

    async def test_regen_goes_through_the_guarded_trigger_from_the_oldest_new_date(self, client, db, monkeypatch):
        """Der direkt gestartete Task lief neben einem zweiten Regen desselben Nutzers."""
        email = "w3-k080@example.com"
        w, _ = await rw_tokens(client, email)
        trigger, direct = self._patch(monkeypatch, created=2)
        res = await client.post(f"{BASE}/import/confirm", json=self._body(), headers=api_auth(w))
        assert res.status_code == 201, res.text
        assert res.json() == {"created_transactions": 2, "recalculated_positions": 0}
        await asyncio.sleep(0)
        trigger.assert_called_once_with(await _user_id(db, email), date(2026, 1, 15))
        assert direct.await_count == 0

    async def test_import_without_new_transactions_starts_no_regen(self, client, monkeypatch):
        w, _ = await rw_tokens(client, "w3-k080-none@example.com")
        trigger, direct = self._patch(monkeypatch, created=0)
        res = await client.post(f"{BASE}/import/confirm", json=self._body(), headers=api_auth(w))
        assert res.status_code == 201, res.text
        await asyncio.sleep(0)
        trigger.assert_not_called()
        assert direct.await_count == 0


# --- K010: Import-Vorschau ohne jsonable_encoder ---


class TestImportPreviewResponse:
    def _preview(self) -> ImportPreview:
        return ImportPreview(
            source_type="generic", filename="x.csv", total_rows=0, transactions=[],
            new_positions=[{"ticker": "AAPL"}], warnings=["Zeile 3: Datum fehlt"],
        )

    async def test_model_is_serialised_by_pydantic(self):
        preview = self._preview()
        res = ext._import_preview_response(preview)
        assert isinstance(res, Response)
        assert res.media_type == "application/json"
        assert res.body == preview.model_dump_json().encode()

    async def test_other_values_pass_through(self):
        assert ext._import_preview_response({"total_rows": 0}) == {"total_rows": 0}

    async def test_parse_route_returns_the_same_json_as_before(self, client, db, monkeypatch):
        email = "w3-k010@example.com"
        w, _ = await rw_tokens(client, email)
        preview = self._preview()
        monkeypatch.setattr("services.import_service.parse_csv", AsyncMock(return_value=preview))
        res = await client.post(
            f"{BASE}/import/parse", headers=api_auth(w),
            files={"file": ("x.csv", b"date;type\n2026-01-01;buy\n", "text/csv")},
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/json"
        assert res.json() == preview.model_dump(mode="json")
        assert "import_parse" in await _log_actions(db, email)


# --- K059: Ticker-Abrufe im eigenen Pool ---


class TestTickerPool:
    @pytest.fixture
    def pool(self, monkeypatch):
        used: list = []

        async def _yf_to_thread(func, *args, **kwargs):
            used.append(func)
            return func(*args, **kwargs)

        monkeypatch.setattr(ext, "yf_to_thread", _yf_to_thread)
        return used

    async def test_profile_runs_in_the_ticker_pool(self, client, monkeypatch, pool):
        """asyncio.to_thread belegte am Ticker-Lock Threads des Default-Executors."""
        _, r = await rw_tokens(client, "w3-k059-profile@example.com")
        service = MagicMock(return_value={"sector": "Technology"})
        monkeypatch.setattr("services.stock_service.get_company_profile", service)
        res = await client.get(f"{BASE}/stock/aapl/profile", headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert res.json() == {"sector": "Technology"}
        assert pool == [service]
        service.assert_called_once_with("AAPL")

    async def test_search_runs_in_the_ticker_pool(self, client, monkeypatch, pool):
        _, r = await rw_tokens(client, "w3-k059-search@example.com")
        quotes = [{"symbol": "NVDA", "shortname": "NVIDIA", "quoteType": "EQUITY"}]
        monkeypatch.setattr("yf_patch.yf_search", MagicMock(return_value=MagicMock(quotes=quotes)))
        res = await client.get(f"{BASE}/stock/search", params={"q": "nvda"}, headers=api_auth(r))
        assert res.status_code == 200, res.text
        assert [(i["ticker"], i["type"]) for i in res.json()] == [("NVDA", "stock")]
        assert [f.__name__ for f in pool] == ["_yf_search"]


# --- GF05: Benchmark und Ziel eines Buckets entfernen ---


class TestBucketClearFields:
    async def _bucket(self, client, token: str) -> dict:
        res = await client.post(
            f"{BASE}/buckets", headers=api_auth(token),
            json={"name": "Wachstum", "benchmark": "^GSPC", "target_pct": 25.0},
        )
        assert res.status_code == 201, res.text
        assert (res.json()["benchmark"], res.json()["target_pct"]) == ("^GSPC", 25.0)
        return res.json()

    async def test_empty_benchmark_and_two_null_targets_clear_the_fields(self, client):
        """null hiess für alle drei Felder «nicht ändern»: entfernen ging über die API nicht."""
        w, _ = await rw_tokens(client, "w3-gf05@example.com")
        bucket = await self._bucket(client, w)
        res = await client.patch(
            f"{BASE}/buckets/{bucket['id']}", headers=api_auth(w),
            json={"benchmark": "", "target_pct": None, "target_chf": None},
        )
        assert res.status_code == 200, res.text
        assert (res.json()["benchmark"], res.json()["target_pct"], res.json()["target_chf"]) == (None, None, None)
        listed = (await client.get(f"{BASE}/buckets", headers=api_auth(w))).json()["buckets"]
        stored = next(b for b in listed if b["id"] == bucket["id"])
        assert (stored["benchmark"], stored["target_pct"], stored["target_chf"]) == (None, None, None)

    @pytest.mark.parametrize("body", [
        {"name": "Umbenannt"},
        {"benchmark": None},
        {"target_pct": None},
        {"target_chf": None},
    ])
    async def test_missing_or_single_null_fields_change_nothing(self, client, body):
        w, _ = await rw_tokens(client, f"w3-gf05-keep-{abs(hash(str(body)))}@example.com")
        bucket = await self._bucket(client, w)
        res = await client.patch(f"{BASE}/buckets/{bucket['id']}", json=body, headers=api_auth(w))
        assert res.status_code == 200, res.text
        assert (res.json()["benchmark"], res.json()["target_pct"]) == ("^GSPC", 25.0)

    async def test_switching_the_target_kind_still_works(self, client):
        w, _ = await rw_tokens(client, "w3-gf05-switch@example.com")
        bucket = await self._bucket(client, w)
        res = await client.patch(
            f"{BASE}/buckets/{bucket['id']}", headers=api_auth(w),
            json={"target_pct": None, "target_chf": 5000.0},
        )
        assert res.status_code == 200, res.text
        assert (res.json()["target_pct"], res.json()["target_chf"]) == (None, 5000.0)

    async def test_unknown_benchmark_is_still_rejected(self, client):
        w, _ = await rw_tokens(client, "w3-gf05-bad@example.com")
        bucket = await self._bucket(client, w)
        res = await client.patch(
            f"{BASE}/buckets/{bucket['id']}", json={"benchmark": "AAPL"}, headers=api_auth(w),
        )
        assert res.status_code == 400


# --- K119: summary der Transaktionsliste ---


class TestTransactionSummary:
    async def _seed(self, client, db, email: str) -> tuple[str, str]:
        jwt = await register_and_login(client, email)
        w = await make_token(client, jwt, name="w", write=True)
        user_id = await _user_id(db, email)
        aapl = uuid.UUID(await _new_position(client, w, "AAPL"))
        nesn = uuid.UUID(await _new_position(client, w, "NESN"))
        rows = [
            (aapl, TransactionType.buy, date(2026, 1, 5), 1000.0, 5.0),
            (aapl, TransactionType.buy, date(2026, 2, 5), 500.0, 2.5),
            (aapl, TransactionType.sell, date(2026, 3, 5), 300.0, 1.0),
            (nesn, TransactionType.buy, date(2026, 3, 9), 200.25, 0.5),
            (nesn, TransactionType.dividend, date(2026, 4, 1), 30.0, 0.0),
        ]
        for position_id, txn_type, day, total, fees in rows:
            db.add(Transaction(
                user_id=user_id, position_id=position_id, type=txn_type, date=day,
                shares=1, price_per_share=total, total_chf=total, fees_chf=fees,
            ))
        await db.commit()
        return jwt, w

    async def test_summary_covers_the_whole_filter_not_only_the_page(self, client, db):
        """Die externe Liste kannte das Feld nicht; die interne liefert es seit Welle 2."""
        _, w = await self._seed(client, db, "w3-k119@example.com")
        res = await client.get(f"{BASE}/transactions", params={"per_page": 1}, headers=api_auth(w))
        assert res.status_code == 200, res.text
        body = res.json()
        assert (body["total"], len(body["items"]), body["pages"]) == (5, 1, 5)
        assert body["summary"] == {
            "total_chf_by_type": {"buy": 1700.25, "sell": 300.0, "dividend": 30.0},
            "fees_chf": 9.0,
        }

    @pytest.mark.parametrize("params, expected", [
        ({"type": "buy"}, {"total_chf_by_type": {"buy": 1700.25}, "fees_chf": 8.0}),
        ({"ticker": "NESN"}, {"total_chf_by_type": {"buy": 200.25, "dividend": 30.0}, "fees_chf": 0.5}),
        ({"search": "aapl", "date_from": "2026-02-01"},
         {"total_chf_by_type": {"buy": 500.0, "sell": 300.0}, "fees_chf": 3.5}),
        ({"date_to": "2025-12-31"}, {"total_chf_by_type": {}, "fees_chf": 0.0}),
        ({"ticker": "GIBTESNICHT"}, {"total_chf_by_type": {}, "fees_chf": 0.0}),
        ({"search": "GIBTESNICHT"}, {"total_chf_by_type": {}, "fees_chf": 0.0}),
    ])
    async def test_summary_follows_every_filter(self, client, db, params, expected):
        _, w = await self._seed(client, db, f"w3-k119-{abs(hash(str(params)))}@example.com")
        res = await client.get(f"{BASE}/transactions", params=params, headers=api_auth(w))
        assert res.status_code == 200, res.text
        assert res.json()["summary"] == expected
        assert res.json()["total"] == len(res.json()["items"])

    async def test_summary_equals_the_internal_list(self, client, db):
        jwt, w = await self._seed(client, db, "w3-k119-parity@example.com")
        for params in ({}, {"type": "sell"}, {"ticker": "AAPL", "date_to": "2026-02-28"}):
            external = await client.get(f"{BASE}/transactions", params=params, headers=api_auth(w))
            internal = await client.get("/api/transactions", params=params, headers=jwt_auth(jwt))
            assert internal.status_code == 200, internal.text
            assert external.json()["summary"] == internal.json()["summary"], params
            assert external.json()["total"] == internal.json()["total"], params

    async def test_other_users_do_not_count(self, client, db):
        await self._seed(client, db, "w3-k119-a@example.com")
        _, other = await rw_tokens(client, "w3-k119-b@example.com")
        res = await client.get(f"{BASE}/transactions", headers=api_auth(other))
        assert res.json()["summary"] == {"total_chf_by_type": {}, "fees_chf": 0.0}


# --- X02: Limits der Lese-Routen mit Pfadparameter ---


_ID_READ_ROUTES = [
    "get_position_by_id_external", "position_history_external",
    "bucket_summary_external", "bucket_history_external", "bucket_drawdown_external",
    "bucket_benchmark_comparison_external", "bucket_monthly_returns_external",
    "bucket_total_return_external", "bucket_fee_summary_external",
    "get_immobilie", "list_hypotheken", "get_vorsorge", "get_pe_holding_external",
]
_TICKER_READ_ROUTES = [
    "get_position", "analysis_score", "analysis_heartbeat", "analysis_breakouts",
    "analysis_mrs", "analysis_levels", "analysis_reversal", "stock_profile_external",
    "etf_sectors_external", "screening_ticker_external", "market_sector_holdings_external",
]
# Teuer (Yahoo je Aufruf): Wert des internen Zwillings.
_HEAVY_PATH_ROUTES = ["position_dividends_external", "market_sector_scores_external"]
# Bewusst beim Standard: kleine Wertemenge (Währungen), ein Scan zur selben
# Zeit, und der Drill-down ruft TradingView (interner Zwilling: 30/minute).
_DEFAULT_PATH_ROUTES = [
    "market_fx_external", "screening_scan_progress_external", "market_industry_members",
]


class TestIdRouteLimits:
    @pytest.mark.parametrize("func", _ID_READ_ROUTES)
    async def test_id_read_routes_get_120_per_minute(self, func):
        """Der Limiter zählt je Route: vorher hatte jede ID ihr eigenes Budget von 30."""
        assert _limits_of(func) == [parse_limit(RL_READ)]

    async def test_every_get_route_with_a_path_parameter_is_classified(self):
        """Eine neue Route mit Pfadparameter fällt hier auf und bekommt bewusst einen Wert."""
        found = {
            r.endpoint.__name__ for r in _external_routes()
            if "GET" in r.methods and "{" in r.path
        }
        assert found == set(
            _ID_READ_ROUTES + _TICKER_READ_ROUTES + _HEAVY_PATH_ROUTES + _DEFAULT_PATH_ROUTES
        )
        for func in _HEAVY_PATH_ROUTES:
            assert _limits_of(func) == [parse_limit(RL_HEAVY)], func
        for func in _DEFAULT_PATH_ROUTES:
            assert _limits_of(func) == [parse_limit(ext.RATE_LIMIT)], func

    async def test_iterating_over_ids_does_not_fail_earlier_than_before(self, client, monkeypatch):
        """Vor dem Umbau: 30 je Minute und ID. 40 IDs in Folge müssen weiter durchgehen."""
        _, r = await rw_tokens(client, "w3-x02@example.com")
        monkeypatch.setattr(
            "services.private_equity_service.get_holding_detail", AsyncMock(return_value={"id": "x"}),
        )
        limiter.enabled = True
        try:
            codes = {
                (await client.get(f"{BASE}/private-equity/{uuid.uuid4()}", headers=api_auth(r))).status_code
                for _ in range(40)
            }
        finally:
            limiter.enabled = False
        assert codes == {200}


# --- Annotated-Falle: das Muster muss am Parameter ankommen ---


def _declared_pattern(annotation) -> str | None:
    for meta in getattr(annotation, "__metadata__", ()):
        pattern = getattr(meta, "pattern", None)
        if pattern:
            return pattern
    return None


def _effective_patterns(field) -> set[str]:
    """Muster, an denen FastAPI den Wert «A,B» für diesen Parameter scheitern lässt.

    Am Verhalten gemessen, nicht an den Metadaten: je nach Deklaration stehen
    sie in field_info.metadata oder in der Annotation des Feldes.
    """
    _, errors = field.validate("A,B", {}, loc=("param", field.name))
    return {e["ctx"]["pattern"] for e in errors or [] if e["type"] == "string_pattern_mismatch"}


def _params_losing_their_pattern(routes: list[APIRoute]) -> list[str]:
    """Parameter, deren Annotation ein Muster trägt, das FastAPI nicht anwendet."""
    lost = []
    for route in routes:
        hints = typing.get_type_hints(route.endpoint, include_extras=True)
        for field in route.dependant.path_params + route.dependant.query_params:
            pattern = _declared_pattern(hints.get(field.name))
            if pattern and pattern not in _effective_patterns(field):
                lost.append(f"{route.path}:{field.name}")
    return lost


class TestAnnotatedTrap:
    async def test_check_detects_the_trap(self):
        """«x: MarketTicker = Query(...)» setzt die Annotation auf str zurück."""
        app = FastAPI()

        @app.get("/broken")
        async def broken(ticker: MarketTicker = Query(...)):
            return ticker

        @app.get("/fine/{ticker}")
        async def fine(ticker: MarketTicker):
            return ticker

        routes = [r for r in app.routes if isinstance(r, APIRoute)]
        assert _params_losing_their_pattern(routes) == ["/broken:ticker"]

    async def test_no_external_parameter_loses_its_pattern(self):
        assert _params_losing_their_pattern(_external_routes()) == []

    async def test_typed_parameters_are_the_expected_ones(self):
        """Ohne diese Liste bliebe der Test oben grün, wenn jemand die Typen entfernt."""
        typed = set()
        for route in _external_routes():
            hints = typing.get_type_hints(route.endpoint, include_extras=True)
            for field in route.dependant.path_params + route.dependant.query_params:
                if _declared_pattern(hints.get(field.name)):
                    typed.add((sorted(route.methods)[0], route.path.removeprefix(BASE), field.name))
        assert typed == {
            ("GET", "/analysis/score/{ticker}", "ticker"),
            ("GET", "/analysis/heartbeat/{ticker}", "ticker"),
            ("GET", "/analysis/breakouts/{ticker}", "ticker"),
            ("GET", "/analysis/mrs/{ticker}", "ticker"),
            ("GET", "/analysis/levels/{ticker}", "ticker"),
            ("GET", "/analysis/reversal/{ticker}", "ticker"),
            ("GET", "/stock/{ticker}/profile", "ticker"),
            ("PUT", "/etf-sectors/{ticker}", "ticker"),
            ("PUT", "/analysis/resistance/{ticker}", "ticker"),
            ("GET", "/market/fx/{from_currency}", "from_currency"),
            ("GET", "/market/fx/{from_currency}", "to_currency"),
        }

    @pytest.mark.parametrize("ticker", ["AAPL,MSFT", "AAPL%20MSFT", "%20AAPL"])
    async def test_etf_sector_put_rejects_comma_and_space(self, client, db, ticker):
        email = f"w3-trap-etf-{abs(hash(ticker))}@example.com"
        w, _ = await rw_tokens(client, email)
        body = {"sectors": [{"sector": "Technology", "weight_pct": 100.0}]}
        res = await client.put(f"{BASE}/etf-sectors/{ticker}", json=body, headers=api_auth(w))
        assert res.status_code == 422, res.text
        assert "etf_sector_update" not in await _log_actions(db, email)

    @pytest.mark.parametrize("ticker", ["AAPL,MSFT", "AAPL%20MSFT", "%20AAPL"])
    async def test_resistance_put_rejects_comma_and_space(self, client, db, ticker):
        email = f"w3-trap-res-{abs(hash(ticker))}@example.com"
        w, _ = await rw_tokens(client, email)
        res = await client.put(
            f"{BASE}/analysis/resistance/{ticker}", json={"manual_resistance": 100.0}, headers=api_auth(w),
        )
        assert res.status_code == 422, res.text
        assert "resistance_update" not in await _log_actions(db, email)

    @pytest.mark.parametrize("url", [
        "/market/fx/US,D", "/market/fx/U%20D", "/market/fx/USD?to_currency=E,R", "/market/fx/USD?to_currency=E%20R",
    ])
    async def test_fx_codes_reject_comma_and_space(self, client, monkeypatch, url):
        _, r = await rw_tokens(client, f"w3-trap-fx-{abs(hash(url))}@example.com")
        service = MagicMock(return_value=1.0)
        monkeypatch.setattr("services.utils.get_fx_rate", service)
        res = await client.get(f"{BASE}{url}", headers=api_auth(r))
        assert res.status_code == 422, res.text
        service.assert_not_called()

    async def test_market_ticker_pattern_is_the_shared_one(self):
        field = next(
            f for r in _external_routes() if r.path == f"{BASE}/analysis/score/{{ticker}}"
            for f in r.dependant.path_params
        )
        assert _effective_patterns(field) == {MARKET_TICKER_PATTERN}
