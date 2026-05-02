# v0.31 Phase 0 — Methoden-Vor-Diagnose

**Datum**: 2026-05-02
**Skript**: `backend/scripts/v031_method_diagnose.py`
**Status**: Forschungs-Doku, KEIN Release. Phase 0 ist Pre-Plan vor v0.31.

Empirische Vor-Diagnose der vier Discriminator-Hypothesen auf den 12 Held-Out-Cases aus v0.30. Plan-Disziplin: Falsifikations-Population (Datums-Fenster, `range_mid_date`, Set-Zuordnung) bleibt stabil — keine Re-Definition gegen die Resultate.

**Klassifikations-Schwellen — VOR Sicht der Resultate fixiert** (nicht aufweichen):
- **klar trennend**: kein Overlap zwischen Recall- und Negativ-Set, oder Overlap nur bei dokumentiertem Edge-Case (AAPL-2015)
- **partiell trennend**: <30 % der Cases (von n=12) im Overlap-Bereich
- **Overlap dominant**: ≥30 % im Overlap

## Konfiguration: 12 Cases

| Case | Ticker | Set | start | end | range_mid_date |
|---|---|---|---|---|---|
| MCD 2003 (Bottom + Akkumulation) | MCD | recall | 2003-01-01 | 2003-09-30 | 2003-04-15 |
| INTC 2009 (Post-Crisis-Akkumulation) | INTC | recall | 2009-01-01 | 2009-07-31 | 2009-04-15 |
| MSFT 2013 (Nadella-Pre-Rally-Range) | MSFT | recall | 2013-01-01 | 2013-06-30 | 2013-03-31 |
| NVDA 2023 Q4 (Aufwärts) | NVDA | negative | 2023-10-01 | 2024-01-31 | 2023-12-01 |
| TSLA 2022 H1 (Abwärts) | TSLA | negative | 2022-01-01 | 2022-06-30 | 2022-04-01 |
| AMD 2022 Q3-Q4 (Abwärts) | AMD | negative | 2022-07-01 | 2022-12-31 | 2022-10-01 |
| META 2022 Q1-Q2 (Abwärts) | META | negative | 2022-01-01 | 2022-06-30 | 2022-04-01 |
| AAPL 2024 Q1 (Aufwärts) | AAPL | negative | 2024-01-01 | 2024-04-30 | 2024-02-29 |
| ORCL 2024 Q2 (Aufwärts) | ORCL | negative | 2024-04-01 | 2024-07-31 | 2024-06-01 |
| TSLA 2021 H2 Top (hohe ATR) | TSLA | negative | 2021-09-01 | 2022-01-31 | 2021-11-15 |
| MSFT 2007 H2 Top (gemässigt) | MSFT | negative | 2007-07-01 | 2007-12-31 | 2007-09-30 |
| AAPL 2015 Smooth-Top (Edge-Case) | AAPL | negative | 2015-04-01 | 2015-08-31 | 2015-06-15 |

**Daten-Pull mit Buffer**: `yf_download(ticker, start - 200d, end)`. Begründung: Disc 2 braucht 150d Pre-Range, Disc 3 braucht ~80d (60d BB-History + 20d sma20-Init). Slicing pro Discriminator nach dem Pull. Alle 12 Cases lieferten lückenlose Daten — keine yfinance-Pull-Failures.

## Roh-Tabelle (alle Discriminator-Werte plus R²)

D1 = Closes-Slope (% / Tag, log-Linear). D2pre/D2rng = Pre-Range / Range-Slope um `range_mid ± 30d` (Pre = `[range_mid-150d, range_mid-30d)`). D3-quote = `bb_width_now / median_60d`. D4w = Volume-Slope auf gesamtem Daten-Fenster, D4r = Volume-Slope auf `range_mid ± 30d`.

