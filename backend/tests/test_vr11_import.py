"""Vollreview 11/2026 — Import (Fixer «import»).

Befunde: K010 (Zeilengrenze, Thread, Warnungen), K025 (FX-Abrufe), K026 (Limits
je Nutzer), K014 (Profil-Mappings), K080 (Snapshot-Regeneration), K043
(is_active nach Import), K045 (Regeln mit Quelle), K048 (Sperre je Nutzer),
X13/K113 (Encoding), X15 (Dividenden-Netto), X32 (eigener Export), K006
(Buchungsdatum), K019 (coingecko_id nur bei Krypto), dazu die Ticker-Prüfung
neuer Positionen.

Kein Netz: yfinance wird an der Bindungsstelle ersetzt. Die Tests laufen auf
SQLite; die Postgres-Sperre wird an einer Attrappe geprüft.
"""
from __future__ import annotations

import io
import threading
import types
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

import api.imports as imports_api
import services.ibkr_parser as ibkr
import services.import_service as imp
import services.pocket_parser as pocket
import services.swissquote_parser as sq
import yf_patch
from api.validation import BOOKING_DATE_ERROR
from constants.limits import MAX_IMPORT_FX_CURRENCIES, RL_READ
from models.import_profile import ImportProfile
from models.position import AssetType, Position, PriceSource
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from services import cache
from services.bucket_service import create_bucket, create_system_buckets, get_liquid_default_bucket
import services.import_bucket_rule_service as rules_service
from services.import_bucket_rule_service import ImportRuleError, create_rule
from services.import_service import ParsedTransaction
from services.settings_service import export_transactions_csv

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"

GENERIC_HEADER = "Date,Type,Ticker,Shares,Price,Currency,Total"

SQ_HEADER = (
    "Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;"
    "Aufgelaufene Zinsen;Nettobetrag;Währung Nettobetrag;"
    "Nettobetrag in Kontowährung;Saldo;Währung"
)

IBKR_HEADER = (
    "Symbol,ISIN,CurrencyPrimary,AssetClass,TradeDate,Buy/Sell,Quantity,TradePrice,"
    "IBCommission,IBCommissionCurrency,TradeMoney,ListingExchange,FXRateToBase,Taxes,"
    "Description,Notes/Codes,TransactionType"
)

IBKR_CASH_HEADER = (
    "ClientAccountID,CurrencyPrimary,FXRateToBase,Symbol,ISIN,ListingExchange,"
    "Date/Time,SettleDate,Amount,Type,Description"
)

POCKET_HEADER = (
    "type;date;reference;price.currency;price.amount;cost.currency;cost.amount;"
    "fee.currency;fee.amount;value.currency;value.amount"
)


# --- Helfer ------------------------------------------------------------------

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


async def _make_position(db, user, *, ticker="AAPL", shares="0", cost="0", **over) -> Position:
    liquid = await get_liquid_default_bucket(db, user.id)
    pos = Position(
        user_id=user.id,
        bucket_id=liquid.id,
        ticker=ticker,
        name=f"{ticker} Inc",
        type=AssetType.stock,
        currency="CHF",
        price_source=PriceSource.yahoo,
        shares=Decimal(shares),
        cost_basis_chf=Decimal(cost),
        **over,
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    return pos


def _txn(pos_id, **over) -> dict:
    base = {
        "position_id": str(pos_id) if pos_id else None,
        "type": "buy",
        "date": "2025-01-15",
        "shares": 10,
        "price_per_share": 150.0,
        "currency": "CHF",
        "fx_rate_to_chf": 1.0,
        "fees_chf": 0,
        "taxes_chf": 0,
        "total_chf": 1500.0,
    }
    base.update(over)
    return base


def _parsed(currency="CHF", **over) -> ParsedTransaction:
    base = dict(
        type="buy", date="2024-03-01", ticker="TEST", shares=10, price_per_share=100.0,
        currency=currency, fx_rate_to_chf=1.0, fees_chf=5.0, total_chf=1005.0,
    )
    base.update(over)
    return ParsedTransaction(**base)


def _fx_frame(rate: float, start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="D")
    return pd.DataFrame({"Close": [rate] * len(idx)}, index=idx)


async def _register_and_login(client, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    res = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    return res.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _generic_csv(rows: list[str], header: str = GENERIC_HEADER) -> bytes:
    return (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")


async def _noop_industries(_db, _positions):
    return None


# --- K010: Zeilengrenze, Thread, Warnungen -----------------------------------

class TestRowLimit:
    ROW = "2025-01-15,buy,AAA,1,10,CHF,10"

    async def test_parse_csv_rejects_more_rows_than_the_limit(self, db, monkeypatch):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 3)
        with pytest.raises(ValueError, match="mehr als"):
            await imp.parse_csv(_generic_csv([self.ROW] * 4), "big.csv", db)

    async def test_parse_csv_accepts_exactly_the_limit(self, db, monkeypatch):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 3)
        preview = await imp.parse_csv(_generic_csv([self.ROW] * 3), "ok.csv", db)
        assert preview.total_rows == 3

    async def test_analyze_rejects_too_many_rows_before_storing_the_upload(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 3)
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        with pytest.raises(ValueError, match="mehr als"):
            await imp.analyze_csv_structure(_generic_csv([self.ROW] * 4), "big.csv", db, uuid.uuid4())
        assert list(tmp_path.iterdir()) == []

    async def test_parse_route_answers_422(self, client, monkeypatch):
        token = await _register_and_login(client, "rows@example.com")
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 3)
        res = await client.post(
            "/api/import/parse",
            files={"file": ("big.csv", io.BytesIO(_generic_csv([self.ROW] * 4)), "text/csv")},
            headers=_auth(token),
        )
        assert res.status_code == 422
        assert "Zeilen" in res.json()["detail"]

    async def test_swissquote_parser_enforces_the_limit(self, db, monkeypatch):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        row = "15-03-2024 10:00:00;00000000;Zinsen;;;;;;;;3.20;CHF;3.20;100.00;CHF"
        with pytest.raises(ValueError, match="mehr als"):
            await sq.parse_swissquote_csv("\n".join([SQ_HEADER] + [row] * 3), "sq.csv", db)

    async def test_pocket_parser_enforces_the_limit(self, monkeypatch):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        row = "exchange;2024-12-20T11:11:08.000Z;RF1;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0.058305"
        with pytest.raises(ValueError, match="mehr als"):
            await pocket.parse_pocket_csv("\n".join([POCKET_HEADER] + [row] * 3), "p.csv")

    async def test_ibkr_cash_parser_enforces_the_limit(self, db, monkeypatch):
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        row = "U1,CHF,1,VT,US9220427424,ARCA,20240315;093000,20240318,85.00,Dividends,VT DIV"
        with pytest.raises(ValueError, match="mehr als"):
            await ibkr.parse_ibkr_csv("\n".join([IBKR_CASH_HEADER] + [row] * 3), "c.csv", db)

    async def test_ibkr_trades_count_only_the_trade_section(self, db, monkeypatch):
        """Ein langer FX-Abschnitt hinter den Trades ist legitim und zählt nicht."""
        monkeypatch.setattr(imp, "MAX_IMPORT_ROWS", 2)
        trade = "NOVN,CH0012005267,CHF,STK,20240320,BUY,20,95.50,-5.00,CHF,-1910.00,SWX,1.0,0,NOVARTIS,,ExchTrade"
        fx_section = ["Date/Time,FromCurrency,ToCurrency,Rate"] + ["20240320,USD,CHF,0.88"] * 10

        ok = await ibkr.parse_ibkr_csv("\n".join([IBKR_HEADER, trade, trade] + fx_section), "t.csv", db)
        assert ok.total_rows == 1  # zwei Teilausführungen, zusammengefasst

        with pytest.raises(ValueError, match="mehr als"):
            await ibkr.parse_ibkr_csv("\n".join([IBKR_HEADER] + [trade] * 3), "t.csv", db)


