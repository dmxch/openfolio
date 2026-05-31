"""Kandidaten-Mappings fuer den Score-Formel-Swap (Iteration 2.5).

Pure-Functions, KEINE Wire-Up in die Hot-Path-Pipeline. Aufgerufen vom
Backtest-Harness (`scripts/backtest_score_mappings.py`, Item E) und nach
Item-F-Decision potenziell vom `screening_service.compute_display_score`.

Item-C-Diagnose 2026-05-29 hat gezeigt: heutige `linear` produziert eine
stark rechts-schiefe Display-Verteilung (96.4 % der Rows in Tertil 0-33,
0 Rows ueber Display 67). Die Alternativen unten spreizen die untere
Population in die oberen Buckets.

Signatur-Konvention: `(raw: int, ctx: dict | None = None) -> int`.
- `linear` ignoriert ctx.
- `log10_stretched` ignoriert ctx (deterministische Funktion).
- `percentile` / `hybrid` brauchen ctx mit 'cdf' bzw. 'upper_cdf' Keys
  (siehe `score_mapping_context.build_percentile_ctx`).

Alle Mappings garantieren Output in [0, 100].
"""
from __future__ import annotations

import math


def linear(raw: int, ctx: dict | None = None) -> int:
    """Baseline (heute live): raw * 10, geclampt auf [0, 100]."""
    return max(0, min(100, raw * 10))


def log10_stretched(raw: int, ctx: dict | None = None) -> int:
    """log10(raw+1) / log10(11) * 100. Spreizung der unteren Bänder.

    log10(1)=0 → display 0, log10(11)=log10(11) → display 100.
    raw=3 wird auf ~58 abgebildet (vs. linear=30) — der dichteste
    Raw-Bucket wandert nach oben.
    """
    if raw <= 0:
        return 0
    if raw >= 10:
        return 100
    return int(round(100 * math.log10(raw + 1) / math.log10(11)))


def percentile(raw: int, ctx: dict | None = None) -> int:
    """Empirische CDF aus den letzten N Tagen Composite-Scans.

    ctx['cdf'] ist eine aufsteigend nach raw_score sortierte Liste
    `[(raw_score, percentile_0_100), ...]` mit kumulativen Perzentilen.
    Der zurueckgegebene Wert ist der Perzentil-Rang der Eingabe-raw in
    der Population.

    Edge-Cases:
    - leere CDF → 0 (kein Signal-Hintergrund vorhanden)
    - raw ≤ 0 → 0
    - raw oberhalb des hoechsten CDF-Buckets → 100
    """
    if raw <= 0:
        return 0
    cdf = (ctx or {}).get("cdf") or []
    if not cdf:
        return 0
    for r, p in cdf:
        if raw <= r:
            return int(p)
    return 100


def hybrid(raw: int, ctx: dict | None = None) -> int:
    """Linear unten (raw 0..3 → display 0/10/20/30) + Perzentil oben.

    Begruendung: 96.4 % der Rows liegen in raw 1..3; dort gibt linear
    eine intuitive Skala. Ab raw=4 (Decision-Layer, ~3.5 % der Rows)
    spreizen wir auf 40..100 via separater upper-CDF, damit das obere
    Drittel der Skala nicht leer bleibt.

    ctx['upper_cdf'] ist `[(raw_score, display_in_40_to_100), ...]`,
    aufsteigend sortiert.
    """
    if raw <= 0:
        return 0
    if raw <= 3:
        return raw * 10
    upper_cdf = (ctx or {}).get("upper_cdf") or []
    if not upper_cdf:
        return 40
    for r, p in upper_cdf:
        if raw <= r:
            return max(40, min(100, int(p)))
    return 100


MAPPINGS = {
    "linear": linear,
    "log10_stretched": log10_stretched,
    "percentile": percentile,
    "hybrid": hybrid,
}
