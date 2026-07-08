"""Unit-Tests fuer den Fidelity-Holdings-Adapter (rein, kein Netz/DB).

Die Fixture spiegelt das reale fidelity.lu-Sheet (verifiziert an IE00BYXVGZ48 /
Fidelity Global Quality Income, Stand 2026-07-07): Zeile 1 Fondsname, Zeile 2
'Date:' | ISO-Datum, Zeile 3 Header ['ISIN','Name','Weight (%)'], danach die
Holdings. Deckt die kippenden Stellen ab: Header-Lokalisierung, Derivat-Skip
(leere ISIN), Self-Reference-Skip (Holding-ISIN == Fonds-ISIN), Null-Gewicht,
Datum-Parsing und die None-Land/Sektor-Invariante (schwaechster Anbieter).
"""
from datetime import date

from services.etf_adapters.base import EtfRef, is_valid_isin
from services.etf_adapters.fidelity import (
    FidelityAdapter,
    _parse_weight,
    parse_fidelity_holdings,
)

_FUND_ISIN = "IE00BYXVGZ48"

# list[list[str]] wie von _excel.read_xlsx zurueckgegeben (Zellen bereits Strings).
_ROWS = [
    ["Fidelity Global Quality Income UCITS ETF INC-USD", "", ""],
    ["Date:", "2026-07-07", ""],
    ["ISIN", "Name", "Weight (%)"],
    ["US67066G1040", "NVIDIA", "5.192810127342247"],
    ["US0378331005", "APPLE", "3.5"],
    ["", "SP500 MIC EMIN FUTSEP26 HWAU6", "0.34256"],   # Derivat: leere ISIN
    [_FUND_ISIN, "FIDELITY SELF REF", "0.10"],          # Self-Reference (== Fonds-ISIN)
    ["GB0003718474", "GAMES WORKSHOP GROUP", "0"],      # Null-Gewicht
    ["GB00B03MLX29", "SHELL", "2.0"],
]


class TestParseFidelityHoldings:
    def test_parses_equity_and_uses_isin_as_key(self):
        rows = parse_fidelity_holdings(_ROWS, "FGQI.L", _FUND_ISIN)
        by = {r["holding_ticker"]: r for r in rows}
        # Nur echte Holdings: Derivat (leere ISIN), Self-Ref, Null-Gewicht raus -> 3.
        assert set(by) == {"US67066G1040", "US0378331005", "GB00B03MLX29"}

        nvda = by["US67066G1040"]
        assert nvda["etf_ticker"] == "FGQI.L"
        assert nvda["holding_ticker"] == "US67066G1040"   # ISIN als Fallback-Key
        assert nvda["holding_isin"] == "US67066G1040"
        assert is_valid_isin(nvda["holding_isin"])
        assert nvda["holding_name"] == "NVIDIA"
        assert nvda["weight_pct"] == 5.192810127342247
        assert nvda["as_of"] == date(2026, 7, 7)
        # Schwaechster Anbieter: kein natives Land / kein nativer Sektor.
        assert nvda["holding_country"] is None
        assert nvda["holding_sector"] is None

    def test_derivative_self_ref_and_zero_weight_excluded(self):
        rows = parse_fidelity_holdings(_ROWS, "FGQI.L", _FUND_ISIN)
        isins = {r["holding_isin"] for r in rows}
        names = {r["holding_name"] for r in rows}
        assert _FUND_ISIN not in isins                       # Self-Reference raus
        assert "GB0003718474" not in isins                   # Null-Gewicht raus
        assert not any("FUTURE" in (n or "").upper() or "FUT" in (n or "").upper()
                       for n in names)                        # Derivat (leere ISIN) raus

    def test_self_ref_kept_when_fund_isin_unknown(self):
        # Ohne Fonds-ISIN gibt es keine Self-Ref-Erkennung: die Zeile ueberlebt.
        rows = parse_fidelity_holdings(_ROWS, "FGQI.L", None)
        assert _FUND_ISIN in {r["holding_isin"] for r in rows}

    def test_datetime_stringified_date_cell(self):
        # read_xlsx kann eine echte Datetime-Zelle als '...' + ' 00:00:00' liefern.
        rows = [
            ["Fund X", "", ""],
            ["Date:", "2026-07-07 00:00:00", ""],
            ["ISIN", "Name", "Weight (%)"],
            ["US0378331005", "APPLE", "1.0"],
        ]
        parsed = parse_fidelity_holdings(rows, "X.L", None)
        assert parsed and parsed[0]["as_of"] == date(2026, 7, 7)

    def test_missing_date_row_yields_none_as_of(self):
        rows = [
            ["Fund X", "", ""],
            ["ISIN", "Name", "Weight (%)"],
            ["US0378331005", "APPLE", "1.0"],
        ]
        parsed = parse_fidelity_holdings(rows, "X.L", None)
        assert parsed and parsed[0]["as_of"] is None

    def test_missing_header_returns_empty(self):
        assert parse_fidelity_holdings([["garbage"], ["no", "header"]], "X.L", None) == []
        assert parse_fidelity_holdings([], "X.L", None) == []


class TestParseWeight:
    def test_plain_and_percent_and_thousands(self):
        assert _parse_weight("5.19") == 5.19
        assert _parse_weight("5.19%") == 5.19       # evtl. '%'-Suffix
        assert _parse_weight("1’234.5") == 1234.5   # CH-Apostroph-Tausender
        assert _parse_weight("") is None
        assert _parse_weight("n/a") is None


class TestFidelityMatches:
    def _ref(self, name: str, isin: str | None) -> EtfRef:
        return EtfRef(ticker="X.L", isin=isin, name=name)

    def test_matches_brand_and_isin(self):
        a = FidelityAdapter()
        assert a.matches(self._ref("Fidelity Global Quality Income UCITS ETF", _FUND_ISIN))
        # Broker-verkuerzter Name faengt weiter (Marke reicht).
        assert a.matches(self._ref("FIDELITY MSCI WORLD", _FUND_ISIN))

    def test_no_match_without_isin_or_brand(self):
        a = FidelityAdapter()
        assert not a.matches(self._ref("Fidelity Global Quality Income", None))  # keine ISIN
        assert not a.matches(self._ref("iShares Core MSCI World", _FUND_ISIN))   # andere Marke
