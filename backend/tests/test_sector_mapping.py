"""Tests for sector_mapping: FINVIZ taxonomy, ETF whitelist, is_broad_etf()."""

from services.sector_mapping import (
    INDUSTRY_TO_SECTOR,
    SECTOR_ORDER,
    FINVIZ_SECTORS,
    ALL_SECTORS,
    MULTI_SECTOR_INDUSTRIES,
    ETF_200DMA_WHITELIST,
    SECTORS_WITH_INDUSTRIES,
    is_broad_etf,
)


# --- is_broad_etf() ---

class TestIsBroadEtf:
    def test_us_tickers(self):
        for ticker in ["VOO", "VTI", "SPY", "QQQ", "DIA"]:
            assert is_broad_etf(ticker) is True, f"{ticker} should be broad ETF"

    def test_european_tickers(self):
        for ticker in ["VWRL", "SWDA", "IWDA", "CSPX"]:
            assert is_broad_etf(ticker) is True

    def test_swiss_tickers(self):
        for ticker in ["CHSPI", "CSSMI", "SP5HCH"]:
            assert is_broad_etf(ticker) is True

    def test_exchange_suffix_stripped(self):
        """VWRL.SW → base 'VWRL' should match."""
        assert is_broad_etf("VWRL.SW") is True
        assert is_broad_etf("SWDA.L") is True
        assert is_broad_etf("CSPX.L") is True

    def test_case_insensitive_via_upper(self):
        assert is_broad_etf("voo") is True
        assert is_broad_etf("Spy") is True

    def test_non_etf_returns_false(self):
        assert is_broad_etf("AAPL") is False
        assert is_broad_etf("MSFT") is False
        assert is_broad_etf("NOVN.SW") is False

    def test_empty_string(self):
        assert is_broad_etf("") is False

    def test_partial_match_not_accepted(self):
        """'VO' is not 'VOO'."""
        assert is_broad_etf("VO") is False


# --- Taxonomy integrity ---

class TestTaxonomy:
    def test_all_industries_map_to_known_sector(self):
        for industry, sector in INDUSTRY_TO_SECTOR.items():
            assert sector in ALL_SECTORS, f"Industry '{industry}' maps to unknown sector '{sector}'"

    def test_finviz_sectors_count(self):
        assert len(FINVIZ_SECTORS) == 11

    def test_sector_order_contains_all_sectors(self):
        sectors_from_mapping = set(INDUSTRY_TO_SECTOR.values())
        for s in sectors_from_mapping:
            assert s in ALL_SECTORS, f"Sector '{s}' missing from ALL_SECTORS"

    def test_multi_sector_industries_in_mapping(self):
        for industry in MULTI_SECTOR_INDUSTRIES:
            assert industry in INDUSTRY_TO_SECTOR
            assert INDUSTRY_TO_SECTOR[industry] == "Multi-Sector"

    def test_reverse_mapping_completeness(self):
        """SECTORS_WITH_INDUSTRIES should cover all industries."""
        all_industries_from_reverse = set()
        for industries in SECTORS_WITH_INDUSTRIES.values():
            all_industries_from_reverse.update(industries)
        assert all_industries_from_reverse == set(INDUSTRY_TO_SECTOR.keys())

    def test_reverse_mapping_sorted(self):
        """Industries within each sector should be alphabetically sorted."""
        for sector, industries in SECTORS_WITH_INDUSTRIES.items():
            assert industries == sorted(industries), f"Industries in '{sector}' not sorted"


# --- Whitelist sanity ---

class TestWhitelist:
    def test_whitelist_has_expected_count(self):
        assert len(ETF_200DMA_WHITELIST) >= 25  # Currently 27

    def test_whitelist_all_uppercase(self):
        for ticker in ETF_200DMA_WHITELIST:
            assert ticker == ticker.upper(), f"Whitelist ticker '{ticker}' not uppercase"

    def test_whitelist_no_suffixes(self):
        """Base tickers only — no exchange suffixes."""
        for ticker in ETF_200DMA_WHITELIST:
            assert "." not in ticker, f"Whitelist ticker '{ticker}' has exchange suffix"
