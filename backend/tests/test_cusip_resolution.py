"""Tests fuer die CUSIP→ticker-Resolution (OpenFIGI, Redis-cached).

Validiert:
- _pick_figi_ticker waehlt das US-Composite-Common-Stock-Papier und verwirft
  Warrant/Preferred — das ist der Kern-Fix gegen Mis-Resolutions wie
  Oracle→ORCL-PD und TSMC→TSMWF.
- resolve_cusips nutzt den Cache (Hit + Negativ-Cache) und ruft OpenFIGI nur
  fuer echte Misses.
"""
from __future__ import annotations

import pytest

from services.screening import sec_13f_service as svc


# --- _pick_figi_ticker (reine Funktion) ------------------------------------

def test_pick_prefers_common_stock_over_preferred():
    # Oracle-Szenario: Preferred + Common am selben US-Exchange → Common gewinnt.
    records = [
        {"ticker": "ORCL-PD", "exchCode": "US", "securityType": "Preferred"},
        {"ticker": "ORCL", "exchCode": "US", "securityType": "Common Stock"},
    ]
    assert svc._pick_figi_ticker(records) == "ORCL"


def test_pick_prefers_us_composite_adr_over_foreign_listing():
    # TSMC-Szenario: Grey-Market/Foreign vs. US-ADR → US-ADR gewinnt.
    records = [
        {"ticker": "TSMWF", "exchCode": "PQ", "securityType": "Common Stock"},
        {"ticker": "2330", "exchCode": "TT", "securityType": "Common Stock"},
        {"ticker": "TSM", "exchCode": "US", "securityType": "ADR"},
    ]
    assert svc._pick_figi_ticker(records) == "TSM"


def test_pick_rejects_warrant_only():
    # Nur Warrant → kein Ticker (lieber Drop als falscher Ticker wie TE-WT).
    records = [{"ticker": "TE-WT", "exchCode": "US", "securityType": "Warrant"}]
    assert svc._pick_figi_ticker(records) is None


def test_pick_skips_rejected_types_to_find_common():
    records = [
        {"ticker": "TE-WT", "exchCode": "US", "securityType": "Warrant"},
        {"ticker": "TE", "exchCode": "US", "securityType": "Common Stock"},
    ]
    assert svc._pick_figi_ticker(records) == "TE"


def test_pick_normalizes_class_share_slash():
    records = [{"ticker": "BRK/A", "exchCode": "US", "securityType": "Common Stock"}]
    assert svc._pick_figi_ticker(records) == "BRK-A"


def test_pick_returns_none_on_empty():
    assert svc._pick_figi_ticker([]) is None


def test_pick_drops_foreign_only_listings():
    # Bitfarms-Szenario: diese CUSIP hat bei OpenFIGI nur Frankfurt/Brazil-
    # Listings, kein US-Composite → droppen statt '1B2' (Foreign) zurueckgeben.
    records = [
        {"ticker": "1B2", "exchCode": "GR", "securityType": "Common Stock"},
        {"ticker": "1B2D", "exchCode": "B3", "securityType": "Common Stock"},
    ]
    assert svc._pick_figi_ticker(records) is None


# --- resolve_cusips (Cache-Logik) ------------------------------------------

class _FakeCache:
    """Minimaler dict-Cache, der die cache.get/set-Signatur nachbildet."""

    def __init__(self, initial: dict[str, str] | None = None):
        self.store: dict[str, str] = dict(initial or {})
        self.set_calls: list[tuple[str, str]] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value, ttl: int = 0):
        self.store[key] = value
        self.set_calls.append((key, value))


async def test_resolve_uses_cache_hits_without_calling_openfigi(monkeypatch):
    fake = _FakeCache({
        f"{svc._FIGI_CACHE_PREFIX}AAA": "NVDA",
        f"{svc._FIGI_CACHE_PREFIX}BBB": "",  # Negativ-Cache
    })
    monkeypatch.setattr(svc, "cache", fake)

    async def _boom(_cusips):
        raise AssertionError("OpenFIGI darf bei reinen Cache-Hits nicht aufgerufen werden")

    monkeypatch.setattr(svc, "_openfigi_lookup", _boom)

    out = await svc.resolve_cusips(["AAA", "BBB"])
    assert out == {"AAA": "NVDA"}  # Negativ-Cache (BBB) faellt raus


async def test_resolve_fetches_misses_and_writes_cache(monkeypatch):
    fake = _FakeCache()
    monkeypatch.setattr(svc, "cache", fake)

    async def _lookup(cusips):
        assert set(cusips) == {"CCC", "DDD"}
        return {"CCC": "ORCL"}  # DDD bleibt unaufloesbar

    monkeypatch.setattr(svc, "_openfigi_lookup", _lookup)

    out = await svc.resolve_cusips(["ccc", "DDD", "ccc"])  # dedup + uppercase
    assert out == {"CCC": "ORCL"}
    # Positiv- UND Negativ-Treffer werden gecached (DDD als "" gegen Re-Fetch).
    assert fake.store[f"{svc._FIGI_CACHE_PREFIX}CCC"] == "ORCL"
    assert fake.store[f"{svc._FIGI_CACHE_PREFIX}DDD"] == ""


async def test_resolve_ignores_blank_cusips(monkeypatch):
    fake = _FakeCache()
    monkeypatch.setattr(svc, "cache", fake)

    async def _lookup(cusips):
        raise AssertionError("keine echten CUSIPs → kein Lookup")

    monkeypatch.setattr(svc, "_openfigi_lookup", _lookup)

    out = await svc.resolve_cusips(["", None, "   "])
    assert out == {}
