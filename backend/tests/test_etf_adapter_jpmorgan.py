"""Unit-Tests fuer den JPMorgan-Holdings-Adapter (rein, kein Netz/DB).

Die Fixture spiegelt die reale Struktur des Endpoints
`FundsMarketingHandler/product-data` (Feld `fundData.dailyHoldingsAll.data[]`),
verifiziert am 08.07.2026 gegen JPGL (IE00BJRCLL96) und JREG (IE00BF4G6Y48):
  - securityIsin / securityDescription / marketValuePercent / country / navDate,
  - securityType als Equity-/Nicht-Equity-Diskriminator ("Common Stock",
    "Depository Receipt - American", "Fund - Real Estate Investment Trust" bleiben;
    "Cash"/"Futures"/"Right"/"Warrant - Equity" fliegen raus),
  - sector = None fuer ALLE Zeilen (der Feed liefert pro Holding keinen Sektor).
"""
from datetime import date

from services.etf_adapters.base import EtfRef
from services.etf_adapters.jpmorgan import (
    JPMorganAdapter,
    parse_jpmorgan_holdings,
)

_FUND_ISIN = "IE00BJRCLL96"

# ~realer Ausschnitt: 4 verwertbare Equity-Zeilen + 5 zu ueberspringende.
_PAYLOAD = {
    "error": None,
    "fundData": {
        "name": "JPM Global Equity Multi-Factor UCITS ETF",
        "dailyHoldings": {  # NUR Top-10 -> darf NICHT gelesen werden
            "effectiveDate": "2026-07-07",
            "data": [{"securityIsin": "US0000000000", "marketValuePercent": 99.0,
                      "securityType": "Common Stock"}],
        },
        "dailyHoldingsAll": {
            "effectiveDate": "2026-07-07",
            "data": [
                {  # 1) Common Stock, lokaler Ticker (mehrdeutig) -> ISIN ist der Key
                    "securityIsin": "KR7000660001",
                    "securityDescription": "SK HYNIX INC /KRW/",
                    "marketValuePercent": 0.3769534725552,
                    "country": "South Korea",
                    "securityTicker": "000660",
                    "sector": None,
                    "industry": None,
                    "navDate": "2026-07-07",
                    "securityType": "Common Stock",
                },
                {  # 2) US Common Stock
                    "securityIsin": "US0382221051",
                    "securityDescription": "APPLIED MATERIALS INC",
                    "marketValuePercent": 0.362227284944902,
                    "country": "United States",
                    "securityTicker": "AMAT",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Common Stock",
                },
                {  # 3) REIT -> Equity, bleibt drin
                    "securityIsin": "US2538681030",
                    "securityDescription": "DIGITAL REALTY TRUST INC",
                    "marketValuePercent": 0.226761142276246,
                    "country": "United States",
                    "securityTicker": "DLR",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Fund - Real Estate Investment Trust",
                },
                {  # 4) ADR -> Equity, bleibt drin (Include-Liste wuerde das faelschlich droppen)
                    "securityIsin": "US4581401001",
                    "securityDescription": "INTEL CORP",
                    "marketValuePercent": 0.15,
                    "country": "United States",
                    "securityTicker": "INTC",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Depository Receipt - American",
                },
                {  # 5) Cash: ISIN null + securityType Cash -> skip
                    "securityIsin": None,
                    "securityDescription": "Cash and Cash Equivalent",
                    "marketValuePercent": 0.086102706050029,
                    "country": "United States",
                    "securityTicker": "USD",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Cash",
                },
                {  # 6) Futures: Kontacode statt ISIN + negatives Gewicht -> skip
                    "securityIsin": "HWAU6",
                    "securityDescription": "F/C SP500 MIC EMIN FUTSEP26",
                    "marketValuePercent": -0.000254165010361,
                    "country": "United States",
                    "securityTicker": "HWAU6",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Futures",
                },
                {  # 7) Right: ISIN-Format gueltig, aber Nicht-Equity -> skip via securityType
                    "securityIsin": "ES06445809W9",
                    "securityDescription": "IBERDROLA RTS 07/20/26/EUR/",
                    "marketValuePercent": 0.006142038883553,
                    "country": "Spain",
                    "securityTicker": "IBE/D",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Right",
                },
                {  # 8) Gewicht 0 -> skip
                    "securityIsin": "US5949181045",
                    "securityDescription": "MICROSOFT CORP",
                    "marketValuePercent": 0.0,
                    "country": "United States",
                    "securityTicker": "MSFT",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Common Stock",
                },
                {  # 9) Selbst-Referenz (holding-ISIN == fund_isin) -> skip
                    "securityIsin": _FUND_ISIN,
                    "securityDescription": "JPM GLOBAL EQUITY MULTI-FACTOR",
                    "marketValuePercent": 1.0,
                    "country": "Ireland",
                    "securityTicker": "JPGL",
                    "sector": None,
                    "navDate": "2026-07-07",
                    "securityType": "Common Stock",
                },
            ],
        },
    },
}


