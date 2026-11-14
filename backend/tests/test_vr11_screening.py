"""Vollreview 11/2026 — Fixer «screening».

K021  globale Sperre gegen parallele Scans, 409 mit scan_id
K055  OpenFIGI-Ausfall wird nicht mehr als «unauflösbar» gecacht
K072  Form 4: verarbeitete Filings werden nicht neu geladen
X21   Form 4: rohes XML statt der XSL-Ansicht
K073  Backtest: schlanke Zeilen, vorbereitete Serien, Rechnung im Thread
K085  SIX-Paginierung begrenzt, Zeitlimit je Quelle und je Scan
K138  Item-4-Regex läuft linear
K147  überlange Fremdwerte, rollback im API-Pfad
K148  Scraper-Fehler erscheinen als error statt «done, 0»
K171  OpenInsider: kein Redirect auf fremde Hosts, Grössenlimit
K157  Dataroma: Tabellen-Parser läuft linear
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import threading
import time
import types
import uuid
from datetime import date, datetime, timedelta

import httpx
import numpy as np
import pandas as pd
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import api.screening as api_screening
import services.screening.activist_tracker as act
import services.screening.backtest_harness as bh
import services.screening.capitoltrades_scraper as ct
import services.screening.dataroma_scraper as ds
import services.screening.openinsider_scraper as oi
import services.screening.screening_service as ss
import services.screening.sec_13f_service as s13
import services.screening.sec_buyback_service as bb
import services.screening.sec_form4_service as f4
import services.screening.six_insider_service as six
from models.fund_holdings import FundHoldingsSnapshot
from models.screening import ScreeningResult, ScreeningScan
from services.screening.scan_health import get_composite_scan_health

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"


async def _register_login(client: AsyncClient, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _free_scan_lock():
    """Die Sperre lebt im Prozess (kein Redis im Test): vor und nach jedem Test frei."""
    ss.release_scan_lock()
    yield
    ss.release_scan_lock()


async def _new_scan(db, steps=None, status="pending") -> ScreeningScan:
    scan = ScreeningScan(status=status, steps=steps or [])
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    return scan


# ---------------------------------------------------------------------------
# K021 — globale Sperre
# ---------------------------------------------------------------------------

class TestScanLock:
    async def test_second_start_answers_409_with_running_scan_id(self, client, db, monkeypatch):
        started: list[tuple] = []

        async def fake_background(scan_id, lock_held=False):
            started.append((scan_id, lock_held))  # Scan "läuft": Sperre bleibt gehalten

        monkeypatch.setattr(api_screening, "_run_scan_background", fake_background)
        headers = await _register_login(client, "vr11-scan-lock@example.com")

        first = await client.post("/api/screening/scan", headers=headers)
        assert first.status_code == 200, first.text
        scan_id = first.json()["scan_id"]

        second = await client.post("/api/screening/scan", headers=headers)
        assert second.status_code == 409
        assert second.json()["scan_id"] == scan_id
        assert second.json()["detail"] == ss.SCAN_BUSY_MESSAGE

        # Ein anderer Nutzer bekommt dieselbe Antwort: die Sperre ist global.
        other = await _register_login(client, "vr11-scan-lock-b@example.com")
        third = await client.post("/api/screening/scan", headers=other)
        assert third.status_code == 409
        assert third.json()["scan_id"] == scan_id

        assert started == [(uuid.UUID(scan_id), True)]
        n_scans = (await db.execute(select(func.count()).select_from(ScreeningScan))).scalar()
        assert n_scans == 1

    async def test_start_works_again_after_the_scan_released_the_lock(self, client, monkeypatch):
        async def fake_background(scan_id, lock_held=False):
            ss.release_scan_lock()  # wie run_scan am Ende

        monkeypatch.setattr(api_screening, "_run_scan_background", fake_background)
        headers = await _register_login(client, "vr11-scan-again@example.com")
        assert (await client.post("/api/screening/scan", headers=headers)).status_code == 200
        assert (await client.post("/api/screening/scan", headers=headers)).status_code == 200

    async def test_run_scan_without_lock_ends_when_another_scan_runs(self, db, monkeypatch):
        """Worker-Pfad und externer Zwilling rufen run_scan ohne eigene Sperre."""
        ran = []

        async def fake_run(db_, scan_id):
            ran.append(scan_id)

        monkeypatch.setattr(ss, "_run_scan", fake_run)
        assert ss.try_acquire_scan_lock() is True  # ein anderer Scan läuft
        scan = await _new_scan(db)

        await ss.run_scan(db, scan.id)

        assert ran == []
        await db.refresh(scan)
        assert scan.status == "error"
        assert scan.error == ss.SCAN_BUSY_MESSAGE
        # Die fremde Sperre bleibt gehalten.
        assert ss.try_acquire_scan_lock() is False

    async def test_run_scan_releases_the_lock_after_success_and_failure(self, db, monkeypatch):
        async def ok(db_, scan_id):
            assert ss.get_active_scan_id() == str(scan_id)

        monkeypatch.setattr(ss, "_run_scan", ok)
        scan = await _new_scan(db)
        await ss.run_scan(db, scan.id)
        assert ss.get_active_scan_id() is None
        assert ss.try_acquire_scan_lock() is True

        async def boom(db_, scan_id):
            raise RuntimeError("kaputt")

        monkeypatch.setattr(ss, "_run_scan", boom)
        with pytest.raises(RuntimeError):
            await ss.run_scan(db, scan.id, lock_held=True)
        assert ss.try_acquire_scan_lock() is True

    async def test_lock_ttl_outlasts_the_scan_timeout(self):
        assert ss.SCAN_LOCK_TTL_S > ss.SCAN_TIMEOUT_S > ss.SOURCE_TIMEOUT_S


# ---------------------------------------------------------------------------
# K085 — Zeitlimits und SIX-Paginierung
# ---------------------------------------------------------------------------

class TestTimeouts:
    async def test_hanging_scan_ends_with_timeout_and_frees_the_lock(self, db, monkeypatch):
        async def hang(db_, scan_id):
            await asyncio.sleep(30)

        monkeypatch.setattr(ss, "_run_scan", hang)
        monkeypatch.setattr(ss, "SCAN_TIMEOUT_S", 0.05)
        scan = await _new_scan(db)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ss.run_scan(db, scan.id), timeout=5)
        assert ss.try_acquire_scan_lock() is True

    async def test_hanging_source_becomes_an_error_step(self, db, monkeypatch):
        monkeypatch.setattr(ss, "SOURCE_TIMEOUT_S", 0.05)
        scan = await _new_scan(db, steps=[{"source": "activist", "status": "running", "count": None}])

        async def hang():
            await asyncio.sleep(30)

        result = await asyncio.wait_for(
            ss._run_source(db, scan, "activist", hang, asyncio.Lock()), timeout=5,
        )
        assert isinstance(result, asyncio.TimeoutError)
        assert scan.steps[0]["status"] == "error"


def _six_page(n: int, offset: int = 0) -> list[dict]:
    return [{"notificationId": offset + i, "securityTypeCode": "1"} for i in range(n)]


class TestSixPagination:
    async def test_api_ignoring_page_number_does_not_loop_forever(self, monkeypatch):
        calls = []

        async def same_page(url, params=None, timeout=15):
            calls.append(params["pageNumber"])
            return _six_page(100)

        monkeypatch.setattr(six, "fetch_json", same_page)
        monkeypatch.setattr(six, "_REQUEST_DELAY", 0)

        txns = await asyncio.wait_for(six._fetch_transactions(90), timeout=5)
        assert len(txns) == 100  # die wiederholte Seite zählt nicht doppelt
        assert calls == [1, 2]

    async def test_page_limit_stops_endless_distinct_pages(self, monkeypatch):
        async def endless(url, params=None, timeout=15):
            return _six_page(100, offset=params["pageNumber"] * 1000)

        monkeypatch.setattr(six, "fetch_json", endless)
        monkeypatch.setattr(six, "_REQUEST_DELAY", 0)
        monkeypatch.setattr(six, "_MAX_PAGES", 3)

        txns = await asyncio.wait_for(six._fetch_transactions(90), timeout=5)
        assert len(txns) == 300

    async def test_normal_pagination_reads_until_the_short_page(self, monkeypatch):
        async def pages(url, params=None, timeout=15):
            return _six_page(100, 0) if params["pageNumber"] == 1 else _six_page(40, 1000)

        monkeypatch.setattr(six, "fetch_json", pages)
        monkeypatch.setattr(six, "_REQUEST_DELAY", 0)
        assert len(await six._fetch_transactions(90)) == 140

    async def test_first_page_error_reaches_the_caller(self, monkeypatch):
        async def boom(url, params=None, timeout=15):
            raise RuntimeError("403")

        monkeypatch.setattr(six, "fetch_json", boom)
        with pytest.raises(RuntimeError):
            await six._fetch_transactions(90)

    async def test_later_page_error_keeps_what_was_read(self, monkeypatch):
        async def flaky(url, params=None, timeout=15):
            if params["pageNumber"] == 2:
                raise RuntimeError("timeout")
            return _six_page(100)

        monkeypatch.setattr(six, "fetch_json", flaky)
        monkeypatch.setattr(six, "_REQUEST_DELAY", 0)
        assert len(await six._fetch_transactions(90)) == 100


# ---------------------------------------------------------------------------
# K055 — OpenFIGI
# ---------------------------------------------------------------------------

class _FakeCache:
    def __init__(self):
        self.store: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=0):
        self.store[key] = value


class _FigiClient:
    """Erster Batch scheitert (429 auch nach dem Backoff), zweiter antwortet."""

    def __init__(self):
        self.calls = 0

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        request = httpx.Request("POST", url)
        if {job["idValue"] for job in json} == {"AAA", "BBB"}:
            return httpx.Response(429, request=request)
        return httpx.Response(200, request=request, json=[
            {"data": [{"ticker": "NVDA", "exchCode": "US", "securityType": "Common Stock"}]},
            {"warning": "No identifier found."},
        ])


class TestOpenFigiOutage:
    async def test_lookup_omits_cusips_of_a_failed_batch(self, monkeypatch):
        client = _FigiClient()
        monkeypatch.setattr(s13, "get_async_client", lambda: client)
        monkeypatch.setattr(s13, "OPENFIGI_JOBS_PER_REQ", 2)
        monkeypatch.setattr(s13, "OPENFIGI_DELAY", 0)

        async def no_sleep(_seconds):
            return None

        monkeypatch.setattr(s13.asyncio, "sleep", no_sleep)

        out = await s13._openfigi_lookup(["AAA", "BBB", "CCC", "DDD"])
        # CCC aufgelöst, DDD beantwortet ohne Treffer, AAA/BBB ohne Antwort.
        assert out == {"CCC": "NVDA", "DDD": ""}

    async def test_resolve_caches_only_answered_cusips_and_raises(self, monkeypatch):
        fake = _FakeCache()
        monkeypatch.setattr(s13, "cache", fake)

        async def lookup(cusips):
            return {"CCC": "ORCL", "DDD": ""}  # EEE: Batch gescheitert

        monkeypatch.setattr(s13, "_openfigi_lookup", lookup)

        with pytest.raises(s13.CusipLookupIncomplete):
            await s13.resolve_cusips(["CCC", "DDD", "EEE"])

        assert fake.store[f"{s13._FIGI_CACHE_PREFIX}CCC"] == "ORCL"
        assert fake.store[f"{s13._FIGI_CACHE_PREFIX}DDD"] == ""
        assert f"{s13._FIGI_CACHE_PREFIX}EEE" not in fake.store  # kein Negativ-Cache

    async def test_fund_is_failed_and_nothing_is_stored_during_an_outage(self, db, monkeypatch):
        fake = _FakeCache()
        monkeypatch.setattr(s13, "cache", fake)
        monkeypatch.setattr(s13, "SEC_DELAY", 0)

        async def filing(cik, fund_name):
            return {
                "filing_date": "2026-11-10", "period_date": "2026-09-30",
                "accession_number": "0001067983-26-000001", "cik_raw": "1067983",
            }

        async def infotable(cik_raw, accession):
            return "<informationTable/>"

        async def outage(cusips):
            return {}

        monkeypatch.setattr(s13, "_find_latest_13f_filing", filing)
        monkeypatch.setattr(s13, "_fetch_infotable_xml", infotable)
        monkeypatch.setattr(s13, "_parse_infotable_xml", lambda xml: [
            {"issuer_name": "APPLE INC", "cusip": "037833100", "shares": 10, "value_1000": 5},
        ])
        monkeypatch.setattr(s13, "_openfigi_lookup", outage)

        # Der Namens-Fallback KÖNNTE auflösen. Er darf den Ausfall nicht überdecken.
        res = await s13._refresh_fund_13f(db, "0001067983", "Testfonds", {"APPLE INC": "AAPL"})

        assert res["status"] == "failed"
        stored = (await db.execute(select(func.count()).select_from(FundHoldingsSnapshot))).scalar()
        assert stored == 0  # nächster Lauf lädt das Filing erneut
        assert fake.store == {}


# ---------------------------------------------------------------------------
# X21 / K072 — Form 4
# ---------------------------------------------------------------------------

# Fixture nach dem SEC-Schema «ownershipDocument» (kein echtes Filing).
_FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion>
  <documentType>4</documentType>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001214156</rptOwnerCik>
      <rptOwnerName>COOK TIMOTHY D</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-11-03</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>P</transactionCode>
        <equitySwapInvolved>0</equitySwapInvolved>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>225.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

# So sieht die XSL-Ansicht aus, die submissions.json als primaryDocument listet.
_FORM4_HTML_VIEW = (
    "<!DOCTYPE html><html><head><title>SEC FORM 4</title></head>"
    "<body><table><tr><td>COOK TIMOTHY D<br></td></tr></table></body></html>"
)

_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000123"


class TestForm4RawXml:
    async def test_xsl_prefix_is_stripped_from_the_primary_document(self, monkeypatch):
        urls = []

        async def fake_fetch_text(url, headers=None, timeout=15):
            urls.append(url)
            return _FORM4_XML

        monkeypatch.setattr(f4, "fetch_text", fake_fetch_text)
        xml = await f4._fetch_form4_xml(
            "0000320193", "0000320193-26-000123", "xslF345X05/wk-form4_1762300000.xml",
        )
        assert xml == _FORM4_XML
        assert urls == [f"{_ARCHIVE}/wk-form4_1762300000.xml"]

    async def test_html_view_falls_back_to_the_filing_index(self, monkeypatch):
        urls = []

        async def fake_fetch_text(url, headers=None, timeout=15):
            urls.append(url)
            if url.endswith("/odd/form4.xml"):
                return _FORM4_HTML_VIEW
            if url.endswith("/"):
                return '<a href="/Archives/edgar/data/320193/000032019326000123/form4.xml">form4.xml</a>'
            return _FORM4_XML

        monkeypatch.setattr(f4, "fetch_text", fake_fetch_text)
        xml = await f4._fetch_form4_xml("0000320193", "0000320193-26-000123", "odd/form4.xml")
        assert xml == _FORM4_XML
        assert urls[-1] == f"{_ARCHIVE}/form4.xml"

    async def test_raw_xml_yields_the_transaction(self):
        rows = f4._parse_form4_xml(_FORM4_XML, "AAPL", date(2026, 11, 4))
        assert len(rows) == 1
        row = rows[0]
        assert row["ticker"] == "AAPL"
        assert row["insider_name"] == "COOK TIMOTHY D"
        assert row["insider_role"] == "Chief Executive Officer / Director"
        assert row["transaction_code"] == "P"
        assert row["transaction_date"] == date(2026, 11, 3)
        assert row["shares"] == 1000
        assert float(row["value_usd"]) == 225500.0

    async def test_html_view_is_reported_as_unreadable(self, caplog):
        with caplog.at_level(logging.WARNING, logger=f4.logger.name):
            assert f4._parse_form4_xml(_FORM4_HTML_VIEW, "AAPL", date(2026, 11, 4)) is None
        assert any("parse error" in r.message for r in caplog.records)


class _Form4Db:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.inserts = 0
        self.commits = 0

    async def execute(self, stmt, *args, **kwargs):
        if self.fail:
            raise RuntimeError("db down")
        self.inserts += 1
        return types.SimpleNamespace(rowcount=1)

    async def commit(self):
        self.commits += 1


def _patch_form4_filings(monkeypatch, documents: dict[str, str | None]) -> list[str]:
    """documents: Accession -> Dokument. Gibt die Liste der geladenen Accessions zurück."""
    fetched: list[str] = []

    async def filings(cik, since, max_count=20):
        return [
            {"accession_number": acc, "filing_date": date(2026, 11, 4), "primary_document": "f.xml"}
            for acc in documents
        ]

    async def fetch(cik, accession, primary_doc):
        fetched.append(accession)
        return documents[accession]

    monkeypatch.setattr(f4, "_find_recent_form4_filings", filings)
    monkeypatch.setattr(f4, "_fetch_form4_xml", fetch)
    monkeypatch.setattr(f4, "SEC_DELAY", 0)
    return fetched


class TestForm4SeenFilings:
    async def test_processed_filings_are_not_downloaded_again(self, monkeypatch):
        acc_a, acc_b = f"a-{uuid.uuid4()}", f"b-{uuid.uuid4()}"
        fetched = _patch_form4_filings(monkeypatch, {acc_a: _FORM4_XML, acc_b: _FORM4_XML})
        db = _Form4Db()

        assert await f4.refresh_form4_for_ticker(db, "AAPL", "0000320193") == 1
        assert sorted(fetched) == sorted([acc_a, acc_b])

        fetched.clear()
        assert await f4.refresh_form4_for_ticker(db, "AAPL", "0000320193") == 0
        assert fetched == []  # vorher: jeden Tag alle Filings der letzten 90 Tage

    async def test_same_filing_is_processed_per_ticker(self, monkeypatch):
        """GOOG und GOOGL teilen sich CIK und Filings, die Zeilen entstehen je Ticker."""
        acc = f"c-{uuid.uuid4()}"
        fetched = _patch_form4_filings(monkeypatch, {acc: _FORM4_XML})
        await f4.refresh_form4_for_ticker(_Form4Db(), "GOOG", "0001652044")
        await f4.refresh_form4_for_ticker(_Form4Db(), "GOOGL", "0001652044")
        assert fetched == [acc, acc]

    async def test_unreadable_or_missing_documents_are_retried(self, monkeypatch):
        acc_html, acc_none = f"h-{uuid.uuid4()}", f"n-{uuid.uuid4()}"
        fetched = _patch_form4_filings(
            monkeypatch, {acc_html: _FORM4_HTML_VIEW, acc_none: None},
        )
        db = _Form4Db()
        await f4.refresh_form4_for_ticker(db, "AAPL", "0000320193")
        fetched.clear()
        await f4.refresh_form4_for_ticker(db, "AAPL", "0000320193")
        assert sorted(fetched) == sorted([acc_html, acc_none])

    async def test_failed_insert_does_not_mark_the_filing(self, monkeypatch):
        acc = f"f-{uuid.uuid4()}"
        fetched = _patch_form4_filings(monkeypatch, {acc: _FORM4_XML})
        with pytest.raises(RuntimeError):
            await f4.refresh_form4_for_ticker(_Form4Db(fail=True), "AAPL", "0000320193")
        fetched.clear()
        await f4.refresh_form4_for_ticker(_Form4Db(), "AAPL", "0000320193")
        assert fetched == [acc]


# ---------------------------------------------------------------------------
# K073 — Backtest
# ---------------------------------------------------------------------------

def _old_first_price(prices: pd.Series, start: date, end_exclusive: date | None = None):
    """Die Fassung vor dem Fix, als Orakel."""
    if prices is None or len(prices) == 0:
        return None
    s = prices.dropna().sort_index()
    if s.empty:
        return None
    idx = pd.to_datetime(s.index)
    mask = idx >= pd.Timestamp(start)
    if end_exclusive is not None:
        mask = mask & (idx < pd.Timestamp(end_exclusive))
    if not mask.any():
        return None
    return float(s.to_numpy()[mask.argmax()])


def _series(start: date, days: int, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=days)
    return pd.Series(100 + rng.normal(0, 1, len(idx)).cumsum(), index=idx)


class TestBacktestPreparedSeries:
    async def test_window_lookup_matches_the_old_implementation(self):
        rng = random.Random(7)
        base = _series(date(2025, 1, 1), 260, seed=1)
        # Lücken, NaN und unsortierter Index wie in echten Serien.
        gappy = base.drop(base.index[rng.sample(range(len(base)), 40)])
        gappy.iloc[rng.sample(range(len(gappy)), 15)] = np.nan
        shuffled = gappy.sample(frac=1.0, random_state=3)

        for series in (base, gappy, shuffled):
            prepared = bh.prepare_series(series)
            for _ in range(400):
                start = date(2024, 12, 1) + timedelta(days=rng.randrange(0, 450))
                end = start + timedelta(days=rng.choice([1, 3, 30, 90])) if rng.random() < 0.6 else None
                expected = _old_first_price(series, start, end)
                assert bh._first_price_in_window(series, start, end) == expected
                assert bh._first_price_prepared(prepared, start, end) == expected

    async def test_forward_return_accepts_a_prepared_series(self):
        series = _series(date(2025, 1, 1), 260, seed=2)
        today = date(2026, 6, 1)
        for days in bh.FORWARD_WINDOWS:
            plain = bh.compute_forward_return(series, date(2025, 3, 3), days, today)
            prepared = bh.compute_forward_return(bh.prepare_series(series), date(2025, 3, 3), days, today)
            assert plain is not None and plain == prepared

    async def test_ten_thousand_snapshots_take_well_under_the_old_runtime(self):
        """Vorher 2,6 ms je Snapshot (26 s für 10 000). Grenze mit viel Reserve."""
        start = date(2025, 1, 1)
        price_map = {f"T{i}": _series(start, 300, seed=i) for i in range(50)}
        price_map[bh.BASELINE_TICKER] = _series(start, 300, seed=999)
        rows = [
            types.SimpleNamespace(
                ticker=f"T{i % 50}", signals={"buyback": {}}, price_usd=100.0,
                started_at=datetime(2025, 1, 6) + timedelta(days=i % 150),
            )
            for i in range(10_000)
        ]
        t0 = time.perf_counter()
        samples = bh.compute_excess_samples(rows, price_map, date(2026, 6, 1))
        elapsed = time.perf_counter() - t0
        assert len(samples) == 10_000
        assert elapsed < 5.0, f"{elapsed:.1f}s"

    async def test_samples_are_computed_off_the_event_loop_from_lean_rows(self, db, monkeypatch):
        started = datetime.utcnow() - timedelta(days=200)
        scan = ScreeningScan(status="completed", started_at=started, finished_at=started, steps=[
            {"source": "x", "status": "done", "count": 1},
        ])
        running = ScreeningScan(status="running", started_at=started, steps=[])
        db.add_all([scan, running])
        await db.commit()
        db.add_all([
            ScreeningResult(scan_id=scan.id, ticker="AAA", name="A", score=3, score_display=30,
                            signals={"buyback": {"filing_date": "x"}}, price_usd=10.0, sector_bonus=1),
            ScreeningResult(scan_id=scan.id, ticker="GONE", name="G", score=1, score_display=10,
                            signals={}, sector_bonus=0),
            ScreeningResult(scan_id=running.id, ticker="AAA", name="A", score=1, score_display=10,
                            signals={}, sector_bonus=0),
        ])
        await db.commit()

        rows = await bh.load_snapshots()
        assert len(rows) == 2  # nur abgeschlossene Scans
        row = next(r for r in rows if r.ticker == "AAA")
        assert not isinstance(row, ScreeningResult) and not hasattr(row, "_sa_instance_state")
        assert (row.signals, row.price_usd, row.sector_bonus) == ({"buyback": {"filing_date": "x"}}, 10.0, 1)
        assert row.started_at.date() == started.date()

        series_start = started.date() - timedelta(days=10)
        prices = {
            "AAA": _series(series_start, 200, seed=5),
            bh.BASELINE_TICKER: _series(series_start, 200, seed=6),
        }

        async def fake_fetch(tickers, start, end):
            assert tickers == ["AAA", "GONE"]
            return prices

        threads = []
        real_compute = bh.compute_excess_samples

        def spy_compute(*args, **kwargs):
            threads.append(threading.current_thread())
            return real_compute(*args, **kwargs)

        monkeypatch.setattr(bh, "fetch_price_histories", fake_fetch)
        monkeypatch.setattr(bh, "compute_excess_samples", spy_compute)

        meta = await bh.collect_per_signal_samples(dict(bh.DEFAULT_WEIGHTS))

        assert threads and threads[0] is not threading.main_thread()
        assert meta["n_samples"] == 1  # GONE hat keine Kursreihe
        signals, excess = meta["samples"][0]
        assert signals == {"buyback": {"filing_date": "x"}}
        today = datetime.now().date()
        for window in bh.FORWARD_WINDOWS:
            expected = (
                bh.compute_forward_return(prices["AAA"], started.date(), window, today, entry_fallback=10.0)
                - bh.compute_forward_return(prices[bh.BASELINE_TICKER], started.date(), window, today)
            )
            assert excess[window] == pytest.approx(expected)

    async def test_cli_harness_buckets_the_same_lean_rows(self, db, monkeypatch, tmp_path):
        started = datetime.utcnow() - timedelta(days=200)
        scan = ScreeningScan(status="completed", started_at=started, finished_at=started, steps=[])
        db.add(scan)
        await db.commit()
        db.add_all([
            # buyback +2, sector_bonus +1: Score 3, Bucket "3-4"
            ScreeningResult(scan_id=scan.id, ticker="AAA", name="A", score=3, score_display=30,
                            signals={"buyback": {"filing_date": "x"}}, price_usd=10.0, sector_bonus=1),
            # ohne Kursreihe: zählt im Bucket, liefert aber keinen Return
            ScreeningResult(scan_id=scan.id, ticker="GONE", name="G", score=0, score_display=0,
                            signals={}, sector_bonus=0),
        ])
        await db.commit()

        series_start = started.date() - timedelta(days=10)
        prices = {
            "AAA": _series(series_start, 200, seed=5),
            bh.BASELINE_TICKER: _series(series_start, 200, seed=6),
        }

        async def fake_fetch(tickers, start, end):
            return prices

        monkeypatch.setattr(bh, "fetch_price_histories", fake_fetch)
        out = tmp_path / "backtest.csv"
        config = bh.HarnessConfig(
            profile="default", weights=dict(bh.DEFAULT_WEIGHTS), min_snapshots=1, output=out,
        )
        assert await bh.run_harness(config) == 0

        rows = {line.split(",")[0]: line.split(",") for line in out.read_text().splitlines() if line}
        today = datetime.now().date()
        expected = (
            bh.compute_forward_return(prices["AAA"], started.date(), 30, today, entry_fallback=10.0)
            - bh.compute_forward_return(prices[bh.BASELINE_TICKER], started.date(), 30, today)
        )
        assert rows["3-4"][1:4] == ["1", "1", f"{expected:.4f}"]
        assert rows["0"][1:3] == ["1", "0"]


# ---------------------------------------------------------------------------
# K138 — Item-4-Regex
# ---------------------------------------------------------------------------

class TestItem4Regex:
    async def test_long_separator_run_no_longer_blocks(self):
        # 400 Trennzeichen brauchten vorher 6,6 s.
        text = "Item 4" + " ." * 200 + "x" * 3000
        t0 = time.perf_counter()
        act._extract_item4(text)
        assert time.perf_counter() - t0 < 1.0

    async def test_item4_is_still_extracted(self):
        body = "The Reporting Persons acquired the Shares for investment purposes and seek board representation. " * 2
        text = f"<p>Item 4. Purpose of Transaction.</p> <p>{body}</p> Item 5. Interest in Securities"
        excerpt = act._extract_item4(text)
        assert excerpt.startswith("The Reporting Persons acquired the Shares")
        assert "board_representation" in act._derive_purpose_tags(excerpt)


# ---------------------------------------------------------------------------
# K147 — überlange Fremdwerte, rollback im API-Pfad
# ---------------------------------------------------------------------------

def _patch_scan_sources(monkeypatch, cluster_buys: list[dict]) -> dict:
    seen: dict = {}

    async def cluster():
        return cluster_buys

    async def empty_list():
        return []

    async def empty_dict():
        return {}

    async def empty_pair():
        return [], []

    async def no_db_source(fn):
        return []

    async def enrich(tickers):
        seen["enriched"] = list(tickers)
        return {}, {}

    async def no_classification(db_, tickers):
        raise RuntimeError("keine Branchendaten im Test")

    monkeypatch.setattr(ss, "fetch_cluster_buys", cluster)
    for name in ("fetch_large_buys", "fetch_buybacks", "fetch_congressional_buys",
                 "fetch_activist_positions", "fetch_six_insider_buys"):
        monkeypatch.setattr(ss, name, empty_list)
    monkeypatch.setattr(ss, "fetch_superinvestor_data", empty_pair)
    monkeypatch.setattr(ss, "fetch_short_trends", empty_dict)
    monkeypatch.setattr(ss, "fetch_ftd_data", empty_dict)
    monkeypatch.setattr(ss, "_isolated_db_call", no_db_source)
    monkeypatch.setattr(ss, "enrich_scored_tickers", enrich)
    monkeypatch.setattr(ss, "load_classification_inputs", no_classification)
    monkeypatch.setattr(ss, "prefetch_close_series", lambda tickers: None)
    monkeypatch.setattr(ss, "compute_moving_averages", lambda ticker, windows: {})
    monkeypatch.setattr(ss, "get_next_earnings_date", lambda ticker: None)
    return seen


class TestForeignValues:
    async def test_overlong_values_do_not_reach_yahoo_or_the_database(self, db, monkeypatch):
        seen = _patch_scan_sources(monkeypatch, [
            {"ticker": "GOOD", "company": "N" * 300, "industry": "I" * 150, "insider_count": 3},
            {"ticker": "X" * 31, "company": "Zu langer Ticker"},
            {"ticker": "NOT A TICKER", "company": "Kein Ticker"},
        ])
        scan = await _new_scan(db)

        await ss.run_scan(db, scan.id)

        await db.refresh(scan)
        assert scan.status == "completed"
        assert scan.result_count == 1
        assert seen["enriched"] == ["GOOD"]
        rows = (await db.execute(select(ScreeningResult))).scalars().all()
        assert [r.ticker for r in rows] == ["GOOD"]
        assert rows[0].name == "N" * 200
        assert rows[0].sector == "I" * 100

    async def test_api_path_closes_the_scan_after_a_failed_commit(self, db, monkeypatch):
        """Ohne rollback warf db.get PendingRollbackError; der Scan blieb auf running."""
        async def failing_run(session, scan_id, *, lock_held=False):
            scan = await session.get(ScreeningScan, scan_id)
            scan.status = "running"
            await session.commit()
            session.add(ScreeningResult(scan_id=scan_id, ticker=None, name="x"))
            await session.commit()  # NOT NULL verletzt: Session braucht ein rollback

        monkeypatch.setattr(ss, "run_scan", failing_run)
        scan = await _new_scan(db)

        await api_screening._run_scan_background(scan.id)

        await db.refresh(scan)
        assert scan.status == "error"
        assert scan.error == "Scan fehlgeschlagen"


# ---------------------------------------------------------------------------
# K148 — Scraper-Fehler sichtbar machen
# ---------------------------------------------------------------------------

class TestSourceFailuresAreVisible:
    async def test_empty_result_of_a_never_empty_source_is_an_error(self, db):
        scan = await _new_scan(db, steps=[
            {"source": "dataroma", "label": "Dataroma", "status": "running", "count": None},
            {"source": "activist", "label": "Aktivisten", "status": "running", "count": None},
        ])

        async def empty_pair():
            return [], []

        async def empty_list():
            return []

        lock = asyncio.Lock()
        assert await ss._run_source(db, scan, "dataroma", empty_pair, lock) == ([], [])
        assert await ss._run_source(db, scan, "activist", empty_list, lock) == []

        by_source = {s["source"]: s for s in scan.steps}
        assert (by_source["dataroma"]["status"], by_source["dataroma"]["count"]) == ("error", 0)
        # Eine Quelle, die auch im Normalbetrieb leer sein kann, bleibt "done".
        assert (by_source["activist"]["status"], by_source["activist"]["count"]) == ("done", 0)

        scan.status = "completed"
        await db.commit()
        health = await get_composite_scan_health(db)
        assert health["status"] == "degraded"
        assert "pipeline_error:dataroma" in health["warnings"]

    async def test_every_blocking_prone_source_is_checked_for_emptiness(self):
        assert ss._NEVER_EMPTY_SOURCES == {
            "openinsider_cluster", "openinsider_large", "sec_buyback", "capitoltrades",
            "dataroma", "finra", "ftd",
        }

    async def test_openinsider_fetch_error_reaches_the_caller(self, monkeypatch):
        async def blocked(url):
            raise RuntimeError("403")

        monkeypatch.setattr(oi, "_fetch_html", blocked)
        with pytest.raises(RuntimeError):
            await oi.fetch_cluster_buys()
        with pytest.raises(RuntimeError):
            await oi.fetch_large_buys()

    async def test_buyback_fetch_error_reaches_the_caller(self, monkeypatch):
        async def blocked(*args, **kwargs):
            raise RuntimeError("403")

        monkeypatch.setattr(bb, "fetch_json", blocked)
        with pytest.raises(RuntimeError):
            await bb.fetch_buybacks()

    async def test_capitoltrades_first_page_error_reaches_the_caller(self, monkeypatch):
        async def blocked(*args, **kwargs):
            raise RuntimeError("403")

        monkeypatch.setattr(ct, "fetch_text", blocked)
        with pytest.raises(RuntimeError):
            await ct.fetch_congressional_buys()

    async def test_capitoltrades_later_page_error_keeps_the_first_page(self, monkeypatch):
        async def flaky(url, headers=None, timeout=15):
            if "page=1&" not in url:
                raise RuntimeError("timeout")
            return '"issuerName":"Apple Inc","issuerTicker":"AAPL:US"'

        monkeypatch.setattr(ct, "fetch_text", flaky)
        assert await ct.fetch_congressional_buys() == [{"ticker": "AAPL", "company": "Apple Inc"}]

    async def test_dataroma_fetch_error_reaches_the_caller(self, monkeypatch):
        async def blocked(url, headers=None, timeout=15):
            if url == ds.PORTFOLIO_URL:
                raise RuntimeError("403")
            return ""

        monkeypatch.setattr(ds, "fetch_text", blocked)
        monkeypatch.setattr(ds, "_homepage_warmed", True)
        with pytest.raises(RuntimeError, match="403"):
            await ds.fetch_superinvestor_data()

    async def test_dataroma_empty_portfolio_is_an_error(self, monkeypatch):
        async def layout_changed(url, headers=None, timeout=15):
            return "<html><body>neu</body></html>"

        monkeypatch.setattr(ds, "fetch_text", layout_changed)
        monkeypatch.setattr(ds, "_homepage_warmed", True)
        with pytest.raises(RuntimeError, match="no holdings"):
            await ds.fetch_superinvestor_data()


# ---------------------------------------------------------------------------
# K171 — OpenInsider-Abruf
# ---------------------------------------------------------------------------

_TINYTABLE = (
    '<table class="tinytable"><tr>' + "<th>h</th>" * 13 + "</tr><tr>"
    "<td></td><td>2026-11-10</td><td>2026-11-09</td><td>ACME</td><td>Acme Corp</td>"
    "<td>Machinery</td><td>4</td><td>P - Purchase</td><td>$10.00</td><td>+1,000</td>"
    "<td>5,000</td><td>+25%</td><td>+$10,000</td></tr></table>"
)


def _mock_client(monkeypatch, handler) -> list[str]:
    requested: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)

    # follow_redirects=True wie der geteilte Client in services.api_utils.
    client = httpx.AsyncClient(transport=httpx.MockTransport(recording), follow_redirects=True)
    monkeypatch.setattr(oi, "get_async_client", lambda: client)
    return requested


class TestOpenInsiderFetch:
    async def test_redirect_to_a_foreign_host_is_not_followed(self, monkeypatch):
        def handler(request):
            if request.url.host == "openinsider.com":
                return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
            return httpx.Response(200, text=_TINYTABLE)

        requested = _mock_client(monkeypatch, handler)
        with pytest.raises(ValueError, match="redirect"):
            await oi.fetch_cluster_buys()
        assert requested == [oi.CLUSTER_BUYS_URL]  # das interne Ziel wurde nie abgerufen

    async def test_redirect_within_openinsider_is_followed(self, monkeypatch):
        def handler(request):
            if request.url.scheme == "http":
                return httpx.Response(301, headers={"location": "https://www.openinsider.com/latest-cluster-buys"})
            return httpx.Response(200, text=_TINYTABLE)

        requested = _mock_client(monkeypatch, handler)
        trades = await oi.fetch_cluster_buys()
        assert [t["ticker"] for t in trades] == ["ACME"]
        assert trades[0]["insider_count"] == 4
        assert requested[-1] == "https://www.openinsider.com/latest-cluster-buys"

    async def test_oversized_response_is_refused(self, monkeypatch):
        monkeypatch.setattr(oi, "_MAX_HTML_BYTES", 1000)
        _mock_client(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 5000))
        with pytest.raises(ValueError, match="larger"):
            await oi.fetch_cluster_buys()


# ---------------------------------------------------------------------------
# K157 — Dataroma-Parser
# ---------------------------------------------------------------------------

def _old_parse_html_table(html: str) -> list[tuple[list[str], str]]:
    """Die Fassung vor dem Fix, als Orakel."""
    rows = []
    for raw in re.findall(r"<[Tt][Rr][^>]*>(.*?)</[Tt][Rr]>", html, re.DOTALL):
        cells = re.findall(r"<[Tt][Dd][^>]*>(.*?)</[Tt][Dd]>", raw, re.DOTALL)
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if clean and any(clean):
            rows.append((clean, raw))
    return rows


class TestDataromaParser:
    async def test_parser_matches_the_old_regex_on_real_and_broken_html(self):
        real = (
            '<table id="grid"><TR class="h"><td>Symbol</td><td>Stock</td></TR>\n'
            '<tr><td class="sym"><a href="/m/stock.php?sym=BRK.B">BRK.B</a></td>'
            '<td><a href="https://www.sec.gov/Archives/edgar/data/1067983/x.htm">Berkshire</a></td></tr>\n'
            "<tr><td></td><td> </td></tr><tr><td>A < B</td><td><></td><td>x<br/>y</td></tr></table>"
        )
        assert ds._parse_html_table(real) == _old_parse_html_table(real)
        assert len(ds._parse_html_table(real)) == 3

        rng = random.Random(11)
        tokens = ["<tr>", "</tr>", "<TR class=x>", "</TR>", "<td>", "</td>", "<TD a='1'>", "</Td>",
                  "<", ">", "<>", "a", " b ", "<b>", "</b>", "<tr", "\n"]
        for _ in range(500):
            html = "".join(rng.choice(tokens) for _ in range(rng.randrange(0, 40)))
            assert ds._parse_html_table(html) == _old_parse_html_table(html), html

    async def test_unclosed_rows_no_longer_block(self):
        # Vorher suchte der Regex von jedem <tr> bis zum Textende: quadratisch.
        for html in ("<tr>" * 20_000, "<tr><td>" + "<td>" * 20_000 + "</tr>", "<tr><td>" + "<" * 20_000 + "</td></tr>"):
            t0 = time.perf_counter()
            ds._parse_html_table(html)
            assert time.perf_counter() - t0 < 1.0

    async def test_oversized_html_is_cut_before_parsing(self, monkeypatch):
        monkeypatch.setattr(ds, "_MAX_HTML_CHARS", 60)
        html = "<tr><td>AAPL</td></tr>" * 10
        assert len(ds._parse_html_table(html)) == 2
