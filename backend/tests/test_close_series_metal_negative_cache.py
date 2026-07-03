"""Analyse-Close-Series: Metall-Pseudo-Ticker + Negative-Caching (03.07.2026).

Prod-Log-Befund nach dem v0.53-Deploy: der Analyse-Pfad fragte XAUCHF=X
(bewusster Gold-Spot-Pseudo-Ticker, existiert bei Yahoo nicht) im Sekundentakt
an — pro Aufruf ein toter yf_download, kein Negative-Caching. Zahlen waren
korrekt (Bewertung läuft über Gold.org/Futures), aber Yahoo-Budget + Rauschen.
"""
from __future__ import annotations

import pandas as pd
import pytest

import services.utils as utils


class _DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


@pytest.fixture()
def dict_cache(monkeypatch):
    c = _DictCache()
    monkeypatch.setattr(utils, "cache", c)
    return c


def _boom_download(*a, **k):
    raise AssertionError("yf_download darf hier nicht aufgerufen werden")


def test_metal_spot_ticker_never_hits_yahoo(dict_cache, monkeypatch):
    monkeypatch.setattr(utils, "yf_download", _boom_download)
    for t in ("XAUCHF=X", "XAGCHF=X", "XPTCHF=X", "XPDCHF=X"):
        assert utils._get_close_series(t, "2y") is None


def test_prefetch_filters_metal_spot_tickers(dict_cache, monkeypatch):
    monkeypatch.setattr(utils, "yf_download", _boom_download)
    utils.prefetch_close_series(["XAUCHF=X"])  # darf nicht downloaden/crashen


def test_total_failure_negative_cached(dict_cache, monkeypatch):
    calls: list[str] = []

    def _empty_download(ticker, *a, **k):
        calls.append(ticker)
        return pd.DataFrame()

    monkeypatch.setattr(utils, "yf_download", _empty_download)
    import services.cache_service as cs
    monkeypatch.setattr(cs, "get_close_series_from_db", lambda t, p: None)

    assert utils._get_close_series("DEADTICKER", "2y") is None
    assert calls == ["DEADTICKER"]
    # Zweiter Aufruf: Sentinel greift, KEIN erneuter Download
    assert utils._get_close_series("DEADTICKER", "2y") is None
    assert calls == ["DEADTICKER"]
    assert dict_cache.store.get("close:DEADTICKER:2y") == utils._CLOSE_NEG_SENTINEL


def test_sentinel_does_not_break_prefetch_derive(dict_cache, monkeypatch):
    monkeypatch.setattr(utils, "yf_download", _boom_download)
    dict_cache.store["close:DEADTICKER:2y"] = utils._CLOSE_NEG_SENTINEL
    # 2y "gecacht" (Sentinel) → kein Download; 1y-Ableitung darf nicht auf
    # dem String crashen und nichts Falsches schreiben.
    utils.prefetch_close_series(["DEADTICKER"])
    assert dict_cache.store.get("close:DEADTICKER:1y") is None


def test_successful_series_still_cached_normally(dict_cache, monkeypatch):
    idx = pd.date_range("2026-01-01", periods=30, freq="D")

    def _ok_download(ticker, *a, **k):
        return pd.DataFrame({"Close": range(30)}, index=idx)

    monkeypatch.setattr(utils, "yf_download", _ok_download)
    series = utils._get_close_series("AAPL", "2y")
    assert series is not None and len(series) == 30
    # Cache-Hit liefert die Serie, keinen Sentinel
    again = utils._get_close_series("AAPL", "2y")
    assert again is not None and len(again) == 30