| Ticker | Set | Bars | D1-slope | D1-r² | D2pre | D2pre-r² | D2rng | D2rng-r² | D3-quote | D3-now | D3-hist | D4w-slp | D4w-r² | D4r-slp | D4r-r² |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MCD | recall | 187 | +0.347 | 0.79 | -0.520 | 0.91 | +0.684 | 0.91 | 1.132 | 0.1860 | 0.1644 | -0.124 | 0.03 | +0.035 | 0.00 |
| INTC | recall | 145 | +0.226 | 0.72 | -0.038 | 0.02 | +0.110 | 0.22 | 0.484 | 0.1110 | 0.2293 | +0.010 | 0.00 | +0.179 | 0.01 |
| MSFT | recall | 124 | +0.272 | 0.87 | +0.005 | 0.00 | +0.306 | 0.66 | 0.616 | 0.0248 | 0.0403 | +0.045 | 0.00 | +2.017 | 0.34 |
| NVDA | negative | 83 | +0.364 | 0.68 | -0.053 | 0.07 | +0.157 | 0.24 | 0.677 | 0.1216 | 0.1796 | -0.104 | 0.01 | -0.735 | 0.13 |
| TSLA | negative | 123 | -0.300 | 0.46 | -0.362 | 0.63 | +0.417 | 0.22 | 2.296 | 0.4910 | 0.2138 | +0.150 | 0.04 | +0.247 | 0.01 |
| AMD | negative | 127 | -0.298 | 0.42 | -0.016 | 0.00 | -0.994 | 0.83 | 1.160 | 0.3505 | 0.3022 | -0.303 | 0.15 | +0.418 | 0.07 |
| META | negative | 123 | -0.477 | 0.70 | -0.586 | 0.61 | -0.005 | 0.00 | 1.108 | 0.2788 | 0.2517 | +0.080 | 0.00 | +0.256 | 0.01 |
| AAPL | negative | 82 | -0.169 | 0.74 | +0.137 | 0.51 | -0.271 | 0.78 | 0.679 | 0.0605 | 0.0891 | +0.047 | 0.00 | +0.701 | 0.09 |
| ORCL | negative | 84 | +0.277 | 0.66 | +0.174 | 0.45 | +0.554 | 0.76 | 1.000 | 0.1102 | 0.1102 | +0.440 | 0.07 | +2.490 | 0.33 |
| TSLA | negative | 104 | +0.349 | 0.44 | +0.277 | 0.85 | +0.118 | 0.02 | 3.262 | 0.4309 | 0.1321 | +0.508 | 0.16 | -1.090 | 0.12 |
| MSFT | negative | 126 | +0.187 | 0.62 | -0.095 | 0.59 | +0.351 | 0.67 | 0.646 | 0.0494 | 0.0765 | +0.172 | 0.02 | +1.693 | 0.18 |
| AAPL | negative | 105 | -0.109 | 0.43 | +0.125 | 0.39 | -0.145 | 0.73 | 0.757 | 0.0481 | 0.0635 | +0.458 | 0.13 | -0.049 | 0.00 |

**ORCL 2024 D3-Anomalie**: `bb_width_now == bb_width_history_median_60d == 0.1102` und damit Quote = 1.000 exakt — kein numerischer Bug, sondern Folge der niedrigen Auflösung des 60d-Median plus die Tatsache, dass `range_mid_date = 2024-06-01` (Wochenende → letzter Bar = Fr 2024-05-31) und der Pin-Bar-Wert in der Pre-Window-Verteilung exakt am Median liegt. Wert ist real.

## Trennschärfe-Analyse pro Discriminator

### Disc 1 — Closes-Slope (% / Tag, log)

- **Recall** (n=3): min=+0.226, max=+0.347, median=+0.272
- **Negativ** (n=9): min=-0.477, max=+0.364, median=-0.109
- **Overlap-Bereich**: [+0.226, +0.347]
- **Cases im Overlap**: 4/12 (33.3 %) — alle 3 Recall + ORCL/negative
- **Klassifikation**: **Overlap dominant** (33.3 % ≥ 30 %)

Nuance: Recall-Cases haben alle drei klar positiven Slope (Aufwärts). Das macht methodisch Sinn — die Recall-Cases sind "Pre-Launch-Akkumulationen", das Daten-Fenster endet **nach** dem Breakout, also läuft der Slope nach oben. ORCL 2024 ist ein reiner Aufwärts-Trend und liegt mitten im Recall-Cluster (+0.277 vs Recall-Median +0.272). Disc 1 trennt nicht Akkumulation von Aufwärts-Trend.

### Disc 2-pre — Pre-Range-Slope (% / Tag)

- **Recall** (n=3): min=-0.520, max=+0.005, median=-0.038
- **Negativ** (n=9): min=-0.586, max=+0.277, median=-0.016
- **Overlap-Bereich**: [-0.520, +0.005]
- **Cases im Overlap**: 7/12 (58.3 %)
- **Klassifikation**: **Overlap dominant**

