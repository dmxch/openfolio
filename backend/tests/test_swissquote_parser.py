"""Tests for swissquote_parser: detection, type mapping, date parsing, ticker mapping, partials."""

import pytest

from services.swissquote_parser import (
    is_swissquote_csv,
    _map_type,
    _parse_date,
    _parse_num,
    _is_bond,
    _isin_to_suffix,
    _map_ticker,
    _aggregate_partials,
)
from datetime import datetime


# --- CSV detection ---

class TestDetection:
    def test_valid_headers(self):
        headers = ["Datum", "Auftrag #", "Transaktionen", "Symbol", "Stückpreis", "ISIN"]
        assert is_swissquote_csv(headers) is True

    def test_latin1_header(self):
        headers = ["Datum", "Transaktionen", "St\xfcckpreis"]
        assert is_swissquote_csv(headers) is True

    def test_ibkr_headers_rejected(self):
        headers = ["Symbol", "ISIN", "AssetClass", "TradeDate", "Buy/Sell"]
        assert is_swissquote_csv(headers) is False

    def test_empty_list(self):
        assert is_swissquote_csv([]) is False


# --- Type mapping ---

class TestMapType:
    def test_buy(self):
        assert _map_type("Kauf") == "buy"
        assert _map_type("Kauf Aktien") == "buy"

    def test_sell(self):
        assert _map_type("Verkauf") == "sell"

    def test_dividend(self):
        assert _map_type("Dividende") == "dividend"

    def test_fee(self):
        assert _map_type("Depotgebühr") == "fee"
        assert _map_type("Spesen") == "fee"

    def test_deposit(self):
        assert _map_type("Zahlung") == "deposit"

    def test_unknown(self):
        assert _map_type("Something else") == "unknown"

    def test_case_insensitive(self):
        assert _map_type("KAUF") == "buy"
        assert _map_type("verkauf") == "sell"


# --- Date parsing ---

class TestParseDate:
    def test_dash_format(self):
        result = _parse_date("15-03-2024 10:30:00")
        assert result == datetime(2024, 3, 15, 10, 30, 0)

    def test_dot_format(self):
        result = _parse_date("15.03.2024 10:30:00")
        assert result == datetime(2024, 3, 15, 10, 30, 0)

    def test_date_only(self):
        result = _parse_date("15-03-2024")
        assert result == datetime(2024, 3, 15)

    def test_invalid(self):
        assert _parse_date("not-a-date") is None

    def test_whitespace_stripped(self):
        result = _parse_date("  15-03-2024  ")
        assert result == datetime(2024, 3, 15)


# --- Numeric parsing ---

class TestParseNum:
    def test_simple(self):
        assert _parse_num("123.45") == 123.45

    def test_swiss_apostrophe(self):
        assert _parse_num("1'234.56") == 1234.56

    def test_unicode_apostrophe(self):
        assert _parse_num("1\u2019234.56") == 1234.56

    def test_empty(self):
        assert _parse_num("") == 0.0

    def test_invalid(self):
        assert _parse_num("abc") == 0.0


# --- ISIN to suffix ---

class TestIsinToSuffix:
    def test_swiss(self):
        assert _isin_to_suffix("CH0012005267") == ".SW"

    def test_us(self):
        assert _isin_to_suffix("US0378331005") == ""

    def test_irish(self):
        assert _isin_to_suffix("IE00B4L5Y983") == ".L"

    def test_canadian(self):
        assert _isin_to_suffix("CA1234567890") == ".TO"

    def test_unknown_prefix(self):
        assert _isin_to_suffix("JP1234567890") == ""

    def test_empty(self):
        assert _isin_to_suffix("") == ""

    def test_short(self):
        assert _isin_to_suffix("C") == ""


# --- Ticker mapping ---

class TestMapTicker:
    def test_swiss_stock(self):
        assert _map_ticker("NOVN", "CH0012005267") == "NOVN.SW"

    def test_us_stock(self):
        assert _map_ticker("AAPL", "US0378331005") == "AAPL"

    def test_canadian_cad(self):
        assert _map_ticker("RY", "CA7677441056", "CAD") == "RY.TO"

    def test_canadian_usd(self):
        """Canadian ISIN traded in USD → NYSE, no suffix."""
        assert _map_ticker("RY", "CA7677441056", "USD") == "RY"

    def test_already_has_suffix(self):
        assert _map_ticker("NOVN.SW", "CH0012005267") == "NOVN.SW"

    def test_empty_symbol(self):
        assert _map_ticker("", "CH0012005267") == ""


# --- Bond detection ---

class TestIsBond:
    def test_bond_detected(self):
        row = {"Stückpreis": "98.5%"}
        assert _is_bond(row) is True

    def test_stock_not_bond(self):
        row = {"Stückpreis": "172.50"}
        assert _is_bond(row) is False


# --- Partial execution aggregation ---

class TestAggregatePartials:
    def test_single_row_passthrough(self):
        rows = [{"_order_id": "123", "_symbol": "AAPL", "_quantity": 10, "_unit_price": 170.0, "_fees": 1.0, "_accrued_interest": 0, "_net_amount": 1701, "_net_amount_account": 1701, "_date": datetime(2024, 3, 15)}]
        result = _aggregate_partials(rows)
        assert len(result) == 1

    def test_aggregation(self):
        rows = [
            {"_order_id": "ABC", "_symbol": "AAPL", "_quantity": 10, "_unit_price": 170.0, "_fees": 1.0, "_accrued_interest": 0, "_net_amount": 1700, "_net_amount_account": 1700, "_date": datetime(2024, 3, 15)},
            {"_order_id": "ABC", "_symbol": "AAPL", "_quantity": 5, "_unit_price": 172.0, "_fees": 0.5, "_accrued_interest": 0, "_net_amount": 860, "_net_amount_account": 860, "_date": datetime(2024, 3, 15)},
        ]
        result = _aggregate_partials(rows)
        assert len(result) == 1
        agg = result[0]
        assert agg["_quantity"] == 15
        # Weighted average: (10*170 + 5*172) / 15 = 2560/15 ≈ 170.667
        assert abs(agg["_unit_price"] - 170.667) < 0.01
        assert agg["_fees"] == 1.5

    def test_system_orders_not_aggregated(self):
        """order_id '00000000' should not be aggregated."""
        rows = [
            {"_order_id": "00000000", "_symbol": "AAPL", "_quantity": 10, "_unit_price": 170.0, "_fees": 0, "_accrued_interest": 0, "_net_amount": 1700, "_net_amount_account": 1700, "_date": datetime(2024, 3, 15)},
            {"_order_id": "00000000", "_symbol": "AAPL", "_quantity": 5, "_unit_price": 172.0, "_fees": 0, "_accrued_interest": 0, "_net_amount": 860, "_net_amount_account": 860, "_date": datetime(2024, 3, 15)},
        ]
        result = _aggregate_partials(rows)
        assert len(result) == 2
