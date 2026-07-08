"""Unit-Tests fuer den Xtrackers-(DWS-)Holdings-Adapter (rein, kein Netz/DB).

Das Fixture spiegelt die REALE Payload-Struktur von etf.dws.com/.../holdings
(verifiziert an IE00BJ0KDQ92 / IE00BTJRMP35, Stand 06.07.2026):
  - tables[0].columns = [{key, value}, ...], value = Header-NAME
  - tables[0].values  = Liste von Dicts, keyed nach Spalten-key
  - jede Zelle = Dict {value, sortValue, type}  (PITFALL: kein Skalar)
  - Stichtag im Disclaimer "Source: DWS 06.07.2026" (DD.MM.YYYY)

Abgedeckt: NAME->key-Mapping, sortValue-vs-String-Gewicht, Equity-Filter
(Cash/Future raus), Selbstreferenz-Skip, Null-Gewicht-Skip, Land-Platzhalter
"--" -> None, unbekannte Industry ("Unknown") -> Sektor None.
"""
from datetime import date

from services.etf_adapters.base import EtfRef
from services.etf_adapters.xtrackers import XtrackersAdapter, parse_xtrackers_holdings


def _cell(value, sort_value=None):
    return {"value": value, "sortValue": sort_value, "type": "text"}


def _row(isin, name, weight_cell, country, industry, asset_class):
    return {
        "header": _cell(isin),
        "column_0": _cell(name),
        "column_1": weight_cell,
        "column_2": _cell("1.00 B USD", 1_000_000_000.0),
        "column_3": _cell(country),
        "column_4": _cell(industry),
        "column_5": _cell(asset_class),
    }


# Fondsname-Slug ist egal; ISIN des Fonds = IE00BJ0KDQ92 (fuer Selbstreferenz-Test).
_FUND_ISIN = "IE00BJ0KDQ92"

_PAYLOAD = {
    "asOfDate": "",  # top-level in der Praxis leer -> Stichtag kommt aus Disclaimer
    "tables": [
        {
            "rowsPerPage": 15,  # nur Anzeige-Hinweis; wir nehmen ALLE .values
            "columns": [
                {"key": "header", "value": "ISIN"},
                {"key": "column_0", "value": "Name"},
                {"key": "column_1", "value": "% Weight"},
                {"key": "column_2", "value": "Market value"},
                {"key": "column_3", "value": "Country"},
                {"key": "column_4", "value": "Industry"},
                {"key": "column_5", "value": "Asset class"},
            ],
            "values": [
                # Equity, Gewicht aus numerischem sortValue (Anzeige "5.074%").
                _row("US67066G1040", "NVIDIA CORP", _cell("5.074%", 5.0741409),
                     "United States", "Information Technology", "Equities"),
                # Equity, andere Boerse/Land.
                _row("TW0002330008", "TAIWAN SEMICONDUCTOR MANUFACTURI",
                     _cell("14.857%", 14.85717259), "Taiwan",
                     "Information Technology", "Equities"),
                # Equity: sortValue fehlt -> Gewicht aus String "0.500%"; Land "--"
                # -> None; Industry "Unknown" -> Sektor None.
                _row("IE00B4BNMY34", "ACCENTURE PLC", _cell("0.500%", None),
                     "--", "Unknown", "Equities"),
                # Depository Receipt (Thai NVDR) -> BEHALTEN (echtes Aktien-Exposure).
                _row("TH0004010R14", "DELTA ELECTRONICS THAILAND NVDR",
                     _cell("0.250%", 0.25), "Thailand",
                     "Information Technology", "Depository Receipts"),
                # Preferred Stock (brasilianische Vorzugsaktie) -> BEHALTEN.
                _row("BRPETRACNPR6", "PETROBRAS PN", _cell("0.180%", 0.18),
                     "Brazil", "Energy", "Preferred Stock"),
                # Cash-Zeile (pseudo-ISIN) -> raus.
                _row("_CURRENCYUSD", "US DOLLAR", _cell("0.123%", 0.123),
                     "United States", "Unknown", "Cash"),
                # Fonds-Selbstreferenz (ISIN == Fonds-ISIN) -> raus.
                _row(_FUND_ISIN, "XTRACKERS MSCI WORLD SWAP",
                     _cell("0.010%", 0.01), "Ireland", "Financials", "Equities"),
                # Null-Gewicht-Equity -> raus (make_holding_row skippt <= 0).
                _row("NL0011794037", "ASML HOLDING NV", _cell("0.000%", 0.0),
                     "Netherlands", "Information Technology", "Equities"),
                # Derivat (Future) -> raus.
                _row("___ADI2TZ8S1", "MSCI WORLD INDEX SEP26",
                     _cell("0.000%", 0.0), "Germany", "Unknown", "Future"),
            ],
            "disclaimers": [
                {"text": "<p>Source: DWS 06.07.2026</p>", "asOfDate": None},
            ],
        }
    ],
}