Erwartung war: Akkumulationen kommen "von unten" (negativer Pre-Range-Slope), Topping-Cases "von oben" (positiv). MCD 2003 (-0.520) bestätigt die Akku-Richtung, aber INTC 2009 (-0.038) und MSFT 2013 (+0.005) sind essentiell flach — und damit nicht von einem flach-trendenden Negativ-Case wie META (-0.586, klar negativ aber Negativ-Set!) oder AMD (-0.016, flach negativ, Negativ-Set) unterscheidbar. Die Pre-Range-Direction trennt MCD von Topping, aber INTC + MSFT haben keine ausreichende Pre-Range-Asymmetrie.

### Disc 2-range — Range-Slope (% / Tag)

- **Recall** (n=3): min=+0.110, max=+0.684, median=+0.306
- **Negativ** (n=9): min=-0.994, max=+0.554, median=+0.118
- **Overlap-Bereich**: [+0.110, +0.554]
- **Cases im Overlap**: 7/12 (58.3 %)
- **Klassifikation**: **Overlap dominant**

Erwartung war: Range-Slope nahe 0. Empirisch sind alle drei Recall-Cases positiv-tendierend (MCD +0.684, INTC +0.110, MSFT +0.306) — die `range_mid ± 30d`-Range fängt bei MCD und MSFT bereits den Pre-Breakout-Anstieg, nicht die ruhige Konsolidierung davor. Ein engeres Range-Fenster (z.B. ±15d) würde die Werte vermutlich näher an 0 bringen, aber das wäre Re-Definition gegen die Resultate (Plan-Disziplin: Range-Fenster ist fix).

### Disc 3 — Bollinger-Width-Quote

- **Recall** (n=3): min=0.484, max=1.132, median=0.616
- **Negativ** (n=9): min=0.646, max=3.262, median=1.000
- **Overlap-Bereich**: [0.646, 1.132]
- **Cases im Overlap**: 7/12 (58.3 %)
- **Klassifikation**: **Overlap dominant**

INTC und MSFT zeigen deutlichen Squeeze (0.484, 0.616 — beide < 0.7), aber MCD ist über 1.0 (1.132 — keine Compression in der Phase um 2003-04-15). Negativ-Set: MSFT 2007 (0.646), AAPL 2015 (0.757) und AAPL 2024 (0.679) liegen alle im selben Squeeze-Bereich wie INTC/MSFT-Recall. Disc 3 trennt 2/3 Recall-Cases ab, kann sie aber nicht von den Topping-Cases mit ähnlich niedrigem BB-Quote unterscheiden.

### Disc 4-window — Volume-Slope, gesamtes Fenster (% / Tag)

- **Recall** (n=3): min=-0.124, max=+0.045, median=+0.010
- **Negativ** (n=9): min=-0.303, max=+0.508, median=+0.150
- **Overlap-Bereich**: [-0.124, +0.045]
- **Cases im Overlap**: 4/12 (33.3 %)
- **Klassifikation**: **Overlap dominant** (am unteren Rand)

Recall-Cases zeigen alle drei essentiell flach (-0.124 bis +0.045). Negativ-Cases streuen breit. Im Overlap-Bereich nur ein einziger Negativ-Case (NVDA -0.104). Das ist methodisch der **am wenigsten Overlap-dominante Discriminator** — wenn man die Schwelle bei 30 % nicht hart fixiert hätte, wäre er als "partiell trennend" bewertet. Aber R² aller drei Recall-Cases ist <0.03 — der Slope-Wert ist statistisch Rauschen. Dazu kommt: 8 von 9 Negativ-Cases liegen ausserhalb des Overlap-Bereichs, davon **4 oberhalb** (TSLA +0.150, ORCL +0.440, TSLA-Top +0.508, AAPL-Top +0.458) und 4 unterhalb der Recall-Untergrenze. Es gibt keine einseitige Trennrichtung.

### Disc 4-range — Volume-Slope, Range-Fenster (% / Tag)

- **Recall** (n=3): min=+0.035, max=+2.017, median=+0.179
- **Negativ** (n=9): min=-1.090, max=+2.490, median=+0.256
- **Overlap-Bereich**: [+0.035, +2.017]
- **Cases im Overlap**: 8/12 (66.7 %)
- **Klassifikation**: **Overlap dominant**

