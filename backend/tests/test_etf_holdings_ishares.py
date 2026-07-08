"""Unit-Tests fuer den iShares-Holdings-Adapter (rein, kein Netz/DB).

Deckt die zwei kippenden Stellen ab: Exchange->yf-Ticker-Normalisierung und das
CSV-Parsing (Equity-Filter, Self-Ref-Skip, Land, as_of).
"""
from datetime import date

from constants.exchange_suffix import exchange_to_suffix, exchange_to_yf_ticker
from services.etf_holdings_ishares import map_gics_sector, parse_ishares_csv


class TestExchangeSuffix:
    def test_major_exchanges(self):
        assert exchange_to_yf_ticker("2330", "Taiwan Stock Exchange") == "2330.TW"
        assert exchange_to_yf_ticker("005930", "Korea Exchange (Stock Market)") == "005930.KS"
        assert exchange_to_yf_ticker("RELIANCE", "National Stock Exchange Of India") == "RELIANCE.NS"

    def test_kosdaq_before_korea(self):
        # KOSDAQ MUSS .KQ ergeben, nicht .KS (Reihenfolge spezifisch vor generisch).
        assert exchange_to_yf_ticker("035720", "Korea Exchange (Kosdaq)") == "035720.KQ"

    def test_hong_kong_zero_pad(self):
        # HK: numerischer Code links auf 4 Stellen mit Nullen (yfinance-Konvention).
        assert exchange_to_yf_ticker("700", "Hong Kong Exchanges And Clearing Ltd") == "0700.HK"
        assert exchange_to_yf_ticker("9988", "Hong Kong Exchanges And Clearing Ltd") == "9988.HK"

    def test_mic_and_alias(self):
        assert exchange_to_yf_ticker("PETR4", "XBSP") == "PETR4.SA"        # B3 Brasilien (MIC)
        assert exchange_to_yf_ticker("3105", "Gretai Securities Market") == "3105.TWO"  # Taipei OTC

    def test_us_no_suffix(self):
        assert exchange_to_yf_ticker("AAPL", "NASDAQ") == "AAPL"
        assert exchange_to_yf_ticker("BRK", "New York Stock Exchange Inc.") == "BRK"

    def test_unknown_exchange_is_none(self):
        assert exchange_to_suffix("Some Unlisted Venue") is None
        assert exchange_to_yf_ticker("XYZ", "Some Unlisted Venue") is None
        assert exchange_to_yf_ticker("", "Taiwan Stock Exchange") is None


_CSV = "\n".join([
    '"iShares Core MSCI EM IMI UCITS ETF"',
    '"Fund Holdings as of","May 31, 2026"',
    '""',
    '"Ticker","Name","Sector","Asset Class","Market Value","Weight (%)","Notional Value","Shares","Price","Location","Exchange","Market Currency"',
    '"2330","TAIWAN SEMICONDUCTOR","Information Technology","Equity","1,000,000","6.32","x","x","x","Taiwan","Taiwan Stock Exchange","TWD"',
    '"700","TENCENT HOLDINGS","Communication","Equity","x","3.50","x","x","x","China","Hong Kong Exchanges And Clearing Ltd","HKD"',
    '"035720","SOME KOSDAQ CO","Information Technology","Equity","x","0.50","x","x","x","Korea (South)","Korea Exchange (Kosdaq)","KRW"',
    '"USD","USD CASH","Cash","Cash and/or Derivatives","x","0.59","x","x","x","-","-","USD"',
    '"EIMI","SELF REF","-","Equity","x","0.10","x","x","x","-","-","-"',
])


class TestParseIsharesCsv:
    def test_parses_equity_and_resolves_tickers(self):
        rows = parse_ishares_csv(_CSV, "EIMI.L")
        by = {r["holding_ticker"]: r for r in rows}
        # Nur Equity, Cash + Self-Ref (EIMI) raus -> 3 Holdings
        assert set(by) == {"2330.TW", "0700.HK", "035720.KQ"}

        tsmc = by["2330.TW"]
        assert tsmc["weight_pct"] == 6.32
        assert tsmc["holding_country"] == "Taiwan"
        assert tsmc["holding_name"] == "TAIWAN SEMICONDUCTOR"
        assert tsmc["holding_isin"] is None              # iShares-CSV ohne ISIN
        assert tsmc["holding_sector"] == "Technology"    # GICS "Information Technology"
        assert tsmc["as_of"] == date(2026, 5, 31)
        assert by["0700.HK"]["holding_country"] == "China"
        assert by["0700.HK"]["holding_sector"] == "Communication Services"  # GICS "Communication"


class TestGicsSector:
    def test_maps_gics_to_openfolio(self):
        assert map_gics_sector("Information Technology") == "Technology"
        assert map_gics_sector("Health Care") == "Healthcare"
        assert map_gics_sector("Consumer Discretionary") == "Consumer Cyclical"
        assert map_gics_sector("Consumer Staples") == "Consumer Defensive"
        assert map_gics_sector("Materials") == "Basic Materials"
        assert map_gics_sector("Communication") == "Communication Services"

    def test_unknown_and_empty(self):
        assert map_gics_sector("Cash and/or Derivatives") is None
        assert map_gics_sector("") is None
        assert map_gics_sector(None) is None

    def test_cash_and_self_reference_excluded(self):
        rows = parse_ishares_csv(_CSV, "EIMI.L")
        tickers = {r["holding_ticker"] for r in rows}
        assert "USD" not in tickers          # Cash-Zeile (Asset Class != Equity)
        assert "EIMI.L" not in tickers and "EIMI" not in tickers  # Self-Ref

    def test_missing_header_returns_empty(self):
        assert parse_ishares_csv("garbage\nno,header,here", "EIMI.L") == []

    def test_non_finite_and_negative_weight_skipped(self):
        # iShares ist die meistgenutzte Quelle (SWDA/EIMI/CHSPI). Ein nicht-endliches
        # (NaN/Inf) oder <=0-Gewicht darf NICHT persistiert werden — es korrumpierte
        # sonst die Laender-/Sektor-Durchsicht (/country-lookthrough 500).
        csv = "\n".join([
            '"iShares Test"',
            '"Fund Holdings as of","May 31, 2026"',
            '""',
            '"Ticker","Name","Sector","Asset Class","Market Value","Weight (%)",'
            '"Notional Value","Shares","Price","Location","Exchange","Market Currency"',
            '"2330","GOOD CO","Information Technology","Equity","x","6.32","x","x","x",'
            '"Taiwan","Taiwan Stock Exchange","TWD"',
            '"700","NAN CO","Communication","Equity","x","NaN","x","x","x",'
            '"China","Hong Kong Exchanges And Clearing Ltd","HKD"',
            '"035720","NEG CO","Information Technology","Equity","x","-1.5","x","x","x",'
            '"Korea (South)","Korea Exchange (Kosdaq)","KRW"',
        ])
        rows = parse_ishares_csv(csv, "EIMI.L")
        keys = {r["holding_ticker"] for r in rows}
        assert keys == {"2330.TW"}                 # nur die valide Zeile ueberlebt
        assert rows[0]["weight_pct"] == 6.32
