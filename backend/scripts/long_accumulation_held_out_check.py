"""Held-Out + Negativ-Set Validation für Long-Accumulation-Detector (v0.30 Phase 3).

Style analog zu ``wyckoff_textbook_check.py``: Pull historischer OHLCV via
``yf_download(start, end)``, Detector-Aufruf, JSON-Output. KEIN Pytest-Test
(yfinance gegen Live-API zu flaky für CI).

Validiert ``detect_long_accumulation_pattern`` auf zwei separaten Sets:

- **Recall-Set (3 Cases)**: textbook-Akkumulationen, Detector soll feuern
  mit ``wyckoff.score == +1`` (MCD 2003, INTC 2009, MSFT 2013).
- **Negativ-Set (9 Cases)**: Trend- und Topping-Slices, Detector soll
  NICHT feuern. Inkl. AAPL-2015-Smooth-Top als wertvollster Edge-Case
  (Pin-Rank 13 würde unter Schwelle 50 fallen, geometrisch fast wie
  Akkumulation).

**Ship-Bedingung**: Recall ≥1/3 UND Precision ≤2/9 false-positives.
Bei Precision >2/9 → BAIL-OUT (kein Re-Tuning gegen das Negativ-Set,
Plan-Disziplin), zurück zu Phase 1 oder Discriminator-Erweiterung in v0.30.x.

Aufruf (via docker compose):
  docker compose exec backend python scripts/long_accumulation_held_out_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Skript läuft aus /app im Container — Backend-Source liegt direkt da
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.analysis_config import (
    LONG_ACCUMULATION_ATR_HISTORY_DAYS,
    LONG_ACCUMULATION_ATR_PERCENTILE,
    LONG_ACCUMULATION_ATR_PERIOD,
    LONG_ACCUMULATION_ATR_RANK_WINDOW,
    LONG_ACCUMULATION_LOOKBACK_DAYS,
    LONG_ACCUMULATION_MIN_DURATION_DAYS,
    LONG_ACCUMULATION_MIN_HIGH_TOUCHES,
    LONG_ACCUMULATION_MIN_LOW_TOUCHES,
    LONG_ACCUMULATION_MIN_RANGE_PCT,
    LONG_ACCUMULATION_RANGE_TOLERANCE,
    LONG_ACCUMULATION_SWING_LOOKBACK,
)
from services.chart_service import detect_long_accumulation_pattern
from yf_patch import yf_download

# Detector-Version inline gepinnt (v0.30 BAIL-OUT-Snapshot). Die Konstante
# wurde in v0.30.0 aus analysis_config entfernt (Cleanup-Release), bleibt
# hier aber als Baseline-Marker im Held-Out-Output erhalten.
LONG_ACCUMULATION_DETECTOR_VERSION: str = "1.0-bailout"


# --- Recall-Set (3 textbook-Akkumulationen) -----------------------------
# Erwartung: detected=True UND wyckoff.score == +1
RECALL_CASES: list[dict] = [
    {
        "name": "MCD 2003 (Bottom + Akkumulation vor Launch)",
        "ticker": "MCD",
        "start": "2003-01-01",
        "end": "2003-09-30",
        "set": "recall",
        "expected_detected": True,
        "expected_score": 1,
        "rationale": "Bottom ~$13 im Maerz, Range $13-15 Maerz-Juli, Launch zu $25+ bis Jahresende.",
    },
    {
        "name": "INTC 2009 (Post-Crisis-Akkumulation vor 2x-Rallye)",
        "ticker": "INTC",
        "start": "2009-01-01",
        "end": "2009-07-31",
        "set": "recall",
        "expected_detected": True,
        "expected_score": 1,
        "rationale": "Post-Finanzkrise-Akkumulation vor anschliessender 2x-Rallye.",
    },
    {
        "name": "MSFT 2013 (Nadella-Pre-Rally-Range)",
        "ticker": "MSFT",
        "start": "2013-01-01",
        "end": "2013-06-30",
        "set": "recall",
        "expected_detected": True,
        "expected_score": 1,
        "rationale": "Nadella-Pre-Rally-Range (Bekanntgabe Februar 2014, Pre-Rally-Range zieht sich).",
    },
]


# --- Reserve-Cases (NUR bei DB-seitigem Daten-Bruch eines Recall-Cases) -
# Negativ-Set hat KEINE Backups — Daten-Bruch dort wird als
# "data_unavailable" markiert und NICHT in die Precision-Bilanz mitgezaehlt.
RESERVE_CASES: list[dict] = [
    {
        "name": "ORCL 2002-2003 (Post-Dotcom-Akkumulation)",
        "ticker": "ORCL",
        "start": "2002-10-01",
        "end": "2003-03-31",
        "set": "recall",
        "expected_detected": True,
        "expected_score": 1,
        "rationale": "Reserve. Post-Dotcom-Akkumulation.",
    },
    {
        "name": "CSCO 2002 (Post-Dotcom-Akkumulation)",
        "ticker": "CSCO",
        "start": "2002-07-01",
        "end": "2002-12-31",
        "set": "recall",
        "expected_detected": True,
        "expected_score": 1,
        "rationale": "Reserve. Post-Dotcom-Akkumulation.",
    },
]


# --- Negativ-Set (9 Cases, Detector soll NICHT feuern) ------------------
# AAPL 2015 Smooth-Top ist der wertvollste Edge-Case: niedrige ATR (Pin-
# Rank 13 unter Schwelle 50), geometrisch faehnlich einer Akkumulation —
# wenn der Detector hier feuert, ist das Wissen ueber einen Blind Spot
# fuer v0.31.x (Pre-Range-Direction-Filter oder Wyckoff-Score-Co-Filter).
NEGATIVE_CASES: list[dict] = [
    {
        "name": "NVDA 2023 Q4 (Aufwaerts-Trend)",
        "ticker": "NVDA",
        "start": "2023-10-01",
        "end": "2024-01-31",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Klare Aufwaerts-Bewegung, keine Range.",
    },
    {
        "name": "TSLA 2022 H1 (Abwaerts)",
        "ticker": "TSLA",
        "start": "2022-01-01",
        "end": "2022-06-30",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Klare Abwaerts-Bewegung.",
    },
    {
        "name": "AMD 2022 Q3-Q4 (Abwaerts)",
        "ticker": "AMD",
        "start": "2022-07-01",
        "end": "2022-12-31",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Abwaerts-Bewegung.",
    },
    {
        "name": "META 2022 Q1-Q2 (Abwaerts)",
        "ticker": "META",
        "start": "2022-01-01",
        "end": "2022-06-30",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Abwaerts-Bewegung.",
    },
    {
        "name": "AAPL 2024 Q1 (Aufwaerts-Trend)",
        "ticker": "AAPL",
        "start": "2024-01-01",
        "end": "2024-04-30",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Aufwaerts-Trend.",
    },
    {
        "name": "ORCL 2024 Q2 (Aufwaerts-Trend)",
        "ticker": "ORCL",
        "start": "2024-04-01",
        "end": "2024-07-31",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Aufwaerts-Trend.",
    },
    {
        "name": "TSLA 2021 H2 Top (Topping, hohe ATR)",
        "ticker": "TSLA",
        "start": "2021-09-01",
        "end": "2022-01-31",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Topping (KEIN Blow-off-Run, Sep -> Jan), hohe ATR.",
    },
    {
        "name": "MSFT 2007 H2 Top (Top vor Finanzkrise, gemaessigt)",
        "ticker": "MSFT",
        "start": "2007-07-01",
        "end": "2007-12-31",
        "set": "negative",
        "expected_detected": False,
        "rationale": "Top vor Finanzkrise, gemaessigte ATR.",
    },
    {
        "name": "AAPL 2015 Smooth-Top (niedrige ATR, Edge-Case)",
        "ticker": "AAPL",
        "start": "2015-04-01",
        "end": "2015-08-31",
        "set": "negative",
        "expected_detected": False,
        "rationale": (
            "Smooth-Grinding-Topping mit niedriger ATR (Phase-1.5-Pin-Befund: "
            "ATR-Rank 12.78). Wertvollster Edge-Case: koennte unter Schwelle "
            "50 fallen, geometrisch fast wie Akkumulation."
        ),
    },
]


def _parameters_snapshot() -> dict:
    """Schwellen-Snapshot zum Detect-Zeitpunkt — Ground-Truth fuer das Logging."""
    return {
        "atr_percentile_threshold": LONG_ACCUMULATION_ATR_PERCENTILE,
        "min_duration_days": LONG_ACCUMULATION_MIN_DURATION_DAYS,
        "lookback_days": LONG_ACCUMULATION_LOOKBACK_DAYS,
        "min_high_touches": LONG_ACCUMULATION_MIN_HIGH_TOUCHES,
        "min_low_touches": LONG_ACCUMULATION_MIN_LOW_TOUCHES,
        "min_range_pct": LONG_ACCUMULATION_MIN_RANGE_PCT,
        "range_tolerance": LONG_ACCUMULATION_RANGE_TOLERANCE,
        "atr_rank_window": LONG_ACCUMULATION_ATR_RANK_WINDOW,
        "atr_period": LONG_ACCUMULATION_ATR_PERIOD,
        "atr_history_days": LONG_ACCUMULATION_ATR_HISTORY_DAYS,
        "swing_lookback": LONG_ACCUMULATION_SWING_LOOKBACK,
        "detector_version": LONG_ACCUMULATION_DETECTOR_VERSION,
    }


def run_case(case: dict) -> dict:
    """Lade OHLCV fuer einen Case und fuehre den Long-Accumulation-Detector aus."""
    out: dict = {
        "name": case["name"],
        "ticker": case["ticker"],
        "start": case["start"],
        "end": case["end"],
        "set": case["set"],
        "expected_detected": case["expected_detected"],
        "rationale": case["rationale"],
        "parameters": _parameters_snapshot(),
    }
    if "expected_score" in case:
        out["expected_score"] = case["expected_score"]

    try:
        data = yf_download(
            case["ticker"], start=case["start"], end=case["end"], progress=False,
        )
    except Exception as e:  # noqa: BLE001
        out["error"] = f"download_failed: {e}"
        out["data_unavailable"] = True
        return out

    if data is None or data.empty:
        out["error"] = "no_data"
        out["data_unavailable"] = True
        return out

    close = data["Close"].squeeze().dropna() if "Close" in data else None
    high = data["High"].squeeze().dropna() if "High" in data else None
    low = data["Low"].squeeze().dropna() if "Low" in data else None
    volume = data["Volume"].squeeze().dropna() if "Volume" in data else None

    if close is None or len(close) < 60:
        out["error"] = "insufficient_history"
        out["bars"] = 0 if close is None else int(len(close))
        out["data_unavailable"] = True
        return out

    out["bars"] = int(len(close))

    result = detect_long_accumulation_pattern(close, high, low, volumes=volume)
    out["detected"] = bool(result.get("detected"))
    out["reason"] = result.get("reason")
    out["atr_compression_metric"] = result.get("atr_compression_metric")
    out["atr_compression_ratio"] = result.get("atr_compression_ratio")

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
    else:
        out["wyckoff"] = None

    # matches_expectation:
    # - Recall: detected==True UND wyckoff.score == expected_score (+1)
    # - Negativ: detected==False
    if case["set"] == "recall":
        wy = out.get("wyckoff") or {}
        out["matches_expectation"] = bool(
            out["detected"] and wy.get("score") == case.get("expected_score"),
        )
    else:  # negative
        out["matches_expectation"] = not out["detected"]

    return out


def _print_recall_table(results: list[dict]) -> None:
    print("\n" + "=" * 100)
    print("Recall-Tabelle (3 textbook-Akkumulationen)")
    print("=" * 100)
    print(
        f"{'Ticker':<8}{'Bars':<6}{'Detected':<10}{'Reason':<22}"
        f"{'WyScore':<9}{'ATR-Median':<12}{'Match':<6}"
    )
    for r in results:
        ticker = r.get("ticker", "?")
        bars = r.get("bars", 0)
        detected = r.get("detected") if not r.get("data_unavailable") else "N/A"
        reason = r.get("reason") or r.get("error") or "-"
        wy = r.get("wyckoff") or {}
        score = wy.get("score") if r.get("detected") else "-"
        metric = r.get("atr_compression_metric")
        match = "YES" if r.get("matches_expectation") else "NO"
        print(
            f"{ticker:<8}{bars:<6}{str(detected):<10}{str(reason)[:21]:<22}"
            f"{str(score):<9}{(str(metric) if metric is not None else '-'):<12}"
            f"{match:<6}",
        )


def _print_negative_table(results: list[dict]) -> None:
    print("\n" + "=" * 100)
    print("Negativ-Tabelle (9 Trend-/Topping-Slices, Detector soll NICHT feuern)")
    print("=" * 100)
    print(
        f"{'Ticker':<8}{'Bars':<6}{'Detected':<10}{'Reason':<22}"
        f"{'WyScore':<9}{'ATR-Median':<12}{'Match':<6}"
    )
    for r in results:
        ticker = r.get("ticker", "?")
        bars = r.get("bars", 0)
        detected = r.get("detected") if not r.get("data_unavailable") else "N/A"
        reason = r.get("reason") or r.get("error") or "-"
        wy = r.get("wyckoff") or {}
        score = wy.get("score") if r.get("detected") else "-"
        metric = r.get("atr_compression_metric")
        match = "YES" if r.get("matches_expectation") else "NO"
        print(
            f"{ticker:<8}{bars:<6}{str(detected):<10}{str(reason)[:21]:<22}"
            f"{str(score):<9}{(str(metric) if metric is not None else '-'):<12}"
            f"{match:<6}",
        )


def _recall_score(results: list[dict]) -> tuple[int, int]:
    """Anzahl detected=True UND wyckoff.score=+1 / Anzahl ueberhaupt verfuegbar."""
    valid = [r for r in results if not r.get("data_unavailable")]
    hits = sum(1 for r in valid if r.get("matches_expectation"))
    return hits, len(valid)


def _precision_false_positives(results: list[dict]) -> tuple[int, int]:
    """Anzahl false-positives (detected=True bei expected_detected=False) /
    Anzahl ueberhaupt verfuegbar (data_unavailable wird ausgeklammert)."""
    valid = [r for r in results if not r.get("data_unavailable")]
    fps = sum(1 for r in valid if r.get("detected"))
    return fps, len(valid)


def _recall_vokabular(hits: int, total: int) -> str:
    if total == 0:
        return "Keine Recall-Cases verfuegbar (alle Daten-Pulls fehlgeschlagen)"
    if hits == 3:
        return "Recall-validiert (3/3)"
    if hits == 2:
        return "Recall mit dokumentierter Miss-Analyse (2/3)"
    if hits == 1:
        return "narrow detector (1/3)"
    return "Reichweite zu eng (0/3)"


def _precision_vokabular(fps: int, total: int) -> str:
    if total == 0:
        return "Keine Negativ-Cases verfuegbar"
    if fps <= 1:
        return f"Precision-validiert ({fps}/{total} false-positives)"
    if fps == 2:
        return f"Precision akzeptabel mit Edge-Case-Doku ({fps}/{total})"
    return f"Precision-Problem, BAIL-OUT zu Phase 1 ({fps}/{total})"


def main() -> None:
    print("Long-Accumulation Held-Out + Negativ-Set Validation (v0.30 Phase 3)")
    print("=" * 100)
    print(f"Detector-Version: {LONG_ACCUMULATION_DETECTOR_VERSION}")
    print(f"Schwellen-Snapshot: {json.dumps(_parameters_snapshot(), indent=2)}")

    # --- Recall-Set ---
    print("\n" + "#" * 100)
    print("# Recall-Set (3 Cases)")
    print("#" * 100)
    recall_results: list[dict] = []
    for case in RECALL_CASES:
        print(f"\n--- {case['name']} ({case['ticker']}) ---")
        r = run_case(case)
        # Falls Daten kaputt, versuche Reserve (NUR fuer Recall, NUR bei Daten-Bruch).
        if r.get("data_unavailable"):
            print(
                f"  Recall-Case Daten-Bruch ({r.get('error')}) — versuche Reserve."
            )
            for reserve in RESERVE_CASES:
                print(f"  Reserve: {reserve['name']} ({reserve['ticker']})")
                r2 = run_case(reserve)
                if not r2.get("data_unavailable"):
                    print(f"  Reserve-Case verwendet: {reserve['name']}")
                    r = r2
                    break
        recall_results.append(r)
        print(json.dumps(r, indent=2, default=str))

    # --- Negativ-Set ---
    print("\n" + "#" * 100)
    print("# Negativ-Set (9 Cases)")
    print("#" * 100)
    negative_results: list[dict] = []
    for case in NEGATIVE_CASES:
        print(f"\n--- {case['name']} ({case['ticker']}) ---")
        r = run_case(case)
        negative_results.append(r)
        print(json.dumps(r, indent=2, default=str))

    # --- Tabellen ---
    _print_recall_table(recall_results)
    _print_negative_table(negative_results)

    # --- Bilanz + Validation-Vokabular ---
    recall_hits, recall_total = _recall_score(recall_results)
    fps, neg_total = _precision_false_positives(negative_results)

    print("\n" + "=" * 100)
    print("Bilanz")
    print("=" * 100)
    print(f"Recall: {recall_hits}/{recall_total} -> {_recall_vokabular(recall_hits, recall_total)}")
    print(f"Precision: {fps}/{neg_total} false-positives -> {_precision_vokabular(fps, neg_total)}")

    ship = (recall_hits >= 1) and (fps <= 2)
    print(f"\nShip-Bedingung (Recall >=1/3 UND Precision <=2/9): {'JA' if ship else 'NEIN'}")
    if not ship:
        print("BAIL-OUT: v0.30.0 ist NICHT ship-faehig. KEIN Re-Tuning gegen das Negativ-Set.")
        print("Empfehlung: zurueck zu Phase 1 (erweiterte Diagnose) oder Discriminator-Erweiterung in v0.30.x.")

    # --- AAPL-2015-Smooth-Top spezifische Beobachtung ---
    aapl_2015 = next(
        (r for r in negative_results if r.get("ticker") == "AAPL" and r.get("start") == "2015-04-01"),
        None,
    )
    if aapl_2015 is not None:
        print("\n" + "=" * 100)
        print("Edge-Case: AAPL 2015 Smooth-Top")
        print("=" * 100)
        if aapl_2015.get("data_unavailable"):
            print(f"  Daten nicht verfuegbar: {aapl_2015.get('error')}")
        else:
            print(f"  Detected: {aapl_2015.get('detected')}")
            print(f"  Reason: {aapl_2015.get('reason')}")
            print(f"  ATR-Median-Rank: {aapl_2015.get('atr_compression_metric')}")
            wy = aapl_2015.get("wyckoff") or {}
            if aapl_2015.get("detected"):
                print(f"  Wyckoff-Score: {wy.get('score')}")
                print(
                    "  -> Detector feuert auf Smooth-Top: konkreter Blind Spot "
                    "fuer v0.31.x (Pre-Range-Direction-Filter oder Wyckoff-Score-Co-Filter).",
                )
            else:
                print(
                    f"  -> Detector verwirft via reason='{aapl_2015.get('reason')}': "
                    "Geometrie-Filter fangen die Topping-Asymmetrie auf, Precision-Aussage staerker.",
                )


if __name__ == "__main__":
    main()