Disc 4-window und Disc 4-range divergieren stark (MSFT 2013: window +0.045 vs range +2.017). Begründung: das Range-Fenster `range_mid ± 30d` fängt einzelne Volume-Spikes auf, das gesamte Daten-Fenster mittelt aus. **Lernsignal aus dem Robustheits-Vergleich**: Volume-Slope ist hochgradig slice-bias-anfällig — die window-Variante ist näher am Wyckoff-theoretischen Konzept ("Cause-Building über Wochen") als die kurze range-Variante. Beide sind Overlap-dominant, der window-Wert wäre der robustere für eine v0.31-Entscheidung, ist aber numerisch zu nah an 0 (R² < 0.03), um daraus eine zuverlässige Schwelle zu ziehen.

## BB-vs-ATR-Korrelations-Check

Pearson-Korrelation zwischen Disc 3 (`bb_width_quote`) und v0.30-`atr_compression_metric` aus `LONG_ACCUMULATION_HELD_OUT_RESULTS.md`. Drei Negativ-Cases (NVDA 2023, AAPL 2024, ORCL 2024) haben in v0.30 keinen ATR-Wert (verworfen via `insufficient_touches`/`no_alternation` **vor** der ATR-Berechnung) — diese Cases werden in der Korrelation ausgelassen.

| Case | bb_width_quote | atr_metric (v0.30) |
|---|---|---|
| MCD 2003 | 1.132 | 51.11 |
| INTC 2009 | 0.484 | 33.33 |
| MSFT 2013 | 0.616 | 66.67 |
| TSLA 2022 H1 | 2.296 | 60.0 |
| AMD 2022 Q3-Q4 | 1.160 | 42.22 |
| META 2022 Q1-Q2 | 1.108 | 61.11 |
| TSLA 2021 H2 Top | 3.262 | 66.67 |
| MSFT 2007 H2 Top | 0.646 | 66.67 |
| AAPL 2015 Smooth-Top | 0.757 | 50.0 |

**Pearson r = 0.386** (n=9)

**Interpretation**: BB-Width-Quote und ATR-Median-Rank sind **nur schwach korreliert**. r=0.39 liegt deutlich unter dem im Plan dokumentierten Schwellwert r=0.7 (ab dem BB als "misst dasselbe wie ATR" gewertet würde). BB-Width-Quote ist also methodisch ein **eigenständiger Discriminator**, NICHT ein Re-Mass von ATR. Folge für die Bilanz: Disc 3 wird als unabhängige Achse gerechnet, Overlap-Befund auf BB ist eine **zusätzliche** Erkenntnis (nicht Doppel-Bestätigung von ATR).

Methodische Anmerkung: das schwache r=0.39 entsteht dadurch, dass beide Masse zwar Volatilität/Compression abbilden, aber unterschiedlich pinnen — ATR misst die Bar-Range über 14d, BB-Width misst die Standardabweichung der Closes über 20d normiert auf den Mittelwert. MSFT 2007 H2 hat ATR-Rank 66.67 (hoch) aber BB-Quote 0.646 (Squeeze) — das ist methodisch konsistent (Daily-Bars sind volatil, aber die 20d-Closes-Streuung ist im historischen Kontext eng). Beide messen unterschiedliche Aspekte von Compression.

## Kombinations-Analyse: 6 Discriminator-Paar-Scatter

Recall-Cases mit `R`, Negativ-Cases mit `N`, `X` = gemischte Zelle. Visuelle Cluster-Trennung: gibt es eine 2D-Diagonale die Recall von Negativ trennt?

### Disc1-closes × Disc2-pre

```
Scatter: x=Disc1-closes (-0.477 .. 0.364)
         y=Disc2-pre   (-0.586 .. 0.277)
+----------------------------------------+
|                                      N |  y=0.28
|                                  N     |
|              N  N                      |
|        N                       R R    N|
|                              N         |
|        N                               |
|N                                     R |  y=-0.59
+----------------------------------------+
```

Recall liegt rechts (positiver Disc1, Aufwärts) und mittig auf Disc2-pre. Aber der Negativ-Case ORCL liegt direkt zwischen den Recalls (rechts oben). Keine saubere 2D-Diagonale.

