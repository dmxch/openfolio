"""Vollreview 11/2026, Fixer «marketetf»: Markt-Routen, Sektor-Holdings, ETF-Durchsicht, COT.

K022 (FX-Route ohne Limit und Muster), K137 (Branchen-Cache je Float), K146
(CH-Makro cacht Teilausfälle), K093 (Sektor-Holdings ohne Nutzerfilter), X19
(leeres Kursergebnis als Miss), K054 (Upsert über der Parametergrenze), K094
(fremde Position steuert die Holdings-Quelle), K084 (iShares-Kopfzeile), K124
(NaN-Gewicht bei Amundi), K145 (COT: 403 und Abbruch), K157 (Grössengrenzen),
GS03 (Börsen-Mapping), K142 (Limit Makro-Indikatoren).
"""
from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pandas as pd
import pytest
from httpx import AsyncClient
from limits import parse as parse_limit
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

import services.etf_holdings_ishares as ish
import services.etf_holdings_service as eh
import services.macro.cot_service as cot
import services.sector_analyzer as sa
from constants.exchange_suffix import exchange_to_suffix, exchange_to_yf_ticker
from constants.limits import RL_HEAVY, RL_READ, RL_SEARCH, RL_TICKER_READ
from dateutils import utcnow
from models.bucket import Bucket
from models.etf_holding import EtfHolding
from models.macro_cot import MacroCotSnapshot
from models.market_industry import MarketIndustry
from models.position import AssetType, Position, PriceSource
from models.user import User, UserSettings
from models.watchlist import WatchlistItem
from services import cache
from services.bucket_service import create_system_buckets
from services.ch_macro_service import ch_macro_cache_ttl
from services.etf_adapters import _excel, _http
from services.etf_adapters.amundi import parse_amundi_composition
from services.etf_adapters.base import EtfRef

TEST_PASSWORD = "TestPassw0rd!2026"


async def _login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _route_limits(name: str) -> list:
    import api.etf_sectors  # noqa: F401 — registriert die Routen am Limiter
    import api.market  # noqa: F401
    from api.auth import limiter

    return [lim.limit for lim in limiter._route_limits.get(name, [])]


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await create_system_buckets(db, user.id)
    await db.commit()
    return user


async def _buckets(db, user_id) -> list[Bucket]:
    res = await db.execute(
        select(Bucket).where(Bucket.user_id == user_id).order_by(Bucket.sort_order)
    )
    return list(res.scalars().all())


async def _add_position(
    db, user_id, ticker: str, *, type_=AssetType.stock, name: str | None = None,
    isin: str | None = None, bucket: Bucket | None = None,
) -> Position:
    if bucket is None:
        bucket = (await _buckets(db, user_id))[0]
    pos = Position(
        user_id=user_id, bucket_id=bucket.id, ticker=ticker, name=name or f"{ticker} Inc",
        type=type_, currency="USD", price_source=PriceSource.yahoo, isin=isin,
        shares=Decimal("10"), cost_basis_chf=Decimal("1500"),
    )
    db.add(pos)
    await db.commit()
    return pos


def _warnings(mock) -> list[str]:
    """Formatierte Meldungen eines gepatchten logger.warning."""
    return [c.args[0] % c.args[1:] if len(c.args) > 1 else c.args[0] for c in mock.call_args_list]


_PERF = {
    "price": 100.0, "change_pct": 1.0, "perf_1d": 1.0, "perf_1w": 2.0, "perf_1m": 3.0,
    "perf_3m": 4.0, "perf_6m": 5.0, "relative_to_spy": 0.5, "trend": "up",
}


@pytest.fixture(autouse=True)
def _clean_sector_cache():
    def _clear():
        for etf in sa.SECTOR_ETF_HOLDINGS:
            cache.delete(f"sector_holdings:{etf}")
            cache.release_lock(f"sector_holdings_dl:{etf}")
        cache.delete("external:macro:ch:v1")

    _clear()
    yield
    _clear()


# ---------------------------------------------------------------------------
# K022 — FX-Route: Muster und Limit
# ---------------------------------------------------------------------------


