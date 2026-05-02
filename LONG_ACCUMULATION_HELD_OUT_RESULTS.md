# Long-Accumulation Held-Out + Negativ-Set Validation (v0.30 Phase 3)

**Datum**: 2026-05-02
**Detector**: `detect_long_accumulation_pattern()` (v0.30 Phase 2)
**Skript**: `backend/scripts/long_accumulation_held_out_check.py`

Phase 3 ist der **Bail-Out-Punkt** vor dem Logging-Stack (Phase 4). Recall + Precision werden auf zwei separaten Sets validiert (Held-Out, NICHT der ursprüngliche Sweep aus Phase 1).

## Konfiguration

**Detector-Version**: `1.0` (`LONG_ACCUMULATION_DETECTOR_VERSION`)

**Schwellen-Snapshot** (`backend/services/analysis_config.py`):

| Konstante | Wert |
|---|---|
| `LONG_ACCUMULATION_LOOKBACK_DAYS` | 180 |
| `LONG_ACCUMULATION_MIN_DURATION_DAYS` | 60 |
| `LONG_ACCUMULATION_MIN_RANGE_PCT` | 0.05 |
| `LONG_ACCUMULATION_RANGE_TOLERANCE` | 0.03 |
| `LONG_ACCUMULATION_ATR_PERIOD` | 14 |
| `LONG_ACCUMULATION_ATR_HISTORY_DAYS` | 90 |
| `LONG_ACCUMULATION_ATR_PERCENTILE` | 50 |
| `LONG_ACCUMULATION_ATR_RANK_WINDOW` | 60 (= MIN_DURATION_DAYS) |
| `LONG_ACCUMULATION_SWING_LOOKBACK` | 5 |
| `LONG_ACCUMULATION_MIN_HIGH_TOUCHES` | 3 |
| `LONG_ACCUMULATION_MIN_LOW_TOUCHES` | 3 |

**Methodik-Notiz**: Der Detector nutzt **Rolling-Median-ATR-Percentile** (Median der Per-Bar-Ranks über die letzten 60 Bars) statt Spot-ATR — Phase-1.5-Befund: Spot-ATR im Window-End-Modus zeigte Akku-Cases bei Percentile 99/83 (Slice-Bias).

## Recall-Tabelle (3 textbook-Akkumulationen)

Erwartung: `detected=True` UND `wyckoff.score == +1`.

| Case | Ticker | Bars | Detected | Reason | ATR-Median-Rank | ATR-Ratio | Match |
|---|---|---|---|---|---|---|---|
| MCD 2003 (Bottom + Akkumulation) | MCD | 187 | False | `no_compression` | 51.11 | 1.022 | NO |
| INTC 2009 (Post-Crisis) | INTC | 145 | False | `no_alternation` | 33.33 | 0.667 | NO |
| MSFT 2013 (Nadella-Pre-Rally) | MSFT | 124 | False | `no_compression` | 66.67 | 1.333 | NO |

**Recall-Score**: **0/3** detected — kein Case erfüllt die Detected+Score=+1-Bedingung.

## Negativ-Tabelle (9 Trend-/Topping-Slices)

Erwartung: `detected=False`.

| Case | Ticker | Bars | Detected | Reason | ATR-Median-Rank | Wy-Score | Match |
|---|---|---|---|---|---|---|---|
| NVDA 2023 Q4 (Aufwärts) | NVDA | 83 | False | `insufficient_touches` | – | – | YES |
| TSLA 2022 H1 (Abwärts) | TSLA | 123 | False | `no_compression` | 60.0 | – | YES |
| AMD 2022 Q3-Q4 (Abwärts) | AMD | 127 | False | `insufficient_touches` | 42.22 | – | YES |
| META 2022 Q1-Q2 (Abwärts) | META | 123 | False | `no_compression` | 61.11 | – | YES |
| AAPL 2024 Q1 (Aufwärts) | AAPL | 82 | False | `insufficient_touches` | – | – | YES |
| ORCL 2024 Q2 (Aufwärts) | ORCL | 84 | False | `no_alternation` | – | – | YES |
| TSLA 2021 H2 Top (hohe ATR) | TSLA | 104 | False | `no_compression` | 66.67 | – | YES |
| MSFT 2007 H2 Top (gemässigt) | MSFT | 126 | False | `no_compression` | 66.67 | – | YES |
| **AAPL 2015 Smooth-Top (niedrige ATR)** | AAPL | 105 | **True** | – | 50.0 | 0 (neutral) | **NO** |

