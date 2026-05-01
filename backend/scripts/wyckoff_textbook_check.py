"""Textbook-Ground-Truth-Sweep für Wyckoff-Volumen-Profil (v0.29.1).

Zieht historische OHLCV via ``yf_download(start, end)`` für dokumentierte
Wyckoff-Cases (Akkumulationen + Distributionen) und prüft, ob der
Heartbeat-Detector + Wyckoff-Sub-Layer sie wie erwartet klassifiziert.

Standalone-Skript, KEIN Pytest-Test (yfinance gegen Live-API ist zu flaky
für CI). Output: JSON-Dump pro Case auf stdout — wird von Hand in
``WYCKOFF_TEXTBOOK_RESULTS.md`` als Falsifikations-Dokument abgelegt.

Aufruf (via docker compose):
  docker compose exec backend python scripts/wyckoff_textbook_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Skript läuft aus /app im Container — Backend-Source liegt direkt da
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.chart_service import detect_heartbeat_pattern
from yf_patch import yf_download


CASES: list[dict] = [
    {
        "name": "AMD 2015-Q3 -- 2016-Q2",
        "ticker": "AMD",
        "start": "2015-08-01",
        "end": "2016-07-01",
        "expected_score": 1,
        "rationale": "Klassische Textbook-Akkumulation vor 10x-Rallye (erweitertes 11-Monats-Fenster).",
    },
    {
        "name": "NVDA 2020-Q2 -- 2020-Q3 (post-COVID Re-Akkumulation)",
        "ticker": "NVDA",
        "start": "2020-04-01",
        "end": "2020-09-30",
        "expected_score": 1,
        "rationale": "Selling-Climax + Spring + Re-Akkumulation (erweitert bis September 2020).",
    },
    {
        "name": "NFLX 2018-Q2 -- 2018-Q4 (Distribution)",
        "ticker": "NFLX",
        "start": "2018-06-01",
        "end": "2018-12-31",
        "expected_score": -1,
        "rationale": "Distribution mit steigendem Volumen vor 2019-Down-Move.",
    },
    {
        "name": "SPY 2007-Q2 -- 2008-Q1 (Distributions-Backup)",
        "ticker": "SPY",
        "start": "2007-04-01",
        "end": "2008-03-31",
        "expected_score": -1,
        "rationale": "Top-Range vor Finanzkrise (erweitertes Fenster für ATR-Percentile-Stabilität).",
    },
    {
        "name": "AAPL 2015-Q2 -- 2016-Q1 (Distributions-Backup)",
        "ticker": "AAPL",
        "start": "2015-04-01",
        "end": "2016-04-01",
        "expected_score": -1,
        "rationale": "Top-Range mit hochkommendem Volumen vor 2016-Drawdown (erweitert auf 12 Monate).",
    },
]


def run_case(case: dict) -> dict:
    """Lade OHLCV für einen Case und führe den Detector aus."""
    out: dict = {
        "name": case["name"],
        "ticker": case["ticker"],
        "start": case["start"],
        "end": case["end"],
        "expected_score": case["expected_score"],
        "rationale": case["rationale"],
    }
    try:
        data = yf_download(case["ticker"], start=case["start"], end=case["end"], progress=False)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"download_failed: {e}"
        return out

    if data is None or data.empty:
        out["error"] = "no_data"
        return out

    close = data["Close"].squeeze().dropna() if "Close" in data else None
    high = data["High"].squeeze().dropna() if "High" in data else None
    low = data["Low"].squeeze().dropna() if "Low" in data else None
    volume = data["Volume"].squeeze().dropna() if "Volume" in data else None

    if close is None or len(close) < 60:
        out["error"] = "insufficient_history"
        out["bars"] = 0 if close is None else len(close)
        return out

    out["bars"] = int(len(close))

    result = detect_heartbeat_pattern(close, high, low, volumes=volume)
    out["detected"] = bool(result.get("detected"))
    out["reason"] = result.get("reason")

    if result.get("detected"):
        out["range_pct"] = result.get("range_pct")
        out["duration_days"] = result.get("duration_days")
        out["resistance_level"] = result.get("resistance_level")
        out["support_level"] = result.get("support_level")
        wy = result.get("wyckoff") or {}
        out["wyckoff"] = {
            "score": wy.get("score"),
            "label": wy.get("label"),
            "volume_slope_pct_per_day": wy.get("volume_slope_pct_per_day"),
            "spring_detected": wy.get("spring_detected"),
            "spring_date": wy.get("spring_date"),
            "spring_volume_ratio": wy.get("spring_volume_ratio"),
            "reason": wy.get("reason"),
        }
        # Verdict: stimmt der Score mit Erwartung?
        actual_score = wy.get("score")
        out["matches_expectation"] = actual_score == case["expected_score"]
    else:
        out["wyckoff"] = None
        out["matches_expectation"] = False  # nicht detected zählt als Mismatch

    return out


def main() -> None:
    print("Wyckoff Textbook Ground-Truth Sweep")
    print("=" * 70)
    results: list[dict] = []
    for case in CASES:
        print(f"\n--- {case['name']} ({case['ticker']}) ---")
        r = run_case(case)
        results.append(r)
        print(json.dumps(r, indent=2, default=str))

    # Compact summary table at the end
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"{'Case':<55}{'Detected':<10}{'Score':<8}{'Match':<6}")
    for r in results:
        detected = r.get("detected", False)
        score = (r.get("wyckoff") or {}).get("score") if detected else "-"
        match = "YES" if r.get("matches_expectation") else "NO"
        print(f"{r['name'][:54]:<55}{str(detected):<10}{str(score):<8}{match:<6}")


if __name__ == "__main__":
    main()
