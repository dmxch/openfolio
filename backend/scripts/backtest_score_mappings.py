"""Verteilungs-Backtest fuer die Score-Mapping-Kandidaten (Iteration-2.5 Item E.1).

KEIN Forward-Return-Check — der kommt in E.2 (≥ 2026-06-20, wenn die
sauberen Post-Race-Fix-Scans 30d gereift sind und yfinance-Pull lohnt).

Was hier bewertet wird (3 von 4 Item-F-Kriterien):
- Bucket-Spread: wie gleichmaessig verteilt jedes Mapping die Rows
  ueber die 4 Slider-Buckets [0-29, 30-49, 50-69, 70-100]?
- Hit-Count-Faktor: wieviele Rows haetten Slider ≥ 50 bei jedem Mapping
  ueberlebt (heute live: ~6 pro Scan)?
- Top-Bucket nicht leer: liefert das Mapping mind. 1 Hit ≥ 70 pro Scan
  im 30-Tage-Schnitt?

Production-Semantik-Simulation: per-scan trailing-30d-CDF (kein
Daten-Leak, kein Backwards-Look). Cold-Start-Scans (erste ~30d) bekommen
duenne CDF und werden im Report transparent geflagged.

Aufruf (Output via stdout-Redirect):
  docker compose exec -T backend python scripts/backtest_score_mappings.py \\
    > backtest_score_mappings_$(date +%Y-%m-%d).md
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from db import sync_engine
from models.screening import ScreeningResult, ScreeningScan
from services.screening.score_mappings import MAPPINGS

BUCKETS = [(0, 29), (30, 49), (50, 69), (70, 100)]
SLIDER_THRESHOLDS = [10, 30, 50, 70]
TRAILING_WINDOW_DAYS = 30
COLD_START_MIN_SCANS = 5  # Trailing-CDF mit weniger Scans = Cold-Start


def bucket_of(display: int) -> tuple[int, int]:
    for lo, hi in BUCKETS:
        if lo <= display <= hi:
            return (lo, hi)
    return BUCKETS[-1]


def build_trailing_cdf(
    raw_counts_by_day: dict[date, dict[int, int]],
    target_day: date,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], int]:
    """Aggregiere raw-counts aus den Scans im Fenster
    [target_day - 30, target_day - 1] und baue (cdf, upper_cdf, n_scans).

    Returns leere CDFs falls keine trailing-Daten vorhanden.
    """
    window_start = target_day - timedelta(days=TRAILING_WINDOW_DAYS)
    aggregated: dict[int, int] = defaultdict(int)
    n_scans = 0
    for day, counts in raw_counts_by_day.items():
        if window_start <= day < target_day:
            n_scans += 1
            for raw, n in counts.items():
                aggregated[raw] += n

    if not aggregated:
        return [], [], 0

    sorted_raw = sorted(aggregated.items())
    total = sum(n for _, n in sorted_raw)
    cdf: list[tuple[int, int]] = []
    cumulative = 0
    for raw, n in sorted_raw:
        cumulative += n
        cdf.append((raw, int(round(100 * cumulative / total))))

    upper = [(raw, n) for raw, n in sorted_raw if raw >= 4]
    upper_total = sum(n for _, n in upper)
    upper_cdf: list[tuple[int, int]] = []
    if upper_total > 0:
        cumulative = 0
        for raw, n in upper:
            cumulative += n
            display = 40 + int(round(60 * cumulative / upper_total))
            upper_cdf.append((raw, display))

    return cdf, upper_cdf, n_scans


def main() -> None:
    with sync_engine.connect() as conn:
        scans = conn.execute(
            select(ScreeningScan.id, ScreeningScan.started_at)
            .where(ScreeningScan.status == "completed")
            .order_by(ScreeningScan.started_at)
        ).all()
        if not scans:
            print("FATAL: keine completed scans in der DB.", file=sys.stderr)
            sys.exit(1)

        scan_id_to_date = {s.id: s.started_at.date() for s in scans}
        raw_counts_by_day: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))

        rows = conn.execute(
            select(ScreeningResult.scan_id, ScreeningResult.score)
            .where(ScreeningResult.scan_id.in_([s.id for s in scans]))
        ).all()
        for scan_id, raw in rows:
            day = scan_id_to_date[scan_id]
            raw_counts_by_day[day][int(raw)] += 1

        first_day = min(raw_counts_by_day.keys())
        last_day = max(raw_counts_by_day.keys())
        all_days = sorted(raw_counts_by_day.keys())

        # Per-Mapping-Aggregation
        # mapping_bucket_total[mapping_name][bucket] = sum over all rows
        mapping_bucket_total: dict[str, dict[tuple[int, int], int]] = {
            m: defaultdict(int) for m in MAPPINGS
        }
        # mapping_threshold_total[mapping_name][threshold] = sum of rows ≥ threshold
        mapping_threshold_total: dict[str, dict[int, int]] = {
            m: defaultdict(int) for m in MAPPINGS
        }
        # mapping_per_scan_top_bucket[mapping_name] = list of (day, n_top_bucket)
        mapping_per_scan_top: dict[str, list[tuple[date, int]]] = {
            m: [] for m in MAPPINGS
        }
        # Per-scan total rows (für %-Berechnung)
        per_scan_n: dict[date, int] = {}
        cold_start_days: list[date] = []
        all_n = 0

        for day in all_days:
            cdf, upper_cdf, n_scans_in_window = build_trailing_cdf(raw_counts_by_day, day)
            ctx = {"cdf": cdf, "upper_cdf": upper_cdf}
            is_cold = n_scans_in_window < COLD_START_MIN_SCANS
            if is_cold:
                cold_start_days.append(day)

            day_counts = raw_counts_by_day[day]
            day_n = sum(day_counts.values())
            per_scan_n[day] = day_n
            all_n += day_n

            per_scan_top_for_mapping: dict[str, int] = {m: 0 for m in MAPPINGS}
            for raw, n in day_counts.items():
                for name, fn in MAPPINGS.items():
                    display = fn(raw, ctx)
                    bucket = bucket_of(display)
                    mapping_bucket_total[name][bucket] += n
                    for th in SLIDER_THRESHOLDS:
                        if display >= th:
                            mapping_threshold_total[name][th] += n
                    if display >= 70:
                        per_scan_top_for_mapping[name] += n
            for name in MAPPINGS:
                mapping_per_scan_top[name].append((day, per_scan_top_for_mapping[name]))

        # --- Output -----------------------------------------------------

        print(f"# Score-Mapping-Verteilungs-Backtest (Item E.1)")
        print()
        print(f"**Datum:** {last_day.isoformat()}  ")
        print(f"**Scan-Fenster:** {first_day.isoformat()} – {last_day.isoformat()}  ")
        print(f"**Scans:** {len(all_days)}  ")
        print(f"**Rows total:** {all_n:,}  ")
        print(f"**Trailing-CDF-Fenster:** {TRAILING_WINDOW_DAYS} d  ")
        print(f"**Cold-Start-Scans** (Trailing-CDF mit <{COLD_START_MIN_SCANS} Scans, dünne CDF): {len(cold_start_days)} / {len(all_days)}  ")
        print()
        print('**Scope-Hinweis:** Forward-Return-Auswertung (Item-F-Kriterium "Monotonie") ist in E.2 (>= 2026-06-20, wenn saubere Post-Race-Fix-Scans 30 d gereift sind und yfinance-Pull lohnt). Hier nur Verteilungs-Sanity (3 von 4 Decision-Kriterien).')
        print()
        print("---")
        print()
        print("## 1 — Bucket-Verteilung pro Mapping")
        print()
        print("Slider-Buckets [0-29, 30-49, 50-69, 70-100]. Faire-Verteilung-Referenz: 4 × 25 %.")
        print()
        print("| Mapping | 0-29 | 30-49 | 50-69 | 70-100 | Max-Spread (pp) |")
        print("|---|---:|---:|---:|---:|---:|")
        for name in ["linear", "log10_stretched", "percentile", "hybrid"]:
            buckets = mapping_bucket_total[name]
            pcts = [100.0 * buckets[b] / all_n for b in BUCKETS]
            spread = max(pcts) - min(pcts)
            row = f"| `{name}` "
            for p in pcts:
                row += f"| {p:.1f} % "
            row += f"| {spread:.1f} |"
            print(row)
        print()
        print("**Decision-Kriterium 1 (Bucket-Spread <96 pp):**")
        for name in ["linear", "log10_stretched", "percentile", "hybrid"]:
            buckets = mapping_bucket_total[name]
            pcts = [100.0 * buckets[b] / all_n for b in BUCKETS]
            spread = max(pcts) - min(pcts)
            verdict = "PASS" if spread < 96 else "FAIL"
            print(f"- `{name}`: spread {spread:.1f} pp → **{verdict}**")
        print()
        print("## 2 — Hit-Count pro Slider-Threshold (Mittel pro Scan)")
        print()
        print("Heute live (linear): Slider ≥ 50 ergibt ~6 Hits / Scan. Decision-Kriterium 3: 30–120 Hits ergibt Faktor 5–20×.")
        print()
        print("| Mapping | ≥ 10 | ≥ 30 | ≥ 50 | ≥ 70 |")
        print("|---|---:|---:|---:|---:|")
        for name in ["linear", "log10_stretched", "percentile", "hybrid"]:
            row = f"| `{name}` "
            for th in SLIDER_THRESHOLDS:
                avg = mapping_threshold_total[name][th] / len(all_days)
                row += f"| {avg:.1f} "
            row += "|"
            print(row)
        print()
        print("**Decision-Kriterium 3 (≥ 50: Faktor 5–20× über Linear):**")
        linear_50 = mapping_threshold_total["linear"][50] / len(all_days)
        for name in ["linear", "log10_stretched", "percentile", "hybrid"]:
            avg = mapping_threshold_total[name][50] / len(all_days)
            factor = avg / linear_50 if linear_50 > 0 else float("inf")
            if name == "linear":
                verdict = "BASELINE"
            elif 5 <= factor <= 20:
                verdict = "PASS"
            elif factor < 5:
                verdict = "FAIL (zu eng)"
            else:
                verdict = "FAIL (zu weit — Slider verliert Filterwirkung)"
            print(f"- `{name}`: {avg:.1f} Hits / Scan (Faktor {factor:.1f}×) → **{verdict}**")
        print()
        print("## 3 — Top-Bucket (≥ 70) Belegung")
        print()
        print("**Decision-Kriterium 4: mind. 1 Hit / Scan im Schnitt der letzten 30 d.**")
        print()
        recent_cutoff = last_day - timedelta(days=30)
        print("| Mapping | Hits ≥ 70 in letzten 30 d (Schnitt/Scan) | Scans ohne Top-Hit | Verdict |")
        print("|---|---:|---:|---|")
        for name in ["linear", "log10_stretched", "percentile", "hybrid"]:
            recent = [n for (d, n) in mapping_per_scan_top[name] if d >= recent_cutoff]
            avg = sum(recent) / len(recent) if recent else 0
            zero_scans = sum(1 for n in recent if n == 0)
            verdict = "PASS" if avg >= 1.0 else "FAIL"
            print(f"| `{name}` | {avg:.2f} | {zero_scans}/{len(recent)} | **{verdict}** |")
        print()
        print("## 4 — Kandidaten-Zusammenfassung")
        print()
        print("Bewertete Kriterien (3 von 4 — Forward-Return-Monotonie in E.2):")
        print()
        print("| Mapping | Spread | Hit-Count | Top-Bucket | Vorläufig |")
        print("|---|:---:|:---:|:---:|---|")
        linear_50 = mapping_threshold_total["linear"][50] / len(all_days)
        for name in ["linear", "log10_stretched", "percentile", "hybrid"]:
            buckets = mapping_bucket_total[name]
            pcts = [100.0 * buckets[b] / all_n for b in BUCKETS]
            spread = max(pcts) - min(pcts)
            spread_pass = spread < 96 and name != "linear"
            avg50 = mapping_threshold_total[name][50] / len(all_days)
            factor = avg50 / linear_50 if linear_50 > 0 else 0
            hit_pass = 5 <= factor <= 20 if name != "linear" else False
            recent = [n for (d, n) in mapping_per_scan_top[name] if d >= recent_cutoff]
            top_avg = sum(recent) / len(recent) if recent else 0
            top_pass = top_avg >= 1.0 if name != "linear" else False
            if name == "linear":
                summary = "Baseline (zum Vergleich)"
            else:
                passes = sum([spread_pass, hit_pass, top_pass])
                if passes == 3:
                    summary = "**KANDIDAT** (alle 3 von 3, warten auf E.2)"
                elif passes == 2:
                    summary = f"BORDERLINE ({passes}/3)"
                else:
                    summary = f"verworfen ({passes}/3)"
            sym = lambda b: "✓" if b else "—"
            print(f"| `{name}` | {sym(spread_pass) if name != 'linear' else '—'} | {sym(hit_pass) if name != 'linear' else '—'} | {sym(top_pass) if name != 'linear' else '—'} | {summary} |")
        print()
        print("---")
        print()
        print("## Caveats")
        print()
        print(f"- {len(cold_start_days)} Cold-Start-Scans (Trailing-CDF mit <{COLD_START_MIN_SCANS} Vortags-Scans): {[d.isoformat() for d in cold_start_days[:10]]}{'…' if len(cold_start_days) > 10 else ''}. Bei `percentile`/`hybrid` sind die Display-Scores dieser Scans aus duenner CDF gebaut — wenig statistische Aussagekraft.")
        print(f"- Pre-Race-Fix-Scans (vor 2026-05-21) basieren auf moeglicherweise unvollstaendigen Composite-Scores (Migration-074-Concurrency-Race). Die Verteilungs-Form selbst sollte aber valide sein, weil die fehlenden Signale eher Score reduzieren als verzerren.")
        print(f"- Forward-Return-Monotonie (Item-F-Kriterium 2) NICHT in diesem Report. Re-Lauf als E.2 nach 2026-06-20.")
        print(f"- KEIN Mapping wird in E.1 zum Live-Switch freigegeben. Selbst ein 3/3-Kandidat braucht E.2 + Item-F-Final-Decision.")


if __name__ == "__main__":
    main()
