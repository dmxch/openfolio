"""Tests for the Interactive Brokers CSV parser."""

import pytest

from services.ibkr_parser import (
    detect_ibkr,
    _parse_date,
    _map_ticker,
    _is_forex_symbol,
    _aggregate_partials,
    parse_ibkr_csv,
)

# --- Test CSV fixtures ---

IBKR_HEADER = "Symbol,ISIN,CurrencyPrimary,AssetClass,TradeDate,Buy/Sell,Quantity,TradePrice,IBCommission,IBCommissionCurrency,TradeMoney,ListingExchange,FXRateToBase,Taxes,Description,Notes/Codes,TransactionType"

IBKR_CSV_BASIC = f"""{IBKR_HEADER}
AAPL,US0378331005,USD,STK,20240315,BUY,10,172.50,-1.00,USD,-1725.00,NASDAQ,0.88234,0,APPLE INC,,ExchTrade
AAPL,US0378331005,USD,STK,20240410,SELL,10,178.30,-1.00,USD,1783.00,NASDAQ,0.90120,0,APPLE INC,,ExchTrade
"""

IBKR_CSV_PARTIAL = f"""{IBKR_HEADER}
AAPL,US0378331005,USD,STK,20240315,BUY,10,172.50,-1.00,USD,-1725.00,NASDAQ,0.88234,0,APPLE INC,P,ExchTrade
AAPL,US0378331005,USD,STK,20240315,BUY,5,172.48,-0.50,USD,-862.40,NASDAQ,0.88234,0,APPLE INC,P,ExchTrade
AAPL,US0378331005,USD,STK,20240315,BUY,3,172.52,-0.30,USD,-517.56,NASDAQ,0.88234,0,APPLE INC,P,ExchTrade
"""

IBKR_CSV_MULTI_EXCHANGE = f"""{IBKR_HEADER}
AAPL,US0378331005,USD,STK,20240315,BUY,10,172.50,-1.00,USD,-1725.00,NASDAQ,0.88234,0,APPLE INC,,ExchTrade
NOVN,CH0012005267,CHF,STK,20240320,BUY,20,95.50,-5.00,CHF,-1910.00,SWX,1.0,1.43,NOVARTIS AG-REG,,ExchTrade
SAP,DE0007164600,EUR,STK,20240321,BUY,15,180.00,-3.00,EUR,-2700.00,IBIS,0.94500,0,SAP SE,,ExchTrade
SHEL,GB00BP6MXD84,GBP,STK,20240322,BUY,50,27.50,-2.00,GBP,-1375.00,LSE,1.12300,0,SHELL PLC,,ExchTrade
"""

IBKR_CSV_WITH_FOREX = f"""{IBKR_HEADER}
AAPL,US0378331005,USD,STK,20240315,BUY,10,172.50,-1.00,USD,-1725.00,NASDAQ,0.88234,0,APPLE INC,,ExchTrade
EUR.USD,,USD,CASH,20240318,BUY,1000,1.0865,0,USD,-1086.50,IDEALPRO,0.88234,0,EUR.USD,,ExchTrade
"""

IBKR_CSV_WITH_OPTIONS = f"""{IBKR_HEADER}
AAPL,US0378331005,USD,STK,20240315,BUY,10,172.50,-1.00,USD,-1725.00,NASDAQ,0.88234,0,APPLE INC,,ExchTrade
AAPL 240419C00180000,US0378331005,USD,OPT,20240316,BUY,1,3.50,-1.50,USD,-350.00,CBOE,0.88234,0,AAPL APR24 180 CALL,,ExchTrade
ES,,,FUT,20240317,BUY,1,5200.00,-2.10,USD,-5200.00,CME,0.88234,0,E-MINI S&P 500,,ExchTrade
"""

IBKR_CSV_DATE_DASH = f"""{IBKR_HEADER}
AAPL,US0378331005,USD,STK,2024-03-15,BUY,10,172.50,-1.00,USD,-1725.00,NASDAQ,0.88234,0,APPLE INC,,ExchTrade
"""

IBKR_CSV_NEGATIVE_COMMISSION = f"""{IBKR_HEADER}
AAPL,US0378331005,USD,STK,20240315,BUY,10,172.50,-1.50,USD,-1725.00,NASDAQ,0.88234,0.75,APPLE INC,,ExchTrade
"""

IBKR_CSV_EMPTY = IBKR_HEADER + "\n"

IBKR_CSV_ETF = f"""{IBKR_HEADER}
VOO,US9229087690,USD,ETF,20240322,BUY,3,498.20,-0.75,USD,-1494.60,ARCA,0.88100,0,VANGUARD S&P500 ETF,,ExchTrade
"""

SWISSQUOTE_HEADER = "Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;Aufgelaufene Zinsen;Nettobetrag;Währung Nettobetrag"


# --- detect_ibkr tests ---


