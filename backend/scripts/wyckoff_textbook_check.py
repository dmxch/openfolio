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

import numpy as np

from services.analysis_config import (
    HEARTBEAT_ATR_HISTORY_DAYS,
    HEARTBEAT_ATR_PERCENTILE,
    HEARTBEAT_ATR_PERIOD,
)
from services.chart_service import _compute_atr, detect_heartbeat_pattern
from yf_patch import yf_download


def _percentile_of_score(history: np.ndarray, score: float) -> float:
    """Numpy-only Äquivalent zu scipy.stats.percentileofscore (kind='mean').

    Gibt den Prozentsatz der Werte in ``history`` zurück, die kleiner oder
    gleich ``score`` sind, mit der "mean"-Konvention: Mittel aus strict-less
    und less-or-equal. Vermeidet scipy-Dependency im backend-Container.
    """
    if history.size == 0:
        return float("nan")
    strict = float(np.sum(history < score)) / history.size
    weak = float(np.sum(history <= score)) / history.size
    return round(((strict + weak) / 2.0) * 100.0, 2)


def _atr_diagnosis(highs, lows, closes) -> dict:
    """Berechnet die ATR-Diagnose-Werte unabhängig vom Detector-Pfad.

    Spiegelt die interne Logik von ``detect_heartbeat_pattern`` (Schritt 1):
    ATR(period=14) über die letzten ``HEARTBEAT_ATR_HISTORY_DAYS`` Tage,
    Schwelle = Percentile-30 der History, atr_now = letzter ATR-Wert.

    Output funktioniert auch für Cases die NICHT an ``no_compression``
    scheitern (z.B. AAPL mit ``no_alternation``) — dort ist die Diagnose
    trotzdem aussagekräftig.
    """
    out: dict = {
        "atr_now": None,
        "atr_threshold": None,
        "atr_history_len": 0,
        "atr_now_percentile_rank": None,
        "atr_compression_ratio": None,
    }
    try:
        atr_series = _compute_atr(highs, lows, closes, period=HEARTBEAT_ATR_PERIOD).dropna()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"atr_compute_failed: {e}"
        return out

    if len(atr_series) < HEARTBEAT_ATR_HISTORY_DAYS:
        out["atr_history_len"] = int(len(atr_series))
        out["error"] = "atr_history_too_short"
        return out

    atr_history = atr_series.iloc[-HEARTBEAT_ATR_HISTORY_DAYS:]
    threshold = float(np.percentile(atr_history.values, HEARTBEAT_ATR_PERCENTILE))
    atr_now = float(atr_series.iloc[-1])
    rank = _percentile_of_score(atr_history.values, atr_now)
    out["atr_now"] = round(atr_now, 4)
    out["atr_threshold"] = round(threshold, 4)
    out["atr_history_len"] = int(len(atr_history))
    out["atr_now_percentile_rank"] = rank
    out["atr_compression_ratio"] = round(atr_now / threshold, 3) if threshold > 0 else None
    return out


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


# --- v0.30 Phase 1.5: Range-Mitte-Pin-Sweep -------------------------------
#
# Hintergrund: Phase-1-Diagnose mass den ATR-Now am Fenster-Ende (z.B.
# 2016-07-01 für AMD, 2016-04-01 für AAPL). Das könnte ein Slice-Artefakt
# sein — am Fenster-Ende ist der August-2015-Crash bei AMD/NVDA bereits
# Geschichte, das Skript misst Post-Crash-Beruhigung statt Akkumulations-
# Ruhe. Bei AAPL liegt das Fenster-Ende nach dem August-2015-Crash mit
# anschliessender Beruhigung — das erklärt den absurden Percentile-Wert
# von 5.0 für eine Distribution.
#
# Pin-Mode: ATR-Now wird an einem **mid-range-Tag** geprüft, mitten in der
# vermuteten Akkumulations-/Distributions-Phase. Wenn der Bias real ist,
# kippen die Werte drastisch (Akku-Cases fallen, AAPL steigt). Wenn die
# Werte ähnlich bleiben, ist die ATR-Percentile-Achse strukturell
# unbrauchbar als Discriminator.
#
# 200d Vorlauf statt 180d, weil ATR(14) vor dem 90d-History-Lookback
# einen Vorlauf braucht — sonst wird die History-Stichprobe knapp.