class TestParseOffTheEventLoop:
    async def test_generic_rows_are_parsed_in_a_worker_thread(self, db, monkeypatch):
        seen: list[int] = []
        original = imp._parse_csv_row

        def spy(*args, **kwargs):
            seen.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(imp, "_parse_csv_row", spy)
        preview = await imp.parse_csv(_generic_csv(["2025-01-15,buy,AAA,1,10,CHF,10"]), "t.csv", db)
        assert preview.total_rows == 1
        assert seen and threading.get_ident() not in seen

    async def test_fx_rates_are_applied_in_a_worker_thread(self, monkeypatch):
        seen: list[int] = []
        original = imp._apply_fx_rates

        def spy(*args, **kwargs):
            seen.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(imp, "_apply_fx_rates", spy)
        monkeypatch.setattr(yf_patch, "yf_download", lambda pair, start=None, end=None, **kw: _fx_frame(0.9, start, end))
        await imp._enrich_fx_rates([_parsed("USD", date="2019-05-06")])
        assert seen and threading.get_ident() not in seen


    async def test_broker_rows_are_read_in_a_worker_thread(self, db, monkeypatch):
        seen: dict[str, int] = {}

        def spy_on(module, name):
            original = getattr(module, name)

            def spy(*args, **kwargs):
                seen[name] = threading.get_ident()
                return original(*args, **kwargs)

            monkeypatch.setattr(module, name, spy)

        for module, name in (
            (sq, "_read_swissquote_rows"), (sq, "_convert_swissquote_rows"),
            (ibkr, "_read_ibkr_trades"), (ibkr, "_read_ibkr_cash"), (pocket, "_read_pocket_rows"),
        ):
            spy_on(module, name)
        monkeypatch.setattr(sq, "get_fx_rates_batch", lambda: {"CHF": 1.0})

        await sq.parse_swissquote_csv(
            SQ_HEADER + "\n16-03-2024 10:00:00;00000000;Zinsen;;;;;;;;4.20;CHF;4.20;100.00;CHF", "sq.csv", db
        )
        await ibkr.parse_ibkr_csv(
            IBKR_HEADER + "\nNOVN,CH0012005267,CHF,STK,20240320,BUY,20,95.50,-5.00,CHF,-1910.00,SWX,1.0,0,NOVARTIS,,ExchTrade",
            "t.csv", db,
        )
        await ibkr.parse_ibkr_csv(
            IBKR_CASH_HEADER + "\nU1,CHF,1,VT,US9220427424,ARCA,20240315;093000,20240318,85.00,Dividends,VT DIV", "c.csv", db
        )
        await pocket.parse_pocket_csv(
            POCKET_HEADER + "\nexchange;2024-12-20T11:11:08.000Z;RF1;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0.058305", "p.csv"
        )

        assert len(seen) == 5
        assert threading.get_ident() not in seen.values()


class TestWarningsCap:
    async def test_generic_preview_caps_row_warnings(self, db):
        rows = ["kein-datum,buy,AAA,1,10,CHF,10"] * 250 + ["2025-01-15,buy,AAA,1,10,CHF,10"]
        preview = await imp.parse_csv(_generic_csv(rows), "w.csv", db)
        assert preview.total_rows == 1
        assert len(preview.warnings) == imp.MAX_PREVIEW_WARNINGS + 1
        assert "50 weitere" in preview.warnings[-1]

    async def test_pocket_preview_caps_row_warnings(self):
        rows = ["tausch;2024-12-20T11:11:08.000Z;RF1;CHF;1;CHF;1;CHF;1;BTC;1"] * 300
        preview = await pocket.parse_pocket_csv("\n".join([POCKET_HEADER] + rows), "p.csv")
        assert len(preview.warnings) == imp.MAX_PREVIEW_WARNINGS + 1

    def test_short_lists_stay_untouched(self):
        warnings = ["a", "b"]
        assert imp.cap_warnings(warnings) is warnings


# --- K006: Buchungsdatum -----------------------------------------------------

