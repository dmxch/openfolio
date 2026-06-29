"""Tests fuer _summarize_indicators — Trennung taktische Risk-Treiber vs. Bewertung.

Kern der Aenderung: Bewertung (CAPE/Buffett) ist strukturell-langsam und darf das
taktische Risk-On/Off NICHT mehr kippen (sonst quasi-permanent "Risk Off" bei
teurem Markt). Rein (kein Netzwerk/DB) — testet die Klassifikations-Logik direkt.
"""
from __future__ import annotations

import services.macro_indicators_service as mis


def _ind(name: str, status: str) -> dict:
    return {"name": name, "status": status}


def test_extreme_valuation_does_not_flip_risk_climate():
    # Bullish/ruhige Risk-Treiber, aber CAPE+Buffett extrem -> Risk-Klima bleibt gruen,
    # Bewertung separat rot. (Das gemeldete Problem.)
    inds = [
        _ind("vix", "green"),
        _ind("credit_spread", "green"),
        _ind("yield_curve", "yellow"),
        _ind("unemployment", "green"),
        _ind("shiller_pe", "red"),
        _ind("buffett_indicator", "red"),
    ]
    s = mis._summarize_indicators(inds)
    assert s["overall_status"] == "green"
    assert s["risk_status"] == "green"
    assert s["overall_label"] == "Risk On"
    assert s["red_count"] == 0  # nur Risk-Treiber zaehlen
    assert s["valuation_status"] == "red"
    assert s["valuation_label"] == "Stark überbewertet"
    # group-Tagging
    groups = {i["name"]: i["group"] for i in inds}
    assert groups["shiller_pe"] == "valuation"
    assert groups["buffett_indicator"] == "valuation"
    assert groups["vix"] == "risk"
    assert groups["yield_curve"] == "risk"


def test_two_risk_reds_trigger_risk_off():
    inds = [
        _ind("vix", "red"),
        _ind("credit_spread", "red"),
        _ind("yield_curve", "green"),
        _ind("unemployment", "green"),
        _ind("shiller_pe", "green"),
        _ind("buffett_indicator", "green"),
    ]
    s = mis._summarize_indicators(inds)
    assert s["overall_status"] == "red"
    assert s["red_count"] == 2
    assert s["valuation_status"] == "green"


def test_credit_orange_escalates_like_red_for_decision():
    # Credit 5-7% (orange) ist erhoehter Stress -> eskaliert die ENTSCHEIDUNG wie rot,
    # wird aber NICHT als "rot" gezaehlt (red_count bleibt literal -> Anzeige passt zu Badges).
    inds = [
        _ind("vix", "red"),
        _ind("credit_spread", "orange"),
        _ind("yield_curve", "green"),
        _ind("unemployment", "green"),
    ]
    s = mis._summarize_indicators(inds)
    assert s["overall_status"] == "red"  # 1 rot + 1 orange = 2 kritisch
    assert s["red_count"] == 1           # literal rot (nur VIX)
    assert s["orange_count"] == 1


def test_single_risk_red_is_caution():
    inds = [
        _ind("vix", "red"),
        _ind("credit_spread", "green"),
        _ind("yield_curve", "green"),
        _ind("unemployment", "green"),
        _ind("shiller_pe", "green"),
        _ind("buffett_indicator", "green"),
    ]
    s = mis._summarize_indicators(inds)
    assert s["overall_status"] == "yellow"
    assert s["overall_label"] == "Vorsicht"


def test_one_valuation_red_is_ueberbewertet():
    inds = [_ind("shiller_pe", "red"), _ind("buffett_indicator", "green"), _ind("vix", "green")]
    s = mis._summarize_indicators(inds)
    assert s["valuation_status"] == "orange"
    assert s["valuation_label"] == "Überbewertet"
    assert s["valuation_red_count"] == 1


def test_valuation_unavailable_when_no_data():
    inds = [
        _ind("shiller_pe", "unavailable"),
        _ind("buffett_indicator", "unavailable"),
        _ind("vix", "green"),
    ]
    s = mis._summarize_indicators(inds)
    assert s["valuation_status"] == "unavailable"
    assert s["overall_status"] == "green"
