"""Unit-Tests fuer den SPDR-Holdings-Adapter (rein, kein Netz/DB).

Fixture spiegelt die reale SSGA-.xlsx-Struktur (read_xlsx-Output als list[list[str]]):
Preamble (Fund Name / ISIN / Ticker / Holdings As Of), Leerzeile, Header-Zeile,
Daten, dann die "Unassigned"-Cash- und die "Marketing Communication."-Disclaimer-Zeile.
Deckt die kippenden Stellen ab: ISIN-Regex-Filter, Self-Ref-Skip, Null-Gewicht-Skip,
GICS->OpenFolio-Sektor, native Land-Uebernahme und as_of-Parsing.
"""
from datetime import date

from services.etf_adapters.base import EtfRef
from services.etf_adapters.spdr import (
    SPDR_ISIN_TO_GY,
    SpdrAdapter,
    parse_spdr_holdings,
    spdr_url,
)

# Reale Header-Reihenfolge der SSGA-EMEA-Holdings-Datei (11 Spalten).
_HEADER = [
    "ISIN", "SEDOL", "Security Name", "Currency", "Number of Shares",
    "Percent of Fund", "Trade Country Name", "Local Price",
    "Sector Classification", "Industry Classification", "Base Market Value",
]

# read_xlsx liefert Zeilen bereits als getrimmte Strings (Floats via repr()).
_ROWS: list[list[str]] = [
    ["Fund Name:", "State Street® SPDR® MSCI World UCITS ETF"] + [""] * 9,
    ["ISIN:", "IE00BFY0GT14"] + [""] * 9,
    ["Ticker Symbol:", "SPPW GY"] + [""] * 9,
    ["Holdings As Of:", "07-Jul-2026"] + [""] * 9,
    [""] * 11,
    _HEADER,
    # -- Equity-Holdings (valide ISIN, positives Gewicht) --
    ["US0378331005", "2046251", "Apple Inc.", "USD", "3460662", "5.114354",
     "United States", "310.66", "Information Technology",
     "Technology Hardware Storage & Peripherals", "1075089300"],
    ["TW0002330008", "6889106", "Taiwan Semiconductor Manufacturing", "TWD",
     "1000000", "2.5", "Taiwan", "1000.0", "Information Technology",
     "Semiconductors & Semiconductor Equipment", "500000000"],
    ["DK0062498333", "BQ1DHS0", "Novo Nordisk A/S Class B", "DKK", "800000",
     "1.25", "Denmark", "350.0", "Health Care", "Pharmaceuticals", "280000000"],
    # -- Fonds-Selbstreferenz (ISIN == eigene Fonds-ISIN) -> raus --
    ["IE00BFY0GT14", "Unassigned", "SPDR MSCI World UCITS ETF", "USD", "10",
     "0.30", "Ireland", "100.0", "Unassigned", "Unassigned", "1000"],
    # -- Null-Gewicht trotz valider ISIN -> make_holding_row skippt --
    ["NL0009805522", "B5BSZB3", "Nebius Group N.V. Class A", "USD", "46243",
     "0.0", "Netherlands", "0.0", "Information Technology", "Software", "0.0"],
    # -- Cash-Zeile ("Unassigned", Gewicht "-") -> ISIN-Regex verwirft --
    ["Unassigned", "Unassigned", "U.S. Dollar", "USD", "18471913", "-",
     "United States", "1.0", "Unassigned", "Unassigned", "18471914"],
    # -- Trenn- und Disclaimer-Zeile am Dateiende -> ISIN-Regex verwirft --
    [""] * 11,
    ["Marketing Communication. \nFor institutional use only. © 2026 State Street."]
    + [""] * 10,
]


class TestParseSpdrHoldings:
    def test_parses_equity_and_filters(self):
        rows = parse_spdr_holdings(_ROWS, "SWRD.L", etf_isin="IE00BFY0GT14")
        by = {r["holding_ticker"]: r for r in rows}
        # Nur die 3 Equity-Holdings; Self-Ref, Null-Gewicht, Cash + Disclaimer raus.
        assert set(by) == {"US0378331005", "TW0002330008", "DK0062498333"}

        apple = by["US0378331005"]
        assert apple["holding_ticker"] == "US0378331005"   # ISIN ist der Key
        assert apple["holding_isin"] == "US0378331005"
        assert apple["weight_pct"] == 5.114354
        assert apple["holding_country"] == "United States"
        assert apple["holding_name"] == "Apple Inc."
        assert apple["holding_sector"] == "Technology"      # GICS "Information Technology"
        assert apple["as_of"] == date(2026, 7, 7)

        assert by["TW0002330008"]["holding_country"] == "Taiwan"
        assert by["TW0002330008"]["holding_sector"] == "Technology"
        assert by["DK0062498333"]["holding_country"] == "Denmark"
        assert by["DK0062498333"]["holding_sector"] == "Healthcare"  # GICS "Health Care"

    def test_excludes_cash_selfref_and_zero_weight(self):
        rows = parse_spdr_holdings(_ROWS, "SWRD.L", etf_isin="IE00BFY0GT14")
        tickers = {r["holding_ticker"] for r in rows}
        assert "Unassigned" not in tickers          # Cash-Zeile (ungueltige ISIN)
        assert "IE00BFY0GT14" not in tickers         # Fonds-Selbstreferenz
        assert "NL0009805522" not in tickers         # Null-Gewicht

    def test_missing_header_returns_empty(self):
        assert parse_spdr_holdings([["garbage"], ["no", "header"]], "SWRD.L") == []


class TestSpdrAdapter:
    def _ref(self, isin: str, name: str) -> EtfRef:
        return EtfRef(ticker="SWRD.L", isin=isin, name=name)

    def test_matches_seeded_isin_with_brand(self):
        a = SpdrAdapter()
        assert a.matches(self._ref("IE00BFY0GT14", "SPDR MSCI World UCITS ETF")) is True
        # loose Marke: Broker-Kuerzung auf "State Street ..." matcht ebenfalls.
        assert a.matches(self._ref("IE00B6YX5C33", "State Street S&P 500 ETF")) is True

    def test_no_match_unseeded_isin(self):
        a = SpdrAdapter()
        # SPDR-Name, aber ISIN nicht in der Registry -> ehrlicher Skip.
        assert a.matches(self._ref("IE00B4L5Y983", "SPDR MSCI ACWI Some Fund")) is False
        # Gelistete ISIN, aber Fremd-Marke -> kein Match.
        assert a.matches(self._ref("IE00BFY0GT14", "iShares Core MSCI World")) is False

    def test_url_uses_lowercase_gy(self):
        assert SPDR_ISIN_TO_GY["IE00BFY0GT14"] == "sppw"
        assert spdr_url("SPPW").endswith("holdings-daily-emea-en-sppw-gy.xlsx")
