"""Unit-Tests fuer den Amundi-Holdings-Adapter (rein, kein Netz/DB).

Deckt die kippenden Stellen ab:
  - Swap-Erkennung -> [] (Substitut-Korb darf NIE als Holdings landen),
  - Gewichts-Skala (Bruch 0..1 -> Prozent 0..100),
  - Filter: Cash / Future (traegt GUELTIGE Futures-ISIN!) / Self-Ref / Nullgewicht,
  - bbg -> yf-Ticker (aufgeloest) bzw. ISIN-Fallback-Key,
  - Issuer-native Felder: countryOfRisk, GICS-Sektor-Mapping, as_of.

Fixture spiegelt die REALE Amundi-Antwort (getProductsData): products[0] mit
`characteristics` + `composition.compositionData`, wobei jede Zeile die Felder in
`compositionCharacteristics` traegt und `weight` als BRUCH (0..1) kommt.
"""
from datetime import date

from services.etf_adapters.amundi import (
    AmundiAdapter,
    parse_amundi_composition,
)
from services.etf_adapters.base import EtfRef


def _row(**cc) -> dict:
    """Baue eine Composition-Zeile im realen Amundi-Format (Felder in
    compositionCharacteristics, Gewicht zusaetzlich auf Top-Level)."""
    return {"compositionCharacteristics": cc, "weight": cc.get("weight")}


# Physischer Fonds (Amundi Prime All Country World, IE0003XJA0J9). Gewichte = Bruch.
_PHYSICAL = {
    "products": [
        {
            "productId": "IE0003XJA0J9",
            "characteristics": {
                "ISIN": "IE0003XJA0J9",
                "FUND_REPLICATION_METHODOLOGY": "Direct(Physical)",
            },
            "composition": {
                "totalNumberOfInstruments": 8,
                "compositionData": [
                    # US-Nasdaq (bbg-Code "UW" -> US-Ticker "NVDA", kein Suffix).
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg="NVDA UW",
                         isin="US67066G1040", name="NVIDIA CORP", weight=0.044,
                         currency="USD", sector="Information Technology",
                         countryOfRisk="United States"),
                    # Euronext Amsterdam (bbg "NA" -> .AS).
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg="ASML NA",
                         isin="NL0010273215", name="ASML HOLDING NV", weight=0.03,
                         currency="EUR", sector="Information Technology",
                         countryOfRisk="Netherlands"),
                    # Taiwan (bbg "TT" -> .TW).
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg="2330 TT",
                         isin="TW0002330008", name="TAIWAN SEMICONDUCTOR", weight=0.02,
                         currency="TWD", sector="Information Technology",
                         countryOfRisk="Taiwan"),
                    # countryOfRisk fehlt -> Fallback auf `country`; bbg "GY" -> .DE.
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg="SAP GY",
                         isin="DE0007164600", name="SAP SE", weight=0.015,
                         currency="EUR", sector="Information Technology",
                         countryOfRisk=None, country="Germany"),
                    # Depository Receipt (ADR) -> BEHALTEN: der Token-Filter darf
                    # 'DEPOSITORY_RECEIPT' NICHT ueber das Cash-Token 'DEPOSIT' droppen.
                    _row(date="2026-07-06", type="DEPOSITORY_RECEIPT", bbg="TSM US",
                         isin="US8740391003", name="TAIWAN SEMI ADR", weight=0.012,
                         currency="USD", sector="Information Technology",
                         countryOfRisk="Taiwan"),
                    # Cash -> raus (keine ISIN, Typ CASH).
                    _row(date="2026-07-06", type="CASH", bbg=None, isin=None,
                         name=None, weight=0.01, currency="USD", sector=None,
                         countryOfRisk=None),
                    # Future -> raus TROTZ gueltiger Futures-ISIN (nur der Typ-Filter faengt das).
                    _row(date="2026-07-06", type="FUTURE", bbg="MESU6",
                         isin="DE000C71QQS6", name="MSCI EMGMKT FUT", weight=0.005,
                         currency="USD", sector="", countryOfRisk="Supranationals"),
                    # Self-Reference (Holding-ISIN == Fonds-ISIN) -> raus.
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg=None,
                         isin="IE0003XJA0J9", name="AMUNDI PRIME ACWI", weight=0.001,
                         currency="USD", sector=None, countryOfRisk="Ireland"),
                    # Nullgewicht -> raus.
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg="0005 HK",
                         isin="HK0000000012", name="ZERO WEIGHT CO", weight=0.0,
                         currency="HKD", sector="Financials", countryOfRisk="Hong Kong"),
                ],
            },
        }
    ]
}