class TestDetectIBKR:
    def test_detect_positive(self):
        headers = IBKR_HEADER.split(",")
        assert detect_ibkr(headers) is True

    def test_detect_minimal_headers(self):
        # Only core columns + commission
        headers = ["Symbol", "AssetClass", "Buy/Sell", "IBCommission"]
        assert detect_ibkr(headers) is True

    def test_detect_negative_empty(self):
        assert detect_ibkr([]) is False

    def test_detect_negative_swissquote(self):
        headers = SWISSQUOTE_HEADER.split(";")
        assert detect_ibkr(headers) is False

    def test_detect_negative_generic(self):
        headers = ["Date", "Type", "Ticker", "Shares", "Price"]
        assert detect_ibkr(headers) is False

    def test_detect_only_one_criterion(self):
        # Only TradePrice + TradeMoney — only 1 of 3 criteria
        headers = ["TradePrice", "TradeMoney", "Date", "Amount"]
        assert detect_ibkr(headers) is False


# --- _parse_date tests ---


class TestParseDate:
    def test_yyyymmdd(self):
        d = _parse_date("20240315")
        assert d is not None
        assert d.year == 2024
        assert d.month == 3
        assert d.day == 15

    def test_yyyy_mm_dd(self):
        d = _parse_date("2024-03-15")
        assert d is not None
        assert d.year == 2024
        assert d.month == 3
        assert d.day == 15

    def test_invalid(self):
        assert _parse_date("15.03.2024") is None
        assert _parse_date("") is None
        assert _parse_date("invalid") is None


# --- _map_ticker tests ---


class TestMapTicker:
    def test_us_no_suffix(self):
        assert _map_ticker("AAPL", "US0378331005", "NASDAQ") == "AAPL"
        assert _map_ticker("MSFT", "US5949181045", "NYSE") == "MSFT"

    def test_swiss_exchange(self):
        assert _map_ticker("NOVN", "CH0012005267", "SWX") == "NOVN.SW"
        assert _map_ticker("NOVN", "CH0012005267", "EBS") == "NOVN.SW"

    def test_german_exchange(self):
        assert _map_ticker("SAP", "DE0007164600", "IBIS") == "SAP.DE"
        assert _map_ticker("SAP", "DE0007164600", "FWB") == "SAP.F"

    def test_uk_exchange(self):
        assert _map_ticker("SHEL", "GB00BP6MXD84", "LSE") == "SHEL.L"

    def test_isin_fallback(self):
        # No exchange, fall back to ISIN
        assert _map_ticker("NOVN", "CH0012005267", "") == "NOVN.SW"
        assert _map_ticker("SAP", "DE0007164600", "") == "SAP.DE"

    def test_no_mapping_assumes_us(self):
        assert _map_ticker("AAPL", "", "") == "AAPL"

    def test_empty_symbol(self):
        assert _map_ticker("", "US123", "NYSE") == ""

    def test_already_has_suffix(self):
        assert _map_ticker("NOVN.SW", "CH0012005267", "SWX") == "NOVN.SW"


# --- _is_forex_symbol tests ---


class TestIsForexSymbol:
    def test_forex_pair(self):
        assert _is_forex_symbol("EUR.USD") is True
        assert _is_forex_symbol("GBP.CHF") is True

    def test_stock_ticker(self):
        assert _is_forex_symbol("AAPL") is False
        assert _is_forex_symbol("NOVN.SW") is False

    def test_empty(self):
        assert _is_forex_symbol("") is False
        assert _is_forex_symbol(None) is False


# --- _aggregate_partials tests ---