class TestParseJpmorganHoldings:
    def _rows(self):
        return parse_jpmorgan_holdings(_PAYLOAD, "JPGL.L", fund_isin=_FUND_ISIN)

    def test_keeps_only_equity_holdings(self):
        rows = self._rows()
        by = {r["holding_ticker"]: r for r in rows}
        # Common Stock (2) + REIT + ADR = 4; Cash/Futures/Right/Zero/Self-Ref raus.
        assert set(by) == {
            "KR7000660001", "US0382221051", "US2538681030", "US4581401001"
        }

    def test_holding_fields_are_native(self):
        rows = self._rows()
        by = {r["holding_isin"]: r for r in rows}
        hynix = by["KR7000660001"]
        # holding_ticker == ISIN: kein yf-Ticker gebaut (Boersen-Suffix mehrdeutig).
        assert hynix["holding_ticker"] == "KR7000660001"
        assert hynix["holding_isin"] == "KR7000660001"
        assert hynix["weight_pct"] == 0.3769534725552
        assert hynix["holding_country"] == "South Korea"
        assert hynix["holding_name"] == "SK HYNIX INC"      # Waehrungs-Tag entfernt
        assert hynix["holding_sector"] is None              # Feed liefert keinen Sektor
        assert hynix["as_of"] == date(2026, 7, 7)
        assert hynix["etf_ticker"] == "JPGL.L"

    def test_sector_is_none_for_all_rows(self):
        assert all(r["holding_sector"] is None for r in self._rows())

    def test_reit_and_adr_are_kept(self):
        by = {r["holding_isin"]: r for r in self._rows()}
        assert by["US2538681030"]["holding_name"] == "DIGITAL REALTY TRUST INC"  # REIT
        assert by["US4581401001"]["holding_name"] == "INTEL CORP"                # ADR

    def test_cash_futures_right_zero_and_self_ref_excluded(self):
        isins = {r["holding_isin"] for r in self._rows()}
        assert None not in isins                 # Cash (keine ISIN)
        assert "HWAU6" not in isins              # Futures (Kontacode)
        assert "ES06445809W9" not in isins       # Right (Nicht-Equity)
        assert "US5949181045" not in isins       # Gewicht 0
        assert _FUND_ISIN not in isins           # Selbst-Referenz

    def test_uses_daily_holdings_all_not_top10(self):
        # Der dailyHoldings-Block (Top-10) traegt US0000000000; es darf nicht auftauchen.
        isins = {r["holding_isin"] for r in self._rows()}
        assert "US0000000000" not in isins

    def test_accepts_json_string_and_bytes(self):
        import json
        s = json.dumps(_PAYLOAD)
        assert len(parse_jpmorgan_holdings(s, "JPGL.L", fund_isin=_FUND_ISIN)) == 4
        assert len(parse_jpmorgan_holdings(s.encode(), "JPGL.L", fund_isin=_FUND_ISIN)) == 4

    def test_missing_or_empty_payload_returns_empty(self):
        assert parse_jpmorgan_holdings({}, "JPGL.L") == []
        assert parse_jpmorgan_holdings({"fundData": {}}, "JPGL.L") == []
        assert parse_jpmorgan_holdings("not-json", "JPGL.L") == []
        assert parse_jpmorgan_holdings(
            {"fundData": {"dailyHoldingsAll": {"data": []}}}, "JPGL.L"
        ) == []


class TestJpmorganMatches:
    def _match(self, name: str, isin: str | None) -> bool:
        return JPMorganAdapter().matches(EtfRef(ticker="X", isin=isin, name=name))

    def test_matches_brand_variants_with_isin(self):
        assert self._match("JPMorgan Global Equity Multi-Factor UCITS ETF", _FUND_ISIN)
        assert self._match("JPM Global Research Enhanced Index Equity", _FUND_ISIN)
        assert self._match("JPMorgan BetaBuilders US Equity UCITS ETF", "IE00BJK9H753")
        assert self._match("J.P. Morgan Active US Value UCITS ETF", "IE0001234567")

    def test_requires_isin(self):
        # Ohne ISIN keine URL baubar -> kein Match, auch bei passendem Namen.
        assert not self._match("JPMorgan Global Equity Multi-Factor UCITS ETF", None)

    def test_does_not_false_match_other_issuers(self):
        assert not self._match("iShares Core MSCI World UCITS ETF", _FUND_ISIN)
        assert not self._match("Xtrackers MSCI World UCITS ETF", _FUND_ISIN)
        assert not self._match("Vanguard FTSE All-World UCITS ETF", _FUND_ISIN)
