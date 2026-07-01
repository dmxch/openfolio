"""External-API-Paritaet: jede neue Analyse-Sicht muss unter /api/v1/external/analysis/*
exakt dasselbe liefern wie der interne /api/analysis/*-Endpoint (read-Scope).

Stehende Regel: alles muss per API erreichbar sein. Dieser Test faengt eine
fehlende externe Spiegelung (oder Shape-Divergenz) sofort.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TEST_PASSWORD = "TestPassw0rd!2026"

# Endpoints, die unter BEIDEN Praefixen identisch existieren muessen.
ANALYSIS_VIEWS = [
    "net-worth",
    "dividend-yoc",
    "dividend-forecast",
    "rebalancing",
    "position-rebalancing",
    "trade-journal",
    "country-lookthrough",
    "fire-projection",
    "fire-assumptions",
    "signal-backtest-history",
]


async def _setup(client: AsyncClient, email: str):
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    jwt = (await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})).json()["access_token"]
    tok_res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "r", "write_access": False},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert tok_res.status_code == 201, tok_res.text
    return jwt, tok_res.json()["token"]


@pytest.mark.parametrize("view", ANALYSIS_VIEWS)
async def test_external_analysis_parity(client, view):
    jwt, token = await _setup(client, f"parity-{view}@test.local")

    ext = await client.get(f"/api/v1/external/analysis/{view}", headers={"X-API-Key": token})
    assert ext.status_code == 200, f"external {view}: {ext.status_code} {ext.text}"

    intern = await client.get(f"/api/analysis/{view}", headers={"Authorization": f"Bearer {jwt}"})
    assert intern.status_code == 200, f"internal {view}: {intern.status_code} {intern.text}"

    assert ext.json() == intern.json(), f"Paritaet verletzt fuer {view}"


async def test_external_analysis_requires_token(client):
    """Ohne Token -> 401/403 (kein offener Zugang zu den Sichten)."""
    res = await client.get("/api/v1/external/analysis/net-worth")
    assert res.status_code in (401, 403)


async def _write_token(client: AsyncClient, email: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": TEST_PASSWORD})
    jwt = (await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})).json()["access_token"]
    tok_res = await client.post(
        "/api/settings/api-tokens",
        json={"name": "w", "write_access": True},
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert tok_res.status_code == 201, tok_res.text
    return tok_res.json()["token"]


async def test_external_dividend_forecast_refresh_requires_write(client):
    """POST /dividend-forecast/refresh ist write-gated; read-Token -> 403."""
    _, read_token = await _setup(client, "fc-refresh-read@test.local")
    res = await client.post(
        "/api/v1/external/analysis/dividend-forecast/refresh",
        headers={"X-API-Key": read_token},
    )
    assert res.status_code == 403, res.text


async def test_external_dividend_forecast_refresh_write_ok(client):
    """Write-Token -> 200; leerer User loest keinen yfinance-Call aus (keine Holdings)."""
    write_token = await _write_token(client, "fc-refresh-write@test.local")
    res = await client.post(
        "/api/v1/external/analysis/dividend-forecast/refresh",
        headers={"X-API-Key": write_token},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("has_data") is True
    assert body.get("forecast_12m_chf") == 0


async def test_external_risk_metrics_parity(client, monkeypatch):
    """risk-metrics: interner /api/portfolio/risk-metrics == externer
    /api/v1/external/performance/risk-metrics fuer dasselbe Fenster.

    Eigener Fall (nicht in ANALYSIS_VIEWS): Pfad-Asymmetrie
    (portfolio<->performance) + Param-Asymmetrie (start/end <-> period). Der
    Service wird gemockt -> deterministische Body-Paritaet unabhaengig von
    Test-Daten; zusaetzlich wird geprueft, dass das interne Default-Fenster dem
    externen 'period=5y' entspricht (beide today-1825d..today).
    """
    sentinel = {
        "n_obs": 123,
        "annualized_return_pct": 4.2,
        "volatility_pct": 11.0,
        "downside_volatility_pct": 7.5,
        "max_drawdown_pct": 18.0,
        "sharpe_ratio": 0.38,
        "sortino_ratio": 0.5,
        "calmar_ratio": 0.23,
        "information_ratio": -0.1,
        "benchmark": "^GSPC",
        "benchmark_annualized_return_pct": 9.0,
        "rolling_returns": {"1m": 1.0, "3m": -2.0, "6m": 0.5, "1y": -7.0},
        "risk_free_rate_pct": 0.0,
    }
    calls = []

    async def fake_compute(db, start, end, benchmark="^GSPC", user_id=None, bucket_id=None):
        calls.append((start, end))
        return dict(sentinel)

    # Beide Endpoints importieren compute_risk_metrics zur Laufzeit aus dem Modul
    # -> ein Patch am Modul-Attribut greift fuer intern UND extern.
    monkeypatch.setattr("services.risk_metrics_service.compute_risk_metrics", fake_compute)

    jwt, token = await _setup(client, "parity-risk-metrics@test.local")

    # extern: period=5y -> Fenster (today-1825d, today)
    ext = await client.get(
        "/api/v1/external/performance/risk-metrics?period=5y",
        headers={"X-API-Key": token},
    )
    assert ext.status_code == 200, f"external risk-metrics: {ext.status_code} {ext.text}"

    # intern: ohne start/end -> Default-Fenster (today-5*365d, today)
    intern = await client.get(
        "/api/portfolio/risk-metrics",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert intern.status_code == 200, f"internal risk-metrics: {intern.status_code} {intern.text}"

    assert ext.json() == intern.json(), "Risk-Metrics-Paritaet (intern==extern) verletzt"
    assert calls[0] == calls[1], f"Fenster-Asymmetrie: extern {calls[0]} != intern {calls[1]}"


async def test_external_levels_parity_and_params(client, monkeypatch):
    """/analysis/levels/{ticker}: intern == extern, und beide reichen dieselben
    validierten Query-Params (lookback/pivot_k/below_only) an den geteilten
    Service. Eigener Fall (ticker-Pfad-Param, nicht in ANALYSIS_VIEWS) — Service
    gemockt -> deterministische Body-Paritaet ohne yfinance-Call.
    """
    sentinel = {
        "ticker": "AAPL", "as_of": "2026-06-30T00:00:00Z", "current_price": 100.0,
        "atr_22": 2.0, "atr_pct": 2.0, "highest_high_22": 110.0, "lowest_low_22": 90.0,
        "high_52w": 120.0, "low_52w": 80.0, "swing_lows": [], "swing_highs": [],
        "gap_bases": [], "resistance": 120.0, "support": 80.0,
        "resistance_historical": [], "support_historical": [],
    }
    calls = []

    def fake_levels(ticker, lookback=90, pivot_k=2, below_only=False):
        calls.append((ticker, lookback, pivot_k, below_only))
        return dict(sentinel)

    # Beide Endpoints importieren get_support_resistance_levels zur Laufzeit
    # -> ein Patch am Modul-Attribut greift fuer intern UND extern.
    monkeypatch.setattr("services.chart_service.get_support_resistance_levels", fake_levels)

    jwt, token = await _setup(client, "parity-levels@test.local")
    q = "?lookback=120&pivot_k=3&below_only=true"

    ext = await client.get(f"/api/v1/external/analysis/levels/AAPL{q}", headers={"X-API-Key": token})
    assert ext.status_code == 200, f"external levels: {ext.status_code} {ext.text}"

    intern = await client.get(f"/api/analysis/levels/AAPL{q}", headers={"Authorization": f"Bearer {jwt}"})
    assert intern.status_code == 200, f"internal levels: {intern.status_code} {intern.text}"

    assert ext.json() == intern.json() == sentinel, "Levels-Paritaet (intern==extern) verletzt"
    # beide reichen ticker-upper + dieselben validierten Params an den geteilten Service
    assert calls == [("AAPL", 120, 3, True), ("AAPL", 120, 3, True)], calls