class TestBookingDate:
    async def test_generic_rows_outside_the_range_are_dropped_with_a_warning(self, db):
        future = (date.today() + timedelta(days=30)).isoformat()
        rows = [
            "1900-01-01,buy,AAA,1,10,CHF,10",
            f"{future},buy,AAA,1,10,CHF,10",
            "2025-01-15,buy,AAA,1,10,CHF,10",
        ]
        preview = await imp.parse_csv(_generic_csv(rows), "d.csv", db)
        assert [t.date for t in preview.transactions] == ["2025-01-15"]
        assert preview.warnings == [f"Zeile 2: {BOOKING_DATE_ERROR}", f"Zeile 3: {BOOKING_DATE_ERROR}"]

    async def test_swissquote_row_outside_the_range_is_dropped(self, db, monkeypatch):
        monkeypatch.setattr(sq, "get_fx_rates_batch", lambda: {"CHF": 1.0})
        text = "\n".join([
            SQ_HEADER,
            "01-01-1900 10:00:00;00000000;Zinsen;;;;;;;;3.20;CHF;3.20;100.00;CHF",
            "16-03-2024 10:00:00;00000000;Zinsen;;;;;;;;4.20;CHF;4.20;100.00;CHF",
        ])
        preview = await sq.parse_swissquote_csv(text, "sq.csv", db)
        assert [t.date for t in preview.transactions] == ["2024-03-16"]
        assert any(BOOKING_DATE_ERROR in w for w in preview.warnings)

    async def test_ibkr_trade_outside_the_range_is_dropped(self, db):
        text = "\n".join([
            IBKR_HEADER,
            "NOVN,CH0012005267,CHF,STK,19000320,BUY,20,95.50,-5.00,CHF,-1910.00,SWX,1.0,0,NOVARTIS,,ExchTrade",
            "NOVN,CH0012005267,CHF,STK,20240320,BUY,20,95.50,-5.00,CHF,-1910.00,SWX,1.0,0,NOVARTIS,,ExchTrade",
        ])
        preview = await ibkr.parse_ibkr_csv(text, "t.csv", db)
        assert [t.date for t in preview.transactions] == ["2024-03-20"]
        assert any(BOOKING_DATE_ERROR in w for w in preview.warnings)

    async def test_ibkr_dividend_outside_the_range_is_dropped(self, db):
        text = "\n".join([
            IBKR_CASH_HEADER,
            "U1,CHF,1,VT,US9220427424,ARCA,19000315;093000,19000318,85.00,Dividends,VT DIV",
            "U1,CHF,1,VT,US9220427424,ARCA,20240315;093000,20240318,90.00,Dividends,VT DIV",
        ])
        preview = await ibkr.parse_ibkr_csv(text, "c.csv", db)
        assert [t.date for t in preview.transactions] == ["2024-03-15"]

    async def test_pocket_rows_outside_the_range_are_dropped(self):
        text = "\n".join([
            POCKET_HEADER,
            "exchange;1900-12-20T11:11:08.000Z;RF1;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0.058305",
            "withdrawal;1900-12-21T14:00:00.000Z;RF2;BTC;0;BTC;0;BTC;0.00005;BTC;0.058255",
            "exchange;2024-12-20T11:11:08.000Z;RF3;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0.058305",
        ])
        preview = await pocket.parse_pocket_csv(text, "p.csv")
        assert [t.date for t in preview.transactions] == ["2024-12-20"]
        assert any(BOOKING_DATE_ERROR in w for w in preview.warnings)

    async def test_confirm_import_skips_dates_outside_the_range(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user)
        res = await imp.confirm_import(
            transactions=[_txn(pos.id, date="1900-01-01"), _txn(pos.id, date=date(1, 1, 8), total_chf=7.0)],
            new_positions=[], db=db, user_id=user.id,
        )
        assert res["created_transactions"] == 0
        assert (await db.execute(select(Transaction))).scalars().all() == []

    async def test_confirm_route_rejects_dates_outside_the_range(self, client):
        token = await _register_and_login(client, "dates@example.com")
        res = await client.post(
            "/api/import/confirm",
            json={"transactions": [_txn(uuid.uuid4(), date="1900-01-01")], "new_positions": []},
            headers=_auth(token),
        )
        assert res.status_code == 422

        fx = {
            "date": "0002-01-01", "currency_from": "CHF", "currency_to": "USD",
            "amount_from": 100, "amount_to": 110, "rate": 0.9,
        }
        res = await client.post(
            "/api/import/confirm",
            json={"transactions": [], "new_positions": [], "fx_transactions": [fx]},
            headers=_auth(token),
        )
        assert res.status_code == 422


# --- K025: FX-Abrufe ---------------------------------------------------------