# Swap-Fonds (Amundi MSCI World SWAP, LU1681043599): Composition = Substitut-Korb.
_SWAP = {
    "products": [
        {
            "productId": "LU1681043599",
            "characteristics": {
                "ISIN": "LU1681043599",
                "FUND_REPLICATION_METHODOLOGY": "Indirect(Swap Based)",
            },
            "composition": {
                "totalNumberOfInstruments": 2,
                "compositionData": [
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg="ENR GY",
                         isin="DE000ENER6Y0", name="SIEMENS ENERGY AG", weight=0.068,
                         currency="EUR", sector="Industrials", countryOfRisk="Germany"),
                    _row(date="2026-07-06", type="EQUITY_ORDINARY", bbg="ASML NA",
                         isin="NL0010273215", name="ASML HOLDING NV", weight=0.068,
                         currency="EUR", sector="Information Technology",
                         countryOfRisk="Netherlands"),
                ],
            },
        }
    ]
}


class TestParsePhysical:
    def test_row_count_after_filtering(self):
        rows = parse_amundi_composition(_PHYSICAL, "PRAW.DE")
        # 9 Quell-Zeilen -> Cash, Future, Self-Ref, Nullgewicht raus -> 5 Holdings
        # (Equity x4 + Depository Receipt).
        assert len(rows) == 5

    def test_resolved_and_isin_fallback_tickers(self):
        rows = parse_amundi_composition(_PHYSICAL, "PRAW.DE")
        by = {r["holding_ticker"]: r for r in rows}
        # bbg aufgeloest inkl. US-Nasdaq "UW" -> "NVDA" und "US" -> "TSM".
        assert set(by) == {"NVDA", "ASML.AS", "2330.TW", "SAP.DE", "TSM"}

    def test_depository_receipt_kept(self):
        # Regression: 'DEPOSITORY_RECEIPT' darf nicht ueber 'DEPOSIT' gefiltert werden.
        rows = parse_amundi_composition(_PHYSICAL, "PRAW.DE")
        by = {r["holding_ticker"]: r for r in rows}
        assert by["TSM"]["holding_isin"] == "US8740391003"
        assert by["TSM"]["holding_country"] == "Taiwan"
        assert by["TSM"]["holding_sector"] == "Technology"

    def test_weight_normalized_fraction_to_percent(self):
        rows = parse_amundi_composition(_PHYSICAL, "PRAW.DE")
        by = {r["holding_ticker"]: r for r in rows}
        nvda = by["NVDA"]
        assert round(nvda["weight_pct"], 6) == 4.4      # 0.044 (Bruch) -> 4.4 (Prozent)
        assert round(by["ASML.AS"]["weight_pct"], 6) == 3.0

    def test_native_fields_country_sector_isin_asof(self):
        rows = parse_amundi_composition(_PHYSICAL, "PRAW.DE")
        by = {r["holding_ticker"]: r for r in rows}
        nvda = by["NVDA"]
        assert nvda["holding_isin"] == "US67066G1040"
        assert nvda["holding_country"] == "United States"   # countryOfRisk
        assert nvda["holding_sector"] == "Technology"       # GICS-Mapping
        assert nvda["holding_name"] == "NVIDIA CORP"
        assert nvda["as_of"] == date(2026, 7, 6)
        # countryOfRisk fehlt -> Fallback auf `country`.
        assert by["SAP.DE"]["holding_country"] == "Germany"

    def test_cash_future_selfref_zero_excluded(self):
        rows = parse_amundi_composition(_PHYSICAL, "PRAW.DE")
        isins = {r["holding_isin"] for r in rows}
        tickers = {r["holding_ticker"] for r in rows}
        assert "DE000C71QQS6" not in isins        # Future (trug gueltige ISIN!)
        assert "IE0003XJA0J9" not in isins         # Self-Reference (Fonds-ISIN)
        assert "HK0000000012" not in isins         # Nullgewicht
        assert not any(t.startswith("USD") for t in tickers)  # Cash