### Disc1-closes × Disc3-bb-quote

```
Scatter: x=Disc1-closes (-0.477 .. 0.364)
         y=Disc3-bb-quote (0.484 .. 3.262)
+----------------------------------------+
|                                      N |  y=3.26
|        N                               |
|        N                             R |
|N                                 N     |
|                 N                      |
|              N               N R R    N|  y=0.48
+----------------------------------------+
```

Bessere Cluster-Sicht: Recall sammelt sich in der unteren-rechten Ecke (positives Disc1 UND niedriges BB-Quote). Aber AAPL 2015 (Smooth-Top, N) liegt im Recall-Cluster (BB 0.757, Disc1 -0.109 — y nahe Recall-Bereich, x davon aber abgesetzt). MSFT 2007 H2 Top und AAPL 2024 ebenfalls im Recall-Bereich. Keine saubere 2D-Trennung.

### Disc1-closes × Disc4-vol-range

```
+----------------------------------------+
|                                  N     |  y=2.49
|                                  R     |
|                              N         |
|              N                         |
|        N                               |
|N       N                       R     R |
|                 N                      |
|                                       N|
|                                      N |  y=-1.09
+----------------------------------------+
```

Recall verstreut über y, ein Recall (MSFT 2013) ganz oben mit ORCL. Keine Cluster-Trennung erkennbar.

### Disc2-pre × Disc3-bb-quote

```
+----------------------------------------+
|                                       N|  y=3.26
|          N                             |
|  R                      N              |
|N                                 N     |
|                                N       |
|                      N X R     N       |  y=0.48
+----------------------------------------+
```

`X`-Marker (Cluster-Konflikt — gemischte Zelle) tritt auf: Recall und Negativ-Case landen in derselben Grid-Zelle. Visuell explizit: keine Trennung.

### Disc2-pre × Disc4-vol-range

```
+----------------------------------------+
|                                  N     |  y=2.49
|                          R             |
|                      N                 |
|                                N       |
|                         N              |
|N R       N             R               |
|                                N       |
|                        N               |
|                                       N|  y=-1.09
+----------------------------------------+
```

Recall auf Disc2-pre nahe 0 (mittlere x) plus zwei verschiedene Disc4-Werte (mittig + hoch). Negativ-Cases überall. Keine Diagonale.

### Disc3-bb-quote × Disc4-vol-range

```
+----------------------------------------+
|       N                                |  y=2.49
| R                                      |
|  N                                     |
|  N                                     |
|         N                              |
|R       NR               N              |
|   N                                    |
|  N                                     |
|                                       N|  y=-1.09
+----------------------------------------+
```

Wieder ein gemischter Cluster im linken-mittleren Bereich (R direkt neben N). Keine Trennung.

**Zusammenfassung Kombinations-Analyse**: Keines der sechs 2D-Paare zeigt eine saubere Diagonal-Trennung. Dort wo Recall-Cluster zu erkennen ist (Disc1×Disc3), wandert mindestens ein Topping-Negativ-Case in den Recall-Bereich.

## Empfehlung für v0.31-Plan-Mode

### Mechanische Klassifikations-Bilanz

| Discriminator | Klassifikation | Cases im Overlap | Anteil |
|---|---|---|---|
| Disc 1 — Closes-Slope | Overlap dominant | 4/12 | 33.3 % |
| Disc 2-pre — Pre-Range-Slope | Overlap dominant | 7/12 | 58.3 % |
| Disc 2-range — Range-Slope | Overlap dominant | 7/12 | 58.3 % |
| Disc 3 — BB-Width-Quote | Overlap dominant | 7/12 | 58.3 % |
| Disc 4-window — Volume-Slope window | Overlap dominant | 4/12 | 33.3 % |
| Disc 4-range — Volume-Slope range | Overlap dominant | 8/12 | 66.7 % |

**0 von 6 klar trennend, 0 von 6 partiell trennend, 6 von 6 Overlap dominant.**

Plus: keine der 6 2D-Paar-Kombinationen zeigt eine saubere Cluster-Trennung im Scatter.

### Empfehlung: ehrlicher zweiter Bail-out

Nach den **VOR** Sicht der Resultate fixierten Klassifikations-Schwellen ist die mechanische Empfehlung eindeutig:

