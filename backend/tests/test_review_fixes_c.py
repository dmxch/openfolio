"""Regressionstests fuer Review-Batch C (Code-Review 2026-07-02).

Abgedeckte Findings:
  - M1:  manuell bepreiste Positionen werden im Live-Summary FX-konvertiert
         (shares x price x fx), identisch zum Snapshot-Pfad.
  - M4+M16: portfolio_summary:{user_id}-Cache enthaelt NUR die rohe Summary;
         die Anreicherung (PII/Alerts/24h-Change) laeuft nach dem Cache-Read
         auf einer Kopie — das gecachte Objekt bleibt unveraendert.
  - M20: get_concentration_for_ticker laedt die Portfolio-Summary genau EINMAL.
  - M25: First-Buy-Query in get_realized_gains ist user-gescoped.
  - M27: get_portfolio_summary loest Preise gebatcht auf
         (get_stock_prices_bulk), Einzel-Fallback nur fuer Batch-Misses.
  - LOW: dividends_gross_chf zaehlt Rows ohne gross_amount mit ihrem Netto
         (gross >= net Invariante).

Alle Tests laufen ohne Netz — externe Aufrufe sind gemockt/gepatcht.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from models.position import AssetType, Position, PricingMode, PriceSource
from models.transaction import Transaction, TransactionType


# --- Shared helpers ----------------------------------------------------------


def _ns_pos(**over):
    """SimpleNamespace-Position fuer _compute_market_value (kein DB-Zugriff)."""
    base = {
        "id": "test-id", "ticker": "AAPL", "name": "Apple",
        "type": SimpleNamespace(value="stock"), "currency": "USD",
        "shares": 10, "cost_basis_chf": 5000, "current_price": 150,
        "yfinance_ticker": "AAPL", "coingecko_id": None,
        "gold_org": False, "pricing_mode": SimpleNamespace(value="yahoo"),
    }
    base.update(over)
    return SimpleNamespace(**base)


def _db_pos(uid, **over) -> Position:
    """Position-Row fuer die SQLite-Fixture (FK-Constraints sind aus)."""
    base = dict(
        user_id=uid,
        bucket_id=uuid.uuid4(),
        ticker="AAA",
        name="AAA Corp",
        type=AssetType.stock,
        currency="CHF",
        shares=Decimal("10"),
        cost_basis_chf=Decimal("1000"),
        current_price=Decimal("110"),
        count_as_cash=False,
        is_active=True,
        coingecko_id=None,
        gold_org=False,
        pricing_mode=PricingMode.auto,
        price_source=PriceSource.yahoo,
    )
    base.update(over)
    return Position(**base)


def _txn(uid, pos_id, txn_type, d, **over) -> Transaction:
    base = dict(
        user_id=uid, position_id=pos_id, type=txn_type, date=d,
        shares=Decimal("0"), price_per_share=Decimal("0"),
        currency="CHF", fx_rate_to_chf=Decimal("1"),
        fees_chf=Decimal("0"), taxes_chf=Decimal("0"),
        total_chf=Decimal("0"),
    )
    base.update(over)
    return Transaction(**base)


# --- M1: manuelle Positionen mit FX ------------------------------------------


class TestM1ManualPricingFx:
    def test_manual_chf_unchanged(self):
        """Regression: CHF-Fall bleibt exakt wie vorher (Golden-Master-Schutz)."""
        from services.portfolio_service import _compute_market_value
        pos = _ns_pos(pricing_mode=PricingMode.manual, current_price=75.0,
                      shares=20, currency="CHF")
        mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 1500.0
        assert price == 75.0
        assert ccy == "CHF"
        assert stale == {}

    def test_manual_usd_applies_fx(self):
        """M1-Kern: shares x price x fx — wie der Snapshot-Pfad."""
        from services.portfolio_service import _compute_market_value
        pos = _ns_pos(pricing_mode=PricingMode.manual, current_price=100.0,
                      shares=5, currency="USD")
        mv, price, ccy, stale = _compute_market_value(pos, {"USD": 0.88})
        assert mv == pytest.approx(5 * 100.0 * 0.88)
        assert price == 100.0
        assert ccy == "USD"
        assert stale == {}

    def test_manual_usd_missing_fx_uses_stale_db_rate(self):
        from services.portfolio_service import _compute_market_value
        pos = _ns_pos(pricing_mode=PricingMode.manual, current_price=100.0,
                      shares=5, currency="USD")
        with patch("services.cache_service.get_cached_price_sync",
                   return_value={"price": 0.85}):
            mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == pytest.approx(5 * 100.0 * 0.85)
        assert stale == {}

    def test_manual_usd_no_fx_at_all_is_stale_zero(self):
        from services.portfolio_service import _compute_market_value
        pos = _ns_pos(pricing_mode=PricingMode.manual, current_price=100.0,
                      shares=5, currency="USD")
        with patch("services.cache_service.get_cached_price_sync",
                   return_value=None):
            mv, price, ccy, stale = _compute_market_value(pos, {})
        assert mv == 0
        assert stale["is_stale"] is True


# --- M27: Batch-Preis-Resolution ----------------------------------------------


class TestM27BatchPrices:
    def test_bulk_prefers_cache_then_batched_db(self, monkeypatch):
        """Redis/Memory-Hit gewinnt; Misses gehen in EINEM Batch zur DB;
        DB-Hits werden in den App-Cache zurueckgeschrieben."""
        from services import price_service

        mem = {"price:A": {"price": 10.0, "currency": "CHF", "change_pct": 0.5}}
        written: dict = {}
        monkeypatch.setattr("services.cache.get", lambda k: mem.get(k))

        def fake_set(k, v, ttl=900):
            written[k] = v
        monkeypatch.setattr("services.cache.set", fake_set)

        batch_calls: list = []

        def fake_batch(tickers, fallback_days=5):
            batch_calls.append((list(tickers), fallback_days))
            return {"B": {"price": 20.0, "currency": "USD",
                          "stale": False, "date": "2026-07-01"}}
        monkeypatch.setattr(
            "services.cache_service.get_cached_prices_batch_sync", fake_batch
        )

        out = price_service.get_stock_prices_bulk(["A", "B", "C", "A"])

        assert out["A"] == {"price": 10.0, "currency": "CHF", "change_pct": 0.5}
        assert out["B"] == {"price": 20.0, "currency": "USD", "change_pct": 0}
        assert "C" not in out  # Batch-Miss → Caller-Fallback
        assert len(batch_calls) == 1  # genau EIN DB-Roundtrip
        assert sorted(batch_calls[0][0]) == ["B", "C"]  # dedupliziert, nur Misses
        assert written["price:B"]["price"] == 20.0

    def test_compute_market_value_uses_price_map_before_single_lookup(self):
        from services.portfolio_service import _compute_market_value
        pos = _ns_pos(type=AssetType.stock, shares=10, currency="USD")
        price_map = {"AAPL": {"price": 200.0, "currency": "USD", "change_pct": 0}}
        with patch("services.portfolio_service.get_stock_price") as mock_single:
            mv, price, ccy, stale = _compute_market_value(
                pos, {"USD": 0.9}, price_map
            )
        mock_single.assert_not_called()
        assert mv == pytest.approx(10 * 200.0 * 0.9)
        assert price == 200.0

    def test_compute_market_value_falls_back_on_batch_miss(self):
        from services.portfolio_service import _compute_market_value
        pos = _ns_pos(type=AssetType.stock, shares=10, currency="USD")
        with patch("services.portfolio_service.get_stock_price",
                   return_value={"price": 50.0, "currency": "USD"}) as mock_single:
            mv, price, ccy, stale = _compute_market_value(pos, {"USD": 0.9}, {})
        mock_single.assert_called_once_with("AAPL")
        assert mv == pytest.approx(10 * 50.0 * 0.9)

    async def test_summary_batches_once_and_values_positions(self, db, monkeypatch):
        """End-to-end: get_portfolio_summary ruft die Bulk-Funktion genau
        einmal, kein Einzel-Lookup bei Batch-Hit; manuelle USD-Position wird
        FX-konvertiert (M1 + M27 zusammen)."""
        import services.portfolio_service as ps

        uid = uuid.uuid4()
        db.add_all([
            _db_pos(uid, ticker="AAA", shares=Decimal("10"),
                    current_price=Decimal("110"), currency="CHF"),
            _db_pos(uid, ticker="MAN", name="Manual Inc",
                    shares=Decimal("5"), current_price=Decimal("100"),
                    currency="USD", pricing_mode=PricingMode.manual),
        ])
        await db.commit()

        monkeypatch.setattr(ps, "get_fx_rates_batch",
                            lambda: {"CHF": 1.0, "USD": 0.9})
        monkeypatch.setattr(ps, "prefetch_close_series", lambda tickers: None)
        monkeypatch.setattr(ps, "_get_ma_status",
                            lambda t: {"ma_status": None, "ma_detail": None})
        monkeypatch.setattr(ps, "_get_mrs", lambda t: None)

        bulk_calls: list = []

        def fake_bulk(tickers):
            bulk_calls.append(list(tickers))
            return {"AAA": {"price": 110.0, "currency": "CHF", "change_pct": 0}}
        monkeypatch.setattr(ps, "get_stock_prices_bulk", fake_bulk)

        def fail_single(*args, **kwargs):
            raise AssertionError("get_stock_price darf bei Batch-Hit nicht laufen")
        monkeypatch.setattr(ps, "get_stock_price", fail_single)

        summary = await ps.get_portfolio_summary(db, uid)

        assert len(bulk_calls) == 1
        assert set(bulk_calls[0]) == {"AAA", "MAN"}
        values = {p["ticker"]: p["market_value_chf"] for p in summary["positions"]}
        assert values["AAA"] == pytest.approx(10 * 110.0 * 1.0)
        assert values["MAN"] == pytest.approx(5 * 100.0 * 0.9)  # M1: fx angewendet
        assert summary["total_market_value_chf"] == pytest.approx(1100.0 + 450.0)


# --- M4 + M16: roher Summary-Cache, Anreicherung pro Request ------------------


class TestM4M16RawCacheEnrichment:
    async def test_enrich_summary_does_not_mutate_cached_object(self, monkeypatch):
        from api import portfolio as portfolio_api

        raw_summary = {
            "total_market_value_chf": 1000.0,
            "positions": [{
                "id": "pos-1", "ticker": "AAPL", "market_value_chf": 1000.0,
            }],
        }
        row = SimpleNamespace(
            id="pos-1", bank_name="enc-bank", iban="enc-iban",
            notes="enc-notes", coingecko_id=None,
            yfinance_ticker=None, ticker="AAPL",
        )
        alerts_result = SimpleNamespace(all=lambda: [("AAPL", 2)])
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[[row], alerts_result])
        user = SimpleNamespace(id=uuid.uuid4())

        monkeypatch.setattr(portfolio_api, "decrypt_field",
                            lambda v: f"dec:{v}" if v else None)
        monkeypatch.setattr(portfolio_api, "decrypt_and_mask_iban",
                            lambda v: "CH** **** 1234" if v else None)
        monkeypatch.setattr(
            "services.cache.get",
            lambda k: {"change_pct": 1.5} if k == "price:AAPL" else None,
        )

        enriched = await portfolio_api._enrich_summary(db, user, raw_summary)

        # Anreicherung vorhanden (Response-Shape unveraendert zu vorher)
        pos = enriched["positions"][0]
        assert pos["bank_name"] == "dec:enc-bank"
        assert pos["notes"] == "dec:enc-notes"
        assert pos["iban"] == "CH** **** 1234"
        assert pos["active_alerts"] == 2
        assert pos["change_pct_24h"] == 1.5

        # M16-Kern: das (potenziell gecachte) Original bleibt ROH —
        # keine entschluesselten PII, keine volatilen Felder.
        raw_pos = raw_summary["positions"][0]
        for key in ("bank_name", "iban", "notes", "active_alerts", "change_pct_24h"):
            assert key not in raw_pos
        # Kopie, nicht dieselbe Referenz
        assert enriched is not raw_summary
        assert enriched["positions"][0] is not raw_summary["positions"][0]

    async def test_enrich_summary_empty_positions_noop(self):
        from api import portfolio as portfolio_api
        db = AsyncMock()
        user = SimpleNamespace(id=uuid.uuid4())
        summary = {"total_market_value_chf": 0.0, "positions": []}
        enriched = await portfolio_api._enrich_summary(db, user, summary)
        assert enriched["positions"] == []
        db.execute.assert_not_awaited()


# --- M20: eine Summary pro Konzentrations-Request ------------------------------


class TestM20SingleSummaryLoad:
    async def test_get_concentration_loads_summary_exactly_once(self, monkeypatch):
        import services.concentration_service as cs

        positions = [
            {"ticker": "SPY", "yfinance_ticker": "SPY", "name": "SPDR S&P 500",
             "type": "etf", "weight_pct": 50.0, "market_value_chf": 5000.0},
            {"ticker": "AAPL", "yfinance_ticker": "AAPL", "name": "Apple",
             "type": "stock", "weight_pct": 50.0, "market_value_chf": 5000.0},
        ]
        summary = {"positions": positions, "total_market_value_chf": 10_000.0}

        class _EmptyResult:
            def all(self_inner):
                return []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_EmptyResult())

        summary_mock = AsyncMock(return_value=summary)
        monkeypatch.setattr(
            "services.portfolio_service.get_portfolio_summary", summary_mock
        )
        monkeypatch.setattr(cs, "_classify_target_sector", lambda t: "Technology")
        monkeypatch.setattr(
            "services.sector_classification_service.classify_tickers_bulk",
            lambda tickers: {},
        )

        result = await cs.get_concentration_for_ticker(db, "AAPL", uuid.uuid4())

        # Kern-Assertion M20: genau EIN Summary-Load fuer den ganzen Request
        # (vorher 5: ETF-Map, Direkt-Position, Liquid-Total, Sektor-Agg-Summary,
        # Sektor-Agg-ETF-Map).
        assert summary_mock.await_count == 1

        # Werte kommen weiterhin aus der (einen) Summary
        assert result["single_name"]["direct_position_chf"] == pytest.approx(5000.0)
        assert result["single_name"]["total_pct"] == pytest.approx(50.0)
        assert result["sector"]["sector"] == "Technology"
        assert result["portfolio"]["nominal_count"] == 2

    async def test_helpers_still_load_summary_when_not_provided(self, monkeypatch):
        """Public-Verhalten stabil: _get_user_etf_positions_with_values ohne
        summary-Param laedt selbst (get_country_lookthrough-/Overlap-Pfad)."""
        import services.concentration_service as cs

        summary = {
            "positions": [{"ticker": "SPY", "name": "SPDR", "type": "etf",
                           "market_value_chf": 3000.0}],
            "total_market_value_chf": 3000.0,
        }
        summary_mock = AsyncMock(return_value=summary)
        monkeypatch.setattr(
            "services.portfolio_service.get_portfolio_summary", summary_mock
        )
        etf_map = await cs._get_user_etf_positions_with_values(
            AsyncMock(), uuid.uuid4()
        )
        assert summary_mock.await_count == 1
        assert etf_map == {"SPY": {"name": "SPDR", "market_value_chf": 3000.0}}


# --- M25: get_realized_gains user-gescoped -------------------------------------


class TestM25RealizedGainsUserScope:
    async def test_first_buy_query_is_user_scoped(self, db):
        uid_a = uuid.uuid4()
        uid_b = uuid.uuid4()

        pos_a = _db_pos(uid_a, ticker="AAA")
        pos_b = _db_pos(uid_b, ticker="BBB")
        db.add_all([pos_a, pos_b])
        await db.commit()

        db.add_all([
            _txn(uid_a, pos_a.id, TransactionType.buy, date(2024, 1, 1),
                 shares=Decimal("10"), price_per_share=Decimal("100"),
                 total_chf=Decimal("1000")),
            _txn(uid_a, pos_a.id, TransactionType.sell, date(2024, 6, 1),
                 shares=Decimal("10"), price_per_share=Decimal("110"),
                 total_chf=Decimal("1100"),
                 realized_pnl_chf=Decimal("100"),
                 cost_basis_at_sale=Decimal("1000")),
            # Fremd-User-Noise: darf weder auftauchen noch den Scan aufblaehen
            _txn(uid_b, pos_b.id, TransactionType.buy, date(2020, 1, 1),
                 shares=Decimal("5"), price_per_share=Decimal("50"),
                 total_chf=Decimal("250")),
        ])
        await db.commit()

        from services.total_return_service import get_realized_gains
        result = await get_realized_gains(db, user_id=uid_a)

        assert len(result["positions"]) == 1
        item = result["positions"][0]
        assert item["ticker"] == "AAA"
        assert item["buy_date"] == "2024-01-01"
        assert item["holding_period_days"] == (date(2024, 6, 1) - date(2024, 1, 1)).days
        assert result["total_realized_pnl_chf"] == pytest.approx(100.0)


# --- LOW: gross >= net bei Dividenden ohne gross_amount -------------------------


class TestLowDividendGrossIncludesNullRows:
    async def test_null_gross_rows_count_net_into_gross(self, db):
        uid = uuid.uuid4()
        pos = _db_pos(uid, ticker="DIV")
        db.add(pos)
        await db.commit()

        db.add_all([
            # USD-Dividende mit gross/tax: gross_chf = 100 x 0.9 = 90
            _txn(uid, pos.id, TransactionType.dividend, date(2024, 3, 1),
                 currency="USD", fx_rate_to_chf=Decimal("0.9"),
                 total_chf=Decimal("76.50"), taxes_chf=Decimal("13.50"),
                 gross_amount=Decimal("100"), tax_amount=Decimal("15")),
            # CHF-Dividende OHNE gross_amount: zaehlt mit Netto 50 in gross
            _txn(uid, pos.id, TransactionType.dividend, date(2024, 4, 1),
                 total_chf=Decimal("50"), gross_amount=None, tax_amount=None),
        ])
        await db.commit()

        from services.total_return_service import get_total_return
        stub_summary = {
            "total_pnl_chf": 0.0, "total_invested_chf": 0.0, "positions": [],
        }
        result = await get_total_return(db, user_id=uid, summary=stub_summary)

        assert result["dividends_net_chf"] == pytest.approx(126.50)
        assert result["dividends_gross_chf"] == pytest.approx(140.0)  # 90 + 50
        assert result["dividends_tax_chf"] == pytest.approx(13.50)
        # Invariante: gross >= net (vorher fiel die NULL-Row aus der SUM
        # -> gross 90 < net 126.50)
        assert result["dividends_gross_chf"] >= result["dividends_net_chf"]

    async def test_bucket_twin_same_gross_semantics(self, db):
        uid = uuid.uuid4()
        bucket_id = uuid.uuid4()
        pos = _db_pos(uid, ticker="DIV", bucket_id=bucket_id)
        db.add(pos)
        await db.commit()

        db.add_all([
            _txn(uid, pos.id, TransactionType.dividend, date(2024, 3, 1),
                 currency="USD", fx_rate_to_chf=Decimal("0.9"),
                 total_chf=Decimal("76.50"), taxes_chf=Decimal("13.50"),
                 gross_amount=Decimal("100"), tax_amount=Decimal("15")),
            _txn(uid, pos.id, TransactionType.dividend, date(2024, 4, 1),
                 total_chf=Decimal("50"), gross_amount=None, tax_amount=None),
        ])
        await db.commit()

        from services.total_return_service import get_bucket_total_return
        stub_summary = {"positions": []}
        result = await get_bucket_total_return(
            db, uid, bucket_id, summary=stub_summary
        )

        assert result["dividends_net_chf"] == pytest.approx(126.50)
        assert result["dividends_gross_chf"] == pytest.approx(140.0)
        assert result["dividends_gross_chf"] >= result["dividends_net_chf"]