**Precision-Score (false-positives)**: **1/9** — nur AAPL 2015 Smooth-Top feuert (erwartungsgemäss der Edge-Case).

## Validation-Note (nach Plan-Skala)

| Achse | Score | Vokabular |
|---|---|---|
| **Recall** | 0/3 | **Reichweite zu eng (0/3)** |
| **Precision** | 1/9 false-positives | **Precision-validiert (1/9)** |

**Ship-Bedingung** (Recall ≥1/3 UND Precision ≤2/9): **NEIN — BAIL-OUT.**

Die Ship-Bedingung scheitert an der Recall-Achse, NICHT an Precision. Das Negativ-Set hat den Detector hart bestraft (1/9 false-positive, gut), aber das Recall-Set hat 0/3 erbracht — der Detector ist zu eng.

## Methodische Beobachtungen

### 1. Recall-Miss-Analyse

Alle drei Recall-Cases verworfen, aber aus **drei unterschiedlichen Gründen** — das ist eine wertvolle Diagnose:

- **MCD 2003** (`no_compression`, ATR-Median-Rank **51.11**): Nur **0.11 Punkte** über der Schwelle 50. Der Akku-Charakter ist da, der ATR-Filter ist im Border-Bereich. Eine moderate Lockerung würde MCD reinholen.
- **INTC 2009** (`no_alternation`, ATR-Median-Rank **33.33**): ATR-Filter qualifiziert deutlich (33 < 50). Der Detector wird hier durch den Alternations-Check verworfen — drei gleichartige Touches in Folge. Das ist ein **Geometrie-Filter**, nicht ATR. INTC würde auch bei laxerer ATR-Schwelle nicht reinkommen.
- **MSFT 2013** (`no_compression`, ATR-Median-Rank **66.67**): Deutlich über Schwelle (16.67 Punkte). Volatilität in diesem Slice ist tatsächlich hoch — die Range zieht sich nicht ruhig durch.

**Kernbefund**: Die ATR-Compression-Achse ist als alleiniger Discriminator nicht trennscharf. Phase-1.5 hatte gewarnt (Spread AMD 37 / NVDA 43 → Spread klein, aber MCD 51 / MSFT 67 zeigt: andere Akku-Cases liegen weit höher). Der Diskriminator-Validitäts-Check war richtig konservativ.

### 2. Edge-Case AAPL 2015 Smooth-Top — der Blind Spot

AAPL 2015 wurde detected — geometrisch wie eine Akkumulation, ATR-Median-Rank exakt **50.0** (an der Schwelle), Range 6.09% über 94 Tage, 3+3 Touches alterniert sauber. **Wyckoff-Score = 0 (neutral)**, Volume-Slope leicht negativ (-0.025% pro Tag).

Das ist der vorhergesagte Blind Spot aus dem Plan: Smooth-Topping mit niedriger ATR ist geometrisch von Akkumulation nicht trennbar **ohne** zusätzlichen Pre-Range-Direction-Filter oder Wyckoff-Score-Co-Filter (`detected = detected AND wyckoff.score >= 0` würde AAPL 2015 mit Score 0 nicht stoppen, aber bei Score=-1 würde es greifen).

