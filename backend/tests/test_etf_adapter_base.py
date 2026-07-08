"""Unit-Tests fuer den geteilten Adapter-Vertrag (base.py):

- ISIN-Format-Validierung als Fetch-Gate (is_valid_isin / EtfRef.isin_valid),
- defensive Gewicht-Coercion in make_holding_row (String-Weight -> float statt
  TypeError),
- der isin_valid-Guard in matches(): jeder Adapter, der die ISIN in eine
  Fetch-URL / einen Request-Body interpoliert, darf bei formal ungueltiger ISIN
  NICHT matchen (der ETF faellt sauber auf no_source durch, statt einen
  womoeglich manipulierten Request zu bauen).
"""
from services.etf_adapters.amundi import AmundiAdapter
from services.etf_adapters.base import EtfRef, is_valid_isin, make_holding_row
from services.etf_adapters.fidelity import FidelityAdapter
from services.etf_adapters.hsbc import HsbcAdapter
from services.etf_adapters.jpmorgan import JPMorganAdapter
from services.etf_adapters.xtrackers import XtrackersAdapter

_VALID = "IE00BJ0KDQ92"
# Formal ungueltige "ISINs": zu kurz, endet nicht auf Ziffer, kein Laender-Prefix, leer.
_MALFORMED = ("GARBAGE", "IE00BJ0KDQ9X", "12345678901234", "")


class TestIsinValid:
    def test_valid_formats(self):
        assert is_valid_isin(_VALID)
        assert is_valid_isin("US0378331005")
        assert is_valid_isin("ie00bj0kdq92")  # wird intern normalisiert

    def test_invalid_formats(self):
        for bad in _MALFORMED:
            assert not is_valid_isin(bad), bad
        assert not is_valid_isin(None)

    def test_isin_valid_property_normalises(self):
        assert EtfRef("X", "ie00bj0kdq92", "n").isin_valid == _VALID
        assert EtfRef("X", "  IE00BJ0KDQ92 ", "n").isin_valid == _VALID

    def test_isin_valid_property_rejects_garbage(self):
        for bad in _MALFORMED:
            assert EtfRef("X", bad, "n").isin_valid is None, bad
        assert EtfRef("X", None, "n").isin_valid is None


class TestMakeHoldingRowWeight:
    def _row(self, w):
        return make_holding_row(etf_ticker="ETF", weight_pct=w, isin=_VALID)

    def test_string_weight_is_coerced(self):
        r = self._row("0.5")
        assert r is not None and r["weight_pct"] == 0.5

    def test_int_and_float_preserved(self):
        assert self._row(5)["weight_pct"] == 5.0
        assert self._row(2.75)["weight_pct"] == 2.75

    def test_non_numeric_string_dropped(self):
        assert self._row("abc") is None
        assert self._row("") is None
        assert self._row("   ") is None

    def test_none_zero_and_negative_dropped(self):
        assert self._row(None) is None
        assert self._row(0) is None
        assert self._row(-1) is None
        assert self._row("0") is None
        assert self._row("-2.5") is None

    def test_non_finite_weight_dropped(self):
        # NaN/Inf (als String "NaN"/"inf"/"Infinity" ODER als float) darf NICHT als
        # Holding durchgehen: `nan/inf <= 0` ist False -> wuerde sonst persistiert und
        # die Laender-Durchsicht mit NaN korrumpieren (Endpoint-500).
        assert self._row("NaN") is None
        assert self._row("nan") is None
        assert self._row("inf") is None
        assert self._row("Infinity") is None
        assert self._row("-inf") is None
        assert self._row(float("nan")) is None
        assert self._row(float("inf")) is None
        assert self._row(float("-inf")) is None


class TestAdaptersGateOnValidIsin:
    # Adapter, die die ISIN in URL/Body interpolieren (SPDR ist registry-gated und
    # daher separat sicher — hier bewusst nicht gelistet).
    _CASES = [
        (HsbcAdapter(), "HSBC MSCI World UCITS ETF"),
        (JPMorganAdapter(), "JPMorgan Global Equity Multi-Factor UCITS ETF"),
        (XtrackersAdapter(), "Xtrackers MSCI World UCITS ETF"),
        (AmundiAdapter(), "Amundi MSCI World UCITS ETF"),
        (FidelityAdapter(), "Fidelity US Quality Income UCITS ETF"),
    ]

    def test_malformed_isin_never_matches(self):
        for adapter, name in self._CASES:
            for bad in _MALFORMED:
                ref = EtfRef(ticker="X", isin=bad, name=name)
                assert adapter.matches(ref) is False, (adapter.name, repr(bad))

    def test_valid_isin_with_brand_matches(self):
        for adapter, name in self._CASES:
            ref = EtfRef(ticker="X", isin=_VALID, name=name)
            assert adapter.matches(ref) is True, adapter.name
