"""Tests for the Pocket (pocketbitcoin.com) CSV parser."""

import pytest

from services.pocket_parser import detect_pocket, _parse_pocket_date, _safe_float, parse_pocket_csv

# --- Test CSV fixtures ---

POCKET_HEADER = "type;date;reference;price.currency;price.amount;cost.currency;cost.amount;fee.currency;fee.amount;value.currency;value.amount"

POCKET_CSV_BASIC = f"""{POCKET_HEADER}
exchange;2024-12-20T11:11:08.000Z;RF123456;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0.058305
exchange;2025-01-15T09:30:00.000Z;RF789012;CHF;92150.00;CHF;4900.00;CHF;75.00;BTC;0.054000
"""

POCKET_CSV_WITH_DEPOSIT_AND_WITHDRAWAL = f"""{POCKET_HEADER}
deposit;2024-12-19T08:00:00.000Z;RF100001;CHF;0;CHF;0;CHF;0;CHF;5000.00
exchange;2024-12-20T11:11:08.000Z;RF123456;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0.058305
withdrawal;2024-12-21T14:00:00.000Z;RF100002;BTC;0;BTC;0;BTC;0.00005;BTC;0.058255
"""

POCKET_CSV_ONLY_DEPOSITS = f"""{POCKET_HEADER}
deposit;2024-12-19T08:00:00.000Z;RF100001;CHF;0;CHF;0;CHF;0;CHF;5000.00
deposit;2024-12-20T08:00:00.000Z;RF100002;CHF;0;CHF;0;CHF;0;CHF;3000.00
"""

POCKET_CSV_EMPTY = POCKET_HEADER + "\n"

POCKET_CSV_BAD_DATE = f"""{POCKET_HEADER}
exchange;not-a-date;RF999;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0.058305
"""

POCKET_CSV_ZERO_SHARES = f"""{POCKET_HEADER}
exchange;2024-12-20T11:11:08.000Z;RF123456;CHF;84469.58;CHF;4850.00;CHF;75.00;BTC;0
"""

POCKET_CSV_UNKNOWN_TYPE = f"""{POCKET_HEADER}
refund;2024-12-20T11:11:08.000Z;RF999;CHF;100;CHF;100;CHF;0;CHF;100
"""

# Header from other brokers (negative detection)
IBKR_HEADER = "Symbol,ISIN,CurrencyPrimary,AssetClass,TradeDate,Buy/Sell,Quantity,TradePrice,IBCommission"
SWISSQUOTE_HEADER = "Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten"


# --- detect_pocket tests ---


class TestDetectPocket:
    def test_detect_positive(self):
        headers = POCKET_HEADER.split(";")
        assert detect_pocket(headers) is True

    def test_detect_positive_with_whitespace(self):
        headers = [" type ", " date ", " reference ", " price.currency ", " price.amount ",
                   " cost.currency ", " cost.amount ", " fee.currency ", " fee.amount ",
                   " value.currency ", " value.amount "]
        assert detect_pocket(headers) is True

    def test_detect_negative_empty(self):
        assert detect_pocket([]) is False

    def test_detect_negative_ibkr(self):
        assert detect_pocket(IBKR_HEADER.split(",")) is False

    def test_detect_negative_swissquote(self):
        assert detect_pocket(SWISSQUOTE_HEADER.split(";")) is False

    def test_detect_negative_partial_headers(self):
        assert detect_pocket(["type", "date", "reference"]) is False


# --- _parse_pocket_date tests ---


class TestParsePocketDate:
    def test_iso_with_millis(self):
        d = _parse_pocket_date("2024-12-20T11:11:08.000Z")
        assert d is not None
        assert d.isoformat() == "2024-12-20"

    def test_iso_without_millis(self):
        d = _parse_pocket_date("2024-12-20T11:11:08Z")
        assert d is not None
        assert d.isoformat() == "2024-12-20"

    def test_date_only(self):
        d = _parse_pocket_date("2024-12-20")
        assert d is not None
        assert d.isoformat() == "2024-12-20"

    def test_empty(self):
        assert _parse_pocket_date("") is None

    def test_invalid(self):
        assert _parse_pocket_date("not-a-date") is None


# --- _safe_float tests ---


