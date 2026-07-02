"""Regressionstests Review 2026-07-02, Batch A (Dividenden/FX).

- C1: Dividenden-Cache ist per-share — shares des ersten Aufrufers dürfen
  nie das Resultat späterer Aufrufer (anderer User, andere Stückzahl) prägen.
- H3: Pence-Quotes (GBp/GBX) werden auf GBP normalisiert (÷100).
- H2/M26: get_fx_rate löst unbekannte Währungen auf statt still 1.0;
  get_fallback_fx läuft nur noch bei Batch-Miss.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

import services.dividend_service as ds
import services.utils as utils


class _DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


def _fake_yf_attr(dividends: pd.Series, currency: str):
    def _attr(ticker, attr):
        if attr == "dividends":
            return dividends
        if attr == "fast_info":
            return SimpleNamespace(currency=currency)
        raise AssertionError(f"unexpected attr {attr}")
    return _attr


def test_c1_dividend_cache_is_share_independent(monkeypatch):
    today = date.today()
    divs = pd.Series([2.0], index=[pd.Timestamp(today - timedelta(days=30))])
    cache = _DictCache()
    monkeypatch.setattr(ds, "cache", cache)
    monkeypatch.setattr(ds, "yf_ticker_attr", _fake_yf_attr(divs, "USD"))
    monkeypatch.setattr(ds, "get_fx_rate", lambda c, t="CHF": 0.9)

    since = today - timedelta(days=365)
    first = ds.fetch_dividends("VT", since, shares=10.0)
    assert first[0]["total_chf"] == pytest.approx(10 * 2.0 * 0.9)
    assert first[0]["shares_held"] == 10.0

    # Zweiter Aufrufer (anderer User, 50× mehr Anteile) trifft den Cache —
    # und muss trotzdem SEINE Stückzahl gerechnet bekommen.
    monkeypatch.setattr(
        ds, "yf_ticker_attr",
        lambda *a: (_ for _ in ()).throw(AssertionError("cache miss — yf called")),
    )
    second = ds.fetch_dividends("VT", since, shares=500.0)
    assert second[0]["total_chf"] == pytest.approx(500 * 2.0 * 0.9)
    assert second[0]["shares_held"] == 500.0

    # Der Cache-Inhalt selbst ist stückzahlfrei.
    cached_rows = next(iter(cache.store.values()))
    for row in cached_rows:
        assert "shares_held" not in row
        assert "total_chf" not in row


def test_h3_pence_quotes_normalized(monkeypatch):
    monkeypatch.setattr(
        ds, "yf_ticker_attr",
        _fake_yf_attr(pd.Series(dtype=float), "GBp"),
    )
    ccy, divisor = ds.resolve_dividend_currency("SWDA.L", "GBP")
    assert ccy == "GBP"
    assert divisor == 100.0

    monkeypatch.setattr(
        ds, "yf_ticker_attr",
        _fake_yf_attr(pd.Series(dtype=float), "USD"),
    )
    ccy, divisor = ds.resolve_dividend_currency("EIMI.L", "GBP")
    assert ccy == "USD"
    assert divisor == 1.0


def test_h2_unknown_currency_resolved_not_one(monkeypatch):
    monkeypatch.setattr(utils, "get_fx_rates_batch", lambda: {"CHF": 1.0, "USD": 0.88})
    monkeypatch.setattr(utils, "get_fallback_fx", lambda: {})
    monkeypatch.setattr(utils, "_resolve_extended_fx", lambda ccy: 0.085)
    assert utils.get_fx_rate("SEK", "CHF") == pytest.approx(0.085)


def test_h2_unresolvable_falls_back_to_one(monkeypatch):
    monkeypatch.setattr(utils, "get_fx_rates_batch", lambda: {"CHF": 1.0})
    monkeypatch.setattr(utils, "get_fallback_fx", lambda: {})
    monkeypatch.setattr(utils, "_resolve_extended_fx", lambda ccy: None)
    assert utils.get_fx_rate("XXX", "CHF") == 1.0


def test_m26_fallback_not_queried_on_batch_hit(monkeypatch):
    def _boom():
        raise AssertionError("get_fallback_fx darf bei Batch-Hit nicht laufen")

    monkeypatch.setattr(utils, "get_fx_rates_batch", lambda: {"CHF": 1.0, "USD": 0.88})
    monkeypatch.setattr(utils, "get_fallback_fx", _boom)
    assert utils.get_fx_rate("USD", "CHF") == pytest.approx(0.88)