class TestFxRoute:
    @pytest.mark.parametrize("path", [
        "/api/market/fx/X1",
        "/api/market/fx/USDT",
        "/api/market/fx/US%24",
        "/api/market/fx/USD?to_currency=EURO",
        "/api/market/fx/USD?to_currency=E1",
    ])
    async def test_rejects_codes_that_are_not_three_letters(self, client, path):
        headers = await _login(client, "fx-bad@example.com")
        with patch("services.utils.get_fx_rate", return_value=1.0) as fx:
            res = await client.get(path, headers=headers)
        assert res.status_code == 422
        fx.assert_not_called()  # kein Kursabruf für ungeprüfte Eingaben

    async def test_accepts_lowercase_and_passes_uppercase(self, client):
        headers = await _login(client, "fx-ok@example.com")
        with patch("services.utils.get_fx_rate", return_value=0.93) as fx:
            res = await client.get("/api/market/fx/usd?to_currency=eur", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json() == {"from": "USD", "to": "EUR", "rate": 0.93}
        fx.assert_called_once_with("USD", "EUR")

    def test_route_has_limit(self):
        assert _route_limits("api.market.fx_rate") == [parse_limit(RL_SEARCH)]


# ---------------------------------------------------------------------------
# K137 — Branchen-Route ohne Antwort-Cache
# ---------------------------------------------------------------------------


class TestIndustriesNoResponseCache:
    async def test_free_float_creates_no_cache_entry_and_data_stays_fresh(self, client, db):
        ts = datetime(2026, 11, 12)
        db.add(MarketIndustry(slug="semis", name="Semiconductors", scraped_at=ts,
                              perf_ytd=Decimal("40"), market_cap=Decimal("5000000000")))
        await db.commit()
        headers = await _login(client, "ind@example.com")

        with patch.object(cache, "set", wraps=cache.set) as spy:
            first = await client.get("/api/market/industries?min_mcap=1.000001", headers=headers)
            db.add(MarketIndustry(slug="banks", name="Banks", scraped_at=ts,
                                  perf_ytd=Decimal("10"), market_cap=Decimal("7000000000")))
            await db.commit()
            # Gleiche Parameter: ein Antwort-Cache lieferte hier noch eine Zeile.
            second = await client.get("/api/market/industries?min_mcap=1.000001", headers=headers)

        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["count"] == 1
        assert second.json()["count"] == 2
        keys = [c.args[0] for c in spy.call_args_list]
        assert not [k for k in keys if k.startswith("market:industries")]


# ---------------------------------------------------------------------------
# K146 — CH-Makro: lückenhafte Snapshots nur kurz cachen
# ---------------------------------------------------------------------------


class TestChMacroCacheTtl:
    def test_ttl_helper(self):
        assert ch_macro_cache_ttl({"warnings": []}) == 21600
        assert ch_macro_cache_ttl({}) == 21600
        assert ch_macro_cache_ttl({"warnings": ["fx_unavailable"]}) == 600

    @pytest.mark.parametrize("warnings,expected_ttl", [
        (["fx_unavailable"], 600),
        ([], 21600),
    ])
    async def test_route_uses_ttl(self, client, warnings, expected_ttl):
        headers = await _login(client, f"chmacro{expected_ttl}@example.com")
        snapshot = {"as_of": "2026-11-13T08:00:00", "fx": None, "warnings": warnings}
        with patch("api.market.get_ch_macro_snapshot", new=AsyncMock(return_value=snapshot)), \
                patch.object(cache, "set", wraps=cache.set) as spy:
            res = await client.get("/api/market/macro/ch", headers=headers)
        assert res.status_code == 200, res.text
        calls = [c for c in spy.call_args_list if c.args[0] == "external:macro:ch:v1"]
        assert len(calls) == 1
        assert calls[0].kwargs["ttl"] == expected_ttl


# ---------------------------------------------------------------------------
# K093 — Sektor-Holdings: Flags nur für den eigenen Nutzer
# ---------------------------------------------------------------------------


class TestSectorHoldingsTenant:
    async def test_flags_are_scoped_to_the_calling_user(self, client, db):
        held, watched = "AAPL", "MSFT"
        cache.set("sector_holdings:XLK", {held: _PERF, watched: _PERF}, ttl=60)

        headers_a = await _login(client, "holder-a@example.com")
        headers_b = await _login(client, "holder-b@example.com")
        user_b = (
            await db.execute(select(User).where(User.email == "holder-b@example.com"))
        ).scalar_one()
        await create_system_buckets(db, user_b.id)
        await db.commit()
        await _add_position(db, user_b.id, held)
        db.add(WatchlistItem(user_id=user_b.id, ticker=watched, name="Microsoft"))
        await db.commit()

        res_a = await client.get("/api/market/sectors/XLK/holdings", headers=headers_a)
        res_b = await client.get("/api/market/sectors/XLK/holdings", headers=headers_b)
        assert res_a.status_code == 200 and res_b.status_code == 200

        rows_a = res_a.json()["holdings"]
        assert not any(h["in_portfolio"] or h["in_watchlist"] for h in rows_a)

        by_b = {h["ticker"]: h for h in res_b.json()["holdings"]}
        assert by_b[held]["in_portfolio"] is True
        assert by_b[watched]["in_watchlist"] is True
        assert sum(h["in_portfolio"] for h in by_b.values()) == 1
        assert sum(h["in_watchlist"] for h in by_b.values()) == 1

    async def test_without_user_no_flags_at_all(self, db):
        """Aufrufer ohne user_id (alter Aufruf): keine Flags statt Flags aller Nutzer."""
        cache.set("sector_holdings:XLK", {"AAPL": _PERF}, ttl=60)
        user = await _make_user(db)
        await _add_position(db, user.id, "AAPL")
        db.add(WatchlistItem(user_id=user.id, ticker="MSFT", name="Microsoft"))
        await db.commit()

        result = await sa.get_sector_holdings("XLK", db)
        assert not any(h["in_portfolio"] or h["in_watchlist"] for h in result["holdings"])

        own = await sa.get_sector_holdings("XLK", db, user_id=user.id)
        by = {h["ticker"]: h for h in own["holdings"]}
        assert by["AAPL"]["in_portfolio"] is True and by["MSFT"]["in_watchlist"] is True


# ---------------------------------------------------------------------------
# X19 — leeres Kursergebnis, Sperre, Limit
# ---------------------------------------------------------------------------


class TestSectorHoldingsCacheAndLock:
    async def test_empty_result_is_a_cache_hit_and_cached_briefly(self, db):
        with patch.object(sa, "yf_download", return_value=pd.DataFrame()) as dl, \
                patch.object(cache, "set", wraps=cache.set) as spy:
            first = await sa.get_sector_holdings("XLE", db)
            second = await sa.get_sector_holdings("XLE", db)
        assert dl.call_count == 1  # der zweite Aufruf lädt nicht erneut
        assert first["holdings"][0]["price"] is None
        assert second["holdings"][0]["price"] is None
        ttls = [c.kwargs["ttl"] for c in spy.call_args_list if c.args[0] == "sector_holdings:XLE"]
        assert ttls == [60]

    async def test_no_second_download_while_another_request_holds_the_lock(self, db, monkeypatch):
        monkeypatch.setattr(sa, "_HOLDINGS_WAIT_STEPS", 2)
        monkeypatch.setattr(sa, "_HOLDINGS_WAIT_STEP_S", 0)
        assert cache.acquire_lock("sector_holdings_dl:XLF", 60) is True
        with patch.object(sa, "yf_download") as dl:
            result = await sa.get_sector_holdings("XLF", db)
        dl.assert_not_called()
        assert all(h["price"] is None for h in result["holdings"])
        assert cache.get("sector_holdings:XLF") is None  # der Notbehelf wird nicht gecacht

    async def test_waiter_takes_the_result_of_the_lock_holder(self, db, monkeypatch):
        monkeypatch.setattr(sa, "_HOLDINGS_WAIT_STEPS", 200)
        monkeypatch.setattr(sa, "_HOLDINGS_WAIT_STEP_S", 0.01)
        ticker = sa.SECTOR_ETF_HOLDINGS["XLV"][0][0]
        assert cache.acquire_lock("sector_holdings_dl:XLV", 60) is True

        async def _holder_finishes():
            await asyncio.sleep(0.05)
            cache.set("sector_holdings:XLV", {ticker: _PERF}, ttl=60)

        holder = asyncio.create_task(_holder_finishes())
        with patch.object(sa, "yf_download") as dl:
            result = await sa.get_sector_holdings("XLV", db)
        await holder
        dl.assert_not_called()
        assert result["holdings"][0]["price"] == 100.0

    async def test_lock_is_released_after_download_and_after_failure(self, db):
        with patch.object(sa, "yf_download", return_value=pd.DataFrame()):
            await sa.get_sector_holdings("XLI", db)
        assert cache.acquire_lock("sector_holdings_dl:XLI", 5) is True
        cache.release_lock("sector_holdings_dl:XLI")

        with patch.object(sa, "yf_download", side_effect=RuntimeError("yahoo down")):
            with pytest.raises(RuntimeError):
                await sa.get_sector_holdings("XLB", db)
        assert cache.acquire_lock("sector_holdings_dl:XLB", 5) is True

    def test_route_limits(self):
        assert _route_limits("api.market.sector_holdings") == [parse_limit(RL_READ)]
        # K142
        assert _route_limits("api.market.macro_indicators") == [parse_limit(RL_HEAVY)]
        # Q3: das Frontend ruft die Route je ETF-Position auf
        assert _route_limits("api.etf_sectors.get_etf_sectors") == [parse_limit(RL_TICKER_READ)]


class TestEtfSectorTicker:
    """Q2: die Schreibroute nimmt nur Markt-Ticker, die in die Spalte passen."""

    _BODY = {"sectors": [{"sector": "Technology", "weight_pct": 100.0}]}

    @pytest.mark.parametrize("ticker", ["A" * 21, "VWRL%20L", "VW%24"])
    async def test_put_rejects_invalid_ticker(self, client, ticker):
        headers = await _login(client, "etfsec-bad@example.com")
        res = await client.put(f"/api/etf-sectors/{ticker}", json=self._BODY, headers=headers)
        assert res.status_code == 422, res.text

    async def test_put_accepts_ticker_at_column_length_and_returns_weights(self, client):
        headers = await _login(client, "etfsec-ok@example.com")
        res = await client.put(f"/api/etf-sectors/{'a' * 20}", json=self._BODY, headers=headers)
        assert res.status_code == 200, res.text
        assert res.json() == {
            "ticker": "A" * 20,
            "sectors": [{"sector": "Technology", "weight_pct": 100.0}],
            "is_complete": True,
        }
        read = await client.get(f"/api/etf-sectors/{'A' * 20}", headers=headers)
        assert read.status_code == 200 and read.json()["is_complete"] is True


# ---------------------------------------------------------------------------
# K054 — Holdings-Upsert in Blöcken
# ---------------------------------------------------------------------------


def _holding_rows(n: int, etf: str) -> list[dict]:
    return [
        {
            "etf_ticker": etf,
            "holding_ticker": f"H{i:05d}",
            "holding_name": f"Holding {i}",
            "weight_pct": 0.01,
            "as_of": date(2026, 10, 31),
            "holding_isin": None,
            "holding_country": "United States",
            "holding_sector": None,
        }
        for i in range(n)
    ]


class _FakeAdapter:
    name = "Fake"

    def __init__(self, rows):
        self._rows = rows

    def matches(self, ref):
        return True

    async def fetch(self, ref):
        return self._rows


class TestHoldingsUpsertChunks:
    async def test_5000_rows_are_stored_in_blocks_below_the_parameter_limit(self, db, monkeypatch):
        etf = "BIGFUND.L"
        monkeypatch.setattr(eh, "get_adapter", lambda ref: _FakeAdapter(_holding_rows(5000, etf)))

        inserts: list[int] = []
        real_execute = db.execute

        async def recording_execute(stmt, *args, **kwargs):
            if isinstance(stmt, Insert):
                inserts.append(len(stmt.compile(dialect=postgresql.dialect()).params))
            return await real_execute(stmt, *args, **kwargs)

        monkeypatch.setattr(db, "execute", recording_execute)

        out = await eh.refresh_etf_holdings(db, EtfRef(etf, None, "Fake Fund"), "")
        assert out["count"] == 5000

        # asyncpg lehnt mehr als 32'767 Bind-Parameter je Statement ab.
        assert len(inserts) == 5
        assert max(inserts) <= 32767

        stored = (
            await real_execute(
                select(func.count()).select_from(EtfHolding).where(EtfHolding.etf_ticker == etf)
            )
        ).scalar()
        assert stored == 5000


# ---------------------------------------------------------------------------
# K094 — fremde Positions-Metadaten steuern die Quelle nicht mehr
# ---------------------------------------------------------------------------


class TestEtfRefConflicts:
    async def test_ticker_with_diverging_sources_keeps_the_oldest_and_logs(self, db):
        """Welle 5: der Ticker fällt nicht mehr aus, die älteste Angabe gewinnt."""
        victim = await _make_user(db)
        attacker = await _make_user(db)
        await _add_position(db, victim.id, "LYX0.DE", type_=AssetType.etf,
                            name="Amundi MSCI World", isin="LU1781541179")
        await _add_position(db, attacker.id, "LYX0.DE", type_=AssetType.etf,
                            name="Xtrackers MSCI Japan", isin="LU0274209740")
        await _add_position(db, victim.id, "VOO", type_=AssetType.etf, name="Vanguard S&P 500")

        with patch.object(eh.logger, "warning") as warn:
            refs = await eh._get_active_etf_refs(db)

        by_ticker = {r.ticker: r for r in refs}
        assert sorted(by_ticker) == ["LYX0.DE", "VOO"]
        assert by_ticker["LYX0.DE"].isin_valid == "LU1781541179"
        assert eh.get_adapter(by_ticker["LYX0.DE"]).name == "Amundi"
        messages = _warnings(warn)
        assert any("LYX0.DE" in m and "different holdings sources" in m for m in messages)

    async def test_same_isin_under_different_brand_spelling_is_no_conflict(self, db):
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_position(db, a.id, "XDWD.DE", type_=AssetType.etf,
                            name="Xtrackers MSCI World", isin="IE00BJ0KDQ92")
        await _add_position(db, b.id, "XDWD.DE", type_=AssetType.etf,
                            name="XTRACKERS MSCI WORLD UCITS ETF 1C", isin="ie00bj0kdq92")
        refs = await eh._get_active_etf_refs(db)
        assert [r.ticker for r in refs] == ["XDWD.DE"]
        assert refs[0].isin_valid == "IE00BJ0KDQ92"

    async def test_two_different_isins_for_one_ticker_are_a_conflict(self, db):
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_position(db, a.id, "XDWD.DE", type_=AssetType.etf,
                            name="Xtrackers MSCI World", isin="IE00BJ0KDQ92")
        await _add_position(db, b.id, "XDWD.DE", type_=AssetType.etf,
                            name="Xtrackers MSCI World", isin="LU0274209740")
        # Welle 5: kein Ausfall mehr, die ISIN der älteren Position gilt.
        refs, conflicts = await eh._resolve_active_etf_refs(db)
        assert [r.isin_valid for r in refs] == ["IE00BJ0KDQ92"]
        assert [c["etf_ticker"] for c in conflicts] == ["XDWD.DE"]

    async def test_registry_ticker_ignores_name_and_isin(self, db):
        """iShares routet nur nach Ticker: abweichende Nutzerfelder ändern die Quelle nicht."""
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_position(db, a.id, "SWDA.L", type_=AssetType.etf, name="iShares Core MSCI World")
        await _add_position(db, b.id, "SWDA.L", type_=AssetType.etf,
                            name="Xtrackers Irgendwas", isin="LU0274209740")
        refs = await eh._get_active_etf_refs(db)
        assert [r.ticker for r in refs] == ["SWDA.L"]

    async def test_one_user_with_two_positions_keeps_the_isin_row(self, db):
        """Derselbe Nutzer hält den ETF in zwei Buckets, nur eine Position trägt die ISIN."""
        user = await _make_user(db)
        buckets = await _buckets(db, user.id)
        await _add_position(db, user.id, "XDWD.DE", type_=AssetType.etf,
                            name="Xtrackers MSCI World", bucket=buckets[0])
        await _add_position(db, user.id, "XDWD.DE", type_=AssetType.etf,
                            name="Xtrackers MSCI World", isin="IE00BJ0KDQ92", bucket=buckets[1])
        refs = await eh._get_active_etf_refs(db)
        assert len(refs) == 1
        assert refs[0].isin == "IE00BJ0KDQ92"


# ---------------------------------------------------------------------------
# K084 — iShares: Kopfzeile tolerant suchen, Fehlschlag sichtbar machen
# ---------------------------------------------------------------------------

_ISHARES_HEADER = (
    '"{ticker_col}","Name","Sector","Asset Class","Market Value","Weight (%)",'
    '"Notional Value","Shares","Price","Location","Exchange","Market Currency"'
)
_ISHARES_ROW = (
    '"2330","TAIWAN SEMICONDUCTOR","Information Technology","Equity","x","6.32","x","x","x",'
    '"Taiwan","Taiwan Stock Exchange","TWD"'
)


class TestIsharesHeader:
    def test_bom_before_header_in_first_line(self):
        text = "﻿" + _ISHARES_HEADER.format(ticker_col="Ticker") + "\n" + _ISHARES_ROW
        rows = ish.parse_ishares_csv(text, "EIMI.L")
        assert [r["holding_ticker"] for r in rows] == ["2330.TW"]

    def test_issuer_ticker_column_is_accepted(self):
        text = "\n".join([
            '"iShares Core MSCI EM IMI UCITS ETF"',
            '"Fund Holdings as of","Oct 31, 2026"',
            _ISHARES_HEADER.format(ticker_col="Issuer Ticker"),
            _ISHARES_ROW,
        ])
        rows = ish.parse_ishares_csv(text, "EIMI.L")
        assert [r["holding_ticker"] for r in rows] == ["2330.TW"]
        assert rows[0]["as_of"] == date(2026, 10, 31)

    async def test_missing_header_logs_status_content_type_and_body_start(self, monkeypatch):
        body = b"<!DOCTYPE html><html><head><title>Cookie consent</title></head></html>"
        seen: dict = {}

        async def fake_capped_get(url, **kwargs):
            seen.update(kwargs)
            kwargs["meta"]["status"] = 200
            kwargs["meta"]["content_type"] = "text/html; charset=utf-8"
            return body

        monkeypatch.setattr(_http, "capped_get", fake_capped_get)
        with patch.object(ish.logger, "warning") as warn:
            rows = await ish.fetch_ishares_holdings("SWDA.L")

        assert rows == []
        assert "Mozilla" in seen["headers"]["User-Agent"]
        message = "\n".join(_warnings(warn))
        assert "SWDA.L" in message
        assert "status=200" in message
        assert "text/html" in message
        assert "<!DOCTYPE html>" in message

    async def test_body_is_decoded_with_declared_charset_and_bom_is_dropped(self, monkeypatch):
        text = "\n".join([
            _ISHARES_HEADER.format(ticker_col="Ticker"),
            '"NESN","NESTLÉ SA","Consumer Staples","Equity","x","3.10","x","x","x",'
            '"Switzerland","SIX Swiss Exchange","CHF"',
        ])

        def fake(body: bytes, content_type: str | None):
            async def _capped_get(url, **kwargs):
                kwargs["meta"].update(status=200, content_type=content_type)
                return body
            return _capped_get

        monkeypatch.setattr(_http, "capped_get", fake(text.encode("utf-8-sig"), "text/csv"))
        rows = await ish.fetch_ishares_holdings("CHSPI.SW")
        assert [(r["holding_ticker"], r["holding_name"]) for r in rows] == [("NESN.SW", "NESTLÉ SA")]

        monkeypatch.setattr(
            _http, "capped_get", fake(text.encode("latin-1"), "text/csv; charset=ISO-8859-1"),
        )
        rows = await ish.fetch_ishares_holdings("CHSPI.SW")
        assert [(r["holding_ticker"], r["holding_name"]) for r in rows] == [("NESN.SW", "NESTLÉ SA")]

    async def test_fetch_error_returns_none(self, monkeypatch):
        """K157: der Abruf läuft über capped_get (Byte-Grenze); None bleibt ein Fetch-Fehler."""
        monkeypatch.setattr(_http, "capped_get", AsyncMock(return_value=None))
        assert await ish.fetch_ishares_holdings("SWDA.L") is None

    async def test_failed_etf_is_logged_as_warning(self, monkeypatch):
        async def fake_key(db):
            return ""

        async def fake_refs(db):
            return [EtfRef("SWDA.L", None, "iShares Core MSCI World")], []

        async def no_rows(db, ref, api_key):
            return {"etf_ticker": "SWDA.L", "error": "no_parseable_rows"}

        monkeypatch.setattr(eh, "_get_any_user_fmp_key", fake_key)
        monkeypatch.setattr(eh, "_resolve_active_etf_refs", fake_refs)
        monkeypatch.setattr(eh, "refresh_etf_holdings", no_rows)
        with patch.object(eh.logger, "warning") as warn:
            out = await eh.refresh_all_user_etfs(None)
        assert len(out["errors"]) == 1
        assert any("SWDA.L" in m and "no_parseable_rows" in m for m in _warnings(warn))


# ---------------------------------------------------------------------------
# K124 — Amundi: ein nicht endliches Gewicht kippt die Skala nicht
# ---------------------------------------------------------------------------


def _amundi_payload(bad_weight) -> dict:
    def row(bbg, isin, name, weight):
        cc = {"date": "2026-11-06", "type": "EQUITY_ORDINARY", "bbg": bbg, "isin": isin,
              "name": name, "weight": weight, "sector": "Information Technology",
              "countryOfRisk": "United States"}
        return {"compositionCharacteristics": cc, "weight": weight}

    return {"products": [{
        "productId": "IE0003XJA0J9",
        "characteristics": {"ISIN": "IE0003XJA0J9",
                            "FUND_REPLICATION_METHODOLOGY": "Direct(Physical)"},
        "composition": {"compositionData": [
            row("AAPL UW", "US0378331005", "APPLE INC", 0.05),
            row("MSFT UW", "US5949181045", "MICROSOFT CORP", 0.04),
            row("NVDA UW", "US67066G1040", "NVIDIA CORP", bad_weight),
        ]},
    }]}


class TestAmundiNonFiniteWeight:
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
    def test_bad_weight_row_is_dropped_and_scale_stays(self, bad):
        rows = parse_amundi_composition(_amundi_payload(bad), "PRAW.DE")
        assert {r["holding_ticker"]: r["weight_pct"] for r in rows} == {"AAPL": 5.0, "MSFT": 4.0}

    def test_bare_nan_literal_in_json_text(self):
        text = json.dumps(_amundi_payload(float("nan")))  # schreibt das Literal NaN
        assert "NaN" in text
        rows = parse_amundi_composition(text, "PRAW.DE")
        assert {r["holding_ticker"]: r["weight_pct"] for r in rows} == {"AAPL": 5.0, "MSFT": 4.0}


# ---------------------------------------------------------------------------
# K145 — COT: Browser-UA, Teilergebnisse, stale
# ---------------------------------------------------------------------------


def _zip_bytes(name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, content)
    return buf.getvalue()


def _tff_zip(report_date: date) -> bytes:
    lines = [
        "Market_and_Exchange_Names,Report_Date_as_YYYY-MM-DD,Dealer_Positions_Long_All,"
        "Dealer_Positions_Short_All,Lev_Money_Positions_Long_All,"
        "Lev_Money_Positions_Short_All,Open_Interest_All",
        f"USD INDEX - ICE FUTURES U.S.,{report_date.isoformat()},100,40,30,50,1000",
        f"UST 10Y NOTE - CHICAGO BOARD OF TRADE,{report_date.isoformat()},500,700,900,300,9000",
    ]
    return _zip_bytes("FinFutYY.txt", "\n".join(lines).encode())


class TestCotRefresh:
    async def test_fetch_zip_sends_browser_user_agent(self, monkeypatch):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["ua"] = request.headers.get("user-agent", "")
            if "Mozilla" not in seen["ua"]:
                return httpx.Response(403)
            return httpx.Response(200, content=b"zip-bytes")

        real = cot.capped_get

        async def with_transport(url, **kwargs):
            return await real(url, transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(cot, "capped_get", with_transport)
        content = await cot._fetch_zip(cot.CFTC_TFF_URL_TEMPLATE.format(year=2026))
        assert content == b"zip-bytes"
        assert "Mozilla" in seen["ua"]

    async def test_fetch_zip_raises_on_http_error(self, monkeypatch):
        monkeypatch.setattr(cot, "capped_get", AsyncMock(return_value=None))
        with pytest.raises(RuntimeError):
            await cot._fetch_zip(cot.CFTC_TFF_URL_TEMPLATE.format(year=2026))

    async def test_failed_disagg_archive_does_not_block_tff(self, monkeypatch):
        report_date = utcnow().date() - timedelta(days=3)

        async def fake_fetch_zip(url: str) -> bytes:
            if "disagg" in url:
                raise RuntimeError("Client error '403 Forbidden'")
            return _tff_zip(report_date)

        monkeypatch.setattr(cot, "_fetch_zip", fake_fetch_zip)
        rows, errors = await cot._fetch_year(2026)
        assert sorted(r.instrument.code for r in rows) == ["DX", "ZN"]
        assert len(errors) == 1 and "disagg" in errors[0] and "403" in errors[0]

    async def test_refresh_stores_partial_result_and_overview_marks_stale(self, db, monkeypatch):
        report_date = utcnow().date() - timedelta(days=3)

        async def fake_fetch_zip(url: str) -> bytes:
            if "disagg" in url:
                raise RuntimeError("Client error '403 Forbidden'")
            return _tff_zip(report_date)

        monkeypatch.setattr(cot, "_fetch_zip", fake_fetch_zip)
        result = await cot.refresh_cot_snapshots(years=1)
        assert result["status"] == "partial"
        assert result["inserted"] == 2
        assert len(result["errors"]) == 1

        overview = await cot.get_latest_cot_overview(db)
        by = {i["code"]: i for i in overview["instruments"]}
        assert by["DX"]["stale"] is False and by["DX"]["commercial_net"] == 60
        assert by["ZN"]["stale"] is False
        assert by["GC"]["stale"] is True  # ohne Daten
        assert overview["stale"] is True

    async def test_stale_flag_follows_report_age(self, db):
        today = utcnow().date()
        for inst in cot.COT_INSTRUMENTS:
            age = 20 if inst.code == "CL" else 5
            db.add(MacroCotSnapshot(
                instrument=inst.code, report_date=today - timedelta(days=age),
                commercial_long=10, commercial_short=5, commercial_net=5,
                mm_long=7, mm_short=3, mm_net=4, oi_total=100,
            ))
        await db.commit()

        overview = await cot.get_latest_cot_overview(db)
        by = {i["code"]: i for i in overview["instruments"]}
        assert by["CL"]["stale"] is True
        assert all(by[c]["stale"] is False for c in ("GC", "SI", "DX", "ZN"))
        assert overview["stale"] is True

    async def test_overview_not_stale_when_all_reports_are_recent(self, db):
        today = utcnow().date()
        for inst in cot.COT_INSTRUMENTS:
            db.add(MacroCotSnapshot(
                instrument=inst.code, report_date=today - timedelta(days=cot.STALE_AFTER_DAYS),
                commercial_net=5, mm_net=4,
            ))
        await db.commit()
        overview = await cot.get_latest_cot_overview(db)
        assert overview["stale"] is False
        assert all(i["stale"] is False for i in overview["instruments"])


# ---------------------------------------------------------------------------
# K157 — Grössen- und Dekompressionsgrenzen
# ---------------------------------------------------------------------------


class TestSizeCaps:
    def test_zip_member_over_cap_is_rejected_before_unpacking(self):
        data = _zip_bytes("big.txt", b"0" * 200_000)  # gepackt wenige hundert Bytes
        assert len(data) < 2_000
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with pytest.raises(ValueError):
                _http.read_zip_member_capped(zf, "big.txt", max_bytes=100_000)
            assert len(_http.read_zip_member_capped(zf, "big.txt", max_bytes=200_000)) == 200_000

    def test_cot_extract_uses_the_capped_reader(self, monkeypatch):
        data = _zip_bytes("annual.txt", b"0" * 50_000)
        real = _http.read_zip_member_capped
        monkeypatch.setattr(
            cot, "read_zip_member_capped", lambda zf, name: real(zf, name, max_bytes=1_000),
        )
        with pytest.raises(ValueError):
            cot._extract_first_text_file(data)

    def test_cot_extract_returns_small_member(self):
        assert cot._extract_first_text_file(_zip_bytes("annual.txt", b"a,b\n1,2\n")) == b"a,b\n1,2\n"

    @staticmethod
    def _xlsx(rows: int) -> bytes:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        for i in range(rows):
            ws.append([f"ISIN{i}", "Name", 1.5])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_xlsx_within_limits_is_read(self):
        rows = _excel.read_xlsx(self._xlsx(20))
        assert len(rows) == 20
        assert rows[0][0] == "ISIN0"

    def test_xlsx_over_row_limit_returns_nothing(self, monkeypatch):
        monkeypatch.setattr(_excel, "MAX_XLSX_ROWS", 10)
        assert _excel.read_xlsx(self._xlsx(20)) == []

    def test_xlsx_over_cell_limit_returns_nothing(self, monkeypatch):
        monkeypatch.setattr(_excel, "MAX_XLSX_CELLS", 30)
        assert _excel.read_xlsx(self._xlsx(20)) == []

    def test_xlsx_over_unpacked_size_returns_nothing(self, monkeypatch):
        monkeypatch.setattr(_excel, "MAX_XLSX_UNZIPPED_BYTES", 100)
        assert _excel.read_xlsx(self._xlsx(20)) == []

    async def test_capped_request_reports_status_and_content_type(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x", headers={"content-type": "text/csv"})

        meta: dict = {}
        body = await _http.capped_get(
            "https://example.invalid/f", adapter="t", ticker="T",
            transport=httpx.MockTransport(handler), meta=meta,
        )
        assert body == b"x"
        assert meta == {"status": 200, "content_type": "text/csv"}


# ---------------------------------------------------------------------------
# GS03 — Börsen-Mapping der Industrieländer
# ---------------------------------------------------------------------------


class TestDevelopedMarketExchanges:
    @pytest.mark.parametrize("exchange,suffix", [
        ("Nyse Euronext - Euronext Paris", ".PA"),
        ("Nyse Euronext - Euronext Brussels", ".BR"),
        ("Nyse Euronext - Euronext Lisbon", ".LS"),
        ("Euronext Amsterdam", ".AS"),
        ("SIX Swiss Exchange", ".SW"),
        ("Nasdaq Omx Helsinki Ltd.", ".HE"),
        ("Nasdaq Omx Nordic", ".ST"),
        ("Omx Nordic Exchange Copenhagen A/S", ".CO"),
        ("Oslo Bors Asa", ".OL"),
        ("Tokyo Stock Exchange", ".T"),
        ("Toronto Stock Exchange", ".TO"),
        ("Asx - All Markets", ".AX"),
        ("Bolsa De Madrid", ".MC"),
        ("Borsa Italiana", ".MI"),
        ("Singapore Exchange", ".SI"),
        ("New Zealand Exchange Ltd", ".NZ"),
        # US bleibt US
        ("NASDAQ", ""),
        ("New York Stock Exchange Inc.", ""),
        ("Nyse Mkt Llc", ""),
    ])
    def test_suffix(self, exchange, suffix):
        assert exchange_to_suffix(exchange) == suffix

    def test_ticker_normalisation(self):
        assert exchange_to_yf_ticker("BP.", "London Stock Exchange") == "BP.L"
        assert exchange_to_yf_ticker("ATCO A", "Nasdaq Omx Nordic") == "ATCO-A.ST"
        assert exchange_to_yf_ticker("NOVO B", "Omx Nordic Exchange Copenhagen A/S") == "NOVO-B.CO"
        assert exchange_to_yf_ticker("TECK.B", "Toronto Stock Exchange") == "TECK-B.TO"
        # Schwellenländer-Schlüssel bleiben, wie sie waren
        assert exchange_to_yf_ticker("M&M", "National Stock Exchange Of India") == "M&M.NS"
        assert exchange_to_yf_ticker("700", "Hong Kong Exchanges And Clearing Ltd") == "0700.HK"

    def test_swda_csv_keeps_european_titles_apart_from_us_tickers(self):
        def row(ticker, name, location, exchange):
            return (f'"{ticker}","{name}","Industrials","Equity","x","1.00","x","x","x",'
                    f'"{location}","{exchange}","XXX"')

        text = "\n".join([
            '"iShares Core MSCI World UCITS ETF"',
            '"Fund Holdings as of","Oct 31, 2026"',
            '""',
            _ISHARES_HEADER.format(ticker_col="Ticker"),
            row("AAPL", "APPLE INC", "United States", "NASDAQ"),
            row("MC", "LVMH", "France", "Nyse Euronext - Euronext Paris"),
            row("SU", "SCHNEIDER ELECTRIC", "France", "Nyse Euronext - Euronext Paris"),
            row("SU", "SUNCOR ENERGY INC", "Canada", "Toronto Stock Exchange"),
            row("NESN", "NESTLE SA", "Switzerland", "SIX Swiss Exchange"),
            row("SAND", "SANDVIK", "Sweden", "Nasdaq Omx Nordic"),
            row("7203", "TOYOTA MOTOR CORP", "Japan", "Tokyo Stock Exchange"),
            row("BHP", "BHP GROUP LTD", "Australia", "Asx - All Markets"),
        ])
        rows = ish.parse_ishares_csv(text, "SWDA.L")
        by = {r["holding_ticker"]: r["holding_name"] for r in rows}
        assert by == {
            "AAPL": "APPLE INC",
            "MC.PA": "LVMH",
            "SU.PA": "SCHNEIDER ELECTRIC",
            "SU.TO": "SUNCOR ENERGY INC",
            "NESN.SW": "NESTLE SA",
            "SAND.ST": "SANDVIK",
            "7203.T": "TOYOTA MOTOR CORP",
            "BHP.AX": "BHP GROUP LTD",
        }