class TestSafeFloat:
    def test_normal(self):
        assert _safe_float("84469.58") == 84469.58

    def test_zero(self):
        assert _safe_float("0") == 0.0

    def test_empty(self):
        assert _safe_float("") == 0.0

    def test_whitespace(self):
        assert _safe_float("  75.00  ") == 75.0

    def test_invalid(self):
        assert _safe_float("abc") == 0.0

    def test_none(self):
        assert _safe_float(None) == 0.0


# --- parse_pocket_csv tests ---


@pytest.mark.asyncio
class TestParsePocketCsv:
    async def test_basic_exchange(self):
        result = await parse_pocket_csv(POCKET_CSV_BASIC, "pocket.csv")
        assert result.source_type == "pocket_csv"
        assert len(result.transactions) == 2
        assert result.total_rows == 2

        txn = result.transactions[0]
        assert txn.ticker == "BTC-USD"
        assert txn.type == "buy"
        assert txn.date == "2024-12-20"
        assert txn.shares == 0.058305
        assert txn.price_per_share == 84469.58
        assert txn.fees_chf == 75.0
        assert txn.total_chf == 4925.0  # 4850 + 75
        assert txn.currency == "CHF"
        assert txn.fx_rate_to_chf == 1.0
        assert txn.order_id == "RF123456"
        assert txn.import_source == "pocket_csv"
        assert txn.suggested_asset_type == "crypto"

    async def test_skips_deposit_and_withdrawal(self):
        result = await parse_pocket_csv(POCKET_CSV_WITH_DEPOSIT_AND_WITHDRAWAL, "pocket.csv")
        assert len(result.transactions) == 1
        assert result.transactions[0].order_id == "RF123456"
        assert result.broker_meta["skipped_deposits"] == 1
        assert result.broker_meta["skipped_withdrawals"] == 1
        # Warnings about skipped rows
        assert any("Einzahlung" in w for w in result.warnings)
        assert any("Auszahlung" in w for w in result.warnings)

    async def test_only_deposits_no_transactions(self):
        result = await parse_pocket_csv(POCKET_CSV_ONLY_DEPOSITS, "pocket.csv")
        assert len(result.transactions) == 0

    async def test_empty_csv(self):
        result = await parse_pocket_csv(POCKET_CSV_EMPTY, "pocket.csv")
        assert len(result.transactions) == 0
        assert result.total_rows == 0

    async def test_bad_date_skipped(self):
        result = await parse_pocket_csv(POCKET_CSV_BAD_DATE, "pocket.csv")
        assert len(result.transactions) == 0
        assert any("Ungültiges Datum" in w for w in result.warnings)

    async def test_zero_shares_skipped(self):
        result = await parse_pocket_csv(POCKET_CSV_ZERO_SHARES, "pocket.csv")
        assert len(result.transactions) == 0
        assert any("BTC-Menge" in w for w in result.warnings)

    async def test_unknown_type_skipped(self):
        result = await parse_pocket_csv(POCKET_CSV_UNKNOWN_TYPE, "pocket.csv")
        assert len(result.transactions) == 0
        assert any("Unbekannter Typ" in w for w in result.warnings)

    async def test_no_enrichment_without_db(self):
        """Without db, enrich_transactions is skipped — new_positions stays empty."""
        result = await parse_pocket_csv(POCKET_CSV_BASIC, "pocket.csv")
        assert len(result.new_positions) == 0
        # Transactions are still parsed correctly
        assert len(result.transactions) == 2

    async def test_broker_meta(self):
        result = await parse_pocket_csv(POCKET_CSV_WITH_DEPOSIT_AND_WITHDRAWAL, "pocket.csv")
        meta = result.broker_meta
        assert meta["broker"] == "Pocket"
        assert meta["exchanges"] == 1
        assert meta["skipped_deposits"] == 1
        assert meta["skipped_withdrawals"] == 1
        assert meta["total_rows"] == 3

    async def test_import_batch_id_consistent(self):
        result = await parse_pocket_csv(POCKET_CSV_BASIC, "pocket.csv")
        batch_ids = {t.import_batch_id for t in result.transactions}
        assert len(batch_ids) == 1  # All transactions share the same batch ID
