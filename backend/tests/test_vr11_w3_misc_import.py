"""Vollreview 11/2026, Welle 3, Fixer «misc»: Import.

C2 (Ticker mit Leer- oder Sonderzeichen werden angenommen, Yahoo-Symbol nur
wenn eindeutig), K023 (yf_download bekommt eine Liste), K059 (yf_to_thread
für den Branchen-Abruf), K149 (date_format passt in die Spalte).
"""

from __future__ import annotations

import uuid

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import select

import api.imports as imports_api
import services.import_service as imp
import yf_patch
from models.import_profile import ImportProfile
from models.position import AssetType, Position
from models.user import User, UserSettings
from services.bucket_service import create_system_buckets, get_liquid_default_bucket
from services.import_service import ImportPreview, ParsedTransaction

TEST_PASSWORD = "TestPassw0rd!2026"


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


def _parsed(**over) -> ParsedTransaction:
    base = dict(
        type="buy", date="2024-03-01", ticker="TEST", shares=10, price_per_share=100.0,
        currency="CHF", fx_rate_to_chf=1.0, fees_chf=5.0, total_chf=1005.0,
    )
    base.update(over)
    return ParsedTransaction(**base)


async def _noop_industries(_db, _positions):
    return None


async def _positions(db, user_id) -> dict[str, Position]:
    rows = (await db.execute(select(Position).where(Position.user_id == user_id))).scalars().all()
    return {p.ticker: p for p in rows}


# --- C2: Yahoo-Symbol zu einem Anzeige-Ticker --------------------------------


class TestYahooSymbolFor:
    @pytest.mark.parametrize("ticker, expected", [
        ("BRK B", "BRK-B"),          # IBKR, US-Klassen-Aktie
        ("BF B", "BF-B"),
        ("NOVO B.CO", "NOVO-B.CO"),  # mit Börsen-Suffix aus dem IBKR-Mapping
        ("VOLV B.ST", "VOLV-B.ST"),
        ("  BRK B ", "BRK-B"),
        ("NESN.SW", "NESN.SW"),      # gültiger Markt-Ticker bleibt
        ("BRK-B", "BRK-B"),
    ])
    def test_unambiguous_tickers_are_translated(self, ticker, expected):
        assert imp.yahoo_symbol_for(ticker) == expected

    @pytest.mark.parametrize("ticker", [
        "", None, "FOO BAR", "A B C", "BRK  B", "BTC/USD", "AAPL?x=1", "AA,AB AC",
        "Mein Fonds 1", "BRK B.TOOLONG", "ÄBC B",
    ])
    def test_everything_else_gets_no_symbol(self, ticker):
        assert imp.yahoo_symbol_for(ticker) is None

    def test_result_is_always_a_market_ticker(self):
        from api.validation import is_market_ticker

        for ticker in ("BRK B", "NOVO B.CO", "X1 A", "ABCDEF Z.L"):
            assert is_market_ticker(imp.yahoo_symbol_for(ticker))


class TestPreview:
    async def test_class_share_gets_the_yahoo_symbol_and_a_warning(self, db):
        txns, new_positions = await imp.enrich_transactions([_parsed(ticker="BRK B", name="Berkshire")], db)

        assert new_positions[0]["ticker"] == "BRK B"  # Anzeige-Ticker bleibt
        assert new_positions[0]["yfinance_ticker"] == "BRK-B"
        assert txns[0].suggested_yfinance_ticker == "BRK-B"
        assert len(txns[0].warnings) == 1
        warning = txns[0].warnings[0]
        assert "«BRK B» enthält Leer- oder Sonderzeichen" in warning
        assert "«BRK-B»" in warning

    async def test_ambiguous_ticker_gets_no_yahoo_symbol(self, db):
        txns, new_positions = await imp.enrich_transactions([_parsed(ticker="FOO BAR 1", name="Foo")], db)

        assert new_positions[0]["ticker"] == "FOO BAR 1"
        assert new_positions[0]["yfinance_ticker"] is None
        assert txns[0].warnings == [
            "Ticker «FOO BAR 1» enthält Leer- oder Sonderzeichen; bitte nach dem Import "
            "den Yahoo-Ticker setzen."
        ]

    async def test_valid_ticker_is_untouched(self, db):
        txns, new_positions = await imp.enrich_transactions([_parsed(ticker="NOVN.SW")], db)
        assert new_positions[0]["yfinance_ticker"] == "NOVN.SW"
        assert txns[0].suggested_yfinance_ticker == "NOVN.SW"
        assert txns[0].warnings == []

    async def test_unpriced_types_keep_their_free_text_ticker_without_warning(self, db):
        txns, new_positions = await imp.enrich_transactions(
            [_parsed(ticker="Mein Konto (CHF)", suggested_asset_type="cash")], db
        )
        assert new_positions[0]["yfinance_ticker"] == "Mein Konto (CHF)"
        assert txns[0].warnings == []

    def test_preview_lists_the_tickers_in_the_top_level_warnings(self):
        preview = ImportPreview(
            source_type="csv", filename="x.csv", total_rows=3, transactions=[],
            new_positions=[
                {"ticker": "BRK B", "suggested_type": "stock", "yfinance_ticker": "BRK-B"},
                {"ticker": "FOO BAR 1", "suggested_type": "etf", "yfinance_ticker": None},
                {"ticker": "NESN.SW", "suggested_type": "stock", "yfinance_ticker": "NESN.SW"},
                {"ticker": "Mein Konto (CHF)", "suggested_type": "cash"},
            ],
        )
        imp.add_preview_warnings(preview)
        assert len(preview.warnings) == 2
        assert "«BRK-B»" in preview.warnings[0]
        assert preview.warnings[1].endswith("bitte nach dem Import den Yahoo-Ticker setzen.")

    def test_top_level_ticker_warnings_are_capped(self):
        preview = ImportPreview(
            source_type="csv", filename="x.csv", total_rows=0, transactions=[],
            new_positions=[{"ticker": f"FOO BAR {i}", "suggested_type": "stock"} for i in range(25)],
        )
        imp.add_preview_warnings(preview)
        assert len(preview.warnings) == imp._MAX_TICKER_WARNINGS + 1
        assert "5 weitere Ticker" in preview.warnings[-1]