class TestFxLookups:
    async def test_unknown_currency_codes_never_reach_yahoo(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(yf_patch, "yf_download", lambda pair, **kw: calls.append(pair) or pd.DataFrame())
        txns = [_parsed(code) for code in ("XQZ", "ZZ9", "US1", "DOLLAR", "../x")]

        await imp._enrich_fx_rates(txns)

        assert calls == []
        assert all(t.fx_rate_to_chf == 1.0 for t in txns)
        assert all(any("Unbekannte Währung" in w for w in t.warnings) for t in txns)

    async def test_offshore_yuan_is_still_looked_up(self, monkeypatch):
        calls: list[str] = []

        def fake(pair, start=None, end=None, **kw):
            calls.extend(pair)  # yf_download bekommt eine Liste mit einem Symbol (K023)
            return _fx_frame(0.12, start, end)

        monkeypatch.setattr(yf_patch, "yf_download", fake)
        txn = _parsed("CNH", date="2019-06-03")
        await imp._enrich_fx_rates([txn])
        assert calls == ["CNHCHF=X"]
        assert txn.fx_rate_to_chf == 0.12

    async def test_at_most_ten_currencies_per_import(self, monkeypatch):
        calls: list[str] = []

        def fake(pair, start=None, end=None, **kw):
            calls.extend(pair)
            return _fx_frame(0.5, start, end)

        monkeypatch.setattr(yf_patch, "yf_download", fake)
        codes = ["AUD", "CAD", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "NZD", "SEK", "SGD", "USD"]
        assert len(codes) > MAX_IMPORT_FX_CURRENCIES
        # USD zweimal: die häufigste Währung bleibt, auch wenn sie alphabetisch hinten liegt.
        txns = [_parsed(code, date="2018-02-01") for code in codes] + [_parsed("USD", date="2018-02-02")]

        await imp._enrich_fx_rates(txns)

        assert len(calls) == MAX_IMPORT_FX_CURRENCIES
        assert "USDCHF=X" in calls
        skipped = [t for t in txns if t.fx_rate_to_chf == 1.0]
        assert {t.currency for t in skipped} == {"SEK", "SGD"}
        assert all(any("Fremdwährungen" in w for w in t.warnings) for t in skipped)

    async def test_failed_lookups_are_cached_negatively(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(yf_patch, "yf_download", lambda pair, **kw: calls.extend(pair) or pd.DataFrame())
        miss_keys = [
            f"import_fx_miss:{pair}:2017-03-27:2017-04-06" for pair in ("SEKCHF=X", "SEKUSD=X", "USDSEK=X")
        ]
        for key in miss_keys:
            cache.delete(key)
        try:
            first = _parsed("SEK", date="2017-04-01")
            await imp._enrich_fx_rates([first])
            assert calls == ["SEKCHF=X", "SEKUSD=X", "USDSEK=X"]
            assert any("Kein Wechselkurs" in w for w in first.warnings)

            await imp._enrich_fx_rates([_parsed("SEK", date="2017-04-01")])
            assert len(calls) == 3  # zweiter Import: kein weiterer Abruf
        finally:
            for key in miss_keys:
                cache.delete(key)

    @staticmethod
    def _sq_dividend(day: int, currency: str) -> str:
        # Ohne «Nettobetrag in Kontowährung» und ohne Forex-Paar: der Kurs kommt von Yahoo.
        return f"{day:02d}-03-2024 10:00:00;00000000;Dividende;AAPL;Apple;US0378331005;1;10.00;1.50;;8.50;{currency};;100.00;CHF"

    async def _parse_sq(self, db, monkeypatch, rows: list[str], rate: float | None = 0.9):
        calls: list[tuple[str, str]] = []

        async def fake_rate(currency, txn_date):
            calls.append((currency, txn_date))
            return rate

        monkeypatch.setattr(sq, "get_fx_rates_batch", lambda: {"CHF": 1.0, "USD": 0.88})
        monkeypatch.setattr(sq, "get_historical_fx_rate", fake_rate)
        preview = await sq.parse_swissquote_csv("\n".join([SQ_HEADER] + rows), "sq.csv", db)
        return preview, calls

    async def test_swissquote_skips_unknown_currency_codes(self, db, monkeypatch):
        rows = [self._sq_dividend(1, "XQZ"), self._sq_dividend(2, "USD")]
        preview, calls = await self._parse_sq(db, monkeypatch, rows)
        assert calls == [("USD", "2024-03-02")]
        by_currency = {t.currency: t for t in preview.transactions}
        assert by_currency["USD"].fx_source == "yfinance_historical"
        assert by_currency["XQZ"].fx_source == "market_fallback"

    async def test_swissquote_caps_the_number_of_currencies(self, db, monkeypatch):
        codes = ["AUD", "CAD", "DKK", "EUR", "GBP", "HKD", "JPY", "NOK", "NZD", "SEK", "SGD", "USD"]
        rows = [self._sq_dividend(1, code) for code in codes]
        preview, calls = await self._parse_sq(db, monkeypatch, rows)
        assert len({currency for currency, _ in calls}) == MAX_IMPORT_FX_CURRENCIES
        assert any("Wechselkurs-Abfragen" in w for w in preview.warnings)

    async def test_swissquote_caps_the_number_of_date_lookups(self, db, monkeypatch):
        monkeypatch.setattr(sq, "MAX_FX_DATE_LOOKUPS", 3)
        rows = [self._sq_dividend(day, "USD") for day in range(1, 7)]
        preview, calls = await self._parse_sq(db, monkeypatch, rows)
        assert len(calls) == 3
        sources = [t.fx_source for t in preview.transactions]
        assert sources.count("yfinance_historical") == 3
        assert sources.count("market_fallback") == 3
        assert any("3 Kombination(en)" in w for w in preview.warnings)

    async def test_swissquote_caches_failed_lookups(self, db, monkeypatch):
        rows = [self._sq_dividend(9, "USD")]
        cache.delete("import_fx_miss:USD:2024-03-09")
        try:
            _, calls = await self._parse_sq(db, monkeypatch, rows, rate=None)
            assert calls == [("USD", "2024-03-09")]
            _, calls = await self._parse_sq(db, monkeypatch, rows, rate=None)
            assert calls == []
        finally:
            cache.delete("import_fx_miss:USD:2024-03-09")


# --- K026: Limits je Nutzer --------------------------------------------------

class TestUserLimits:
    @staticmethod
    def _cash(n: int) -> dict:
        return {"ticker": f"Konto {n}", "name": f"Konto {n}", "suggested_type": "cash", "key": f"K{n}"}

    async def test_position_limit_counts_existing_and_new(self, db, monkeypatch):
        monkeypatch.setattr(imp, "MAX_POSITIONS_PER_USER", 2)
        user = await _make_user(db)
        await _make_position(db, user, ticker="HAVE")

        with pytest.raises(HTTPException) as exc:
            await imp.confirm_import([], [self._cash(1), self._cash(2)], db, user.id)
        assert exc.value.status_code == 400
        assert "Positionen" in exc.value.detail

        tickers = (await db.execute(select(Position.ticker).where(Position.user_id == user.id))).scalars().all()
        assert tickers == ["HAVE"]

        res = await imp.confirm_import([], [self._cash(1)], db, user.id)
        assert res["created_positions"] == 1

    async def test_transaction_limit_rolls_the_whole_import_back(self, db, monkeypatch):
        monkeypatch.setattr(imp, "MAX_TRANSACTIONS_PER_USER", 2)
        user = await _make_user(db)
        pos = await _make_position(db, user)
        user_id, pos_id = user.id, pos.id
        rows = [_txn(pos_id, date=f"2025-01-1{i}", total_chf=100.0 + i) for i in range(3)]

        with pytest.raises(HTTPException) as exc:
            await imp.confirm_import(rows, [self._cash(1)], db, user_id)
        assert exc.value.status_code == 400
        assert "Transaktionen" in exc.value.detail

        assert (await db.execute(select(Transaction).where(Transaction.user_id == user_id))).scalars().all() == []
        tickers = (await db.execute(select(Position.ticker).where(Position.user_id == user_id))).scalars().all()
        assert tickers == ["AAPL"]

    async def test_duplicates_do_not_count_against_the_limit(self, db, monkeypatch):
        monkeypatch.setattr(imp, "MAX_TRANSACTIONS_PER_USER", 2)
        user = await _make_user(db)
        pos = await _make_position(db, user)
        rows = [_txn(pos.id, date="2025-01-10"), _txn(pos.id, date="2025-01-11")]
        assert (await imp.confirm_import(rows, [], db, user.id))["created_transactions"] == 2

        # Erneuter Import derselben Datei am Limit: alles Duplikate, kein Fehler.
        res = await imp.confirm_import(rows, [], db, user.id)
        assert res["created_transactions"] == 0
        assert res["skipped_duplicates"] == 2

    async def test_route_passes_the_400_through(self, client, monkeypatch):
        token = await _register_and_login(client, "limits@example.com")
        monkeypatch.setattr(imp, "MAX_POSITIONS_PER_USER", 0)
        res = await client.post(
            "/api/import/confirm",
            json={"transactions": [], "new_positions": [self._cash(1)]},
            headers=_auth(token),
        )
        assert res.status_code == 400
        assert "Positionen" in res.json()["detail"]


# --- K014: Profil-Mappings ---------------------------------------------------

class TestProfileMappings:
    @staticmethod
    def _profile(**over) -> dict:
        base = {"name": "Profil", "column_mapping": {"date": "Datum"}, "type_mapping": {"Kauf": "buy"}}
        base.update(over)
        return base

    @pytest.mark.parametrize("field", ["column_mapping", "type_mapping"])
    async def test_oversized_mappings_are_rejected(self, client, field):
        token = await _register_and_login(client, f"{field}@example.com")
        too_many = {f"k{i}": "v" for i in range(101)}
        for bad in (too_many, {"k": "v" * 201}, {"k" * 201: "v"}, {"k": {"nested": 1}}, {"k": 5}):
            res = await client.post("/api/import/profiles", json=self._profile(**{field: bad}), headers=_auth(token))
            assert res.status_code == 422, bad

        at_limit = {f"k{i}": "v" * 200 for i in range(100)}
        res = await client.post("/api/import/profiles", json=self._profile(**{field: at_limit}), headers=_auth(token))
        assert res.status_code == 201

    async def test_parse_with_mapping_rejects_oversized_mappings(self, client):
        token = await _register_and_login(client, "mapping@example.com")
        res = await client.post(
            "/api/import/parse-with-mapping",
            json={
                "upload_id": str(uuid.uuid4()),
                "column_mapping": {"date": "Datum"},
                "type_mapping": {f"k{i}": "buy" for i in range(101)},
            },
            headers=_auth(token),
        )
        assert res.status_code == 422

    async def test_profile_list_has_a_rate_limit(self):
        from limits import parse as parse_limit

        from api.auth import limiter

        registered = [lim.limit for lim in limiter._route_limits.get("api.imports.list_profiles", [])]
        assert registered == [parse_limit(RL_READ)]

    async def test_analyze_lists_saved_profiles_by_id_and_name(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        user = await _make_user(db)
        other = await _make_user(db)
        for owner, name in ((user, "Mein Profil"), (other, "Fremdes Profil")):
            db.add(ImportProfile(user_id=owner.id, name=name, column_mapping={"date": "Datum"}, type_mapping={}))
        await db.commit()

        result = await imp.analyze_csv_structure(_generic_csv(["2025-01-15,buy,AAA,1,10,CHF,10"]), "a.csv", db, user.id)
        assert [p["name"] for p in result["saved_profiles"]] == ["Mein Profil"]
        assert set(result["saved_profiles"][0]) == {"id", "name"}


# --- K080: Snapshot-Regeneration ---------------------------------------------

class TestSnapshotRegenTrigger:
    async def test_regen_runs_only_when_transactions_were_created(self, client, monkeypatch):
        calls: list[tuple] = []
        monkeypatch.setattr(imports_api, "trigger_snapshot_regen", lambda user_id, from_date=None: calls.append((user_id, from_date)))
        token = await _register_and_login(client, "regen@example.com")
        res = await client.post(
            "/api/portfolio/positions",
            json={"name": "Bitcoin", "ticker": "BTC-USD", "type": "crypto", "currency": "CHF", "cost_basis_chf": 0, "shares": 0},
            headers=_auth(token),
        )
        assert res.status_code in (200, 201), res.text
        position_id = res.json()["id"]
        payload = {
            "transactions": [
                _txn(position_id, date="2026-06-15", shares=0.01, price_per_share=60000, total_chf=600.0),
                _txn(position_id, date="2026-06-01", shares=0.02, price_per_share=50000, total_chf=1000.0),
            ],
            "new_positions": [],
        }

        res = await client.post("/api/import/confirm", json=payload, headers=_auth(token))
        assert res.status_code == 201, res.text
        assert res.json()["created_transactions"] == 2
        assert len(calls) == 1
        assert calls[0][1] == date(2026, 6, 1)  # ältestes importiertes Datum

        # Dieselbe Datei noch einmal: nur Duplikate, also keine Regeneration.
        res = await client.post("/api/import/confirm", json=payload, headers=_auth(token))
        assert res.status_code == 201, res.text
        assert res.json()["created_transactions"] == 0
        assert len(calls) == 1


# --- K043: is_active und Stop-Loss nach dem Import ---------------------------

class TestActiveStateAfterImport:
    async def test_newest_row_first_ends_with_a_closed_position(self, db):
        """Verkauf (2024) vor Kauf (2023) in der Datei: Endbestand 0, also inaktiv."""
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="FLIP")
        await imp.confirm_import(
            [
                _txn(pos.id, type="sell", date="2024-05-02", total_chf=1600.0),
                _txn(pos.id, type="buy", date="2023-05-02", total_chf=1500.0),
            ],
            [], db, user.id,
        )
        await db.refresh(pos)
        assert float(pos.shares) == 0
        assert pos.is_active is False

    async def test_older_statement_keeps_position_and_stop_loss(self, db):
        """Ein älterer Auszug mit Verkauf darf eine Position mit Bestand nicht schliessen."""
        user = await _make_user(db)
        pos = await _make_position(
            db, user, ticker="KEEP", shares="10", cost="1500",
            stop_loss_price=Decimal("120"), stop_loss_method="manual",
        )
        db.add(Transaction(
            position_id=pos.id, user_id=user.id, type=TransactionType.buy,
            date=date(2023, 5, 2), shares=Decimal("10"), price_per_share=Decimal("150"),
            currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("1500"),
        ))
        await db.commit()

        await imp.confirm_import(
            [_txn(pos.id, type="sell", date="2021-03-01", total_chf=900.0)],
            [], db, user.id,
        )
        await db.refresh(pos)
        assert float(pos.shares) == 10
        assert pos.is_active is True
        assert float(pos.stop_loss_price) == 120

    async def test_selling_everything_clears_the_stop_loss(self, db):
        user = await _make_user(db)
        pos = await _make_position(
            db, user, ticker="GONE", shares="10", cost="1500",
            stop_loss_price=Decimal("120"), stop_loss_method="manual",
        )
        db.add(Transaction(
            position_id=pos.id, user_id=user.id, type=TransactionType.buy,
            date=date(2023, 5, 2), shares=Decimal("10"), price_per_share=Decimal("150"),
            currency="CHF", fx_rate_to_chf=Decimal("1"), total_chf=Decimal("1500"),
        ))
        await db.commit()

        await imp.confirm_import(
            [_txn(pos.id, type="sell", date="2024-03-01", total_chf=1700.0)],
            [], db, user.id,
        )
        await db.refresh(pos)
        assert float(pos.shares) == 0
        assert pos.is_active is False
        assert pos.stop_loss_price is None

    async def test_dividend_only_import_leaves_the_position_alone(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="DIVI", shares="7", cost="700")
        await imp.confirm_import(
            [_txn(pos.id, type="dividend", shares=0, price_per_share=0, total_chf=12.5)],
            [], db, user.id,
        )
        await db.refresh(pos)
        assert float(pos.shares) == 7
        assert float(pos.cost_basis_chf) == 700


# --- K026: Obergrenze für Import-Regeln --------------------------------------

class TestImportRuleLimit:
    async def test_rules_per_user_are_capped(self, db, monkeypatch):
        monkeypatch.setattr(rules_service, "MAX_IMPORT_BUCKET_RULES_PER_USER", 2)
        user = await _make_user(db)
        other = await _make_user(db)
        bucket = await create_bucket(db, user.id, name="Regeln")
        other_bucket = await create_bucket(db, other.id, name="Regeln")
        await db.commit()

        for pattern in ("A*", "B*"):
            await create_rule(db, user.id, bucket_id=bucket.id, ticker_pattern=pattern)
        with pytest.raises(ImportRuleError, match="Limit erreicht"):
            await create_rule(db, user.id, bucket_id=bucket.id, ticker_pattern="C*")

        # Das Limit gilt je Nutzer.
        await create_rule(db, other.id, bucket_id=other_bucket.id, ticker_pattern="A*")


# --- K045: Bucket-Regeln mit Quelle ------------------------------------------

class TestImportRuleSource:
    async def test_rule_with_source_applies_to_new_positions(self, db):
        user = await _make_user(db)
        bucket = await create_bucket(db, user.id, name="Satellite")
        await db.commit()
        await create_rule(db, user.id, bucket_id=bucket.id, source="swissquote", priority=10)
        await db.commit()

        res = await imp.confirm_import(
            transactions=[
                _txn(None, is_new_position=True, ticker="Konto CHF", import_source="swissquote_csv"),
                _txn(None, is_new_position=True, ticker="Konto EUR", import_source="pocket_csv"),
            ],
            new_positions=[
                {"ticker": "Konto CHF", "name": "Konto CHF", "suggested_type": "commodity", "key": "Konto CHF"},
                {"ticker": "Konto EUR", "name": "Konto EUR", "suggested_type": "commodity", "key": "Konto EUR"},
            ],
            db=db, user_id=user.id,
        )
        assert res["created_positions"] == 2

        rows = (await db.execute(select(Position.ticker, Position.bucket_id).where(Position.user_id == user.id))).all()
        buckets = dict(rows)
        liquid = await get_liquid_default_bucket(db, user.id)
        assert buckets["Konto CHF"] == bucket.id
        assert buckets["Konto EUR"] == liquid.id


# --- K048: Sperre je Nutzer --------------------------------------------------

class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeSession:
    def __init__(self, dialect: str, answers: list[bool] | None = None):
        self._dialect = dialect
        self._answers = list(answers or [])
        self.statements: list[tuple[str, dict]] = []

    def get_bind(self):
        return types.SimpleNamespace(dialect=types.SimpleNamespace(name=self._dialect))

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return _FakeResult(self._answers.pop(0) if self._answers else False)


class TestImportLock:
    async def test_postgres_takes_an_advisory_lock_for_the_user(self):
        user_id = uuid.uuid4()
        session = _FakeSession("postgresql", [True])
        await imp._lock_user_import(session, user_id)
        (sql, params), = session.statements
        assert "pg_try_advisory_xact_lock" in sql
        assert params == {
            "ns": imp._IMPORT_LOCK_NAMESPACE,
            "key": int.from_bytes(user_id.bytes[:4], "big", signed=True),
        }

    async def test_waits_until_the_first_import_is_done(self, monkeypatch):
        monkeypatch.setattr(imp, "_IMPORT_LOCK_POLL_SECONDS", 0)
        session = _FakeSession("postgresql", [False, False, True])
        await imp._lock_user_import(session, uuid.uuid4())
        assert len(session.statements) == 3

    async def test_gives_up_with_409_after_the_wait(self, monkeypatch):
        monkeypatch.setattr(imp, "_IMPORT_LOCK_MAX_WAIT_SECONDS", 0)
        session = _FakeSession("postgresql", [False])
        with pytest.raises(HTTPException) as exc:
            await imp._lock_user_import(session, uuid.uuid4())
        assert exc.value.status_code == 409

    async def test_other_dialects_run_without_lock_statement(self):
        session = _FakeSession("sqlite")
        await imp._lock_user_import(session, uuid.uuid4())
        assert session.statements == []

    async def test_confirm_locks_before_reading_the_duplicate_keys(self, db, monkeypatch):
        order: list[str] = []
        original = imp._load_dup_sets

        async def fake_lock(_db, user_id):
            order.append(f"lock:{user_id}")

        async def spy_dups(*args, **kwargs):
            order.append("dups")
            return await original(*args, **kwargs)

        monkeypatch.setattr(imp, "_lock_user_import", fake_lock)
        monkeypatch.setattr(imp, "_load_dup_sets", spy_dups)
        user = await _make_user(db)
        pos = await _make_position(db, user)
        await imp.confirm_import([_txn(pos.id)], [], db, user.id)
        assert order == [f"lock:{user.id}", "dups"]


# --- X13 / K113: Encoding ----------------------------------------------------

class TestEncoding:
    def test_shared_order_reaches_cp1252_and_strips_the_bom(self):
        assert imp.decode_csv_bytes("ä’".encode("cp1252")) == ("ä’", "cp1252")
        assert imp.decode_csv_bytes("﻿Date".encode("utf-8")) == ("Date", "utf-8")
        assert imp.decode_csv_bytes("Stückpreis".encode("utf-8")) == ("Stückpreis", "utf-8")
        # 0x81 ist in cp1252 nicht belegt: erst hier greift latin-1.
        assert imp.decode_csv_bytes(b"St\xfcck\x81")[1] == "latin-1"

    async def test_cp1252_amount_with_typographic_apostrophe_is_read(self, db):
        body = "Date;Type;Ticker;Shares;Price;Currency;Total\n2025-01-15;buy;AAA;10;123.45;CHF;1’234.50\n"
        preview = await imp.parse_csv(body.encode("cp1252"), "excel.csv", db)
        assert preview.transactions[0].total_chf == 1234.5
        assert preview.warnings == []

    async def test_bom_does_not_hide_the_first_column(self, db, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "UPLOAD_DIR", str(tmp_path))
        content = ("﻿" + GENERIC_HEADER + "\n2025-01-15,buy,AAA,1,10,CHF,10\n").encode("utf-8")
        result = await imp.analyze_csv_structure(content, "bom.csv", db, uuid.uuid4())
        assert result["headers"][0] == "Date"
        assert result["suggested_mapping"]["date"] == "Date"
        assert result["encoding"] == "utf-8"

        preview = await imp.parse_csv(content, "bom.csv", db)
        assert preview.total_rows == 1

    async def test_bom_does_not_hide_the_ibkr_cash_format(self, db):
        content = (
            "﻿" + IBKR_CASH_HEADER
            + "\nU1,CHF,1,VT,US9220427424,ARCA,20240315;093000,20240318,85.00,Dividends,VT DIV\n"
        ).encode("utf-8")
        preview = await imp.parse_csv(content, "ibkr.csv", db)
        assert preview.source_type == "ibkr_csv"
        assert preview.total_rows == 1

    async def test_unreadable_amounts_are_reported(self, db):
        rows = ["2025-01-15,dividend,AAA,0,0,CHF,abc"]
        preview = await imp.parse_csv(_generic_csv(rows), "amount.csv", db)
        assert preview.warnings == ["Zeile 2: Betrag 'abc' konnte nicht gelesen werden — auf 0 gesetzt"]


# --- X15: Dividenden behalten ihr Netto --------------------------------------

class TestDividendKeepsNet:
    async def test_confirm_does_not_turn_a_dividend_into_gross_plus_fees(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="DIV")
        await imp.confirm_import(
            [_txn(
                pos.id, type="dividend", currency="USD", fx_rate_to_chf=0.9,
                shares=100, price_per_share=0.5, fees_chf=2.0,
                gross_amount=50.0, tax_amount=7.5, total_chf=38.25,
            )],
            [], db, user.id,
        )
        txn = (await db.execute(select(Transaction).where(Transaction.position_id == pos.id))).scalar_one()
        assert float(txn.total_chf) == 38.25  # (50 − 7.5) × 0.9, nicht 100 × 0.5 × 0.9 + 2

    async def test_trades_keep_the_derived_total(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="TRD")
        await imp.confirm_import(
            [_txn(pos.id, type="delivery_in", currency="USD", fx_rate_to_chf=0.9, shares=10, price_per_share=150.0, fees_chf=5, total_chf=0.0)],
            [], db, user.id,
        )
        txn = (await db.execute(select(Transaction).where(Transaction.position_id == pos.id))).scalar_one()
        assert float(txn.total_chf) == 1355.0

    async def test_fx_enrichment_leaves_non_trade_totals_alone(self, monkeypatch):
        monkeypatch.setattr(yf_patch, "yf_download", lambda pair, start=None, end=None, **kw: _fx_frame(0.9, start, end))
        dividend = _parsed("USD", type="dividend", date="2016-08-01", shares=100, price_per_share=0.5, fees_chf=0, total_chf=38.25)
        buy = _parsed("USD", type="buy", date="2016-08-02")

        await imp._enrich_fx_rates([dividend, buy])

        assert dividend.fx_rate_to_chf == 0.9
        assert dividend.total_chf == 38.25
        assert buy.total_chf == 905.0  # 10 × 100 × 0.9 + 5


# --- X32: eigener Export -----------------------------------------------------

class TestOwnExportRoundTrip:
    def test_export_header_maps_the_amount_column(self):
        header = ["Datum", "Typ", "Ticker", "Stueck", "Kurs", "Waehrung", "FX", "Gebuehren", "Steuern", "Total CHF"]
        assert imp._auto_detect_mapping(header)["total_chf"] == "Total CHF"

    async def test_export_then_parse_returns_the_same_amounts(self, db):
        user = await _make_user(db)
        pos = await _make_position(db, user, ticker="NESN.SW")
        for txn_type, day, shares, price, fees, total in (
            (TransactionType.buy, 10, "10", "100", "5", "1005"),
            (TransactionType.dividend, 20, "0", "0", "0", "12.30"),
        ):
            db.add(Transaction(
                position_id=pos.id, user_id=user.id, type=txn_type, date=date(2025, 3, day),
                shares=Decimal(shares), price_per_share=Decimal(price), currency="CHF",
                fx_rate_to_chf=Decimal("1"), fees_chf=Decimal(fees), total_chf=Decimal(total),
            ))
        await db.commit()

        exported = await export_transactions_csv(db, user.id)
        preview = await imp.parse_csv(exported.encode("utf-8"), "export.csv", db, user_id=user.id)

        assert {(t.type, t.total_chf) for t in preview.transactions} == {("buy", 1005.0), ("dividend", 12.3)}
        assert {t.fees_chf for t in preview.transactions} == {5.0, 0.0}


# --- K019: coingecko_id nur bei Krypto ---------------------------------------

class TestCoingeckoOnlyForCrypto:
    async def test_stock_position_gets_no_coingecko_id(self, db, monkeypatch):
        monkeypatch.setattr(imp, "_auto_assign_industries", _noop_industries)
        user = await _make_user(db)
        await imp.confirm_import(
            [],
            [
                {"ticker": "AAPL", "name": "Apple", "suggested_type": "stock", "key": "AAPL",
                 "coingecko_id": "bitcoin", "price_source": "coingecko"},
                {"ticker": "BTC-USD", "name": "Bitcoin", "suggested_type": "crypto", "key": "BTC-USD",
                 "coingecko_id": "bitcoin", "price_source": "coingecko"},
            ],
            db, user.id,
        )
        rows = (await db.execute(select(Position).where(Position.user_id == user.id))).scalars().all()
        by_ticker = {p.ticker: p for p in rows}
        assert by_ticker["AAPL"].coingecko_id is None
        assert by_ticker["AAPL"].price_source == PriceSource.yahoo
        assert by_ticker["BTC-USD"].coingecko_id == "bitcoin"
        assert by_ticker["BTC-USD"].price_source == PriceSource.coingecko


# --- Ticker neuer Positionen (Querschnitt Q2) --------------------------------

class TestNewPositionTicker:
    """Welle 3: der Anzeige-Ticker aus der Broker-Datei wird angenommen, auch mit
    Leer- oder Sonderzeichen. Was als Yahoo-Symbol gespeichert wird, prüft
    confirm_import (test_vr11_w3_misc_import.py)."""

    def test_priced_types_reject_only_empty_or_control_char_tickers(self):
        for bad in (
            {"ticker": "", "name": "leer", "suggested_type": "etf"},
            {"ticker": "   ", "name": "leer"},
            {"ticker": "AB\nCD", "name": "Zeilenumbruch"},
        ):
            with pytest.raises(ValidationError):
                imports_api.ImportNewPosition(**bad)

        for ok in (
            {"ticker": "BRK B", "name": "Berkshire"},
            {"ticker": "AAPL", "name": "Apple", "yfinance_ticker": "AAPL?x=1"},
            {"ticker": "BTC/USD", "name": "Bitcoin", "suggested_type": "crypto"},
        ):
            assert imports_api.ImportNewPosition(**ok).ticker == ok["ticker"]

    def test_free_text_tickers_stay_allowed_for_unpriced_types(self):
        for suggested_type in ("cash", "pension", "real_estate", "private_equity", "commodity"):
            np = imports_api.ImportNewPosition(
                ticker="Mein Konto (CHF)", name="Konto", suggested_type=suggested_type,
                yfinance_ticker="Mein Konto (CHF)",
            )
            assert np.model_dump()["suggested_type"] == suggested_type

        ok = imports_api.ImportNewPosition(ticker="NESN.SW", name="Nestlé", yfinance_ticker="NESN.SW")
        assert ok.ticker == "NESN.SW"

    async def test_confirm_route_accepts_the_ticker(self, client):
        """Regression aus Welle 2: IBKR liefert «BRK B», der Import scheiterte mit 422."""
        token = await _register_and_login(client, "ticker@example.com")
        res = await client.post(
            "/api/import/confirm",
            json={"transactions": [], "new_positions": [{"ticker": "BRK B", "name": "Berkshire", "suggested_type": "stock"}]},
            headers=_auth(token),
        )
        assert res.status_code == 201, res.text
        assert res.json()["created_positions"] == 1

    async def test_preview_warns_about_the_ticker(self, db):
        txns, new_positions = await imp.enrich_transactions(
            [_parsed(ticker="BRK B"), _parsed(ticker="NOVN.SW")], db
        )
        assert len(new_positions) == 2
        assert any("Leer- oder Sonderzeichen" in w for w in txns[0].warnings)
        assert txns[1].warnings == []
