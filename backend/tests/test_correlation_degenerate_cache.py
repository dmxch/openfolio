"""Degenerate-Guard fuer den Korrelations-Matrix-Cache (Vorfall 01.07.2026).

Transiente Yahoo-Rate-Limits liessen 7/14 Ticker aus der Matrix fallen; das
degenerierte Resultat wurde 24h gecacht (UI + externe API teilen den Key).
Neu: Resultate mit no_price_data-Warnings werden nur 60s gecacht — der
naechste Compute heilt sich selbst (gleiches Muster wie Broken-Score, M15).
"""
from __future__ import annotations

from services.correlation_service import (
    CACHE_TTL,
    DEGENERATE_CACHE_TTL,
    result_cache_ttl,
)


def test_clean_result_cached_long():
    data = {"warnings": [], "matrix": [[1.0]], "tickers": [{"yf_ticker": "AAPL"}]}
    assert result_cache_ttl(data) == CACHE_TTL


def test_missing_warnings_key_cached_long():
    assert result_cache_ttl({}) == CACHE_TTL


def test_no_price_data_warning_cached_short():
    data = {"warnings": ["no_price_data:NOVN.SW", "insufficient_data:ABC"]}
    assert result_cache_ttl(data) == DEGENERATE_CACHE_TTL
    assert DEGENERATE_CACHE_TTL == 60


def test_insufficient_data_alone_not_degenerate():
    # insufficient_data kann strukturell sein (junges Listing) — ein dauerhaft
    # kurzes TTL wuerde dann pro Aufruf einen yfinance-Batch ausloesen.
    data = {"warnings": ["insufficient_data:NEWIPO"]}
    assert result_cache_ttl(data) == CACHE_TTL


async def test_endpoint_uses_degenerate_ttl(client, monkeypatch):
    """Der interne Endpoint muss das TTL aus result_cache_ttl verwenden."""
    import api.portfolio as portfolio_api

    degenerate = {
        "warnings": ["no_price_data:AAPL"],
        "matrix": [],
        "tickers": [],
    }

    async def _fake_compute(db, user_id, **kwargs):
        return degenerate

    set_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(portfolio_api, "compute_correlation_matrix", _fake_compute)
    monkeypatch.setattr(portfolio_api.app_cache, "get", lambda key: None)
    monkeypatch.setattr(
        portfolio_api.app_cache,
        "set",
        lambda key, value, ttl=None: set_calls.append((key, ttl)),
    )

    await client.post(
        "/api/auth/register",
        json={"email": "corrttl@test.local", "password": "Test-Passwort-42x!"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": "corrttl@test.local", "password": "Test-Passwort-42x!"},
    )
    token = login.json()["access_token"]

    res = await client.get(
        "/api/portfolio/correlation-matrix",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["warnings"] == ["no_price_data:AAPL"]
    # Genau der Korrelations-Key mit kurzem TTL; andere set-Aufrufe
    # (z.B. portfolio_summary aus dem Login-Flow) ignorieren.
    corr_calls = [(k, t) for k, t in set_calls if "correlation" in k]
    assert len(corr_calls) == 1
    assert corr_calls[0][1] == DEGENERATE_CACHE_TTL