class TestConfirm:
    async def test_class_share_is_stored_with_the_yahoo_symbol(self, db, monkeypatch):
        """IBKR «BRK B»: Anzeige-Ticker bleibt, yfinance_ticker wird «BRK-B»."""
        monkeypatch.setattr(imp, "_auto_assign_industries", _noop_industries)
        user = await _make_user(db)
        # Die Vorschau liefert das Symbol mit; ein älterer Client schickt den Ticker selbst.
        result = await imp.confirm_import(
            [],
            [
                {"ticker": "BRK B", "name": "Berkshire", "suggested_type": "stock", "yfinance_ticker": "BRK-B"},
                {"ticker": "BF B", "name": "Brown-Forman", "suggested_type": "stock", "yfinance_ticker": "BF B"},
                {"ticker": "NOVO B.CO", "name": "Novo Nordisk", "suggested_type": "stock"},
            ],
            db, user.id,
        )
        assert result["created_positions"] == 3
        by_ticker = await _positions(db, user.id)
        assert by_ticker["BRK B"].yfinance_ticker == "BRK-B"
        assert by_ticker["BF B"].yfinance_ticker == "BF-B"
        assert by_ticker["NOVO B.CO"].yfinance_ticker == "NOVO-B.CO"

    async def test_invalid_yahoo_symbol_is_never_stored_for_priced_types(self, db, monkeypatch):
        """Der Wert geht in Abrufe, deren Ergebnis sich alle Nutzer teilen (K023)."""
        from api.validation import is_market_ticker

        monkeypatch.setattr(imp, "_auto_assign_industries", _noop_industries)
        user = await _make_user(db)
        await imp.confirm_import(
            [],
            [
                {"ticker": "FOO BAR 1", "name": "Foo", "suggested_type": "etf"},
                {"ticker": "AA,AB AC", "name": "Komma", "suggested_type": "stock", "yfinance_ticker": "AA,AB AC"},
                {"ticker": "AAPL", "name": "Apple", "suggested_type": "stock", "yfinance_ticker": "AAPL?x=1"},
                {"ticker": "BTC/USD", "name": "Bitcoin", "suggested_type": "crypto"},
                {"ticker": "MSFT", "name": "Microsoft", "suggested_type": "stock", "yfinance_ticker": "MSFT"},
            ],
            db, user.id,
        )
        by_ticker = await _positions(db, user.id)
        assert by_ticker["FOO BAR 1"].yfinance_ticker is None
        assert by_ticker["AA,AB AC"].yfinance_ticker is None
        assert by_ticker["BTC/USD"].yfinance_ticker is None
        assert by_ticker["AAPL"].yfinance_ticker == "AAPL"  # der gültige Anzeige-Ticker gilt
        assert by_ticker["MSFT"].yfinance_ticker == "MSFT"
        for pos in by_ticker.values():
            assert pos.yfinance_ticker is None or is_market_ticker(pos.yfinance_ticker)

    async def test_unpriced_types_are_unchanged(self, db, monkeypatch):
        monkeypatch.setattr(imp, "_auto_assign_industries", _noop_industries)
        user = await _make_user(db)
        await imp.confirm_import(
            [],
            [
                {"ticker": "Mein Konto (CHF)", "name": "Konto", "suggested_type": "cash"},
                {"ticker": "Gold 1oz", "name": "Gold", "suggested_type": "commodity"},
            ],
            db, user.id,
        )
        by_ticker = await _positions(db, user.id)
        assert by_ticker["Mein Konto (CHF)"].yfinance_ticker is None  # Saldo-Konto, wie bisher
        assert by_ticker["Gold 1oz"].yfinance_ticker == "Gold 1oz"
        assert by_ticker["Gold 1oz"].type == AssetType.commodity

    async def test_route_imports_the_ibkr_symbol_end_to_end(self, client, db):
        """Regression aus Welle 2: der Import scheiterte am 422, ohne Ausweg im Wizard."""
        await client.post("/api/auth/register", json={"email": "ibkr@example.com", "password": TEST_PASSWORD})
        res = await client.post("/api/auth/login", json={"email": "ibkr@example.com", "password": TEST_PASSWORD})
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

        res = await client.post(
            "/api/import/confirm",
            json={
                "transactions": [{
                    "type": "buy", "date": "2024-03-01", "ticker": "BRK B", "shares": 2,
                    "price_per_share": 400.0, "currency": "USD", "fx_rate_to_chf": 0.9,
                    "total_chf": 720.0, "is_new_position": True, "import_source": "ibkr_csv",
                }],
                "new_positions": [{
                    "key": "BRK B", "ticker": "BRK B", "name": "BERKSHIRE HATHAWAY INC-CL B",
                    "suggested_type": "stock", "currency": "USD", "yfinance_ticker": "BRK-B",
                }],
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["created_positions"] == 1
        assert body["created_transactions"] == 1

        pos = (await db.execute(select(Position).where(Position.ticker == "BRK B"))).scalars().one()
        assert pos.yfinance_ticker == "BRK-B"
        assert float(pos.shares) == 2.0


# --- K023 / K059 --------------------------------------------------------------


class TestYfinanceCalls:
    async def test_fx_download_passes_a_list_with_one_symbol(self, monkeypatch):
        """K023: ein String ginge durch die Zerlegung von yfinance («A,B C» = drei Abrufe)."""
        seen: list = []

        def fake(tickers, start=None, end=None, **kw):
            seen.append(tickers)
            idx = pd.date_range(start, end, freq="D")
            return pd.DataFrame({"Close": [0.9] * len(idx)}, index=idx)

        monkeypatch.setattr(yf_patch, "yf_download", fake)
        txn = _parsed(currency="USD", date="2019-05-06")
        await imp._enrich_fx_rates([txn])

        assert seen == [["USDCHF=X"]]
        assert txn.fx_rate_to_chf == 0.9

    async def test_industry_lookup_runs_in_the_ticker_pool(self, db, monkeypatch):
        """K059: der Abruf am Ticker-Lock belegt nicht den Standard-Pool."""
        calls: list[tuple] = []

        async def fake_to_thread(func, /, *args, **kwargs):
            calls.append((func.__name__, args))
            return func(*args, **kwargs)

        def fake_attr(ticker, attr):
            return {"industry": "Software - Infrastructure", "sector": "Technology"}

        monkeypatch.setattr(yf_patch, "yf_to_thread", fake_to_thread)
        monkeypatch.setattr(yf_patch, "yf_ticker_attr", fake_attr)

        user = await _make_user(db)
        bucket = await get_liquid_default_bucket(db, user.id)
        pos = Position(
            user_id=user.id, bucket_id=bucket.id, ticker="MSFT", name="Microsoft",
            type=AssetType.stock, currency="USD", shares=1, cost_basis_chf=1,
        )
        db.add(pos)
        await db.commit()

        await imp._auto_assign_industries(db, [pos])

        assert calls == [("fake_attr", ("MSFT", "info"))]
        assert pos.industry == "Software - Infrastructure"


# --- K149 ---------------------------------------------------------------------


class TestProfileDateFormat:
    def test_date_format_fits_the_column(self):
        column_length = ImportProfile.__table__.c.date_format.type.length
        assert column_length == 30
        ok = imports_api.ProfileCreate(
            name="p", column_mapping={}, type_mapping={}, date_format="x" * column_length,
        )
        assert len(ok.date_format) == column_length
        with pytest.raises(ValidationError):
            imports_api.ProfileCreate(
                name="p", column_mapping={}, type_mapping={}, date_format="x" * (column_length + 1),
            )

    def test_default_date_format_is_valid(self):
        profile = imports_api.ProfileCreate(name="p", column_mapping={}, type_mapping={})
        assert len(profile.date_format) <= 30
