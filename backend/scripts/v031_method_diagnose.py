"""v0.31 Phase 0 — Methoden-Vor-Diagnose der vier Discriminator-Hypothesen.

Standalone-Skript analog zu ``wyckoff_textbook_check.py`` und
``long_accumulation_held_out_check.py``. Kein pytest, keine Backend-Integration,
kein Detector-Code.

Empirische Vor-Diagnose VOR einem v0.31-Plan-Mode: prueft auf den 12
existierenden Held-Out-Cases (Recall + Negativ-Set aus v0.30) ob die vier
hypothetischen Discriminatoren tatsaechlich Recall- von Negativ-Cases trennen.

Vier Discriminatoren:

1. **Closes-Slope** (log-Linear-Regression ueber gesamtes [start, end])
2. **Pre-Range vs Range-Slope** (Pin-konsistent: range_mid_date +/- 30d Range,
   range_mid - 150d bis range_mid - 30d Pre-Range)
3. **Bollinger-Width-Quote** (Squeeze: bb_width am range_mid_date / Median
   ueber 60d-Pre-Window)
4. **Volume-Slope** (zwei Varianten: gesamtes Daten-Fenster + Range-Fenster
   fuer Robustheits-Vergleich)

**Daten-Pull mit Buffer**: ``yf_download(ticker, start - 200d, end)``.
Begruendung: Disc 2 braucht 150d Pre-Range, Disc 3 braucht 60d BB-History +
20d sma20-Init = ~80d Pre-Window. Bei MCD 2003 (range_mid 2003-04-15) ist
Pre-Range-Start ~ 2002-11-15, das liegt VOR dem nominalen start=2003-01-01.
Ohne 200d-Buffer: NaN/IndexError. Slicing pro Discriminator NACH dem Pull.

Aufruf (nach docker rebuild — Skripte sind nicht volume-gemountet):
  docker compose up --build -d backend
  docker compose exec backend python scripts/v031_method_diagnose.py
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Skript laeuft aus /app im Container — Backend-Source liegt direkt da
sys.path.insert(0, str(Path(__file__).parent.parent))

from yf_patch import yf_download  # noqa: E402


# --- 12 Cases (aus v0.30, identische Datums-Fenster) --------------------
# range_mid_date Pin-konsistent zur v0.30-Methodik (Pattern-Mitte).
CASES: list[dict] = [
    # Recall-Set (3)
    {
        "name": "MCD 2003 (Bottom + Akkumulation vor Launch)",
        "ticker": "MCD",
        "start": "2003-01-01",
        "end": "2003-09-30",
        "range_mid_date": "2003-04-15",
        "set": "recall",
    },
    {
        "name": "INTC 2009 (Post-Crisis-Akkumulation)",
        "ticker": "INTC",
        "start": "2009-01-01",
        "end": "2009-07-31",
        "range_mid_date": "2009-04-15",
        "set": "recall",
    },
    {
        "name": "MSFT 2013 (Nadella-Pre-Rally-Range)",
        "ticker": "MSFT",
        "start": "2013-01-01",
        "end": "2013-06-30",
        "range_mid_date": "2013-03-31",
        "set": "recall",
    },
    # Negativ-Set (9)
    {
        "name": "NVDA 2023 Q4 (Aufwaerts-Trend)",
        "ticker": "NVDA",
        "start": "2023-10-01",
        "end": "2024-01-31",
        "range_mid_date": "2023-12-01",
        "set": "negative",
    },
    {
        "name": "TSLA 2022 H1 (Abwaerts)",
        "ticker": "TSLA",
        "start": "2022-01-01",
        "end": "2022-06-30",
        "range_mid_date": "2022-04-01",
        "set": "negative",
    },
    {
        "name": "AMD 2022 Q3-Q4 (Abwaerts)",
        "ticker": "AMD",
        "start": "2022-07-01",
        "end": "2022-12-31",
        "range_mid_date": "2022-10-01",
        "set": "negative",
    },
    {
        "name": "META 2022 Q1-Q2 (Abwaerts)",
        "ticker": "META",
        "start": "2022-01-01",
        "end": "2022-06-30",
        "range_mid_date": "2022-04-01",
        "set": "negative",
    },
    {
        "name": "AAPL 2024 Q1 (Aufwaerts-Trend)",
        "ticker": "AAPL",
        "start": "2024-01-01",
        "end": "2024-04-30",
        "range_mid_date": "2024-02-29",
        "set": "negative",
    },
    {
        "name": "ORCL 2024 Q2 (Aufwaerts-Trend)",
        "ticker": "ORCL",
        "start": "2024-04-01",
        "end": "2024-07-31",
        "range_mid_date": "2024-06-01",
        "set": "negative",
    },
    {
        "name": "TSLA 2021 H2 Top (Topping, hohe ATR)",
        "ticker": "TSLA",
        "start": "2021-09-01",
        "end": "2022-01-31",
        "range_mid_date": "2021-11-15",
        "set": "negative",
    },
    {
        "name": "MSFT 2007 H2 Top (Top vor Finanzkrise)",
        "ticker": "MSFT",
        "start": "2007-07-01",
        "end": "2007-12-31",
        "range_mid_date": "2007-09-30",
        "set": "negative",
    },
    {
        "name": "AAPL 2015 Smooth-Top (niedrige ATR, Edge-Case)",
        "ticker": "AAPL",
        "start": "2015-04-01",
        "end": "2015-08-31",
        "range_mid_date": "2015-06-15",
        "set": "negative",
    },
]


# --- Helpers ------------------------------------------------------------

def _log_slope_with_r2(values: np.ndarray) -> tuple[float | None, float | None]:
    """Log-Linear-Slope (% pro Tag) plus R^2.

    Returns (slope_pct_per_day, r2). Bei zu kurzem Input oder
    nicht-positiven Werten: (None, None).
    """
    if values is None or len(values) < 3:
        return None, None
    arr = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0):
        return None, None
    n = len(arr)
    x = np.arange(n, dtype=float)
    log_y = np.log(arr)
    # polyfit liefert [slope, intercept]
    slope, intercept = np.polyfit(x, log_y, 1)
    predicted = slope * x + intercept
    ssr = float(np.sum((log_y - predicted) ** 2))
    sst = float(np.sum((log_y - log_y.mean()) ** 2))
    r2 = 1.0 - ssr / sst if sst > 0 else 0.0
    return float(slope * 100.0), float(r2)


def _slice_by_dates(
    df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
) -> pd.DataFrame:
    """Inklusive Slicing auf DatetimeIndex zwischen [start, end]."""
    mask = (df.index >= start) & (df.index <= end)
    return df.loc[mask]


def _nearest_index_at_or_before(
    df: pd.DataFrame, target: pd.Timestamp,
) -> pd.Timestamp | None:
    """Naechster Index <= target. None falls keiner existiert."""
    earlier = df.index[df.index <= target]
    if len(earlier) == 0:
        return None
    return earlier[-1]


def _disc1_closes_slope(closes_window: pd.Series) -> dict:
    """Disc 1: log-Slope der Closes ueber [start, end] (ohne Buffer)."""
    slope, r2 = _log_slope_with_r2(closes_window.values)
    return {
        "disc1_closes_slope_pct_per_day": slope,
        "disc1_closes_slope_r2": r2,
    }


def _disc2_pre_vs_range(
    closes_full: pd.Series, range_mid: pd.Timestamp,
) -> dict:
    """Disc 2: Pre-Range vs Range-Slope, Pin-konsistent.

    Range = [range_mid - 30d, range_mid + 30d]
    Pre-Range = [range_mid - 150d, range_mid - 30d]
    """
    pre_start = range_mid - timedelta(days=150)
    pre_end = range_mid - timedelta(days=30)
    range_start = range_mid - timedelta(days=30)
    range_end = range_mid + timedelta(days=30)

    pre = closes_full.loc[(closes_full.index >= pre_start) & (closes_full.index < pre_end)]
    rng = closes_full.loc[(closes_full.index >= range_start) & (closes_full.index <= range_end)]

    pre_slope, pre_r2 = _log_slope_with_r2(pre.values)
    rng_slope, rng_r2 = _log_slope_with_r2(rng.values)
    return {
        "disc2_pre_range_slope_pct_per_day": pre_slope,
        "disc2_pre_range_slope_r2": pre_r2,
        "disc2_range_slope_pct_per_day": rng_slope,
        "disc2_range_slope_r2": rng_r2,
        "_disc2_pre_bars": int(len(pre)),
        "_disc2_range_bars": int(len(rng)),
    }


def _disc3_bb_width_quote(
    closes_full: pd.Series, range_mid: pd.Timestamp,
) -> dict:
    """Disc 3: Bollinger-Width-Quote am range_mid_date.

    bb_width_t = 4 * std20(closes) / sma20(closes)
    bb_width_now = bb_width am Trading-Tag <= range_mid_date
    bb_width_history_median_60d = Median aller bb_width_t fuer t in
                                   [range_mid - 60d, range_mid - 1d]
    bb_width_quote = bb_width_now / bb_width_history_median_60d
    """
    sma20 = closes_full.rolling(window=20, min_periods=20).mean()
    std20 = closes_full.rolling(window=20, min_periods=20).std(ddof=0)
    bb_width = 4.0 * std20 / sma20

    pin_idx = _nearest_index_at_or_before(closes_full.to_frame(), range_mid)
    if pin_idx is None:
        return {
            "disc3_bb_width_now": None,
            "disc3_bb_width_history_median_60d": None,
            "disc3_bb_width_quote": None,
        }
    bb_now = bb_width.loc[pin_idx]
    if bb_now is None or not np.isfinite(bb_now):
        return {
            "disc3_bb_width_now": None,
            "disc3_bb_width_history_median_60d": None,
            "disc3_bb_width_quote": None,
        }

    hist_start = range_mid - timedelta(days=60)
    hist_end = range_mid - timedelta(days=1)
    hist = bb_width.loc[(bb_width.index >= hist_start) & (bb_width.index <= hist_end)]
    hist = hist.dropna()
    if len(hist) < 5:
        return {
            "disc3_bb_width_now": float(bb_now),
            "disc3_bb_width_history_median_60d": None,
            "disc3_bb_width_quote": None,
        }
    hist_median = float(hist.median())
    quote = float(bb_now) / hist_median if hist_median > 0 else None
    return {
        "disc3_bb_width_now": float(bb_now),
        "disc3_bb_width_history_median_60d": hist_median,
        "disc3_bb_width_quote": quote,
    }


def _disc4_volume_slopes(
    volumes_window: pd.Series, volumes_full: pd.Series, range_mid: pd.Timestamp,
) -> dict:
    """Disc 4: Volume-Slope, zwei Varianten.

    - Window: log-Slope ueber gesamtes [start, end]
    - Range: log-Slope ueber [range_mid - 30d, range_mid + 30d]
    """
    win_slope, win_r2 = _log_slope_with_r2(volumes_window.values)

    range_start = range_mid - timedelta(days=30)
    range_end = range_mid + timedelta(days=30)
    rng_vols = volumes_full.loc[
        (volumes_full.index >= range_start) & (volumes_full.index <= range_end)
    ]
    rng_slope, rng_r2 = _log_slope_with_r2(rng_vols.values)

    return {
        "disc4_volume_slope_window_pct_per_day": win_slope,
        "disc4_volume_slope_window_r2": win_r2,
        "disc4_volume_slope_range_pct_per_day": rng_slope,
        "disc4_volume_slope_range_r2": rng_r2,
    }


def run_case(case: dict) -> dict:
    """Pull OHLCV mit 200d-Buffer, berechne alle vier Discriminatoren."""
    out: dict = {
        "name": case["name"],
        "ticker": case["ticker"],
        "set": case["set"],
        "start": case["start"],
        "end": case["end"],
        "range_mid_date": case["range_mid_date"],
    }

    start_dt = datetime.fromisoformat(case["start"])
    end_dt = datetime.fromisoformat(case["end"])
    range_mid_dt = datetime.fromisoformat(case["range_mid_date"])
    pull_start = start_dt - timedelta(days=200)

    try:
        data = yf_download(
            case["ticker"],
            start=pull_start.strftime("%Y-%m-%d"),
            end=case["end"],
            progress=False,
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
    volume = data["Volume"].squeeze().dropna() if "Volume" in data else None

    if close is None or len(close) < 60:
        out["error"] = "insufficient_history"
        out["bars"] = 0 if close is None else int(len(close))
        out["data_unavailable"] = True
        return out

    # Index als Timestamp normalisieren (yfinance liefert tz-naive DatetimeIndex)
    close.index = pd.to_datetime(close.index)
    if volume is not None:
        volume.index = pd.to_datetime(volume.index)

    range_mid_ts = pd.Timestamp(range_mid_dt)
    start_ts = pd.Timestamp(start_dt)
    end_ts = pd.Timestamp(end_dt)

    # Window-Slice fuer Disc 1 + Disc 4-window
    closes_window = close.loc[(close.index >= start_ts) & (close.index <= end_ts)]
    volumes_window = (
        volume.loc[(volume.index >= start_ts) & (volume.index <= end_ts)]
        if volume is not None
        else pd.Series([], dtype=float)
    )
    out["bars"] = int(len(closes_window))

    # Discriminator-Berechnung
    out.update(_disc1_closes_slope(closes_window))
    out.update(_disc2_pre_vs_range(close, range_mid_ts))
    out.update(_disc3_bb_width_quote(close, range_mid_ts))
    out.update(_disc4_volume_slopes(volumes_window, volume if volume is not None else pd.Series([], dtype=float), range_mid_ts))

    return out


# --- Aggregierte Trennschaerfe-Statistik --------------------------------

DISC_KEYS = [
    ("disc1_closes_slope_pct_per_day", "Disc 1: Closes-Slope (% pro Tag)"),
    ("disc2_pre_range_slope_pct_per_day", "Disc 2-pre: Pre-Range-Slope (% pro Tag)"),
    ("disc2_range_slope_pct_per_day", "Disc 2-range: Range-Slope (% pro Tag)"),
    ("disc3_bb_width_quote", "Disc 3: Bollinger-Width-Quote"),
    ("disc4_volume_slope_window_pct_per_day", "Disc 4-window: Volume-Slope window (% pro Tag)"),
    ("disc4_volume_slope_range_pct_per_day", "Disc 4-range: Volume-Slope range (% pro Tag)"),
]


def _stats_per_set(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min": None, "max": None, "median": None}
    arr = np.asarray(values, dtype=float)
    return {
        "n": len(values),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "median": float(np.median(arr)),
    }


def _classify(
    recall_vals: list[float], neg_vals: list[float],
) -> tuple[str, dict]:
    """Klassifikation mit fixierten Schwellen (vor Sicht der Resultate).

    - klar trennend: kein Overlap, oder Overlap nur bei AAPL-2015 (Edge-Case)
    - partiell trennend: <30 % der Cases im Overlap-Bereich
    - Overlap dominant: >=30 % im Overlap

    Wir koennen das "AAPL-2015 only" hier nicht direkt erkennen — der Aufrufer
    muss bei klar=False pruefen welche Cases im Overlap liegen. Hier
    klassifizieren wir mechanisch und liefern die Overlap-Mitglieder.
    """
    if not recall_vals or not neg_vals:
        return "n/a", {"reason": "set_empty"}

    r_min, r_max = min(recall_vals), max(recall_vals)
    n_min, n_max = min(neg_vals), max(neg_vals)

    overlap_lo = max(r_min, n_min)
    overlap_hi = min(r_max, n_max)

    if overlap_lo > overlap_hi:
        return "klar trennend", {
            "overlap_low": None,
            "overlap_high": None,
            "in_overlap_count": 0,
            "in_overlap_share": 0.0,
        }

    total = len(recall_vals) + len(neg_vals)
    in_overlap = sum(
        1 for v in (recall_vals + neg_vals)
        if overlap_lo <= v <= overlap_hi
    )
    share = in_overlap / total if total else 0.0
    label = "partiell trennend" if share < 0.30 else "Overlap dominant"
    return label, {
        "overlap_low": float(overlap_lo),
        "overlap_high": float(overlap_hi),
        "in_overlap_count": in_overlap,
        "in_overlap_share": round(share, 3),
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson-Korrelation. None falls Std-Dev = 0 oder n < 3."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    r = float(np.corrcoef(x, y)[0, 1])
    if not np.isfinite(r):
        return None
    return r


# v0.30-ATR-Compression-Werte aus LONG_ACCUMULATION_HELD_OUT_RESULTS.md
# (Recall + Negativ Tabelle, Spalte "ATR-Median-Rank")
# ATR-Werte fuer alle 12 Cases.
# Cases ohne ATR-Wert in der Doku ("–"): NVDA 2023 Q4, AAPL 2024 Q1, ORCL 2024 Q2
# (verworfen via insufficient_touches/no_alternation BEVOR ATR-Berechnung lief).
# Diese Cases tragen NICHT zur Pearson-Korrelation bei.
ATR_COMPRESSION_FROM_V030: dict[str, float | None] = {
    "MCD 2003 (Bottom + Akkumulation vor Launch)": 51.11,
    "INTC 2009 (Post-Crisis-Akkumulation)": 33.33,
    "MSFT 2013 (Nadella-Pre-Rally-Range)": 66.67,
    "NVDA 2023 Q4 (Aufwaerts-Trend)": None,
    "TSLA 2022 H1 (Abwaerts)": 60.0,
    "AMD 2022 Q3-Q4 (Abwaerts)": 42.22,
    "META 2022 Q1-Q2 (Abwaerts)": 61.11,
    "AAPL 2024 Q1 (Aufwaerts-Trend)": None,
    "ORCL 2024 Q2 (Aufwaerts-Trend)": None,
    "TSLA 2021 H2 Top (Topping, hohe ATR)": 66.67,
    "MSFT 2007 H2 Top (Top vor Finanzkrise)": 66.67,
    "AAPL 2015 Smooth-Top (niedrige ATR, Edge-Case)": 50.0,
}


# --- Output-Routinen ----------------------------------------------------

def _print_overview_table(results: list[dict]) -> None:
    print("\n" + "=" * 140)
    print("Roh-Tabelle: 12 Cases x Discriminatoren")
    print("=" * 140)
    header = (
        f"{'Ticker':<7}{'Set':<10}{'Bars':<6}"
        f"{'D1-slope':>10}{'D1-r2':>8}"
        f"{'D2pre':>9}{'D2pre-r2':>10}"
        f"{'D2rng':>9}{'D2rng-r2':>10}"
        f"{'D3-quote':>10}{'D3-now':>9}{'D3-hist':>9}"
        f"{'D4w-slp':>9}{'D4w-r2':>9}"
        f"{'D4r-slp':>9}{'D4r-r2':>9}"
    )
    print(header)

    def fmt(v: float | None, decimals: int = 3) -> str:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return "  -  "
        return f"{v:.{decimals}f}"

    for r in results:
        if r.get("data_unavailable"):
            print(f"{r.get('ticker', '?'):<7}{r.get('set', ''):<10}{'N/A':<6} ERROR: {r.get('error')}")
            continue
        print(
            f"{r['ticker']:<7}{r['set']:<10}{r['bars']:<6}"
            f"{fmt(r.get('disc1_closes_slope_pct_per_day')):>10}"
            f"{fmt(r.get('disc1_closes_slope_r2'), 2):>8}"
            f"{fmt(r.get('disc2_pre_range_slope_pct_per_day')):>9}"
            f"{fmt(r.get('disc2_pre_range_slope_r2'), 2):>10}"
            f"{fmt(r.get('disc2_range_slope_pct_per_day')):>9}"
            f"{fmt(r.get('disc2_range_slope_r2'), 2):>10}"
            f"{fmt(r.get('disc3_bb_width_quote'), 3):>10}"
            f"{fmt(r.get('disc3_bb_width_now'), 4):>9}"
            f"{fmt(r.get('disc3_bb_width_history_median_60d'), 4):>9}"
            f"{fmt(r.get('disc4_volume_slope_window_pct_per_day'), 3):>9}"
            f"{fmt(r.get('disc4_volume_slope_window_r2'), 2):>9}"
            f"{fmt(r.get('disc4_volume_slope_range_pct_per_day'), 3):>9}"
            f"{fmt(r.get('disc4_volume_slope_range_r2'), 2):>9}"
        )


def _print_separation_analysis(results: list[dict]) -> dict:
    """Trennschaerfe-Analyse pro Discriminator. Returns aggregierte Statistik."""
    valid = [r for r in results if not r.get("data_unavailable")]
    aggregated: dict[str, dict] = {}

    print("\n" + "=" * 100)
    print("Trennschaerfe-Analyse pro Discriminator")
    print("=" * 100)

    for key, label in DISC_KEYS:
        recall_vals = [
            r[key] for r in valid
            if r["set"] == "recall" and r.get(key) is not None
            and isinstance(r.get(key), (int, float)) and math.isfinite(r[key])
        ]
        neg_vals = [
            r[key] for r in valid
            if r["set"] == "negative" and r.get(key) is not None
            and isinstance(r.get(key), (int, float)) and math.isfinite(r[key])
        ]
        recall_stats = _stats_per_set(recall_vals)
        neg_stats = _stats_per_set(neg_vals)
        classification, overlap_info = _classify(recall_vals, neg_vals)

        # Welche Cases liegen im Overlap?
        overlap_members: list[str] = []
        if overlap_info.get("overlap_low") is not None:
            lo = overlap_info["overlap_low"]
            hi = overlap_info["overlap_high"]
            for r in valid:
                v = r.get(key)
                if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
                    continue
                if lo <= v <= hi:
                    overlap_members.append(f"{r['ticker']}/{r['set']}={v:.3f}")

        aggregated[key] = {
            "label": label,
            "recall": recall_stats,
            "negative": neg_stats,
            "classification": classification,
            "overlap": overlap_info,
            "overlap_members": overlap_members,
        }

        print(f"\n--- {label} ---")
        print(f"  Recall   (n={recall_stats['n']}): min={recall_stats['min']}, max={recall_stats['max']}, median={recall_stats['median']}")
        print(f"  Negativ  (n={neg_stats['n']}): min={neg_stats['min']}, max={neg_stats['max']}, median={neg_stats['median']}")
        print(f"  Overlap-Bereich: [{overlap_info.get('overlap_low')}, {overlap_info.get('overlap_high')}]")
        print(f"  Cases im Overlap: {overlap_info.get('in_overlap_count')} / {len(valid)} (Anteil={overlap_info.get('in_overlap_share')})")
        print(f"  Klassifikation: {classification}")
        if overlap_members:
            print(f"  Overlap-Mitglieder: {', '.join(overlap_members)}")

    return aggregated


def _print_bb_atr_correlation(results: list[dict]) -> dict:
    """Pearson-Korrelation zwischen Disc-3-bb_width_quote und v0.30-ATR.

    Wenn r > 0.7 -> BB-Width misst dasselbe wie ATR-Percentile, dann
    zaehlt das als BESTAETIGUNG der ATR-Erkenntnis (Volatilitaet trennt
    nicht), NICHT als zweiter Bail-out.
    """
    print("\n" + "=" * 100)
    print("BB-vs-ATR-Korrelations-Check")
    print("=" * 100)
    pairs: list[tuple[str, float, float]] = []
    for r in results:
        if r.get("data_unavailable"):
            continue
        bb = r.get("disc3_bb_width_quote")
        atr = ATR_COMPRESSION_FROM_V030.get(r["name"])
        if bb is not None and atr is not None and math.isfinite(bb):
            pairs.append((r["name"], bb, atr))
    if len(pairs) < 3:
        print("  Zu wenig Paare fuer Pearson-Korrelation (<3).")
        return {"n": len(pairs), "pearson_r": None, "interpretation": "insufficient_data"}
    bbs = [p[1] for p in pairs]
    atrs = [p[2] for p in pairs]
    r = _pearson(bbs, atrs)
    print(f"  n = {len(pairs)} Cases mit beiden Werten")
    print(f"  Pearson r = {r}")
    for name, bb, atr in pairs:
        print(f"    {name}: bb_quote={bb:.3f}, atr_metric={atr}")
    if r is None:
        interp = "n/a"
    elif r > 0.7:
        interp = "BB misst dasselbe wie ATR — Bestaetigung ATR-Erkenntnis, KEIN zweiter Bail-out"
    elif r < -0.7:
        interp = "BB stark anti-korreliert zu ATR — methodisch unerwartet, separat untersuchen"
    else:
        interp = "BB und ATR teilweise unabhaengig — BB als eigenstaendiger Discriminator zaehlt"
    print(f"  Interpretation: {interp}")
    return {"n": len(pairs), "pearson_r": r, "interpretation": interp}


def _ascii_scatter(
    results: list[dict], x_key: str, y_key: str, x_label: str, y_label: str,
) -> str:
    """ASCII-Scatter 2D fuer Discriminator-Paar.

    R = Recall, N = Negativ. 24 Cols x 14 Rows Grid.
    """
    valid = [r for r in results if not r.get("data_unavailable")]
    points: list[tuple[float, float, str]] = []
    for r in valid:
        x = r.get(x_key)
        y = r.get(y_key)
        if x is None or y is None:
            continue
        if not (isinstance(x, (int, float)) and math.isfinite(x)):
            continue
        if not (isinstance(y, (int, float)) and math.isfinite(y)):
            continue
        marker = "R" if r["set"] == "recall" else "N"
        points.append((float(x), float(y), marker))

    if len(points) < 2:
        return f"  [Scatter {x_label} vs {y_label}]: zu wenig Datenpunkte\n"

    cols, rows = 40, 14
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_max == x_min:
        x_max = x_min + 1.0
    if y_max == y_min:
        y_max = y_min + 1.0

    grid = [[" " for _ in range(cols)] for _ in range(rows)]
    for x, y, m in points:
        cx = int((x - x_min) / (x_max - x_min) * (cols - 1))
        cy = int((y - y_min) / (y_max - y_min) * (rows - 1))
        cy = (rows - 1) - cy  # invert (top = high y)
        existing = grid[cy][cx]
        if existing == " ":
            grid[cy][cx] = m
        elif existing != m:
            grid[cy][cx] = "X"  # mixed cell

    lines: list[str] = []
    lines.append(f"  Scatter: x={x_label} ({x_min:.3f} .. {x_max:.3f})")
    lines.append(f"           y={y_label} ({y_min:.3f} .. {y_max:.3f})")
    lines.append("           Recall=R, Negativ=N, X=Cluster-Konflikt (gemischte Zelle)")
    lines.append("  +" + "-" * cols + "+")
    for i, row in enumerate(grid):
        if i == 0:
            lines.append(f"  |{''.join(row)}|  y={y_max:.2f}")
        elif i == rows - 1:
            lines.append(f"  |{''.join(row)}|  y={y_min:.2f}")
        else:
            lines.append(f"  |{''.join(row)}|")
    lines.append("  +" + "-" * cols + "+")
    return "\n".join(lines) + "\n"


def _print_pair_scatter(results: list[dict]) -> list[dict]:
    """6 Discriminator-Paar-Scatter (Disc4 nutzt range-Variante)."""
    print("\n" + "=" * 100)
    print("Kombinations-Analyse (6 Discriminator-Paar-Scatter)")
    print("=" * 100)
    pairs = [
        (
            "disc1_closes_slope_pct_per_day", "Disc1-closes",
            "disc2_pre_range_slope_pct_per_day", "Disc2-pre",
        ),
        (
            "disc1_closes_slope_pct_per_day", "Disc1-closes",
            "disc3_bb_width_quote", "Disc3-bb-quote",
        ),
        (
            "disc1_closes_slope_pct_per_day", "Disc1-closes",
            "disc4_volume_slope_range_pct_per_day", "Disc4-vol-range",
        ),
        (
            "disc2_pre_range_slope_pct_per_day", "Disc2-pre",
            "disc3_bb_width_quote", "Disc3-bb-quote",
        ),
        (
            "disc2_pre_range_slope_pct_per_day", "Disc2-pre",
            "disc4_volume_slope_range_pct_per_day", "Disc4-vol-range",
        ),
        (
            "disc3_bb_width_quote", "Disc3-bb-quote",
            "disc4_volume_slope_range_pct_per_day", "Disc4-vol-range",
        ),
    ]
    summaries: list[dict] = []
    for x_key, x_lbl, y_key, y_lbl in pairs:
        print(f"\n--- {x_lbl} x {y_lbl} ---")
        chart = _ascii_scatter(results, x_key, y_key, x_lbl, y_lbl)
        print(chart)
        summaries.append({"x": x_lbl, "y": y_lbl, "chart": chart})
    return summaries


# --- Main ---------------------------------------------------------------

def main() -> None:
    print("v0.31 Phase 0 — Methoden-Vor-Diagnose")
    print("=" * 100)
    print(f"Cases: {len(CASES)} (Recall: 3, Negativ: 9)")
    print("Daten-Pull mit 200d-Buffer (Disc 2/3 brauchen Pre-Range-Window).")

    results: list[dict] = []
    for case in CASES:
        print(f"\n--- {case['name']} ({case['ticker']}, set={case['set']}) ---")
        r = run_case(case)
        results.append(r)
        print(json.dumps(r, indent=2, default=str))

    _print_overview_table(results)
    aggregated = _print_separation_analysis(results)
    bb_atr = _print_bb_atr_correlation(results)
    _print_pair_scatter(results)

    print("\n" + "=" * 100)
    print("Empfehlungs-Trigger (mechanisch, nicht-final)")
    print("=" * 100)
    classifications = {k: v["classification"] for k, v in aggregated.items()}
    for k, c in classifications.items():
        print(f"  {k}: {c}")
    klar_count = sum(1 for c in classifications.values() if c == "klar trennend")
    partiell_count = sum(1 for c in classifications.values() if c == "partiell trennend")
    overlap_count = sum(1 for c in classifications.values() if c == "Overlap dominant")
    print(f"\n  klar trennend:    {klar_count}")
    print(f"  partiell trennend:{partiell_count}")
    print(f"  Overlap dominant: {overlap_count}")
    print("\n  -> finale Empfehlung in V031_METHOD_DIAGNOSE.md ergaenzen")
    print(f"  -> BB-vs-ATR-Pearson r = {bb_atr.get('pearson_r')}")


if __name__ == "__main__":
    main()
