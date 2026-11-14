"""Vollreview 11/2026, Welle 5 — Fixer «market».

R-marketscreen-1  US-Ticker ohne ISIN übernimmt keine fremde ISIN mehr (FMP bleibt)
R-marketscreen-2  abweichende Angaben stoppen den Holdings-Refresh nicht mehr:
                  die älteste Position gewinnt, der Konflikt steht in ``conflicts``
R-marketscreen-3  fred_no_api_key verkürzt den CH-Makro-Cache nicht
R-marketscreen-4  Ausfall des Dataroma-Echtzeit-Feeds verwirft das Grand Portfolio nicht
R-marketscreen-5  belegte Scan-Sperre: der Tagesscan wartet und meldet den Fehler
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

import services.ch_macro_service as chm
import services.etf_holdings_service as eh
import services.screening.dataroma_scraper as ds
import services.screening.screening_service as ss
import worker
from models.bucket import Bucket
from models.position import AssetType, Position, PriceSource
from models.screening import ScreeningScan
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets
from services.etf_adapters.base import EtfRef

pytestmark = pytest.mark.asyncio

ISIN_WORLD = "IE00BJ0KDQ92"
ISIN_JAPAN = "LU0274209740"
T0 = datetime(2026, 1, 1, 12, 0, 0)


async def _make_user(db) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(user_id=user.id, noticed_buckets_migration=True))
    await create_system_buckets(db, user.id)
    await db.commit()
    return user


async def _add_etf(
    db, user_id, ticker: str, *, name: str, isin: str | None = None, day: int = 0,
) -> Position:
    """ETF-Position; ``day`` setzt das Alter (created_at = T0 + day Tage)."""
    bucket = (await db.execute(
        select(Bucket).where(Bucket.user_id == user_id).order_by(Bucket.sort_order)
    )).scalars().first()
    pos = Position(
        user_id=user_id, bucket_id=bucket.id, ticker=ticker, name=name, type=AssetType.etf,
        currency="USD", price_source=PriceSource.yahoo, isin=isin,
        shares=Decimal("10"), cost_basis_chf=Decimal("1500"),
        created_at=T0 + timedelta(days=day),
    )
    db.add(pos)
    await db.commit()
    return pos


def _messages(mock) -> list[str]:
    """Formatierte Meldungen eines gepatchten Loggers."""
    return [c.args[0] % c.args[1:] if len(c.args) > 1 else c.args[0] for c in mock.call_args_list]


# ---------------------------------------------------------------------------
# R-marketscreen-1 — fremde ISIN lenkt einen Ticker mit Quelle nicht um
# ---------------------------------------------------------------------------


class TestForeignIsinDoesNotRedirect:
    async def test_us_ticker_without_isin_keeps_fmp(self, db):
        """Szenario des Fundes für US-ETFs: das Opfer hält JEPI ohne ISIN (Quelle FMP).
        Ein neues Konto legt JEPI mit Markenname und fremder ISIN an."""
        victim = await _make_user(db)
        attacker = await _make_user(db)
        await _add_etf(db, victim.id, "JEPI", name="JPMorgan Equity Premium Income ETF", day=0)
        await _add_etf(db, attacker.id, "JEPI", name="JPMorgan Irgendwas", isin=ISIN_JAPAN, day=5)

        with patch.object(eh.logger, "warning") as warn:
            refs, conflicts = await eh._resolve_active_etf_refs(db)

        assert [(r.ticker, r.isin) for r in refs] == [("JEPI", None)]
        assert eh.get_adapter(refs[0]) is None  # der Abruf bleibt bei FMP
        assert conflicts == [{
            "etf_ticker": "JEPI", "positions": 2,
            "chosen": {"source": "FMP", "isin": ISIN_JAPAN},
            "rejected": [{"source": "JPMorgan", "isin": ISIN_JAPAN}],
        }]
        assert any("JEPI" in m and "oldest wins" in m for m in _messages(warn))

    async def test_new_account_cannot_replace_an_existing_isin(self, db):
        victim = await _make_user(db)
        attacker = await _make_user(db)
        await _add_etf(db, victim.id, "XDWD.DE", name="Xtrackers MSCI World", isin=ISIN_WORLD, day=0)
        await _add_etf(db, attacker.id, "XDWD.DE", name="Xtrackers MSCI Japan", isin=ISIN_JAPAN, day=9)

        refs, conflicts = await eh._resolve_active_etf_refs(db)

        assert [r.isin_valid for r in refs] == [ISIN_WORLD]
        assert conflicts[0]["chosen"] == {"source": "Xtrackers", "isin": ISIN_WORLD}
        assert conflicts[0]["rejected"] == [{"source": "Xtrackers", "isin": ISIN_JAPAN}]

    async def test_age_decides_not_the_insert_order(self, db):
        """Die ältere Position gewinnt, auch wenn sie später in die Tabelle kam."""
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, a.id, "XDWD.DE", name="Xtrackers MSCI Japan", isin=ISIN_JAPAN, day=30)
        await _add_etf(db, b.id, "XDWD.DE", name="Xtrackers MSCI World", isin=ISIN_WORLD, day=1)

        refs = await eh._get_active_etf_refs(db)

        assert [r.isin_valid for r in refs] == [ISIN_WORLD]

    async def test_inherited_isin_of_another_brand_is_not_fetched(self):
        """Die älteste Position nennt Amundi ohne ISIN, eine jüngere Xtrackers mit ISIN:
        der Abruf mischt die beiden Angaben nicht."""
        ref, conflict = eh._pick_etf_ref("LYX0.DE", [
            EtfRef("LYX0.DE", None, "Amundi MSCI World"),
            EtfRef("LYX0.DE", ISIN_JAPAN, "Xtrackers MSCI Japan"),
        ])
        assert ref == EtfRef("LYX0.DE", None, "Amundi MSCI World")
        assert conflict["chosen"] == {"source": "Amundi", "isin": None}


# ---------------------------------------------------------------------------
# R-marketscreen-2 — kein Ticker fällt wegen fehlender Angaben aus
# ---------------------------------------------------------------------------


class TestMissingDetailsDoNotStopTheRefresh:
    @pytest.mark.parametrize("plain_first", [True, False])
    async def test_position_without_isin_and_brand_is_ignored(self, db, plain_first):
        """Szenario des Fundes: A pflegt Marke und ISIN, B weder noch."""
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, a.id, "XDWD.DE", name="Xtrackers MSCI World", isin=ISIN_WORLD,
                       day=5 if plain_first else 0)
        await _add_etf(db, b.id, "XDWD.DE", name="MSCI World 1C", day=0 if plain_first else 5)

        with patch.object(eh.logger, "warning") as warn:
            refs, conflicts = await eh._resolve_active_etf_refs(db)

        assert [(r.ticker, r.isin_valid) for r in refs] == [("XDWD.DE", ISIN_WORLD)]
        assert eh.get_adapter(refs[0]).name == "Xtrackers"
        assert conflicts == []
        warn.assert_not_called()

    async def test_same_isin_without_brand_is_ignored(self, db):
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, b.id, "XDWD.DE", name="MSCI World 1C", isin=ISIN_WORLD, day=0)
        await _add_etf(db, a.id, "XDWD.DE", name="Xtrackers MSCI World", isin=ISIN_WORLD, day=1)

        refs, conflicts = await eh._resolve_active_etf_refs(db)

        assert eh.get_adapter(refs[0]).name == "Xtrackers"
        assert conflicts == []

    async def test_isin_and_brand_from_two_positions_still_select_a_source(self, db):
        """Die eine Position trägt nur die ISIN, die andere nur die Marke."""
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, a.id, "XDWD.DE", name="MSCI World 1C", isin=ISIN_WORLD, day=0)
        await _add_etf(db, b.id, "XDWD.DE", name="Xtrackers MSCI World", day=1)

        refs, conflicts = await eh._resolve_active_etf_refs(db)

        assert [(r.name, r.isin_valid) for r in refs] == [("Xtrackers MSCI World", ISIN_WORLD)]
        assert conflicts == []

    async def test_isin_that_fails_the_format_counts_as_missing(self, db):
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, b.id, "XDWD.DE", name="Xtrackers MSCI World", isin="IE00-TIPPFEHLER", day=0)
        await _add_etf(db, a.id, "XDWD.DE", name="Xtrackers MSCI World", isin=ISIN_WORLD, day=1)

        refs, conflicts = await eh._resolve_active_etf_refs(db)

        assert [r.isin_valid for r in refs] == [ISIN_WORLD]
        assert conflicts == []

    async def test_us_ticker_keeps_fmp_against_a_newer_adapter_choice(self, db):
        """Szenario des Fundes: VOO, ein zweiter Nutzer nennt die Position «Amundi X»."""
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, a.id, "VOO", name="Vanguard S&P 500", day=0)
        await _add_etf(db, b.id, "VOO", name="Amundi X", isin="LU1781541179", day=3)

        refs, conflicts = await eh._resolve_active_etf_refs(db)

        assert [(r.ticker, r.name) for r in refs] == [("VOO", "Vanguard S&P 500")]
        assert eh.get_adapter(refs[0]) is None
        assert [c["etf_ticker"] for c in conflicts] == ["VOO"]
        assert conflicts[0]["rejected"] == [{"source": "Amundi", "isin": "LU1781541179"}]

    async def test_conflicting_ticker_is_refreshed_and_reported(self, db, monkeypatch):
        """Vorher fehlte der Ticker im Lauf, und das Ergebnis nannte ihn nirgends."""
        a = await _make_user(db)
        b = await _make_user(db)
        await _add_etf(db, a.id, "XDWD.DE", name="Xtrackers MSCI World", isin=ISIN_WORLD, day=0)
        await _add_etf(db, b.id, "XDWD.DE", name="Xtrackers MSCI Japan", isin=ISIN_JAPAN, day=2)
        fetched: list[EtfRef] = []

        async def fake_refresh(db_, ref, api_key):
            fetched.append(ref)
            return {"etf_ticker": ref.ticker, "source": "xtrackers", "count": 3}

        monkeypatch.setattr(eh, "_get_any_user_fmp_key", AsyncMock(return_value=""))
        monkeypatch.setattr(eh, "refresh_etf_holdings", fake_refresh)

        with patch.object(eh.logger, "warning") as warn:
            out = await eh.refresh_all_user_etfs(db)

        assert [(r.ticker, r.isin_valid) for r in fetched] == [("XDWD.DE", ISIN_WORLD)]
        assert [r["etf_ticker"] for r in out["refreshed"]] == ["XDWD.DE"]
        assert out["errors"] == []
        assert out["conflicts"] == [{
            "etf_ticker": "XDWD.DE", "positions": 2,
            "chosen": {"source": "Xtrackers", "isin": ISIN_WORLD},
            "rejected": [{"source": "Xtrackers", "isin": ISIN_JAPAN}],
        }]
        assert any("XDWD.DE" in m and "oldest wins" in m for m in _messages(warn))

    async def test_result_without_etfs_carries_the_conflicts_field(self, db, monkeypatch):
        monkeypatch.setattr(eh, "_get_any_user_fmp_key", AsyncMock(return_value=""))
        out = await eh.refresh_all_user_etfs(db)
        assert out == {"refreshed": [], "skipped": [], "conflicts": [], "etf_count": 0}


# ---------------------------------------------------------------------------
# R-marketscreen-3 — fred_no_api_key ist kein Ausfall einer Quelle
# ---------------------------------------------------------------------------


class TestChMacroTtlWithoutFredKey:
    async def test_missing_fred_key_keeps_the_long_ttl(self):
        assert chm.ch_macro_cache_ttl({"warnings": ["fred_no_api_key"]}) == chm.CH_MACRO_TTL_COMPLETE

    async def test_an_outage_next_to_the_missing_key_still_shortens(self):
        snapshot = {"warnings": ["fred_no_api_key", "fx_unavailable"]}
        assert chm.ch_macro_cache_ttl(snapshot) == chm.CH_MACRO_TTL_PARTIAL
        assert chm.ch_macro_cache_ttl({"warnings": ["ch_10y_unavailable"]}) == chm.CH_MACRO_TTL_PARTIAL
        assert chm.ch_macro_cache_ttl({"warnings": None}) == chm.CH_MACRO_TTL_COMPLETE

    async def test_snapshot_of_an_instance_without_fred_key(self, monkeypatch):
        """Szenario des Fundes: kein System-Key, kein Admin-Key, alle Quellen gesund."""
        async def healthy():
            return {"data": {"ok": True}, "warnings": []}

        for name in ("_fetch_snb_policy_rate", "_fetch_saron_with_delta", "_fetch_fx_pairs",
                     "_fetch_ch_inflation", "_fetch_smi_vs_sp500"):
            monkeypatch.setattr(chm, name, healthy)
        monkeypatch.setattr(chm, "_fred_key", lambda: None)

        snapshot = await chm.get_ch_macro_snapshot()

        assert snapshot["warnings"] == ["fred_no_api_key"]
        assert chm.ch_macro_cache_ttl(snapshot) == 21600


# ---------------------------------------------------------------------------
# R-marketscreen-4 — Dataroma: Teilausfall des Echtzeit-Feeds
# ---------------------------------------------------------------------------


def _portfolio_html(n: int) -> str:
    rows = "".join(
        f"<tr><td>T{i:03d}</td><td>Firma {i}</td><td>1.5</td><td>{3 + i % 5}</td></tr>"
        for i in range(n)
    )
    return f"<table><tr><td>Symbol</td><td>Stock</td><td>%</td><td>Ownership count</td></tr>{rows}</table>"


class TestDataromaRealtimeFeedOutage:
    @pytest.mark.parametrize("error", [RuntimeError("403"), TimeoutError()])
    async def test_feed_error_keeps_the_grand_portfolio(self, monkeypatch, error):
        """Szenario des Fundes: rt.php scheitert, portfolio.php liefert 100 Zeilen."""
        async def fetch(url, headers=None, timeout=15):
            if url == ds.RT_URL:
                raise error
            return _portfolio_html(100)

        monkeypatch.setattr(ds, "fetch_text", fetch)
        monkeypatch.setattr(ds, "_homepage_warmed", True)

        with patch.object(ds.logger, "error") as log_error:
            buys, portfolio = await ds.fetch_superinvestor_data()

        assert buys == []
        assert len(portfolio) == 100
        assert any("buys failed" in m for m in _messages(log_error))

    async def test_scan_step_counts_the_portfolio_when_the_feed_fails(self, db, monkeypatch):
        async def fetch(url, headers=None, timeout=15):
            if url == ds.RT_URL:
                raise RuntimeError("403")
            return _portfolio_html(100)

        monkeypatch.setattr(ds, "fetch_text", fetch)
        monkeypatch.setattr(ds, "_homepage_warmed", True)
        scan = ScreeningScan(status="running", steps=[
            {"source": "dataroma", "label": "Dataroma", "status": "running", "count": None},
        ])
        db.add(scan)
        await db.commit()

        result = await ss._run_source(db, scan, "dataroma", ds.fetch_superinvestor_data, asyncio.Lock())

        assert isinstance(result, tuple) and len(result[1]) == 100
        assert scan.steps[0]["status"] == "done"
        assert scan.steps[0]["count"] == 100

    async def test_portfolio_error_still_reaches_the_caller(self, monkeypatch):
        """K148 bleibt behoben: ohne Grand Portfolio gilt die Quelle als ausgefallen."""
        async def fetch(url, headers=None, timeout=15):
            if url == ds.PORTFOLIO_URL:
                raise RuntimeError("403")
            return ""

        monkeypatch.setattr(ds, "fetch_text", fetch)
        monkeypatch.setattr(ds, "_homepage_warmed", True)
        with pytest.raises(RuntimeError, match="403"):
            await ds.fetch_superinvestor_data()


# ---------------------------------------------------------------------------
# R-marketscreen-5 — Tagesscan und belegte Scan-Sperre
# ---------------------------------------------------------------------------


@pytest.fixture
def scan_env(monkeypatch):
    """Freie Sperre, leere Job-Health, Wartezeiten ohne echtes Schlafen."""
    ss.release_scan_lock()
    worker._reported_failures.clear()
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    yield sleeps
    ss.release_scan_lock()
    worker._reported_failures.clear()


async def _scan_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(ScreeningScan))).scalar()


class TestDailyScanAndBusyLock:
    async def test_busy_lock_is_reported_to_job_health(self, db, monkeypatch, scan_env):
        """Szenario des Fundes: die Sperre bleibt belegt, der Tagesscan findet nicht statt."""
        ran = AsyncMock()
        monkeypatch.setattr(ss, "_run_scan", ran)
        assert ss.try_acquire_scan_lock() is True  # ein anderer Scan hält die Sperre

        with patch.object(worker.logger, "info") as info:
            await worker._health_tracked(worker.daily_screening_scan, "daily_screening_scan")()

        assert worker._reported_failures == {
            "daily_screening_scan": "daily_screening_scan: scan lock busy",
        }
        ran.assert_not_called()
        assert not any("completed" in m for m in _messages(info))
        assert await _scan_count(db) == 0
        # Die fremde Sperre bleibt gehalten.
        assert ss.try_acquire_scan_lock() is False

    async def test_waiting_outlasts_a_stale_lock(self, scan_env):
        """Eine nach einem Absturz hängende Sperre läuft nach SCAN_LOCK_TTL_S ab.
        Der Job wartet länger, und die TTL bleibt nahe am Zeitlimit des Scans."""
        assert ss.try_acquire_scan_lock() is True

        assert await worker._wait_for_scan_lock() is False

        assert sum(scan_env) > ss.SCAN_LOCK_TTL_S
        assert ss.SCAN_TIMEOUT_S < ss.SCAN_LOCK_TTL_S <= ss.SCAN_TIMEOUT_S + 300

    async def test_scan_runs_once_the_stale_lock_expired(self, db, monkeypatch, scan_env):
        ran: list[tuple] = []

        async def fake_run(db_, scan_id):
            ran.append((scan_id, ss.get_active_scan_id()))

        monkeypatch.setattr(ss, "_run_scan", fake_run)
        assert ss.try_acquire_scan_lock() is True  # hängende Sperre eines toten Prozesses

        async def expire_after_three_waits(seconds):
            scan_env.append(seconds)
            if len(scan_env) == 3:
                ss.release_scan_lock()  # die TTL läuft ab

        monkeypatch.setattr(worker.asyncio, "sleep", expire_after_three_waits)

        await worker._health_tracked(worker.daily_screening_scan, "daily_screening_scan")()

        assert len(scan_env) == 3
        assert len(ran) == 1
        scan_id, active_id = ran[0]
        assert active_id == str(scan_id)  # der Scan lief unter der eigenen Sperre
        assert worker._reported_failures == {}
        assert await _scan_count(db) == 1
        # Nach dem Scan ist die Sperre wieder frei.
        assert ss.try_acquire_scan_lock() is True

    async def test_free_lock_starts_the_scan_without_waiting(self, db, monkeypatch, scan_env):
        ran = AsyncMock()
        monkeypatch.setattr(ss, "_run_scan", ran)

        with patch.object(worker.logger, "info") as info:
            await worker.daily_screening_scan()

        assert scan_env == []
        ran.assert_awaited_once()
        assert any("completed" in m for m in _messages(info))

    async def test_lock_is_released_when_the_scan_row_cannot_be_created(self, monkeypatch, scan_env):
        class _BrokenSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def add(self, obj):
                pass

            async def commit(self):
                raise RuntimeError("db kaputt")

        monkeypatch.setattr(worker, "async_session", lambda: _BrokenSession())

        with pytest.raises(RuntimeError, match="db kaputt"):
            await worker.daily_screening_scan()

        assert ss.try_acquire_scan_lock() is True
