# Score-Verteilungs-Analyse — Composite-Screening

**Datum:** 2026-05-29
**Anlass:** Iteration-2 Item C (Plan-Spike, Read-Only, KEIN Code-Change)
**Frage:** Linear-Score-Formel (`raw × 10`, raw ∈ [0,10]) beibehalten oder auf log/percentile swappen?
**Datenbasis:** Letzte 7 completed Composite-Scans (2026-05-23 bis 2026-05-29) auf Dev-DB, n=2'377 Rows aggregiert (336–344 pro Scan).

---

## TL;DR — Verdict: **SCHEDULE 2.5 (Formel-Swap)**

Verteilung ist stark rechts-schief, an der oberen Decision-Kante praktisch leer:

- **96.4 %** der Rows liegen im Raw-Score-Band 1–3 (display 10–30).
- **0.1 %** erreichen Raw ≥6 (display ≥60) — 3 Rows von 2'377 über 7 Scans.
- **0 Rows** über alle 7 Scans erreichen Display ≥67 (oberes Tertil der 0–100-Skala).
- Verteilungs-Form ist über 7 Scans stabil (avg_raw 2.19–2.32), kein Anomalie-Tag.

Die Plan-Decision-Rule („>80 % in unterster Tertile → swap") ist mit 96.4 % deutlich überschritten. Linear-Display bricht die Slider-UX: ein Filter `min_score_display ≥ 50` lässt 1.9 % aller Hits durch, `≥ 60` praktisch nichts. Das ist nicht das, was der Slider visuell kommuniziert.

Der Swap geht NICHT in Iteration 2 (Memory `feedback_signal_weights_need_backtest` — kein neues Display-Mapping live ohne Forward-Return-Validation). Spezifikation + Backtest werden Iteration **2.5** (separater Plan).

---

## 1 — Raw-Score-Histogramm (n = 2'377, aggregiert über 7 Scans)

| raw | rows | % | display |
|---:|---:|---:|---:|
| 1 | 454 | 19.1 % | 10 |
| 2 | 1'025 | 43.1 % | 20 |
| 3 | 814 | 34.2 % | 30 |
| 4 | 40 | 1.7 % | 40 |
| 5 | 41 | 1.7 % | 50 |
| 6 | 3 | 0.1 % | 60 |
| 7–10 | 0 | 0 % | — |

**Tertil-Verteilung (Display-Skala 0–100):**

| Tertil | Bereich | Rows | % |
|---|---:|---:|---:|
| unten | 0–33 | 2'293 | **96.4 %** |
| mitte | 34–66 | 84 | 3.5 % |
| oben | 67–100 | 0 | 0.0 % |

Plan-Decision-Threshold (>80 % unten → swap) **deutlich überschritten**.

## 2 — Per-Scan-Volatilität (kein Anomalie-Tag)

| Scan | ≤2 | =3 | ≥4 | max raw | avg raw |
|---|---:|---:|---:|---:|---:|
| 2026-05-29 | 188 | 132 | 16 | 6 | 2.32 |
| 2026-05-28 | 218 | 117 | 8 | 6 | 2.20 |
| 2026-05-27 | 226 | 109 | 9 | 6 | 2.19 |
| 2026-05-26 | 211 | 113 | 13 | 5 | 2.25 |
| 2026-05-25 | 212 | 114 | 13 | 5 | 2.25 |
| 2026-05-24 | 212 | 114 | 13 | 5 | 2.25 |
| 2026-05-23 | 212 | 115 | 12 | 5 | 2.24 |

Per-Scan avg_raw 2.19–2.32, max_raw 5–6 — die Verteilungs-Form ist über die ganze Woche identisch. Heute (29.5.) ist `≥4` leicht erhöht (16 vs. 8–13), plausibel durch frische Q1-13F-Filings, die neue 1-Punkt-`superinvestor_13f_single`-Signale gestiftet haben (TSM bekommt durch Aschenbrenner-Q1 raus → 6). Verteilungs-Form selbst bleibt unverändert. **Kein Single-Day-Bias auf der Datenbasis.**

## 3 — Top-20 letzter Scan (29.5.) — was Multi-Signal-Kombis macht

Beobachtung: Der Decision-Layer (Raw ≥4) ist heute **8 Rows** und besteht zu **6 / 8** aus _einsamen_ `insider_cluster`-Signalen (HUBS, JKHY, LAW, SMWB, SRAD, TONX, ACCS — nur Insider, kein Superinvestor, kein 13F-Layer). Die zwei Multi-Signal-Hits oben:

- **TSM (60):** superinvestor (24 Dataroma) + insider_cluster (3 Insider, 793k) + Aschenbrenner-Q1-Neuposition.
- **V (40):** congressional + superinvestor (28 Dataroma) + Klarman-Q1-Neuposition.

Restliche 50er-Kohorte: 2-Signal-Pairs (überwiegend Superinvestor + Insider, oder Buyback + Insider). Die Skala lässt theoretisch 10 Signale pro Ticker zu — empirisch maximal **3** in einer Woche von 7 Scans. Die obere Hälfte der Skala (Display 70–100) ist konstruktiv unerreichbar mit der aktuellen Quellenmischung.

## 4 — Was das für den UX-Slider bedeutet (heute)

| Slider-Setting | Effekt |
|---|---|
| `≥ 10` | trifft alles (Default) |
| `≥ 30` | hält 35.9 % zurück — UX wirkt etwa wie ein „etwas strenger"-Toggle |
| `≥ 50` | filtert auf **1.9 %** (44 Rows von 2'377) — praktisch ein „nur Multi-Signal-Hits"-Toggle |
| `≥ 60` | filtert auf **0.1 %** — fast immer leerer Grid |
| `≥ 70` | **immer leer** |

Heisst: 70 % der Slider-Range (30→100) sind faktisch zwei Schwellen mit dazwischen leerem Raum, nicht ein Kontinuum. User-Erwartung „50/100 = mittelhart" ↔ Realität „50/100 = harter Edge-Cut auf 1.9 %" sind weit auseinander.

## 5 — Beobachtungs-Hypothesen (NICHT für Iteration-2-Entscheidung, nur als Kontext für 2.5)

1. **Signal-Sparseness ist der Treiber, nicht die Formel.** Die meisten Tickers triggern 1–2 Signal-Quellen. Ein log-/percentile-Mapping würde den Display-Spread reparieren, aber nicht die Signal-Coverage selbst (das ist ein separates Iteration-3+-Thema, z.B. Earnings-Surprise-Layer, Buyback-Programs verbreitern).
2. **Mono-`insider_cluster`-Dominanz im Decision-Band.** 6/8 der Raw-≥4-Rows heute sind Mono-Insider — das `insider_cluster`-Signal ist sehr breit. Ein zukünftiger Filter „mindestens 2 unabhängige Signal-Quellen" könnte das fischiger machen als ein Score-Threshold.
3. **`raw=2` ist der dichteste Bucket (43 %) — Median-Hit ist „1 Signal + Sektor-Momentum-Bonus".** Wenn Iteration 2.5 percentile-mappt, fällt dieser Hügel sauberer in die untere Hälfte.

Diese drei Punkte gehen in den **Iteration-2.5-Plan**, nicht hier — Memory `feedback_signal_weights_need_backtest` blockt Live-Änderungen ohne Forward-Return-Validation.

## 6 — Was JETZT NICHT passiert

- Keine Änderung an `compute_display_score()` in `services/screening/screening_service.py`.
- Keine Änderung an Slider-Defaults oder Range im Frontend.
- Keine Score-Gewicht-Justierung an Signal-Sources (Memory-Block).

## 7 — Was ALS NÄCHSTES passiert

Separater Iteration-2.5-Plan, der mindestens enthält:

- **Mapping-Optionen:** log10, percentile (empirische Quantile aus rolling-window), hybrid (linear unten + percentile oben).
- **Backtest-Protokoll:** Forward-Return-Validation (30/60/90d) auf Slider-Threshold ≥ X für altes vs. neues Display, auf 6–8 Wochen historischer Composite-Daten (verfügbar ab ~2026-04-03, dem first completed scan in der Dev-DB).
- **Decision-Criteria:** Mapping behält den **gleichen Forward-Return-Trend** über die Slider-Schwellen und verteilt die Filter-Reduktion gleichmässiger. Sonst → ablehnen, weiter mit linear.
- **Roll-out-Plan:** Display-Wert ist eine reine Anzeige-Frage — der Raw-Score selbst bleibt unverändert, alles in Backend abwärtskompatibel.

Frühestes Build-Fenster für 2.5: **nach Tag-12-Retro 2026-06-01 (GO/FIX/KILL für Iteration 1)**, frühestens parallel zu Iteration 2 Item A.2 / B-Frontend.

---

## Anhang — Verwendete Queries

```sql
-- 7 jüngste completed Scans als Basis
WITH recent_scans AS (
  SELECT id FROM screening_scans
  WHERE status = 'completed'
  ORDER BY started_at DESC LIMIT 7
)
-- Raw-Histogramm
SELECT score AS raw_score, COUNT(*) AS row_count,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM screening_results
WHERE scan_id IN (SELECT id FROM recent_scans)
GROUP BY score ORDER BY score;
```

(zwei weitere Queries — Per-Scan-Volatilität, Top-20 — im Kommit-Diff.)