CASES_PIN: list[dict] = [
    {
        "name": "AMD 2015 (Pin: 2016-03-01, Mitte $1.80-2.00 Range)",
        "ticker": "AMD",
        "pin_date": "2016-03-01",
        "expected_score": 1,
        "rationale": "Mitten in der $1.80-2.00 Akkumulations-Range, vor Mai-Breakout.",
    },
    {
        "name": "NVDA 2020 (Pin: 2020-05-15, Mitte März-Juli Range)",
        "ticker": "NVDA",
        "pin_date": "2020-05-15",
        "expected_score": 1,
        "rationale": "Mitten in der März-Juli Re-Akkumulations-Range, vor Juli-Breakout.",
    },
    {
        "name": "NFLX 2018 (Pin: 2018-08-15, mid-Topping)",
        "ticker": "NFLX",
        "pin_date": "2018-08-15",
        "expected_score": -1,
        "rationale": "Mitten in der Topping-Phase vor 2018-Q4-Drawdown.",
    },
    {
        "name": "SPY 2007 (Pin: 2007-08-15, mid-Topping)",
        "ticker": "SPY",
        "pin_date": "2007-08-15",
        "expected_score": -1,
        "rationale": "Mid-Topping vor Finanzkrise, mitten in der Distributions-Range.",
    },
    {
        "name": "AAPL 2015 (Pin: 2015-06-01, Topping vor August-Crash)",
        "ticker": "AAPL",
        "pin_date": "2015-06-01",
        "expected_score": -1,
        "rationale": "Topping-Phase, vor August-2015-Crash — mid-Distribution.",
    },
]


