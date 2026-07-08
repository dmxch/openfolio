"""Unit-Tests fuer den HSBC-Holdings-Adapter (rein, kein Netz/DB).

Fixture spiegelt die realen read_xls-Zeilen (Sheet "Report") von
IE00B4X9L533 (HSBC MSCI World) wider: 5 Metadaten-Zeilen inkl. Excel-Datums-Serial,
benannte Header-Zeile, dann Holdings. Deckt die kippenden Stellen ab: Prozent-Weight,
Feed-eigene MSCI-Laenderklassifikation (Cayman KYG... -> "China"), Sektor immer None,
Serial->as_of, sowie das Ausfiltern von Cash (ohne ISIN), null/negativem Gewicht,
Self-Reference und Index-Future (gueltige ISIN!) — ohne die echte Equity "Posco
Future M" faelschlich zu droppen.
"""
from datetime import date

from services.etf_adapters.hsbc import (
    _excel_serial_to_date,
    _is_derivative,
    parse_hsbc_rows,
)

# Zellen kommen als getrimmte Strings aus read_xls (Floats via repr / int-Floats ohne .0);
# der Datums-Serial 46205 landet als String "46205".
_ROWS: list[list[str]] = [
    ["", "", "", "", "", "", "", ""],
    ["Name", "HSBC MSCI World UCITS ETF", "", "", "", "", "", ""],
    ["Date", "46205", "", "", "", "", "", ""],
    ["Fund Size", "15548839328", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["ISIN", "CUSIP", "SecurityName", "NumberOfShare", "MarketValue",
     "Country", "LocalCurrencyCode", "Weighting"],
    # Equity US
    ["US0378331005", "037833100", "Apple Inc", "3053708", "942465900",
     "United States", "USD", "5.05665"],
    # Cayman-domizilierte KYG...-ISIN, Feed klassifiziert Land bereits als "China"
    ["KYG875721634", "", "Tencent Holdings Ltd", "2817755", "154558961",
     "China", "HKD", "2.7769"],
    # Echte Equity mit "Future" im Namen -> MUSS erhalten bleiben (kein Benchmark-Marker)
    ["KR7003670007", "", "Posco Future M", "1000", "1000",
     "South Korea", "KRW", "0.02973"],
    # Index-Total-Return-Future MIT gueltiger ISIN + positivem Gewicht -> MUSS raus
    ["DE000C71QQS6", "", "MSCI World USD Net Total Return Future Sept 26", "1", "1",
     "Germany", "USD", "0.28025"],
    # Cash ohne ISIN, positives Gewicht -> raus (kein Key)
    ["", "", "Capital Cash Ctrl", "", "", "", "USD", "4.21827"],
    # Cash-Klasse mit negativem Gewicht -> raus
    ["", "", "Capital Cash Ctrl Class C", "", "", "", "USD", "-4.19171"],
    # Null-Gewicht-Receivable -> raus
    ["", "", "Usd Distribution Payable", "0", "0", "", "USD", "0"],
    # Self-Reference (eigene Fonds-ISIN) -> raus
    ["IE00B4X9L533", "", "HSBC MSCI World UCITS ETF", "1", "1",
     "Ireland", "USD", "0.01"],
]


class TestExcelSerialToDate:
    def test_serial_1900_system(self):
        assert _excel_serial_to_date("46205") == date(2026, 7, 2)
        assert _excel_serial_to_date("46205.0") == date(2026, 7, 2)

    def test_junk_and_out_of_range(self):
        assert _excel_serial_to_date("") is None
        assert _excel_serial_to_date("n/a") is None
        assert _excel_serial_to_date("0") is None       # ausserhalb Plausibilitaets-Fenster


class TestIsDerivative:
    def test_index_future_is_derivative(self):
        assert _is_derivative("MSCI World USD Net Total Return Future Sept 26") is True
        assert _is_derivative("MSCI Emerging Markets Index Future Sept 26") is True

    def test_real_equity_with_future_word_survives(self):
        # "Future" allein reicht nicht (kein Benchmark-Marker) -> keine Derivat-Klassifikation
        assert _is_derivative("Posco Future M") is False
        assert _is_derivative("Apple Inc") is False

    def test_expanded_index_families_are_derivative(self):
        # Erweiterte Benchmark-Marker: gaengige globale Index-Familien im Cash-Sleeve,
        # die frueher (nur MSCI/FTSE/S&P/Index/Total Return) durchgerutscht waeren.
        assert _is_derivative("Euro Stoxx 50 Future Sep26") is True
        assert _is_derivative("Nikkei 225 Future Mar26") is True
        assert _is_derivative("Kospi 200 Index Future") is True
        assert _is_derivative("Hang Seng Future Dec26") is True
        assert _is_derivative("Topix Future Jun26") is True

    def test_expanded_markers_still_require_deriv_word(self):
        # AND-Bedingung: ohne Deriv-Wort bleibt eine echte Aktie mit Index-artigem
        # Namen Equity (kein Fehl-Drop trotz erweiterter Marker).
        assert _is_derivative("Nasdaq Inc") is False           # echte Aktie (NDAQ)
        assert _is_derivative("Hang Seng Bank Ltd") is False   # echte Aktie (0011.HK)


class TestParseHsbcRows:
    def test_filters_and_maps(self):
        rows = parse_hsbc_rows(_ROWS, "HMWO.L", etf_isin="IE00B4X9L533")
        by = {r["holding_ticker"]: r for r in rows}
        # Nur echte Equities: Apple, Tencent, Posco Future M
        assert set(by) == {"US0378331005", "KYG875721634", "KR7003670007"}

        apple = by["US0378331005"]
        assert apple["weight_pct"] == 5.05665
        assert apple["holding_country"] == "United States"
        assert apple["holding_name"] == "Apple Inc"
        assert apple["holding_isin"] == "US0378331005"     # ISIN dient zugleich als Key
        assert apple["holding_sector"] is None             # HSBC-Feed ohne Sektor-Spalte
        assert apple["as_of"] == date(2026, 7, 2)          # Serial 46205 konvertiert

        # Feed-eigene MSCI-Laenderklassifikation bleibt erhalten (Cayman-ISIN -> China)
        assert by["KYG875721634"]["holding_country"] == "China"
        assert by["KYG875721634"]["holding_isin"] == "KYG875721634"

    def test_excludes_cash_derivative_and_self_ref(self):
        rows = parse_hsbc_rows(_ROWS, "HMWO.L", etf_isin="IE00B4X9L533")
        keys = {r["holding_ticker"] for r in rows}
        assert "DE000C71QQS6" not in keys        # Index-Total-Return-Future (gueltige ISIN)
        assert "IE00B4X9L533" not in keys         # Self-Reference
        # Cash/null/negativ tragen keine ISIN bzw. Gewicht<=0 -> kein Key
        names = {r["holding_name"] for r in rows}
        assert "Capital Cash Ctrl" not in names
        assert "Usd Distribution Payable" not in names

    def test_missing_header_returns_empty(self):
        assert parse_hsbc_rows([["garbage"], ["no", "header"]], "HMWO.L") == []
