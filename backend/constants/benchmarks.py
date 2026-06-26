"""Allowlist erlaubter Benchmark-Ticker.

Wird sowohl von `api/performance.py` (`GET /benchmark-returns`) als auch von
Bucket-Pfaden (PATCH /buckets/{id}, GET /buckets/{id}/benchmark-comparison)
verwendet, damit der vom User in `bucket.benchmark` gespeicherte Wert nicht
ungeprueft an yfinance gereicht wird.

Wer einen neuen Ticker hinzufuegt:
  1. Diese Allowlist erweitern.
  2. `services/benchmark_service.py` (names-Dict) ergaenzen.
  3. `frontend/src/pages/settings/BucketsTab.jsx` (BENCHMARK_OPTIONS) ergaenzen.
"""
from __future__ import annotations

ALLOWED_BENCHMARKS: frozenset[str] = frozenset({
    "^GSPC",      # S&P 500
    "^IXIC",      # NASDAQ Composite
    "^STOXX50E",  # Euro Stoxx 50
    "^SSMI",      # SMI
    "URTH",       # MSCI World ETF (iShares)
    "MTUM",       # iShares MSCI USA Momentum Factor ETF — stil-korrekter Massstab fuer Momentum-/Breakout-Buckets (Satellite)
})
