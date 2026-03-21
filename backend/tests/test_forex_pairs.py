"""Tests for Swissquote CSV forex pair parsing and FX rate derivation."""

import pytest
from datetime import datetime

from services.swissquote_parser import _build_forex_rate_lookup, _pair_forex


def _make_fx_row(date_str, order_id, txn_type, net_amount, currency):
    """Helper to create a forex row dict."""
    return {
        "_row": 1,
        "_date": datetime.strptime(date_str, "%Y-%m-%d"),
        "_order_id": order_id,
        "_type": txn_type,
        "_type_raw": "Forex-Gutschrift" if txn_type == "fx_credit" else "Forex-Belastung",
        "_symbol": "",
        "_name": "",
        "_isin": "",
        "_quantity": 1.0,
        "_unit_price": 0.0,
        "_fees": 0.0,
        "_accrued_interest": 0.0,
        "_net_amount": net_amount,
        "_currency": currency,
        "_net_amount_account": net_amount,
        "_is_aggregated": False,
        "_aggregated_count": 1,
    }


class TestPairForex:
    def test_basic_chf_to_usd(self):
        """CHF→USD: credit USD, debit CHF."""
        rows = [
            _make_fx_row("2026-02-27", "ORD1", "fx_credit", 12866.32, "USD"),
            _make_fx_row("2026-02-27", "ORD1", "fx_debit", -9982.64, "CHF"),
        ]
        fx_pairs, remaining = _pair_forex(rows)

        assert len(fx_pairs) == 1
        pair = fx_pairs[0]
        assert pair["currency_from"] == "CHF"
        assert pair["currency_to"] == "USD"
        assert pair["amount_from"] == 9982.64
        assert pair["amount_to"] == 12866.32
        assert abs(pair["rate"] - 0.775874) < 0.0001

    def test_fx_rows_kept_in_remaining(self):
        """FX rows are also kept in remaining for display."""
        rows = [
            _make_fx_row("2026-02-27", "ORD1", "fx_credit", 12866.32, "USD"),
            _make_fx_row("2026-02-27", "ORD1", "fx_debit", -9982.64, "CHF"),
        ]
        _, remaining = _pair_forex(rows)
        assert len(remaining) == 2

    def test_unpaired_fx_rows(self):
        """FX rows without matching pair stay in remaining."""
        rows = [
            _make_fx_row("2026-02-27", "ORD1", "fx_credit", 12866.32, "USD"),
        ]
        fx_pairs, remaining = _pair_forex(rows)
        assert len(fx_pairs) == 0
        assert len(remaining) == 1


class TestBuildForexRateLookup:
    def test_single_pair(self):
        """Single CHF→USD pair gives correct rate."""
        fx_pairs = [{
            "date": "2026-02-27",
            "currency_from": "CHF",
            "currency_to": "USD",
            "amount_from": 9982.64,
            "amount_to": 12866.32,
            "rate": 0.775874,
        }]
        lookup = _build_forex_rate_lookup(fx_pairs)

        assert "2026-02-27" in lookup
        assert "USD" in lookup["2026-02-27"]
        assert abs(lookup["2026-02-27"]["USD"] - 0.775874) < 0.0001

    def test_reverse_direction_usd_to_chf(self):
        """USD→CHF (selling USD): still derives correct USDCHF rate."""
        fx_pairs = [{
            "date": "2026-03-01",
            "currency_from": "USD",  # debit: paid USD
            "currency_to": "CHF",    # credit: received CHF
            "amount_from": 10000.0,
            "amount_to": 8800.0,
            "rate": 0.88,
        }]
        lookup = _build_forex_rate_lookup(fx_pairs)

        assert "2026-03-01" in lookup
        # CHF per 1 USD = 8800 / 10000 = 0.88
        assert abs(lookup["2026-03-01"]["USD"] - 0.88) < 0.0001

    def test_multiple_pairs_same_day_weighted_average(self):
        """Multiple CHF→USD pairs on same day → weighted average."""
        fx_pairs = [
            {
                "date": "2026-02-25",
                "currency_from": "CHF",
                "currency_to": "USD",
                "amount_from": 10000.0,
                "amount_to": 12800.0,
                "rate": 0.78125,
            },
            {
                "date": "2026-02-25",
                "currency_from": "CHF",
                "currency_to": "USD",
                "amount_from": 8000.0,
                "amount_to": 10256.41,
                "rate": 0.78,
            },
        ]
        lookup = _build_forex_rate_lookup(fx_pairs)

        # Weighted: (10000 + 8000) / (12800 + 10256.41) = 18000 / 23056.41
        expected = 18000.0 / 23056.41
        assert abs(lookup["2026-02-25"]["USD"] - expected) < 0.0001

    def test_multiple_currencies_same_day(self):
        """USD and EUR pairs on same day → separate entries."""
        fx_pairs = [
            {
                "date": "2026-02-25",
                "currency_from": "CHF",
                "currency_to": "USD",
                "amount_from": 10000.0,
                "amount_to": 12800.0,
                "rate": 0.78125,
            },
            {
                "date": "2026-02-25",
                "currency_from": "CHF",
                "currency_to": "EUR",
                "amount_from": 9500.0,
                "amount_to": 10000.0,
                "rate": 0.95,
            },
        ]
        lookup = _build_forex_rate_lookup(fx_pairs)

        assert abs(lookup["2026-02-25"]["USD"] - 0.78125) < 0.0001
        assert abs(lookup["2026-02-25"]["EUR"] - 0.95) < 0.0001

    def test_non_chf_pair_ignored(self):
        """USD→EUR pair (no CHF) is ignored."""
        fx_pairs = [{
            "date": "2026-02-25",
            "currency_from": "USD",
            "currency_to": "EUR",
            "amount_from": 1000.0,
            "amount_to": 920.0,
            "rate": 1.087,
        }]
        lookup = _build_forex_rate_lookup(fx_pairs)
        assert len(lookup) == 0

    def test_empty_input(self):
        """Empty fx_pairs returns empty lookup."""
        assert _build_forex_rate_lookup([]) == {}

    def test_known_values_from_spec(self):
        """Verify against the known values from the task specification."""
        # Build pairs matching the spec's expected FX rates
        fx_pairs = [
            # 25.02: CHF→USD, rate should be 0.780164
            {
                "date": "2026-02-25",
                "currency_from": "CHF",
                "currency_to": "USD",
                "amount_from": 30543.58,  # sum of PEP+PM+JNJ CHF amounts
                "amount_to": 39150.20,    # sum of PEP+PM+JNJ USD amounts
                "rate": 0.780164,
            },
            # 26.02: CHF→USD, rate should be 0.781501
            {
                "date": "2026-02-26",
                "currency_from": "CHF",
                "currency_to": "USD",
                "amount_from": 10069.62,
                "amount_to": 12884.97,
                "rate": 0.781501,
            },
            # 27.02: CHF→USD, rate should be 0.775874
            {
                "date": "2026-02-27",
                "currency_from": "CHF",
                "currency_to": "USD",
                "amount_from": 9982.64,
                "amount_to": 12866.32,
                "rate": 0.775874,
            },
        ]
        lookup = _build_forex_rate_lookup(fx_pairs)

        assert abs(lookup["2026-02-25"]["USD"] - 0.780164) < 0.0001
        assert abs(lookup["2026-02-26"]["USD"] - 0.781501) < 0.0001
        assert abs(lookup["2026-02-27"]["USD"] - 0.775874) < 0.0001