class TestAggregatePartials:
    def test_no_aggregation_single(self):
        rows = [{"_date_str": "20240315", "_symbol": "AAPL", "_direction": "BUY",
                 "_quantity": 10, "_price": 172.50, "_fees": 1.0, "_taxes": 0,
                 "_is_aggregated": False, "_aggregated_count": 1}]
        result = _aggregate_partials(rows)
        assert len(result) == 1
        assert result[0]["_quantity"] == 10

    def test_aggregate_three_partials(self):
        rows = [
            {"_date_str": "20240315", "_symbol": "AAPL", "_direction": "BUY",
             "_quantity": 10, "_price": 172.50, "_fees": 1.0, "_taxes": 0,
             "_is_aggregated": False, "_aggregated_count": 1},
            {"_date_str": "20240315", "_symbol": "AAPL", "_direction": "BUY",
             "_quantity": 5, "_price": 172.48, "_fees": 0.5, "_taxes": 0,
             "_is_aggregated": False, "_aggregated_count": 1},
            {"_date_str": "20240315", "_symbol": "AAPL", "_direction": "BUY",
             "_quantity": 3, "_price": 172.52, "_fees": 0.3, "_taxes": 0,
             "_is_aggregated": False, "_aggregated_count": 1},
        ]
        result = _aggregate_partials(rows)
        assert len(result) == 1
        assert result[0]["_quantity"] == 18
        # Weighted average: (10*172.50 + 5*172.48 + 3*172.52) / 18
        expected_price = (10 * 172.50 + 5 * 172.48 + 3 * 172.52) / 18
        assert abs(result[0]["_price"] - expected_price) < 0.01
        assert result[0]["_fees"] == 1.8
        assert result[0]["_is_aggregated"] is True
        assert result[0]["_aggregated_count"] == 3

    def test_different_directions_not_aggregated(self):
        rows = [
            {"_date_str": "20240315", "_symbol": "AAPL", "_direction": "BUY",
             "_quantity": 10, "_price": 172.50, "_fees": 1.0, "_taxes": 0,
             "_is_aggregated": False, "_aggregated_count": 1},
            {"_date_str": "20240315", "_symbol": "AAPL", "_direction": "SELL",
             "_quantity": 5, "_price": 173.00, "_fees": 0.5, "_taxes": 0,
             "_is_aggregated": False, "_aggregated_count": 1},
        ]
        result = _aggregate_partials(rows)
        assert len(result) == 2

    def test_different_dates_not_aggregated(self):
        rows = [
            {"_date_str": "20240315", "_symbol": "AAPL", "_direction": "BUY",
             "_quantity": 10, "_price": 172.50, "_fees": 1.0, "_taxes": 0,
             "_is_aggregated": False, "_aggregated_count": 1},
            {"_date_str": "20240316", "_symbol": "AAPL", "_direction": "BUY",
             "_quantity": 5, "_price": 173.00, "_fees": 0.5, "_taxes": 0,
             "_is_aggregated": False, "_aggregated_count": 1},
        ]
        result = _aggregate_partials(rows)
        assert len(result) == 2


# --- parse_ibkr_csv integration tests ---


@pytest.mark.asyncio
class TestParseIBKR:
    async def test_basic_buy_sell(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_BASIC, "test.csv", db)
        assert result.source_type == "ibkr_csv"
        assert result.total_rows == 2
        assert result.transactions[0].type == "buy"
        assert result.transactions[0].ticker == "AAPL"
        assert result.transactions[0].shares == 10
        assert result.transactions[0].price_per_share == 172.50
        assert result.transactions[1].type == "sell"
        assert result.transactions[1].shares == 10
        assert result.broker_meta["broker"] == "interactive_brokers"

    async def test_symbol_mapping_multi_exchange(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_MULTI_EXCHANGE, "test.csv", db)
        tickers = {t.ticker for t in result.transactions}
        assert "AAPL" in tickers
        assert "NOVN.SW" in tickers
        assert "SAP.DE" in tickers
        assert "SHEL.L" in tickers

    async def test_partial_aggregation(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_PARTIAL, "test.csv", db)
        assert result.total_rows == 1
        txn = result.transactions[0]
        assert txn.shares == 18
        assert txn.is_aggregated is True
        assert txn.aggregated_count == 3
        assert result.broker_meta["aggregated_count"] == 1

    async def test_skip_forex(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_WITH_FOREX, "test.csv", db)
        assert result.total_rows == 1
        assert result.transactions[0].ticker == "AAPL"
        assert result.broker_meta["skipped"]["forex"] == 1

    async def test_skip_options_futures(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_WITH_OPTIONS, "test.csv", db)
        assert result.total_rows == 1
        assert result.transactions[0].ticker == "AAPL"
        assert result.broker_meta["skipped"]["options"] == 1
        assert result.broker_meta["skipped"]["futures"] == 1

    async def test_commission_and_taxes(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_NEGATIVE_COMMISSION, "test.csv", db)
        txn = result.transactions[0]
        # fees = abs(-1.50) + abs(0.75) = 2.25 in USD
        # fees_chf = 2.25 * 0.88234
        expected_fees = round(2.25 * 0.88234, 2)
        assert abs(txn.fees_chf - expected_fees) < 0.01
        assert txn.taxes_chf > 0

    async def test_date_format_dash(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_DATE_DASH, "test.csv", db)
        assert result.total_rows == 1
        assert result.transactions[0].date == "2024-03-15"

    async def test_empty_csv(self, db):
        with pytest.raises(ValueError, match="keine importierbaren"):
            await parse_ibkr_csv(IBKR_CSV_EMPTY, "test.csv", db)

    async def test_etf_import(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_ETF, "test.csv", db)
        assert result.total_rows == 1
        assert result.transactions[0].ticker == "VOO"

    async def test_date_range_in_meta(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_BASIC, "test.csv", db)
        assert result.broker_meta["date_range"] == "15.03.2024 – 10.04.2024"

    async def test_import_source(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_BASIC, "test.csv", db)
        for txn in result.transactions:
            assert txn.import_source == "ibkr_csv"
            assert txn.import_batch_id is not None

    async def test_warnings_for_skipped(self, db):
        result = await parse_ibkr_csv(IBKR_CSV_WITH_OPTIONS, "test.csv", db)
        assert any("übersprungen" in w for w in result.warnings)