**Konkrete v0.31.x-Optionen, dokumentiert für späteren Release**:
- **Pre-Range-Direction-Filter**: Trend-Slope der 90 Bars VOR dem Range-Beginn. Akkumulation hat vorher Down/Flat (Crash + Bottom), Topping hat vorher Up.
- **Wyckoff-Score-Co-Filter**: `detected = base_detected AND wyckoff.score in {0, +1}` würde Distributions mit klarem Score=-1 hart kicken. Gegen AAPL 2015 (Score 0) wirkt das aber nicht.
- **Volume-Slope-Co-Filter**: Distributions tendieren zu steigendem Volume. AAPL 2015 zeigte hier Slope -0.025% (also fallend) — der Co-Filter würde AAPL 2015 NICHT kicken. Methodisch unzureichend für diesen Case.

### 3. Vergleich Recall vs. Negativ — ATR-Achse

Erwartung war: Recall-Cases haben geringe `atr_compression_metric` (<50), Negativ-Cases liegen höher.

Beobachtung in der Realität:

| Set | Cases mit Metric | Median ATR-Rank | Range |
|---|---|---|---|
| Recall | 3 | **51.1** | 33.3 – 66.7 |
| Negativ | 5 (mit Metric) | **61.1** | 42.2 – 66.7 |

Die Verteilungen **überlappen** stark. Der ATR-Compression-Median ist als Discriminator empirisch nicht ausreichend trennscharf — Recall und Negativ-Set teilen den Bereich 42–67. Das bestätigt den Phase-1-Diskriminator-Validitäts-Befund.

### 4. yfinance pre-2010 Daten

`MSFT 2007`, `AAPL 2015` (auto_adjust=True) lieferten lückenlose Bars. Pre-2010 Splits-Korrekturen wirken sauber. Keine Daten-Pull-Failures, kein Reserve-Case-Einsatz nötig.

## BAIL-OUT — v0.30.0 ist NICHT ship-fähig

**Plan-Disziplin**:
- KEIN Re-Tuning gegen das Negativ-Set (Negativ-Set behält Falsifikations-Kraft).
- KEIN Re-Tuning der ATR-Schwelle nur um MCD reinzuholen — das wäre Tuning gegen das Recall-Set.
- Logging-Stack (Phase 4) wird **nicht** gebaut, solange der Detector nicht ship-fähig ist (Plan: "Logging wird erst gebaut wenn Schwellen final sind").

**Empfehlungen für v0.30.x** (kein Tuning, sondern strukturelle Erweiterung):

1. **Erweiterte Phase-1-Diagnose**: ATR-Percentile-Diagnose auf das vollständige Negativ-Set + Recall-Set zusammen ausführen. Wenn keine saubere Trennung existiert, ist ATR allein nicht ausreichend — Erkenntnis steht dann formell.

2. **Discriminator-Erweiterung als v0.30.x**: Zusätzliche Achsen prüfen, vor allem **Pre-Range-Direction-Filter** (Slope der 90 Bars vor Range-Beginn). Der Geometrie-Anteil "no_alternation"/"insufficient_touches" hat das Negativ-Set bereits gut weggefiltert (6/9 ohne ATR-Beitrag), die Schwäche liegt klar bei smooth-top vs. flat-bottom in der Volatilitäts-Achse.

3. **Alternative Detektor-Variante**: `detect_long_accumulation_pattern_v2` mit `wyckoff.score`-Co-Filter und Pre-Range-Direction. Eigenes Held-Out-Skript, eigener Bail-Out-Punkt.

Logging-Stack (Phase 4) und Frontend (Phase 5) bleiben **on hold** bis ein Detector existiert, der die Ship-Bedingung erfüllt.

---

**Skript-Output**: `docker compose exec backend python scripts/long_accumulation_held_out_check.py`
**Backup-Cases**: ORCL 2002 / CSCO 2002 (NICHT eingesetzt — alle Recall-Daten lückenlos verfügbar).
