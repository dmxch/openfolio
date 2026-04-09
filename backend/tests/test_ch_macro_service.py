"""Unit tests for services.ch_macro_service.

Alle externen Quellen werden gemockt — keine echten Netzwerk-Calls.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest  # noqa: F401  — used by async auto-detection

from services import ch_macro_service as svc


# --- Sync helpers -----------------------------------------------------------

def test_trend_label_thresholds():
    assert svc._trend_label(0.3, threshold=0.5) == "stable"
    assert svc._trend_label(1.2, threshold=0.5) == "up"
    assert svc._trend_label(-1.2, threshold=0.5) == "down"
    assert svc._trend_label(None) == "unknown"


def test_fx_trend_label_semantics():
    # Positives Delta = 1 CHF kauft mehr Fremdwaehrung = CHF staerker.
    assert svc._fx_trend_label(1.5) == "chf_stronger"
    assert svc._fx_trend_label(-1.5) == "chf_weaker"
    assert svc._fx_trend_label(0.1) == "stable"
    assert svc._fx_trend_label(None) == "unknown"


def test_next_meeting_picks_upcoming():
    with patch.object(svc, "_SNB_MEETING_DATES", ["2020-01-01", "2999-06-19", "2999-09-25"]):
        assert svc._next_snb_meeting(today=date(2025, 1, 1)) == "2999-06-19"
    with patch.object(svc, "_SNB_MEETING_DATES", ["2020-01-01"]):
        assert svc._next_snb_meeting(today=date(2025, 1, 1)) is None


# --- Orchestrator: happy path ----------------------------------------------

_HAPPY_RETURNS = {
    "_fetch_snb_policy_rate": {
        "data": {"policy_rate_pct": 0.5, "policy_rate_changed_on": "2025-12-12"},
        "warnings": [],
    },
    "_fetch_saron_with_delta": {
        "data": {"current_pct": 0.45, "as_of": "2026-04-08", "delta_30d_bps": -2.0, "trend": "stable"},
        "warnings": [],
    },
    "_fetch_fx_pairs": {
        "data": {
            "chf_eur": {"rate": 1.0512, "as_of": "2026-04-08", "delta_30d_pct": 0.4, "trend": "chf_stronger"},
            "chf_usd": {"rate": 1.1234, "as_of": "2026-04-08", "delta_30d_pct": -0.1, "trend": "stable"},
        },
        "warnings": [],
    },
    "_fetch_ch_inflation": {
        "data": {"cpi_yoy_pct": 1.2, "cpi_as_of": "2026-03-01", "core_cpi_yoy_pct": None},
        "warnings": ["ch_core_cpi_unavailable"],
    },
    "_fetch_ch_10y": {
        "data": {"eidg_10y_yield_pct": 0.48, "delta_30d_bps": 3.0, "trend": "stable"},
        "warnings": [],
    },
    "_fetch_smi_vs_sp500": {
        "data": {"smi_return_pct": 2.1, "sp500_return_pct": 1.4, "relative_pct": 0.7},
        "warnings": [],
    },
}


async def test_full_snapshot_happy_path():
    patches = [
        patch.object(svc, name, new=AsyncMock(return_value=ret))
        for name, ret in _HAPPY_RETURNS.items()
    ]
    for p in patches:
        p.start()
    try:
        snap = await svc.get_ch_macro_snapshot()
    finally:
        for p in patches:
            p.stop()

    assert "as_of" in snap
    assert snap["snb"]["policy_rate_pct"] == 0.5
    assert snap["snb"]["policy_rate_changed_on"] == "2025-12-12"
    assert "next_meeting" in snap["snb"]
    assert snap["saron"]["current_pct"] == 0.45
    assert snap["fx"]["chf_eur"]["rate"] == 1.0512
    assert snap["fx"]["chf_usd"]["trend"] == "stable"
    assert snap["ch_inflation"]["cpi_yoy_pct"] == 1.2
    assert snap["ch_rates"]["eidg_10y_yield_pct"] == 0.48
    assert snap["smi_vs_sp500_30d"]["relative_pct"] == 0.7
    assert "ch_core_cpi_unavailable" in snap["warnings"]


async def test_partial_failure_adds_warning():
    """Wenn ein einzelner Helfer None-data liefert, faellt das Feld weg,
    der Rest der Response bleibt gueltig."""
    failing = dict(_HAPPY_RETURNS)
    failing["_fetch_saron_with_delta"] = {"data": None, "warnings": ["saron_unavailable"]}

    patches = [
        patch.object(svc, name, new=AsyncMock(return_value=ret))
        for name, ret in failing.items()
    ]
    for p in patches:
        p.start()
    try:
        snap = await svc.get_ch_macro_snapshot()
    finally:
        for p in patches:
            p.stop()

    assert snap["saron"] is None
    assert "saron_unavailable" in snap["warnings"]
    assert snap["snb"]["policy_rate_pct"] == 0.5  # andere Felder intakt
    assert snap["ch_rates"]["eidg_10y_yield_pct"] == 0.48


async def test_helper_exception_becomes_warning():
    """Wirft ein Helper unerwartet (Belt-and-Suspenders), fangt gather()
    das ab und der Orchestrator schreibt nur ein *_unavailable ins warnings."""
    patches = [
        patch.object(svc, name, new=AsyncMock(return_value=ret))
        for name, ret in _HAPPY_RETURNS.items()
        if name != "_fetch_fx_pairs"
    ]
    broken = patch.object(
        svc, "_fetch_fx_pairs", new=AsyncMock(side_effect=RuntimeError("boom"))
    )
    for p in patches:
        p.start()
    broken.start()
    try:
        snap = await svc.get_ch_macro_snapshot()
    finally:
        broken.stop()
        for p in patches:
            p.stop()

    assert snap["fx"] is None
    assert "fx_unavailable" in snap["warnings"]


async def test_fred_missing_key_falls_back():
    """Ohne FRED-API-Key (kein User hat einen eingetragen) liefert der
    10Y-Helfer leere Felder + warning. CPI nutzt Eurostat (kein Key noetig)
    und ist davon nicht betroffen.
    """
    with patch(
        "services.macro_indicators_service._get_fred_api_key",
        return_value=None,
    ):
        y10 = await svc._fetch_ch_10y()

    assert y10["data"]["eidg_10y_yield_pct"] is None
    assert "fred_no_api_key" in y10["warnings"]


async def test_eurostat_hicp_extracts_latest_value():
    """_fetch_eurostat_hicp_ch nimmt den neuesten vorhandenen Wert aus der
    Eurostat-SDMX-JSON-Response, ueberspringt None-Werte korrekt."""
    fake_payload = {
        "value": {"0": 1.1, "1": 0.9, "2": None, "3": 0.6},
        "dimension": {
            "time": {
                "category": {
                    "index": {"2025-09": 0, "2025-10": 1, "2025-11": 2, "2025-12": 3}
                }
            }
        },
    }

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_payload

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _FakeResp()

    with patch.object(svc.httpx, "AsyncClient", return_value=_FakeClient()):
        val, label = await svc._fetch_eurostat_hicp_ch("CP00")

    assert val == 0.6
    assert label == "2025-12"


async def test_snb_policy_rate_fallback():
    """Wenn SNB Data Portal wirft, greift der hardcoded Fallback + warning."""
    class _FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, *a, **kw):
            raise RuntimeError("snb down")

    with patch.object(svc.httpx, "AsyncClient", return_value=_FakeClient()):
        result = await svc._fetch_snb_policy_rate()

    assert result["data"]["policy_rate_pct"] == svc._SNB_POLICY_RATE_FALLBACK["rate"]
    assert result["data"]["policy_rate_changed_on"] == svc._SNB_POLICY_RATE_FALLBACK["changed_on"]
    assert "snb_policy_rate_fallback_used" in result["warnings"]