class TestSwapPitfall:
    def test_swap_fund_returns_empty(self):
        # KRITISCH: Swap-Fonds liefern einen Substitut-Korb -> NICHT persistieren.
        assert parse_amundi_composition(_SWAP, "LYWD.DE") == []

    def test_swap_detected_via_boolean_flag(self):
        payload = {
            "products": [{
                "productId": "LU0000000000",
                "characteristics": {"ISIN": "LU0000000000",
                                    "REPLICATION_IS_SWAP_BASED": True},
                "composition": {"compositionData": [
                    _row(type="EQUITY_ORDINARY", bbg="ENR GY", isin="DE000ENER6Y0",
                         name="SIEMENS ENERGY", weight=0.5, sector="Industrials",
                         countryOfRisk="Germany"),
                ]},
            }]
        }
        assert parse_amundi_composition(payload, "X.DE") == []


class TestWeightScale:
    def test_percent_scale_not_double_multiplied(self):
        # Gewichte schon in Prozent (Summe > 1.5) -> unveraendert lassen.
        payload = {
            "products": [{
                "productId": "IE0000000001",
                "characteristics": {"ISIN": "IE0000000001",
                                    "FUND_REPLICATION_METHODOLOGY": "Direct(Physical)"},
                "composition": {"compositionData": [
                    _row(type="EQUITY_ORDINARY", bbg="ASML NA", isin="NL0010273215",
                         name="ASML", weight=40.0, sector="Information Technology",
                         countryOfRisk="Netherlands"),
                    _row(type="EQUITY_ORDINARY", bbg="2330 TT", isin="TW0002330008",
                         name="TSMC", weight=30.0, sector="Information Technology",
                         countryOfRisk="Taiwan"),
                ]},
            }]
        }
        rows = parse_amundi_composition(payload, "X.DE")
        by = {r["holding_ticker"]: r for r in rows}
        assert by["ASML.AS"]["weight_pct"] == 40.0
        assert by["2330.TW"]["weight_pct"] == 30.0


class TestParseRobustness:
    def test_accepts_json_string_payload(self):
        import json
        rows = parse_amundi_composition(json.dumps(_PHYSICAL), "PRAW.DE")
        assert len(rows) == 5

    def test_empty_and_garbage(self):
        assert parse_amundi_composition("not json", "X.DE") == []
        assert parse_amundi_composition({}, "X.DE") == []
        assert parse_amundi_composition({"products": []}, "X.DE") == []


class TestMatches:
    def test_matches_brand_and_isin(self):
        a = AmundiAdapter()
        assert a.matches(EtfRef(ticker="PRAW.DE", isin="IE0003XJA0J9",
                                name="Amundi Prime All Country World UCITS ETF"))
        # ex-Lyxor traegt teils noch die Lyxor-Marke.
        assert a.matches(EtfRef(ticker="LYY.DE", isin="LU1681043599",
                                name="Lyxor MSCI World UCITS ETF"))

    def test_no_match_other_issuer_or_missing_isin(self):
        a = AmundiAdapter()
        assert not a.matches(EtfRef(ticker="SWDA.L", isin="IE00B4L5Y983",
                                    name="iShares Core MSCI World UCITS ETF"))
        # Marke ok, aber ohne ISIN kein Body baubar.
        assert not a.matches(EtfRef(ticker="PRAW.DE", isin=None,
                                    name="Amundi Prime All Country World"))