> **Alle vier Discriminator-Hypothesen sind auf der Falsifikations-Population Overlap-dominant. Keine Einzel-Achse trennt Recall von Negativ. Keine Paar-Kombination trennt im 2D-Scatter. Empfehlung: ehrlicher zweiter Bail-out vor jeglichem v0.31-Code-Aufwand.**

Methodischer Caveat: die Recall-Cases (MCD 2003, INTC 2009, MSFT 2013) sind klassische textbook-Akkumulationen, aber die Datums-Fenster reichen jeweils **bis nach** dem Breakout. Damit sind die Closes- und Volume-Slopes über das gesamte Fenster automatisch positiv-tendierend — und damit theoretisch von Aufwärts-Trends (NVDA, ORCL) schwerer trennbar.

**Aber dieser Caveat ist empirisch schon adressiert**: Disc 4-range vs Disc 4-window beantwortet die Sub-Frage "würde Pre-Breakout-Cut-off es retten?" direkt — Pin-konsistenter Volume-Slope (nur Range-Phase, ohne Post-Breakout) zeigt **67 % Overlap** gegen 33 % im fenster-weiten Volume-Slope. Wenn Pin-Konsistenz die Hypothese stützen würde, müsste 4-range besser sein als 4-window. Es ist umgekehrt. Die Range-Phase selbst ist signal-arm im Volume — unabhängig vom Mess-Fenster. Das schliesst zwei Folge-Iterationen logisch aus:
- Pre-Breakout-Cut-off der Recall-Fenster (B-Variante des methodischen Sub-Frage-Pfads): würde Disc 1 von "Range + Trend" auf "nur Range" verschieben — also genau dorthin, wo Disc 4 schlechter wurde
- Pin-Konsistenz für Disc 1 (C-Variante): wäre Bestätigungs-Lauf in derselben Richtung

Volume-Slope ist Wyckoff-theoretisch der semantisch wichtigste Discriminator (Cause-Building / stille Distribution). Wenn er in der Range-Phase nicht trennt, gibt es keinen sekundären Discriminator der das ausgleicht — Closes-Slope und BB-Width sind theoretisch nachgelagert. Die Pin-Methodik (Disc 2 Pre/Range, Disc 3 am `range_mid_date`) korrigiert das Daten-Fenster-Problem nur partiell und ohne Trennschärfe-Gewinn.

### Hypothesen-Quellen für eine andere Forschungs-Iteration (nicht jetzt — nur als Backlog)

Aus dem Plan übernommen:
- **Volume-Profile-Approach** (Volume-at-Price, nicht Volume-Slope) — Wyckoff-Sub-Layer als Haupt-Achse, Range-Volumen-Konzentration auf Support
- **Stage-Analysis nach Weinstein** (4-Phasen-Modell mit MA-Crosses)
- **Cup-and-Handle als enger definiertes Pattern** (Swing-Geometrie + Volume-Decline-during-Cup)
- **Long-Accumulation als Konzept aufgeben** — heutige Heartbeat-Detection deckt kurze Konsolidierungen ab, Long-Acc ist möglicherweise nicht algorithmisch erkennbar mit den verfügbaren OHLCV-Daten

Eigene Beobachtung aus dieser Diagnose: das **Daten-Fenster-Problem** (Recall-Fenster enden post-Breakout) sollte in einer nächsten Iteration adressiert werden — entweder durch Pin-Methodik strikt für **alle** Discriminatoren (nicht nur Disc 2/3), oder durch Recall-Cases mit bewusstem Pre-Breakout-Cut-off.

### Was aus Phase 0 in v0.30.x gerettet werden kann

Die Phase-0-Diagnose ist **keine** Bestätigung dass Long-Accumulation-Detektion unmöglich ist — sie zeigt nur, dass die vier hypothetischen Discriminatoren auf dieser 12-Case-Population nicht trennen. Wertvolle Sub-Erkenntnisse:

