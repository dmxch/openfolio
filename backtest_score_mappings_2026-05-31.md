# Score-Mapping-Verteilungs-Backtest (Item E.1)

**Datum:** 2026-05-31  
**Scan-Fenster:** 2026-04-03 – 2026-05-31  
**Scans:** 17  
**Rows total:** 8,016  
**Trailing-CDF-Fenster:** 30 d  
**Cold-Start-Scans** (Trailing-CDF mit <5 Scans, dünne CDF): 9 / 17  

**Scope-Hinweis:** Forward-Return-Auswertung (Item-F-Kriterium "Monotonie") ist in E.2 (>= 2026-06-20, wenn saubere Post-Race-Fix-Scans 30 d gereift sind und yfinance-Pull lohnt). Hier nur Verteilungs-Sanity (3 von 4 Decision-Kriterien).

---

## 1 — Bucket-Verteilung pro Mapping

Slider-Buckets [0-29, 30-49, 50-69, 70-100]. Faire-Verteilung-Referenz: 4 × 25 %.

| Mapping | 0-29 | 30-49 | 50-69 | 70-100 | Max-Spread (pp) |
|---|---:|---:|---:|---:|---:|
| `linear` | 67.0 % | 31.4 % | 1.6 % | 0.0 % | 67.0 |
| `log10_stretched` | 32.1 % | 34.9 % | 31.4 % | 1.6 % | 33.3 |
| `percentile` | 13.9 % | 18.4 % | 21.8 % | 45.9 % | 32.1 |
| `hybrid` | 67.0 % | 29.2 % | 1.3 % | 2.5 % | 65.7 |

**Decision-Kriterium 1 (Bucket-Spread <96 pp):**
- `linear`: spread 67.0 pp → **PASS**
- `log10_stretched`: spread 33.3 pp → **PASS**
- `percentile`: spread 32.1 pp → **PASS**
- `hybrid`: spread 65.7 pp → **PASS**

## 2 — Hit-Count pro Slider-Threshold (Mittel pro Scan)

Heute live (linear): Slider ≥ 50 ergibt ~6 Hits / Scan. Decision-Kriterium 3: 30–120 Hits ergibt Faktor 5–20×.

| Mapping | ≥ 10 | ≥ 30 | ≥ 50 | ≥ 70 |
|---|---:|---:|---:|---:|
| `linear` | 471.5 | 155.6 | 7.5 | 0.0 |
| `log10_stretched` | 471.5 | 320.0 | 155.6 | 7.5 |
| `percentile` | 436.4 | 406.1 | 319.4 | 216.6 |
| `hybrid` | 471.5 | 155.6 | 18.0 | 11.9 |

**Decision-Kriterium 3 (≥ 50: Faktor 5–20× über Linear):**
- `linear`: 7.5 Hits / Scan (Faktor 1.0×) → **BASELINE**
- `log10_stretched`: 155.6 Hits / Scan (Faktor 20.8×) → **FAIL (zu weit — Slider verliert Filterwirkung)**
- `percentile`: 319.4 Hits / Scan (Faktor 42.7×) → **FAIL (zu weit — Slider verliert Filterwirkung)**
- `hybrid`: 18.0 Hits / Scan (Faktor 2.4×) → **FAIL (zu eng)**

## 3 — Top-Bucket (≥ 70) Belegung

**Decision-Kriterium 4: mind. 1 Hit / Scan im Schnitt der letzten 30 d.**

| Mapping | Hits ≥ 70 in letzten 30 d (Schnitt/Scan) | Scans ohne Top-Hit | Verdict |
|---|---:|---:|---|
| `linear` | 0.00 | 11/11 | **FAIL** |
| `log10_stretched` | 6.27 | 0/11 | **PASS** |
| `percentile` | 132.27 | 0/11 | **PASS** |
| `hybrid` | 9.00 | 0/11 | **PASS** |

## 4 — Kandidaten-Zusammenfassung

Bewertete Kriterien (3 von 4 — Forward-Return-Monotonie in E.2):

| Mapping | Spread | Hit-Count | Top-Bucket | Vorläufig |
|---|:---:|:---:|:---:|---|
| `linear` | — | — | — | Baseline (zum Vergleich) |
| `log10_stretched` | ✓ | — | ✓ | BORDERLINE (2/3) |
| `percentile` | ✓ | — | ✓ | BORDERLINE (2/3) |
| `hybrid` | ✓ | — | ✓ | BORDERLINE (2/3) |

---

## Caveats

- 9 Cold-Start-Scans (Trailing-CDF mit <5 Vortags-Scans): ['2026-04-03', '2026-04-09', '2026-04-10', '2026-04-13', '2026-04-18', '2026-05-21', '2026-05-22', '2026-05-23', '2026-05-24']. Bei `percentile`/`hybrid` sind die Display-Scores dieser Scans aus duenner CDF gebaut — wenig statistische Aussagekraft.
- Pre-Race-Fix-Scans (vor 2026-05-21) basieren auf moeglicherweise unvollstaendigen Composite-Scores (Migration-074-Concurrency-Race). Die Verteilungs-Form selbst sollte aber valide sein, weil die fehlenden Signale eher Score reduzieren als verzerren.
- Forward-Return-Monotonie (Item-F-Kriterium 2) NICHT in diesem Report. Re-Lauf als E.2 nach 2026-06-20.
- KEIN Mapping wird in E.1 zum Live-Switch freigegeben. Selbst ein 3/3-Kandidat braucht E.2 + Item-F-Final-Decision.