def _pin_window_start(pin_date: str, lookback_days: int = 200) -> str:
    """Berechnet das Start-Datum für den Pin-Mode-Daten-Pull.

    200d Vorlauf vor dem pin_date statt 180d, weil ATR(14) vor dem
    90d-History-Lookback Vorlauf braucht.
    """
    from datetime import datetime, timedelta

    pin = datetime.strptime(pin_date, "%Y-%m-%d")
    return (pin - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def run_pin_case(case: dict) -> dict:
    """Pin-Mode: lädt 200d vor pin_date bis pin_date, misst ATR am pin_date.

    Im Unterschied zu ``run_case`` wird der Heartbeat-Detector NICHT
    ausgeführt — die Pin-Diagnose interessiert sich ausschliesslich für die
    ATR-Percentile-Lage am Pin-Tag, um den Slice-Bias-Verdacht zu klären.
    """
    out: dict = {
        "name": case["name"],
        "ticker": case["ticker"],
        "pin_date": case["pin_date"],
        "expected_score": case["expected_score"],
        "rationale": case["rationale"],
    }
    start = _pin_window_start(case["pin_date"], lookback_days=200)
    out["start"] = start
    out["end"] = case["pin_date"]
    try:
        data = yf_download(
            case["ticker"], start=start, end=case["pin_date"], progress=False
        )
    except Exception as e:  # noqa: BLE001
        out["error"] = f"download_failed: {e}"
        return out

    if data is None or data.empty:
        out["error"] = "no_data"
        return out

    close = data["Close"].squeeze().dropna() if "Close" in data else None
    high = data["High"].squeeze().dropna() if "High" in data else None
    low = data["Low"].squeeze().dropna() if "Low" in data else None

    if close is None or len(close) < 60:
        out["error"] = "insufficient_history"
        out["bars"] = 0 if close is None else len(close)
        return out

    out["bars"] = int(len(close))

    if high is not None and low is not None:
        out["atr_diagnosis"] = _atr_diagnosis(high, low, close)
    else:
        out["atr_diagnosis"] = {"error": "no_ohlc"}

    return out


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

    # ATR-Diagnose (v0.30 Phase 1): unabhängig vom Detector-Pfad ausgeben,
    # auch wenn der Detector später an ``no_alternation`` o.ä. scheitert.
    if high is not None and low is not None:
        out["atr_diagnosis"] = _atr_diagnosis(high, low, close)
    else:
        out["atr_diagnosis"] = {"error": "no_ohlc"}

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

    # ATR-Diagnose-Tabelle Pass 3 (v0.30 Phase 1) — Window-End-Messung
    print("\n" + "=" * 70)
    print("Pass 3 — Window-End ATR (Phase 1) — Percentile-Rang am Fenster-Ende")
    print("=" * 70)
    print(
        f"{'Ticker':<8}{'Bars':<6}{'atr_now':<12}"
        f"{'atr_thr(p30)':<14}{'percentile':<12}{'reason':<24}"
    )
    for r in results:
        diag = r.get("atr_diagnosis") or {}
        ticker = r.get("ticker", "?")
        bars = r.get("bars", 0)
        atr_now = diag.get("atr_now")
        atr_thr = diag.get("atr_threshold")
        rank = diag.get("atr_now_percentile_rank")
        reason = r.get("reason") or diag.get("error") or "-"
        print(
            f"{ticker:<8}{bars:<6}"
            f"{(str(atr_now) if atr_now is not None else '-'):<12}"
            f"{(str(atr_thr) if atr_thr is not None else '-'):<14}"
            f"{(str(rank) if rank is not None else '-'):<12}"
            f"{str(reason):<24}"
        )

    # --- Pass 4: Range-Mitte-Pin-Sweep (v0.30 Phase 1.5) -----------------
    print("\n" + "=" * 70)
    print("Pass 4 — Range-Mitte-Pin-Sweep (v0.30 Phase 1.5)")
    print("=" * 70)
    print(
        "Misst ATR-Percentile an einem mid-range-Pin-Tag (statt am Fenster-"
        "Ende),\num den Slice-Bias-Verdacht aus Phase 1 zu klären."
    )
    pin_results: list[dict] = []
    for case in CASES_PIN:
        print(f"\n--- {case['name']} ({case['ticker']}) ---")
        r = run_pin_case(case)
        pin_results.append(r)
        print(json.dumps(r, indent=2, default=str))

    print("\n" + "=" * 70)
    print("Pin-Mode Summary — ATR-Diagnose am pin_date")
    print("=" * 70)
    print(
        f"{'Ticker':<8}{'pin_date':<14}{'Bars':<6}{'atr_now':<12}"
        f"{'atr_thr(p30)':<14}{'percentile':<12}{'note':<24}"
    )
    for r in pin_results:
        diag = r.get("atr_diagnosis") or {}
        ticker = r.get("ticker", "?")
        pin = r.get("pin_date", "?")
        bars = r.get("bars", 0)
        atr_now = diag.get("atr_now")
        atr_thr = diag.get("atr_threshold")
        rank = diag.get("atr_now_percentile_rank")
        note = r.get("error") or diag.get("error") or "-"
        print(
            f"{ticker:<8}{pin:<14}{bars:<6}"
            f"{(str(atr_now) if atr_now is not None else '-'):<12}"
            f"{(str(atr_thr) if atr_thr is not None else '-'):<14}"
            f"{(str(rank) if rank is not None else '-'):<12}"
            f"{str(note):<24}"
        )

    # Vergleich Window-End vs Pin (Delta pro Case)
    print("\n" + "=" * 70)
    print("Vergleich Window-End (Pass 3) vs Pin (Pass 4) — Delta-Tabelle")
    print("=" * 70)
    print(
        f"{'Ticker':<8}{'Pass3-Pctile':<14}{'Pass4-Pctile':<14}"
        f"{'Delta':<10}{'Expected':<10}"
    )
    pin_by_ticker = {r.get("ticker"): r for r in pin_results}
    for r in results:
        ticker = r.get("ticker", "?")
        p3_diag = r.get("atr_diagnosis") or {}
        p3_rank = p3_diag.get("atr_now_percentile_rank")
        p4 = pin_by_ticker.get(ticker) or {}
        p4_diag = p4.get("atr_diagnosis") or {}
        p4_rank = p4_diag.get("atr_now_percentile_rank")
        if p3_rank is not None and p4_rank is not None:
            delta = round(p4_rank - p3_rank, 2)
        else:
            delta = "-"
        expected = "+1" if r.get("expected_score") == 1 else "-1"
        print(
            f"{ticker:<8}"
            f"{(str(p3_rank) if p3_rank is not None else '-'):<14}"
            f"{(str(p4_rank) if p4_rank is not None else '-'):<14}"
            f"{str(delta):<10}{expected:<10}"
        )


if __name__ == "__main__":
    main()