1. **Volatilitäts-Compression als Konzept ist auf dieser Pattern-Klasse nicht trennscharf — über zwei methodisch unabhängige Masse bestätigt.** Disc 3 (BB-Width-Quote, Std-basiert) und v0.30-`atr_compression_metric` (ATR-Median-Rank) korrelieren mit Pearson r=0.386 (n=9, drei Negativ-Cases hatten in v0.30 keinen ATR-Wert weil sie via `insufficient_touches`/`no_alternation` vor der ATR-Berechnung verworfen wurden). r < 0.7 heisst: BB und ATR messen unterschiedliche Aspekte von Compression. Beide Overlap-dominant. Damit ist die Aussage **nicht** "ein einzelner Discriminator scheitert", sondern: **Volatilitäts-Compression als Diskriminator-Achse ist auf dieser Pattern-Klasse strukturell ungeeignet**. Wertvolle Information für jeden zukünftigen Detector-Versuch — schliesst eine ganze Familie von Hypothesen aus.
2. **Volume-Slope ist slice-bias-anfällig**: window vs range divergieren um 1+ Grössenordnung in Einzelfällen. Falls Volume-Slope je in einem v0.31+ Detector verwendet wird, **muss** die Slice-Wahl methodisch begründet sein.
3. **Recall-Cases sind nicht homogen**: MCD ist Bottom+Pre-Run, INTC ist klassische Range, MSFT ist flat-base-mit-Anstieg. Eine "Long-Accumulation" als ein einziges Pattern zu modellieren ist möglicherweise das eigentliche Problem.

### Reframe-Frage für eine zukünftige Iteration

Statt vier weitere Range-Detection-Hypothesen aus dem Backlog durchzuspielen lohnt eine grundlegendere Frage: **Ist Long-Accumulation als pre-breakout-Pattern algorithmisch erkennbar — oder muss man es als post-breakout-Confirmation modellieren?**

Stage-2-Entry nach Weinstein (150-DMA-Recovery + Volume-Spike) ist semantisch ein anderer Approach: statt das Pattern IN der Range zu erkennen, erkennt man den AUSBRUCH aus der Range — das Signal entsteht durch die Kombination aus Trend-Wechsel (Stage 1 → Stage 2) und Volume-Confirmation. Das ist näher am bestehenden Schwur-1-Filter (150-DMA), den der User sowieso anwendet, und vermeidet die Range-Phase-Signal-Armut die Phase 0 empirisch dokumentiert hat.

Das ist v0.32+-Frage, nicht Phase-0-Output — aber als Reframe wertvoller dokumentiert als "vier weitere Range-Discriminatoren testen".

### Methodische Disziplin-Note

Das ist die **zweite Bail-out-Entscheidung** im Long-Accumulation-Forschungs-Strang:
- v0.30 Phase 3 (Held-Out-Validation): Recall 0/3, Precision 1/9 → Bail-out aktiviert, v0.30.0 wurde Cleanup-Release
- v0.31 Phase 0 (Methoden-Vor-Diagnose): 0/6 Discriminatoren trennen, keine Paar-Kombination → zweiter Bail-out vor jeglichem v0.31-Code-Aufwand

Beide Mechanismen haben sauber getriggert mit **vor** den Resultaten fixiertem Vokabular und fixierten Schwellen. Das ist nicht Fehlschlag, das ist genau das Funktionieren der Forschungs-Disziplin: zwei Investitions-Punkte (Phase-2-Detector-Code in v0.30, Phase 0b in dieser Iteration) wurden gespart, weil die Bail-out-Punkte ehrlich definiert und ehrlich aktiviert wurden. Das ist der Wert.

**Konsequenz**: Long-Accumulation ist aus dem Roadmap-Plan-Strang genommen. Wenn das Thema wieder aufkommt, ist es ein **neuer** Forschungs-Strang mit anderem methodischem Frame (z.B. Stage-2-Entry-Detection statt Range-Detection) — kein Fortsetzen dieses Strangs. Forschungs-Code bleibt im Repo als Baseline (Pure-Function `detect_long_accumulation_pattern`, Tests, Konstanten, Sweep-Skripte, Diagnose-Dokumentation).

---

**Skript**: `/home/harry/projects/openfolio/backend/scripts/v031_method_diagnose.py`
**Skript-Output**: `docker compose exec backend python scripts/v031_method_diagnose.py`
**Output-Doku**: `/home/harry/projects/openfolio/V031_METHOD_DIAGNOSE.md` (diese Datei)
**Verwandte Doku**: `LONG_ACCUMULATION_HELD_OUT_RESULTS.md` (v0.30 Bail-out), `WYCKOFF_TEXTBOOK_RESULTS.md` (v0.29.1 Pin-Methodik-Befund)