class TestParseXtrackersHoldings:
    def test_filters_and_keys_by_isin(self):
        rows = parse_xtrackers_holdings(_PAYLOAD, "XDWD.DE", etf_isin=_FUND_ISIN)
        by = {r["holding_ticker"]: r for r in rows}
        # Equities + Depository Receipt + Preferred bleiben; Cash/Self-Ref/Null/Future raus.
        assert set(by) == {
            "US67066G1040", "TW0002330008", "IE00B4BNMY34",
            "TH0004010R14", "BRPETRACNPR6",
        }

    def test_depository_receipt_and_preferred_kept(self):
        # Regression: der Equity-Filter darf DR/Preferred NICHT droppen (sonst faellt
        # ein ganzer Thailand-/Brasilien-Sleeve aus dem Land-/Sektor-Look-Through).
        rows = parse_xtrackers_holdings(_PAYLOAD, "XDWD.DE", etf_isin=_FUND_ISIN)
        by = {r["holding_ticker"]: r for r in rows}
        assert by["TH0004010R14"]["holding_country"] == "Thailand"
        assert by["TH0004010R14"]["holding_sector"] == "Technology"
        assert by["BRPETRACNPR6"]["holding_country"] == "Brazil"
        assert by["BRPETRACNPR6"]["holding_sector"] == "Energy"

    def test_row_fields_and_sector_mapping(self):
        rows = parse_xtrackers_holdings(_PAYLOAD, "XDWD.DE", etf_isin=_FUND_ISIN)
        by = {r["holding_ticker"]: r for r in rows}

        nv = by["US67066G1040"]
        assert nv["weight_pct"] == 5.0741409       # numerischer sortValue bevorzugt
        assert nv["holding_isin"] == "US67066G1040"
        assert nv["holding_ticker"] == "US67066G1040"  # kein Ticker im Feed -> ISIN-Key
        assert nv["holding_name"] == "NVIDIA CORP"
        assert nv["holding_country"] == "United States"
        assert nv["holding_sector"] == "Technology"  # GICS "Information Technology"
        assert nv["as_of"] == date(2026, 7, 6)       # aus Disclaimer, nicht top-level

        tsmc = by["TW0002330008"]
        assert tsmc["holding_country"] == "Taiwan"
        assert tsmc["holding_sector"] == "Technology"

    def test_string_weight_fallback_and_placeholders(self):
        rows = parse_xtrackers_holdings(_PAYLOAD, "XDWD.DE", etf_isin=_FUND_ISIN)
        acc = {r["holding_ticker"]: r for r in rows}["IE00B4BNMY34"]
        # sortValue None -> Gewicht aus Anzeige-String "0.500%".
        assert acc["weight_pct"] == 0.5
        # Land-Platzhalter "--" -> None; unbekannte Industry -> Sektor None.
        assert acc["holding_country"] is None
        assert acc["holding_sector"] is None

    def test_cash_self_ref_zero_and_derivative_excluded(self):
        rows = parse_xtrackers_holdings(_PAYLOAD, "XDWD.DE", etf_isin=_FUND_ISIN)
        keys = {r["holding_ticker"] for r in rows}
        assert "_CURRENCYUSD" not in keys      # Cash
        assert _FUND_ISIN not in keys          # Selbstreferenz
        assert "NL0011794037" not in keys      # Null-Gewicht
        assert "___ADI2TZ8S1" not in keys      # Future

    def test_accepts_json_string_and_bytes(self):
        import json
        raw = json.dumps(_PAYLOAD)
        assert len(parse_xtrackers_holdings(raw, "XDWD.DE", etf_isin=_FUND_ISIN)) == 5
        assert len(parse_xtrackers_holdings(raw.encode(), "XDWD.DE", etf_isin=_FUND_ISIN)) == 5

    def test_column_name_mapping_survives_reorder(self):
        # Spalten in anderer Reihenfolge/Position -> Mapping via NAME muss halten.
        import copy
        p = copy.deepcopy(_PAYLOAD)
        p["tables"][0]["columns"] = list(reversed(p["tables"][0]["columns"]))
        rows = parse_xtrackers_holdings(p, "XDWD.DE", etf_isin=_FUND_ISIN)
        assert {r["holding_ticker"] for r in rows} == {
            "US67066G1040", "TW0002330008", "IE00B4BNMY34",
            "TH0004010R14", "BRPETRACNPR6",
        }

    def test_missing_tables_returns_empty(self):
        assert parse_xtrackers_holdings({"tables": []}, "XDWD.DE") == []
        assert parse_xtrackers_holdings({}, "XDWD.DE") == []


class TestXtrackersMatches:
    def test_matches_brand_with_isin(self):
        ref = EtfRef(ticker="XDWD.DE", isin="IE00BJ0KDQ92",
                     name="Xtrackers MSCI World UCITS ETF 1C")
        assert XtrackersAdapter().matches(ref) is True

    def test_no_match_without_isin(self):
        ref = EtfRef(ticker="XDWD.DE", isin=None,
                     name="Xtrackers MSCI World UCITS ETF 1C")
        assert XtrackersAdapter().matches(ref) is False

    def test_no_match_other_issuer(self):
        ref = EtfRef(ticker="SWDA.L", isin="IE00B4L5Y983",
                     name="iShares Core MSCI World UCITS ETF")
        assert XtrackersAdapter().matches(ref) is False
