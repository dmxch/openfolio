"""Review-Fixes Batch E (Code-Review 2026-07-02).

Deckt ab:
- M17: Macro-Gate Missing-Data-Semantik — G1-G3 liefern None statt False,
  G4 None statt fail-open True; Aggregation schliesst None aus dem Nenner aus.
- M12: Backtest-Harness DEFAULT_WEIGHTS synchron mit dem live deployten
  Scoring (screening_service) inkl. 13F-score_applied, Activist-Dedup und
  sector_bonus.
- M10: SEC-Ticker-Maps kleben nach Fetch-Fehler/leerem Ergebnis NICHT leer
  bis zum Prozess-Neustart (Retry mit Cooldown).
- M9 / LOW-13f-perfund: per-Item-Fehler loesen db.rollback() aus und der
  Lauf geht weiter (kein PendingRollbackError-Kaskadeneffekt).
- M11: ETF-Holdings-Refresh loescht weggefallene Titel in derselben
  Transaktion wie der Upsert — mit Plausibilitaets-Guard.
- LOW-form4-dedup: gleichtaegige Teilausfuehrungen desselben Insiders werden
  vor dem Insert aggregiert (shares/value summiert, Preis wertgewichtet).
- LOW-universe: geschlossene Positionen (shares=0 oder inaktiv) laufen nicht
  mehr im SEC-Refresh-Universum mit.

Alle Tests laufen ohne Netzwerk — externe Fetches sind gemockt.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.sql.dml import Delete

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, scalar=None, one_or_none=None, rowcount=0):
        self._scalar = scalar
        self._one_or_none = one_or_none
        self.rowcount = rowcount

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._one_or_none


class _FakeDb:
    """Minimal-AsyncSession: zaehlt rollback/commit, gibt gestagte Results zurueck."""

    def __init__(self, execute_results=None):
        self.rollbacks = 0
        self.commits = 0
        self.executed = []
        self._results = list(execute_results or [])

    async def execute(self, stmt, *args, **kwargs):
        self.executed.append(stmt)
        return self._results.pop(0) if self._results else _FakeResult()

    async def rollback(self):
        self.rollbacks += 1

    async def commit(self):
        self.commits += 1


# ---------------------------------------------------------------------------
# M17 — Macro-Gate Missing-Data-Semantik
# ---------------------------------------------------------------------------

class TestMacroGateMissingData:
    def test_g1_none_on_missing_data(self):
        from services.macro_gate_service import _check_sp500_above_150dma
        assert _check_sp500_above_150dma({}) is None
        assert _check_sp500_above_150dma({"checks": {}}) is None
        assert _check_sp500_above_150dma({"checks": {"price_above_ma150": None}}) is None
        assert _check_sp500_above_150dma({"checks": {"price_above_ma150": True}}) is True
        assert _check_sp500_above_150dma({"checks": {"price_above_ma150": False}}) is False

    def test_g2_kleene_and(self):
        from services.macro_gate_service import _check_sp500_structure
        assert _check_sp500_structure({}) is None
        assert _check_sp500_structure(
            {"checks": {"price_above_ma50": True, "ma50_above_ma150": None}}
        ) is None
        # Ein sicheres False entscheidet auch bei fehlendem zweiten Wert
        assert _check_sp500_structure(
            {"checks": {"price_above_ma50": False, "ma50_above_ma150": None}}
        ) is False
        assert _check_sp500_structure(
            {"checks": {"price_above_ma50": True, "ma50_above_ma150": True}}
        ) is True
        assert _check_sp500_structure(
            {"checks": {"price_above_ma50": True, "ma50_above_ma150": False}}
        ) is False

    def test_g3_vix_none_on_missing_data(self):
        from services.macro_gate_service import _check_vix_below_20
        assert _check_vix_below_20({}) is None
        assert _check_vix_below_20({"vix": None}) is None
        assert _check_vix_below_20({"vix": {"value": None}}) is None
        assert _check_vix_below_20({"vix": {"value": 15.0}}) is True
        assert _check_vix_below_20({"vix": {"value": 25.0}}) is False

    def test_g4_none_instead_of_fail_open(self):
        from services.macro_gate_service import _check_sector_strong
        # Kein Sektor bekannt → nicht bewertbar (frueher: fail-open True)
        assert _check_sector_strong(None, rotation=[]) is None
        # Sektor nicht in der Rotation → nicht bewertbar
        assert _check_sector_strong("XLK", rotation=[{"etf": "XLE", "perf_1m": 2.0}]) is None
        # perf_1m fehlt → nicht bewertbar (frueher: False via `or 0`)
        assert _check_sector_strong("XLK", rotation=[{"etf": "XLK", "perf_1m": None}]) is None
        assert _check_sector_strong("XLK", rotation=[{"etf": "XLK", "perf_1m": 1.5}]) is True
        assert _check_sector_strong("XLK", rotation=[{"etf": "XLK", "perf_1m": -0.5}]) is False

    def test_gate_aggregation_excludes_none(self, monkeypatch):
        import services.macro_gate_service as mg
        monkeypatch.setattr(mg.cache, "get", lambda key: None)
        monkeypatch.setattr(mg.cache, "set", lambda *a, **k: None)
        monkeypatch.setattr(mg, "get_indicator", lambda name: None)  # G5-G7 → None

        climate = {
            "checks": {
                "price_above_ma150": True,
                "price_above_ma50": True,
                "ma50_above_ma150": True,
            },
            "vix": {"value": 15.0},
        }
        gate = mg.calculate_macro_gate(sector=None, climate=climate, rotation=[])
        # G1 (2) + G2 (1) + G3 (2) bestanden; G4-G7 ohne Daten → aus dem Nenner
        assert gate["score"] == 5
        assert gate["max_score"] == 5
        assert gate["unavailable_count"] == 4
        assert gate["passed"] is True
        unavailable_ids = {c["id"] for c in gate["checks"] if c["unavailable"]}
        assert unavailable_ids == {"sector_strong", "shiller_pe_ok", "buffett_ok", "yield_curve_ok"}

    def test_gate_all_unavailable_is_not_passed(self, monkeypatch):
        import services.macro_gate_service as mg
        monkeypatch.setattr(mg.cache, "get", lambda key: None)
        monkeypatch.setattr(mg.cache, "set", lambda *a, **k: None)
        monkeypatch.setattr(mg, "get_indicator", lambda name: None)

        gate = mg.calculate_macro_gate(sector=None, climate={}, rotation=[])
        assert gate["score"] == 0
        assert gate["max_score"] == 0
        assert gate["unavailable_count"] == 7
        # 0 >= 0 darf NICHT als "Bestanden" durchgehen
        assert gate["passed"] is False
        assert gate["label"] == "Keine Daten"


# ---------------------------------------------------------------------------
# M12 — Harness-Gewichte synchron mit dem Live-Scoring
# ---------------------------------------------------------------------------

class TestHarnessWeightsSync:
    def test_default_weights_match_live_scoring(self):
        import services.screening.backtest_harness as bh
        import services.screening.screening_service as ss

        assert bh.DEFAULT_WEIGHTS["insider_cluster"] == ss.WEIGHT_CLUSTER_BUY
        assert bh.DEFAULT_WEIGHTS["superinvestor"] == ss.WEIGHT_SUPERINVESTOR
        assert bh.DEFAULT_WEIGHTS["activist"] == ss.WEIGHT_SUPERINVESTOR
        assert bh.DEFAULT_WEIGHTS["buyback"] == ss.WEIGHT_BUYBACK
        assert bh.DEFAULT_WEIGHTS["large_buy"] == ss.WEIGHT_LARGE_BUY
        assert bh.DEFAULT_WEIGHTS["congressional"] == ss.WEIGHT_CONGRESSIONAL
        assert bh.DEFAULT_WEIGHTS["six_insider"] == ss.WEIGHT_SIX_INSIDER
        assert bh.DEFAULT_WEIGHTS["form4_cluster"] == ss.WEIGHT_FORM4_CLUSTER
        assert bh.DEFAULT_WEIGHTS["estimate_revision"] == ss.WEIGHT_ESTIMATE_REVISION
        assert bh.DEFAULT_WEIGHTS["short_trend"] == ss.WEIGHT_SHORT_TREND
        assert bh.DEFAULT_WEIGHTS["ftd"] == ss.WEIGHT_FTD
        assert bh.DEFAULT_WEIGHTS["unusual_volume"] == 0

    def test_all_live_signal_keys_present(self):
        import services.screening.backtest_harness as bh
        expected = {
            "insider_cluster", "superinvestor", "activist", "buyback",
            "large_buy", "congressional", "six_insider", "form4_cluster",
            "estimate_revision", "superinvestor_13f_consensus",
            "superinvestor_13f_single", "short_trend", "ftd", "unusual_volume",
        }
        assert set(bh.DEFAULT_WEIGHTS) == expected

    def test_reconstruct_activist_dedup_with_superinvestor(self):
        from services.screening.backtest_harness import DEFAULT_WEIGHTS, reconstruct_score
        # Live: activist vergibt WEIGHT_SUPERINVESTOR nur ohne superinvestor-Signal
        both = {"superinvestor": {"num_investors": 4}, "activist": {"investor": "Icahn"}}
        assert reconstruct_score(both, DEFAULT_WEIGHTS) == 2
        alone = {"activist": {"investor": "Icahn"}}
        assert reconstruct_score(alone, DEFAULT_WEIGHTS) == 2

    def test_reconstruct_13f_uses_score_applied(self):
        from services.screening.backtest_harness import DEFAULT_WEIGHTS, reconstruct_score
        consensus = {"superinvestor_13f_consensus": {"action": "new_position", "score_applied": 3}}
        assert reconstruct_score(consensus, DEFAULT_WEIGHTS) == 3
        single_zero = {"superinvestor_13f_single": {"action": "added", "score_applied": 0}}
        assert reconstruct_score(single_zero, DEFAULT_WEIGHTS) == 0
        # Negativer 13F-Score drueckt einen positiven Signal-Mix runter
        mixed = {
            "buyback": {"filing_date": "2026-06-01"},
            "superinvestor_13f_consensus": {"action": "reduced", "score_applied": -1},
        }
        assert reconstruct_score(mixed, DEFAULT_WEIGHTS) == 1

    def test_reconstruct_sector_bonus_and_clamp(self):
        from services.screening.backtest_harness import DEFAULT_WEIGHTS, reconstruct_score
        signals = {
            "insider_cluster": {"insider_count": 3},   # +3
            "six_insider": {"transaction_count": 2},   # +3
            "form4_cluster": {"insider_count": 4},     # +2
            "estimate_revision": {"delta_30d": 0.1},   # +1
        }
        assert reconstruct_score(signals, DEFAULT_WEIGHTS) == 9
        assert reconstruct_score(signals, DEFAULT_WEIGHTS, sector_bonus=1) == 10
        # Cap [0, 10] wie in screening_service.run_scan
        signals["buyback"] = {"filing_date": "2026-06-01"}  # +2 → raw 11
        assert reconstruct_score(signals, DEFAULT_WEIGHTS, sector_bonus=1) == 10
        # Floor 0
        assert reconstruct_score({"short_trend": {"change_pct": 30}}, DEFAULT_WEIGHTS) == 0


# ---------------------------------------------------------------------------
# M10 — SEC-Maps: Fetch-Fehler markiert die Map nicht als geladen
# ---------------------------------------------------------------------------

class TestSecMapRetry:
    async def test_form4_map_failure_then_retry(self, monkeypatch):
        import services.screening.sec_form4_service as f4
        monkeypatch.setattr(f4, "_ticker_cik_map", None)
        monkeypatch.setattr(f4, "_ticker_cik_map_next_retry", 0.0)

        calls = {"n": 0}

        async def failing(*a, **k):
            calls["n"] += 1
            raise RuntimeError("SEC down")

        monkeypatch.setattr(f4, "fetch_json", failing)
        assert await f4._load_ticker_cik_map() == {}
        assert f4._ticker_cik_map is None  # NICHT als geladen markiert
        # Cooldown aktiv: zweiter Aufruf fetcht nicht erneut
        assert await f4._load_ticker_cik_map() == {}
        assert calls["n"] == 1

        # Nach Cooldown-Ablauf: erfolgreicher Fetch fuellt die Map dauerhaft
        monkeypatch.setattr(f4, "_ticker_cik_map_next_retry", 0.0)

        async def ok(*a, **k):
            return {"0": {"ticker": "AAPL", "cik_str": 320193}}

        monkeypatch.setattr(f4, "fetch_json", ok)
        assert await f4._load_ticker_cik_map() == {"AAPL": "0000320193"}
        assert f4._ticker_cik_map == {"AAPL": "0000320193"}

    async def test_form4_map_empty_fetch_not_marked_loaded(self, monkeypatch):
        import services.screening.sec_form4_service as f4
        monkeypatch.setattr(f4, "_ticker_cik_map", None)
        monkeypatch.setattr(f4, "_ticker_cik_map_next_retry", 0.0)

        async def empty(*a, **k):
            return {}

        monkeypatch.setattr(f4, "fetch_json", empty)
        assert await f4._load_ticker_cik_map() == {}
        assert f4._ticker_cik_map is None
        assert f4._ticker_cik_map_next_retry > 0

    async def test_13f_maps_failure_not_marked_loaded(self, monkeypatch):
        import services.screening.sec_13f_service as s13
        monkeypatch.setattr(s13, "_name_ticker_map", None)
        monkeypatch.setattr(s13, "_cusip_ticker_map", None)
        monkeypatch.setattr(s13, "_ticker_maps_next_retry", 0.0)

        calls = {"n": 0}

        async def failing(*a, **k):
            calls["n"] += 1
            raise RuntimeError("SEC down")

        monkeypatch.setattr(s13, "fetch_json", failing)
        name_map, cusip_map = await s13._load_ticker_maps()
        assert name_map == {} and cusip_map == {}
        assert s13._name_ticker_map is None
        # Cooldown: kein erneuter Fetch
        await s13._load_ticker_maps()
        assert calls["n"] == 1

        # Erfolg nach Cooldown setzt beide Maps
        monkeypatch.setattr(s13, "_ticker_maps_next_retry", 0.0)

        async def ok(*a, **k):
            return {"0": {"ticker": "AAPL", "title": "Apple Inc"}}

        monkeypatch.setattr(s13, "fetch_json", ok)
        name_map, cusip_map = await s13._load_ticker_maps()
        assert name_map == {"APPLE INC": "AAPL"}
        assert cusip_map == {}
        assert s13._name_ticker_map == {"APPLE INC": "AAPL"}

    async def test_activist_map_failure_not_marked_loaded(self, monkeypatch):
        import services.screening.activist_tracker as act
        monkeypatch.setattr(act, "_cik_ticker_map", None)
        monkeypatch.setattr(act, "_cik_ticker_map_next_retry", 0.0)

        async def failing(*a, **k):
            raise RuntimeError("SEC down")

        monkeypatch.setattr(act, "fetch_json", failing)
        assert await act._load_cik_ticker_map() == {}
        assert act._cik_ticker_map is None
        assert act._cik_ticker_map_next_retry > 0


# ---------------------------------------------------------------------------
# M9 / LOW-13f-perfund — Rollback + Weiterlaufen bei per-Item-Fehlern
# ---------------------------------------------------------------------------

class TestPerItemRollback:
    async def test_form4_universe_rolls_back_per_ticker(self, monkeypatch):
        import services.screening.sec_form4_service as f4

        async def fake_universe(db):
            return ["AAA", "BBB"]

        async def fake_map():
            return {"AAA": "0000000001", "BBB": "0000000002"}

        async def boom(db, t, cik, lookback_days=90):
            raise RuntimeError("db kaputt")

        monkeypatch.setattr(f4, "_resolve_universe", fake_universe)
        monkeypatch.setattr(f4, "_load_ticker_cik_map", fake_map)
        monkeypatch.setattr(f4, "refresh_form4_for_ticker", boom)

        db = _FakeDb()
        result = await f4.refresh_form4_universe(db)
        assert db.rollbacks == 2  # ein Rollback pro fehlgeschlagenem Ticker
        assert result["tickers_scanned"] == 2
        assert result["transactions_inserted"] == 0

    async def test_etf_refresh_rolls_back_per_etf(self, monkeypatch):
        import services.etf_holdings_service as eh

        async def fake_key(db):
            return "key"

        async def fake_etfs(db):
            return ["SPY", "OEF"]

        async def boom(db, etf_ticker, api_key):
            raise RuntimeError("db kaputt")

        monkeypatch.setattr(eh, "_get_any_user_fmp_key", fake_key)
        monkeypatch.setattr(eh, "_get_distinct_active_etf_tickers", fake_etfs)
        monkeypatch.setattr(eh, "refresh_etf_holdings", boom)

        db = _FakeDb()
        out = await eh.refresh_all_user_etfs(db)
        assert db.rollbacks == 2
        assert len(out["errors"]) == 2
        assert out["refreshed"] == []

    async def test_13f_refresh_isolates_failing_fund(self, monkeypatch):
        import services.screening.sec_13f_service as s13

        async def fake_maps():
            return {}, {}

        monkeypatch.setattr(s13, "_load_ticker_maps", fake_maps)
        monkeypatch.setattr(s13, "SEC_DELAY", 0)

        first_cik = next(iter(s13.TRACKED_13F_FUNDS))

        async def selective(db, cik, fund_name, name_map):
            if cik == first_cik:
                raise RuntimeError("boom")
            return {"status": "skipped", "holdings": 0, "resolved": 0, "unresolved": 0}

        monkeypatch.setattr(s13, "_refresh_fund_13f", selective)

        db = _FakeDb()
        out = await s13.refresh_13f_holdings(db)
        n_funds = len(s13.TRACKED_13F_FUNDS)
        # Ein Fehler bricht den Lauf NICHT ab — alle anderen Fonds laufen weiter
        assert out["failed"] == 1
        assert out["skipped"] == n_funds - 1
        assert db.rollbacks == 1

    async def test_13f_refresh_counts_processed_funds(self, monkeypatch):
        import services.screening.sec_13f_service as s13

        async def fake_maps():
            return {}, {}

        monkeypatch.setattr(s13, "_load_ticker_maps", fake_maps)
        monkeypatch.setattr(s13, "SEC_DELAY", 0)

        async def processed(db, cik, fund_name, name_map):
            return {"status": "processed", "holdings": 5, "resolved": 4, "unresolved": 1}

        monkeypatch.setattr(s13, "_refresh_fund_13f", processed)

        db = _FakeDb()
        out = await s13.refresh_13f_holdings(db)
        n_funds = len(s13.TRACKED_13F_FUNDS)
        assert out["processed"] == n_funds
        assert out["total_holdings_parsed"] == 5 * n_funds
        assert out["total_resolved"] == 4 * n_funds
        assert out["total_unresolved"] == 1 * n_funds
        assert db.rollbacks == 0


# ---------------------------------------------------------------------------
# M11 — ETF-Holdings Stale-Delete inkl. Guard
# ---------------------------------------------------------------------------

def _fake_holding_rows(n: int) -> list[dict]:
    return [
        {
            "etf_ticker": "TESTETF",
            "holding_ticker": f"H{i:03d}",
            "holding_name": f"Holding {i}",
            "weight_pct": 1.0,
            "as_of": date(2026, 6, 30),
            "holding_isin": None,
            "holding_country": None,
            "holding_sector": None,
        }
        for i in range(n)
    ]


class TestEtfHoldingsStaleDelete:
    def test_guard_pure(self):
        from services.etf_holdings_service import _stale_delete_allowed
        assert _stale_delete_allowed(3, 0) is False       # unter Mindestanzahl
        assert _stale_delete_allowed(10, 0) is True       # frischer ETF, plausibel
        assert _stale_delete_allowed(12, 100) is False    # drastisch kleiner als Bestand
        assert _stale_delete_allowed(60, 100) is True
        assert _stale_delete_allowed(500, 3000) is False  # EIMI-Fall: Teil-Fetch
        assert _stale_delete_allowed(2900, 3000) is True

    async def test_delete_runs_in_same_transaction_as_upsert(self, monkeypatch):
        import services.etf_holdings_service as eh
        monkeypatch.setitem(
            eh.ISHARES_HOLDINGS_URLS, "TESTETF", "https://example.invalid/holdings.csv"
        )

        async def fake_fetch(etf_ticker):
            return _fake_holding_rows(12)

        monkeypatch.setattr(eh, "fetch_ishares_holdings", fake_fetch)

        db = _FakeDb(execute_results=[
            _FakeResult(one_or_none=None),  # TTL-Check: keine frische Row
            _FakeResult(scalar=15),         # Bestand vor Upsert
            _FakeResult(),                  # Upsert
            _FakeResult(rowcount=3),        # DELETE weggefallener Holdings
        ])
        out = await eh.refresh_etf_holdings(db, "TESTETF", "")
        assert out["count"] == 12
        assert out["stale_deleted"] == 3
        deletes = [s for s in db.executed if isinstance(s, Delete)]
        assert len(deletes) == 1
        # Ein einziger Commit NACH Upsert+Delete (gleiche Transaktion)
        assert db.commits == 1

    async def test_implausible_fetch_skips_delete(self, monkeypatch):
        import services.etf_holdings_service as eh
        monkeypatch.setitem(
            eh.ISHARES_HOLDINGS_URLS, "TESTETF", "https://example.invalid/holdings.csv"
        )

        async def fake_fetch(etf_ticker):
            return _fake_holding_rows(12)  # nur 12 Rows bei 100 im Bestand

        monkeypatch.setattr(eh, "fetch_ishares_holdings", fake_fetch)

        db = _FakeDb(execute_results=[
            _FakeResult(one_or_none=None),  # TTL-Check
            _FakeResult(scalar=100),        # grosser Bestand → Guard greift
            _FakeResult(),                  # Upsert
        ])
        out = await eh.refresh_etf_holdings(db, "TESTETF", "")
        assert out["stale_deleted"] == 0
        assert not any(isinstance(s, Delete) for s in db.executed)
        assert db.commits == 1  # Upsert wird trotzdem committed


# ---------------------------------------------------------------------------
# LOW-form4-dedup — Aggregation gleichtaegiger Teilausfuehrungen
# ---------------------------------------------------------------------------

def _f4_row(shares: int, price: str | None, *, code: str = "P",
            txn_date: date = date(2026, 6, 1), insider: str = "Jane Doe",
            ticker: str = "AAPL", filing: date = date(2026, 6, 2)) -> dict:
    p = Decimal(price) if price is not None else None
    value = (Decimal(shares) * p).quantize(Decimal("0.01")) if p is not None else None
    return {
        "ticker": ticker,
        "filing_date": filing,
        "transaction_date": txn_date,
        "insider_name": insider,
        "insider_role": "CEO",
        "transaction_code": code,
        "shares": shares,
        "price": p,
        "value_usd": value,
    }


class TestForm4DedupAggregation:
    def test_partial_fills_sum_shares_value_weighted_price(self):
        from services.screening.sec_form4_service import _aggregate_daily_transactions
        rows = [_f4_row(100, "10.00"), _f4_row(200, "13.00")]
        out = _aggregate_daily_transactions(rows)
        assert len(out) == 1
        agg = out[0]
        assert agg["shares"] == 300
        assert agg["value_usd"] == Decimal("3600.00")
        assert agg["price"] == Decimal("12.0000")  # (1000+2600)/300

    def test_different_code_day_or_insider_not_merged(self):
        from services.screening.sec_form4_service import _aggregate_daily_transactions
        rows = [
            _f4_row(100, "10.00"),
            _f4_row(100, "10.00", code="S"),
            _f4_row(100, "10.00", txn_date=date(2026, 6, 2)),
            _f4_row(100, "10.00", insider="John Roe"),
        ]
        assert len(_aggregate_daily_transactions(rows)) == 4

    def test_unpriced_fill_merges_priced_portion(self):
        from services.screening.sec_form4_service import _aggregate_daily_transactions
        rows = [_f4_row(100, None), _f4_row(200, "13.00")]
        out = _aggregate_daily_transactions(rows)
        assert len(out) == 1
        agg = out[0]
        assert agg["shares"] == 300
        # Value/Preis nur aus dem Teil mit bekanntem Preis
        assert agg["value_usd"] == Decimal("2600.00")
        assert agg["price"] == Decimal("13.0000")

    def test_all_unpriced_merge_keeps_none(self):
        from services.screening.sec_form4_service import _aggregate_daily_transactions
        rows = [_f4_row(100, None), _f4_row(50, None)]
        out = _aggregate_daily_transactions(rows)
        assert len(out) == 1
        assert out[0]["shares"] == 150
        assert out[0]["price"] is None
        assert out[0]["value_usd"] is None

    def test_single_row_untouched(self):
        from services.screening.sec_form4_service import _aggregate_daily_transactions
        row = _f4_row(100, "10.1234")
        out = _aggregate_daily_transactions([row])
        assert len(out) == 1
        assert out[0]["price"] == Decimal("10.1234")
        assert out[0]["value_usd"] == Decimal("1012.34")
        assert out[0]["shares"] == 100


# ---------------------------------------------------------------------------
# LOW-universe — geschlossene Positionen raus aus dem SEC-Universum
# ---------------------------------------------------------------------------

async def _make_user(db):
    from models.user import User, UserSettings
    from services.bucket_service import create_system_buckets, get_liquid_default_bucket

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


async def _make_pos(db, user, *, ticker, shares="10", typ=None, is_active=True):
    from models.position import AssetType, Position, PriceSource
    from services.bucket_service import get_liquid_default_bucket

    liquid = await get_liquid_default_bucket(db, user.id)
    p = Position(
        user_id=user.id, bucket_id=liquid.id, ticker=ticker, name=f"{ticker} Inc",
        type=typ or AssetType.stock, currency="USD", price_source=PriceSource.yahoo,
        shares=Decimal(shares), cost_basis_chf=Decimal("1000"), is_active=is_active,
    )
    db.add(p)
    await db.commit()


class TestUniverseActiveFilter:
    async def test_excludes_closed_and_inactive_positions(self, db):
        from models.position import AssetType
        from models.watchlist import WatchlistItem
        from services.screening.universe import resolve_equity_universe

        user = await _make_user(db)
        await _make_pos(db, user, ticker="AAPL", shares="10")                       # bleibt
        await _make_pos(db, user, ticker="DEAD", shares="0")                        # geschlossen (shares=0, aktiv)
        await _make_pos(db, user, ticker="GONE", shares="5", is_active=False)       # inaktiv
        await _make_pos(db, user, ticker="VT", shares="10", typ=AssetType.etf)      # kein stock
        db.add(WatchlistItem(user_id=user.id, ticker="NVDA", name="NVIDIA", is_active=True))
        db.add(WatchlistItem(user_id=user.id, ticker="OLDW", name="Old Watch", is_active=False))
        await db.commit()

        out = await resolve_equity_universe(db)
        assert out == ["AAPL", "NVDA"]
