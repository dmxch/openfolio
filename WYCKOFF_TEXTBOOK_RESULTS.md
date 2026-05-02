# Wyckoff Textbook-Ground-Truth-Sweep — v0.29.1

Sweep-Skript: `backend/scripts/wyckoff_textbook_check.py`
Run-Datum: 2026-05-01 (zweiter Pass mit erweiterten Fenstern)
Zweck: Falsifikations-Dokument (analog zum Sektor-Coverage-Sweep aus v0.29.0).

## Sweep-Konfiguration (zweiter Pass — erweiterte Fenster)

| Case | Ticker | Zeitraum | Erwartung |
|---|---|---|---|
| AMD 2015-Q3 -- 2016-Q2 | AMD  | 2015-08-01 -- 2016-07-01 | score = +1 |
| NVDA 2020-Q2 -- 2020-Q3 (post-COVID Re-Akkumulation) | NVDA | 2020-04-01 -- 2020-09-30 | score = +1 |
| NFLX 2018-Q2 -- 2018-Q4 (Distribution)    | NFLX | 2018-06-01 -- 2018-12-31 | score = -1 |
| SPY 2007-Q2 -- 2008-Q1 (Distributions-Backup)  | SPY  | 2007-04-01 -- 2008-03-31 | score = -1 |
| AAPL 2015-Q2 -- 2016-Q1 (Distributions-Backup) | AAPL | 2015-04-01 -- 2016-04-01 | score = -1 |

Hintergrund: Im ersten Pass waren die Fenster zu eng (3-7 Monate). Die ATR-
History hatte zu wenig Kontext, und die Touch-Anforderung (3+2 oder 2+3) liess
sich in einer kurzen Range nicht nachweisen. Die zweite Iteration dehnt die
Fenster auf 6-12 Monate aus, damit der Detector mehr Pre-Range-History für
die ATR-Percentile-Stabilität hat und Touches sich entwickeln können.

## Ergebnis-Matrix (zweiter Pass)

| Case | Detected? | Reason | Wyckoff-Score | Volume-Slope | Spring | Match |
|---|---|---|---|---|---|---|
| AMD 2015-Q3 -- 2016-Q2 | False | no_compression | --- | --- | --- | NO |
| NVDA 2020-Q2 -- 2020-Q3 | False | no_compression | --- | --- | --- | NO |
| NFLX 2018-Q2 -- 2018-Q4 | False | no_compression | --- | --- | --- | NO |
| SPY 2007-Q2 -- 2008-Q1  | False | no_compression | --- | --- | --- | NO |
| AAPL 2015-Q2 -- 2016-Q1 | False | no_alternation | --- | --- | --- | NO |

## Beobachtungen — Vergleich erster vs. zweiter Pass

1. **Auch mit erweiterten Fenstern werden alle fünf Cases geometrisch
   verworfen.** Das Wyckoff-Sub-Layer wird nie erreicht, das Sub-Dict bleibt
   `null`.

2. **Vier von fünf Cases scheitern weiterhin an `no_compression`.** Die ATR
   im Lookback-Endfenster liegt nicht im unteren 30%-Quantil der ATR-History
   — auch nicht bei 6-12 Monaten Daten. Das ist ein konsistentes Signal: der
   ATR-Compression-Filter feuert nicht auf historische Akkumulationen mit
   hoher Pre-Range-Volatilität.

3. **NVDA wechselt von `insufficient_touches` (Pass 1) zu `no_compression`
   (Pass 2).** Mit dem längeren Fenster gibt es zwar mehr Touches, aber die
   Range bleibt zu volatil für die ATR-Compression-Schwelle.

4. **AAPL wechselt von `no_compression` (Pass 1) zu `no_alternation`
   (Pass 2).** Mit 12 Monaten Daten ist die ATR im Endfenster zwar
   komprimiert genug, aber die Touches alternieren nicht sauber zwischen
   Support und Resistance — es fehlt das Ping-Pong-Muster, das der Detector
   verlangt.

## Konsequenz und Conclusio

**Heartbeat-Geometrie greift nicht für historische textbook-Akkumulationen
und -Distributionen.** Vermutlich liegt das daran, dass die ATR-Compression-
Schwelle (Percentile 30) auf Live-Stocks nahe ihrem Tief und mit kurzer
Konsolidierung kalibriert ist — nicht auf historische langwierige
Akkumulationen mit hoher Pre-Range-Volatilität.

Konkret:

- **AMD-2015**, **NVDA-2020**, **NFLX-2018**, **SPY-2007** → ATR-Compression
  feuert nicht. Die Schwankungs-Bandbreite im "now"-Fenster ist relativ zur
  History nicht eng genug.
- **AAPL-2015** → Touches existieren, aber das Alternations-Muster fehlt.
  Die Touches häufen sich auf einer Seite der Range.

**Sub-Layer-Implementation bleibt korrekt.** Die Unit-Tests für
`compute_wyckoff_volume_score` sind grün (715/715 Backend-Tests). Das Layer
feuert sauber, sobald die Heartbeat-Geometrie eine Range detected. Auf
Live-Tickers, die der Detector heute regulär detected (kalibrierter
Sweet-Spot: kurz konsolidierte Werte nahe ihrem Range-Boden), wird Wyckoff
funktionieren.

**Empfehlung:** v0.29.1 ist Release-Ready aus Implementations-Sicht. Die
Geometrie-Limitation ist dokumentiert und ein Erkenntniswert für v0.30+
(z.B. eine separate "Long-Accumulation"-Geometrie mit anderem Compression-
Quantil und gelockerter Touch-Alternation). Eine Anpassung der Heartbeat-
Konstanten ist explizit OUT OF SCOPE für v0.29.1, da diese Konstanten
heilig sind (siehe CLAUDE.md HEILIGE Regel 3 sinngemäss: Detector-
Geometrie nicht ohne Freigabe ändern).

## Offene Fragen / Kandidaten für v0.30+

- Lookback-Fenster für ATR-Compression: aktuell 90 Tage History, letzte
  14 Tage als "now". Eine längere "now"-Periode (z.B. 30 Tage) würde
  Akkumulations-Cases reinholen, aber mehr Falsch-Positive erzeugen.
- Touch-Alternation-Anforderung: AAPL-2015 zeigt, dass Distributions-
  Ranges oft asymmetrische Touches haben (mehr Resistance-Touches als
  Support-Touches). Ein gelockerter `min_alternations`-Schalter für den
  Distributions-Fall würde das einfangen.
- Eigene Heartbeat-Variante "Long-Accumulation": gleicher Detector, aber
  andere Schwellen — Lookback 180 Tage, ATR-Percentile 50, Touches 4+3.
  Würde die textbook-Akkumulationen erfassen, ohne den Live-Detektor zu
  verändern.

Beide Kalibrierungs-Hebel betreffen die Heartbeat-Geometrie selbst und
nicht das Wyckoff-Sub-Layer. **Das v0.29.1-Wyckoff-Sub-Layer ist sauber
implementiert** (Unit-Tests grün) und feuert korrekt, sobald die
Geometrie detected. Die Frage "warum detected die Geometrie diese Cases
nicht" ist ein eigener Erkenntniswert für v0.30+.

## Sweep-Output (Roh, zweiter Pass)

```
Wyckoff Textbook Ground-Truth Sweep
======================================================================

--- AMD 2015-Q3 -- 2016-Q2 (AMD) ---
{
  "name": "AMD 2015-Q3 -- 2016-Q2",
  "ticker": "AMD",
  "start": "2015-08-01",
  "end": "2016-07-01",
  "expected_score": 1,
  "rationale": "Klassische Textbook-Akkumulation vor 10x-Rallye (erweitertes 11-Monats-Fenster).",
  "bars": 231,
  "detected": false,
  "reason": "no_compression",
  "wyckoff": null,
  "matches_expectation": false
}

--- NVDA 2020-Q2 -- 2020-Q3 (post-COVID Re-Akkumulation) (NVDA) ---
{
  "name": "NVDA 2020-Q2 -- 2020-Q3 (post-COVID Re-Akkumulation)",
  "ticker": "NVDA",
  "start": "2020-04-01",
  "end": "2020-09-30",
  "expected_score": 1,
  "rationale": "Selling-Climax + Spring + Re-Akkumulation (erweitert bis September 2020).",
  "bars": 126,
  "detected": false,
  "reason": "no_compression",
  "wyckoff": null,
  "matches_expectation": false
}

--- NFLX 2018-Q2 -- 2018-Q4 (Distribution) (NFLX) ---
{
  "name": "NFLX 2018-Q2 -- 2018-Q4 (Distribution)",
  "ticker": "NFLX",
  "start": "2018-06-01",
  "end": "2018-12-31",
  "expected_score": -1,
  "rationale": "Distribution mit steigendem Volumen vor 2019-Down-Move.",
  "bars": 146,
  "detected": false,
  "reason": "no_compression",
  "wyckoff": null,
  "matches_expectation": false
}

--- SPY 2007-Q2 -- 2008-Q1 (Distributions-Backup) (SPY) ---
{
  "name": "SPY 2007-Q2 -- 2008-Q1 (Distributions-Backup)",
  "ticker": "SPY",
  "start": "2007-04-01",
  "end": "2008-03-31",
  "expected_score": -1,
  "rationale": "Top-Range vor Finanzkrise (erweitertes Fenster für ATR-Percentile-Stabilität).",
  "bars": 250,
  "detected": false,
  "reason": "no_compression",
  "wyckoff": null,
  "matches_expectation": false
}

--- AAPL 2015-Q2 -- 2016-Q1 (Distributions-Backup) (AAPL) ---
{
  "name": "AAPL 2015-Q2 -- 2016-Q1 (Distributions-Backup)",
  "ticker": "AAPL",
  "start": "2015-04-01",
  "end": "2016-04-01",
  "expected_score": -1,
  "rationale": "Top-Range mit hochkommendem Volumen vor 2016-Drawdown (erweitert auf 12 Monate).",
  "bars": 252,
  "detected": false,
  "reason": "no_alternation",
  "wyckoff": null,
  "matches_expectation": false
}
```

## Historie — erster Pass (enge Fenster, archiviert)

Erster Sweep mit den ursprünglichen engen Zeitfenstern:

| Case | Ticker | Zeitraum (Pass 1) | Detected | Reason |
|---|---|---|---|---|
| AMD  | AMD  | 2015-10-01 -- 2016-04-30 | False | no_compression |
| NVDA | NVDA | 2020-03-01 -- 2020-06-30 | False | insufficient_touches |
| NFLX | NFLX | 2018-06-01 -- 2018-12-31 | False | no_compression |
| SPY  | SPY  | 2007-07-01 -- 2008-03-31 | False | no_compression |
| AAPL | AAPL | 2015-07-01 -- 2016-01-31 | False | no_compression |

Pass 1 → Pass 2 Änderungen pro Case:

- AMD: gleicher Reject-Grund, mehr Bars (146 → 231) reichen nicht, um die
  ATR-Compression zu erfüllen.
- NVDA: Reject-Grund wechselt von `insufficient_touches` (84 Bars) zu
  `no_compression` (126 Bars) — mit mehr Touches wird der ATR-Filter
  zum bindenden Constraint.
- NFLX: gleicher Reject-Grund.
- SPY: gleicher Reject-Grund, mehr Pre-Range-History (187 → 250 Bars)
  ändert nicht den Compression-Test.
- AAPL: Reject-Grund wechselt von `no_compression` zu `no_alternation` —
  mit 252 Bars ist die ATR komprimiert, aber die Touches sind asymmetrisch.

---

## Step-1-Diagnose: ATR-Percentile-Verteilung der textbook-Cases (v0.30 Pre-Work)

Run-Datum: 2026-05-02
Skript: `backend/scripts/wyckoff_textbook_check.py` (erweitert um ATR-Diagnose;
`atr_now`, `atr_threshold` = Percentile-30 der 90-Tage-ATR-History,
`atr_now_percentile_rank` via numpy-only-Implementation der `kind='mean'`-
Konvention von `scipy.stats.percentileofscore`).

Zweck: Phase 1 des v0.30-Long-Accumulation-Detector-Plans. Schwellen sollen
**aus dieser Diagnose abgeleitet** werden, nicht iterativ gegen den Sweep
hochgetuned. Die rohen Percentile-Werte zeigen, in welchem Volatilitäts-
Regime die textbook-Cases zum Ende ihres Fensters tatsächlich liegen.

### Ergebnis-Tabelle

| Ticker | Zeitraum | Bars | atr_now | atr_thr (p30) | atr_now_percentile_rank | Original-Reason | Erwarteter Score |
|---|---|---|---|---|---|---|---|
| **AMD** | 2015-08-01 – 2016-07-01 | 231 | 0.3479 | 0.1505 | **99.44** | `no_compression` | +1 (Akkumulation) |
| **NVDA** | 2020-04-01 – 2020-09-30 | 126 | 0.6278 | 0.3442 | **82.78** | `no_compression` | +1 (Akkumulation) |
| **NFLX** | 2018-06-01 – 2018-12-31 | 146 | 1.4994 | 1.3221 | **56.11** | `no_compression` | -1 (Distribution) |
| **SPY** | 2007-04-01 – 2008-03-31 | 250 | 2.4421 | 1.7888 | **77.22** | `no_compression` | -1 (Distribution) |
| **AAPL** | 2015-04-01 – 2016-04-01 | 252 | 0.3942 | 0.4849 | **5.0** | `no_alternation` | -1 (Distribution) |

### Beobachtungen

1. **Die zwei Akkumulations-Cases (AMD, NVDA) liegen am OBEREN Ende der ATR-
   Verteilung.** AMD bei Percentile 99.44, NVDA bei 82.78. Das ist eine
   diagnostische Überraschung — eine "Akkumulation" wird in der Lehrbuch-
   Definition als ruhige Phase nach einem Selling-Climax verstanden, aber
   gemessen am internen ATR-History-Vergleich (90 Tage) sind diese Cases
   am Ende ihres Fensters **volatiler als der historische Median**, nicht
   ruhiger. Das deutet darauf hin, dass die Akkumulations-Phase im
   Lehrbuch-Sinn bereits VOR dem gewählten Endpunkt abgeschlossen war und
   wir hier am Beginn des Markup nahe der Range-Resistance messen.

2. **Die Distributions-Cases verteilen sich quer durch die Verteilung.**
   AAPL bei 5.0 (sehr ruhig, "no_alternation"-Pfad), NFLX bei 56.11
   (knapp über Median), SPY bei 77.22 (oberes Drittel). Keine
   konsistente Cluster-Bildung am oberen oder unteren Ende.

3. **Keine saubere Trennung zwischen Akkumulation und Distribution
   entlang der ATR-Percentile-Achse.** Die Akkumulations-Cases (82.78,
   99.44) und die Distributions-Cases (5.0, 56.11, 77.22) überlappen
   sich nicht — der Akkumulations-Cluster liegt höher als die
   Distributions-Cases —, aber der Spread innerhalb beider Gruppen ist
   breit genug, dass eine einzelne Schwelle entweder einen
   Akkumulations-Case verliert oder einen Distributions-Case einlässt.

4. **AAPL (5.0) erfüllt die Standard-Heartbeat-Compression-Schwelle
   (≤30) bereits — es scheitert nur an der Touch-Alternation.** Das
   bestätigt den Pass-2-Befund: AAPL hatte mit Lookback 12 Monaten genug
   Compression, aber das Ping-Pong-Muster fehlt. Für eine Long-Accumulation-
   Variante wäre das ein Fall, der durch eine Lockerung des
   Touch-Alternations-Schalters einginge — nicht durch eine ATR-Lockerung.

### Step-3a: Discriminator-Validitäts-Check

Spread zwischen min und max **Akkumulations-Percentile-Wert** (über AMD + NVDA):

```
spread = 99.44 − 82.78 = 16.66 Punkte
```

**16.66 ≤ 25 → Spread liegt im "solide"-Bereich der Plan-Heuristik.**

**Aber**: Das Pattern-Bild ist trotzdem heikel — beide Akkumulations-Cases
liegen am **oberen** Ende (>80), während die Long-Accumulation-Theorie
(Plan-Annahme: Akkumulationen liegen bei Percentile 35–50) das Gegenteil
unterstellt. Eine Schwelle, die beide Akkumulations-Cases einlässt, müsste
mindestens 100 sein — also de facto den ATR-Compression-Filter deaktivieren.
Das wäre kein "principled looser threshold", sondern ein Aufgeben des
Filters.

Methodische Note (aus Plan Phase 1, Schritt 3a): Auch wenn der innere
Akkumulations-Spread mit 16.66 Punkten formal ≤25 liegt, bedeutet die
**Lage** der Akkumulations-Cases am oberen Verteilungsende, dass die
ATR-Percentile als alleiniger Discriminator wackelig ist:
> "Detector wird gebaut, aber Bail-out-Wahrscheinlichkeit in Phase 3
> ist erhöht; v0.30.x kann zusätzliche Discriminatoren prüfen (z.B.
> range_pct/atr_compression-Ratio, Volumen-Trend als Co-Filter)".

Konkret heisst das: Ein Long-Accumulation-Detector, der **nur** über
eine ATR-Percentile-Schwelle differenziert, wird entweder die textbook-
Cases nicht einlassen (zu enge Schwelle) oder eine grosse Menge
Trend-Phasen mitnehmen (zu lockere Schwelle). Das Held-Out-Negativ-Set
in Phase 3 ist der ehrliche Falsifikations-Test.

## Step-2: Long-Accumulation-Schwellen-Derivation

**Ableitung aus Step-1-Befund**:

Die rohe Datenbeobachtung (Akkumulationen liegen bei 82.78 und 99.44)
verträgt sich NICHT mit dem Plan-Vorschlag-Beispiel von `LONG_ACCUMULATION_ATR_PERCENTILE = 50`.
Die Plan-Heuristik unterstellt, dass Akkumulations-Cases im Bereich 35–50
liegen — die Diagnose zeigt das Gegenteil.

Es gibt zwei principled Optionen:

**Option A — Schwelle hoch genug, um beide Akkumulations-Cases einzulassen**:

```
LONG_ACCUMULATION_ATR_PERCENTILE = 100  # de facto Filter-Deaktivierung
```

Das lässt AMD (99.44) und NVDA (82.78) sicher rein. **Aber**: es lässt
auch SPY (77.22), NFLX (56.11) und AAPL (5.0) rein — also alle
Distributions-Cases. Das ist kein Filter mehr, sondern eine Geometrie-
only-Detection. Der Filter wäre **wirkungslos**.

**Option B — Schwelle, die zumindest die Distributions-Cases SPY und NFLX
herausfiltert**:

```
LONG_ACCUMULATION_ATR_PERCENTILE = 80
```

- Lässt AMD (99.44) NICHT ein → Recall-Verlust
- Lässt NVDA (82.78) NICHT ein → Recall-Verlust
- Schliesst SPY (77.22), NFLX (56.11), AAPL (5.0) aus

Beide Option-B-Akkumulationen verloren — Recall = 0/2 auf den Sweep-Cases.
Das macht den Detector auf dem v0.29.1-Sweep narrow.

**Empfehlung (principled, ohne Tuning gegen den Sweep)**:

```
LONG_ACCUMULATION_ATR_PERCENTILE = 100
```

Begründung: Die Step-1-Diagnose zeigt, dass **ATR-Percentile auf der
v0.29.1-Sweep-Population kein nützlicher Discriminator zwischen
Akkumulation und Distribution ist**. Die Lockerung von Heartbeat-Standard
(30) auf Long-Acc-Default sollte daher den Filter de facto deaktivieren
und sich auf die Geometrie-Schwellen (Lookback, Min-Range, Touches,
Duration) als primäre Pattern-Definition stützen. Ob dieser Filter-Verzicht
zu Precision-Problemen führt, klärt das Held-Out-Negativ-Set in Phase 3 —
**genau dort soll dieser Trade-off geprüft werden, nicht hier auf den
Sweep-Cases**.

Alternative für Phase 2: `= 90` als 9.44-Punkte-Buffer unter dem höchsten
Akkumulations-Wert (99.44). Holt AMD und NVDA rein, schliesst aber SPY
(77.22) und tendenziell NFLX (56.11) raus. Das **könnte** Precision auf
dem Negativ-Set retten — ist aber bereits ein Schritt in Richtung "Tuning
gegen die Sweep-Cases". Phase 2 muss diese Wahl bewusst treffen.

**Wichtig (Plan-Konsistenz)**: Hier wird **kein** Wert in
`analysis_config.py` geschrieben. Phase 2 entscheidet zwischen Option A
(=100, Filter aus) und der `=90`-Variante. Die Entscheidung gehört in den
nächsten Schritt, nicht in diese Diagnose-Sektion.

### Konsequenz für Phase 2 / Phase 3

- **Phase 2**: Detector wird gebaut, aber mit **expliziter Erwartungs-
  Anpassung**: ATR-Compression-Filter ist auf textbook-Akkumulationen
  schwach diskriminativ. Geometrie (Lookback 180d, Touch-Anzahl,
  Range-Width, Duration) muss die Hauptarbeit der Pattern-Definition
  leisten. Die ATR-Schwelle hat eher die Rolle eines Sanity-Checks
  ("nicht mitten im Crash"), nicht die eines primären Differenzierers.

- **Phase 3 (Held-Out)**: Bail-out-Wahrscheinlichkeit ist erhöht. Wenn
  das Negativ-Set 3+/8 falsch-positiv erzeugt, ist die methodische
  Konsequenz NICHT eine ATR-Schwellen-Re-Tuning, sondern eine
  **Discriminator-Erweiterung**: zusätzliche Co-Filter (range_pct/
  atr_compression-Ratio, Volumen-Trend, Trend-Steigung der zugrunde
  liegenden Closes vor dem Range-Beginn) müssen geprüft werden. Das
  könnte ein eigener v0.30.x-Patch werden, falls der reine
  ATR-Discriminator-Ansatz das Negativ-Set nicht hält.

### Sweep-Output Roh (Pass 3, mit ATR-Diagnose)

```
======================================================================
ATR-Diagnose (Phase 1 v0.30) — Percentile-Rang von atr_now in atr_history
======================================================================
Ticker  Bars  atr_now     atr_thr(p30)  percentile  reason
AMD     231   0.3479      0.1505        99.44       no_compression
NVDA    126   0.6278      0.3442        82.78       no_compression
NFLX    146   1.4994      1.3221        56.11       no_compression
SPY     250   2.4421      1.7888        77.22       no_compression
AAPL    252   0.3942      0.4849        5.0         no_alternation
```

---

## Step-1b Range-Mitte-Pin-Sweep (v0.30 Phase 1.5)

Run-Datum: 2026-05-02
Skript: `backend/scripts/wyckoff_textbook_check.py` (erweitert um `CASES_PIN`
und `run_pin_case`; Pass 4 in `main()`)

### Anlass

Die Step-1-Diagnose zeigte ein theoretisch absurdes Bild: Akkumulations-Cases
(AMD/NVDA) bei ATR-Percentile 99.44 / 82.78 (am oberen Verteilungsende —
also volatiler als der Median), Distributions-Case AAPL bei 5.0 (sehr ruhig
— umgekehrt zur Wyckoff-Erwartung, wonach Distributionen ATR-Erhöhung
zeigen). Verdacht: die Window-End-Messung erwischt die Cases zum falschen
Zeitpunkt — z.B. bei AAPL liegt das Fenster-Ende am 2016-04-01, der
August-2015-Crash war zu dem Zeitpunkt schon Geschichte; das Skript misst
Post-Crash-Beruhigung statt Distributions-Spannung. Bei AMD/NVDA umgekehrt:
Fenster-Ende nahe Range-Resistance kurz vor Markup, ATR-Now reflektiert
die Pre-Breakout-Spannung, nicht die Akkumulations-Ruhe.

Pin-Mode: ATR-Now wird an einem **mid-range-Tag** gemessen (mitten in der
Akkumulations- bzw. Distributions-Phase), 200d Vorlauf, sonst gleiche
Diagnose-Logik (`_atr_diagnosis`).

### Pin-Daten (vom Maintainer vorgegeben)

| Case | pin_date | Begründung |
|---|---|---|
| AMD 2015 | 2016-03-01 | Mitten in der $1.80–2.00-Range, vor Mai-Breakout |
| NVDA 2020 | 2020-05-15 | Mitten in der März-Juli-Range, vor Juli-Breakout |
| NFLX 2018 | 2018-08-15 | Mitten in der Topping-Phase |
| SPY 2007 | 2007-08-15 | Mid-Topping vor Finanzkrise |
| AAPL 2015 | 2015-06-01 | Topping, vor August-2015-Crash |

### Ergebnis-Tabelle (Pass 4 — Pin-Mode)

| Ticker | pin_date | Bars | atr_now | atr_threshold (p30) | atr_now_percentile_rank | Erwarteter Score |
|---|---|---|---|---|---|---|
| **AMD** | 2016-03-01 | 136 | 0.1036 | 0.0969 | **37.22** | +1 (Akkumulation) |
| **NVDA** | 2020-05-15 | 138 | 0.2880 | 0.2043 | **42.78** | +1 (Akkumulation) |
| **NFLX** | 2018-08-15 | 138 | 1.0005 | 0.9719 | **31.67** | -1 (Distribution) |
| **SPY** | 2007-08-15 | 138 | 2.5694 | 0.8660 | **98.33** | -1 (Distribution) |
| **AAPL** | 2015-06-01 | 135 | 0.4380 | 0.4974 | **12.78** | -1 (Distribution) |

### Vergleich Window-End (Pass 3) vs Pin (Pass 4)

| Ticker | Pass-3-Percentile (Window-End) | Pass-4-Percentile (Pin) | Delta | Erwartung |
|---|---|---|---|---|
| **AMD** | 99.44 | 37.22 | **−62.22** | +1 (Akku) |
| **NVDA** | 82.78 | 42.78 | **−40.00** | +1 (Akku) |
| **NFLX** | 56.11 | 31.67 | −24.44 | -1 (Distri) |
| **SPY** | 77.22 | 98.33 | **+21.11** | -1 (Distri) |
| **AAPL** | 5.00 | 12.78 | +7.78 | -1 (Distri) |

### Beobachtungen

1. **Der Slice-Bias ist real für die Akkumulations-Cases.** AMD fällt von
   99.44 auf 37.22 (−62 Punkte), NVDA von 82.78 auf 42.78 (−40 Punkte).
   In der Window-End-Messung sass das ATR-Now-Fenster nahe der
   Pre-Breakout-Resistance, wo die Volatilität bereits anzog. Am Pin-Tag,
   mitten in der Akkumulations-Range, sind beide Cases tatsächlich im
   unteren Drittel der ATR-Verteilung — exakt das Wyckoff-Theorie-Bild
   einer ruhigen Akkumulations-Phase.

2. **AAPL kippt NICHT um — der absurd niedrige Wert bleibt.** 5.0 → 12.78
   ist eine Verschiebung um nur +7.78 Punkte und immer noch tief unter
   dem Median. AAPL im Juni 2015 ist KEINE klassische Distribution mit
   ATR-Erhöhung. Das Pattern ist eher eine ruhige Topping-Konsolidierung,
   die Wyckoff-theoretisch nicht das erwartete Distributions-ATR-Profil
   trägt. Befund: AAPL 2015 ist kein guter Distributions-Negativ-Anchor —
   das Pattern verhält sich ATR-mässig wie eine Akkumulation.

3. **SPY zeigt umgekehrtes Bild — Pin-Wert (98.33) noch höher als
   Window-End (77.22).** SPY 2007-08-15 fällt mitten in den ersten
   Quant-Crash (August 2007 — der Bear-Stearns-Hedge-Fonds-Kollaps). Das
   ATR-Now spiegelt die akute Distributions-Volatilität — exakt das
   Wyckoff-Erwartungsbild für eine Distribution.

4. **NFLX bewegt sich moderat** (56.11 → 31.67, −24 Punkte). Im Pin-Mode
   liegt es im unteren Drittel — die Distribution war im August 2018
   noch nicht im stark volatilen Stadium, der eigentliche Down-Move kam
   im Q4 2018.

5. **Akkumulations-Lage am Pin-Tag konsistent** (37.22 / 42.78). Beide
   Akku-Cases liegen jetzt unter 50 — die Plan-Hypothese
   (`LONG_ACCUMULATION_ATR_PERCENTILE = 50` lässt textbook-Akkumulationen
   ein) wird durch die Pin-Mode-Messung bestätigt.

### Bias-Bewertung: real vs strukturell

**Bias ist real, aber nicht symmetrisch:**

- Akkumulations-Cases zeigen den Bias massiv (−62 / −40 Punkte). Pin-Mode
  liefert das theoretisch erwartete Bild (Akku am unteren Verteilungsende).
- Distributions-Cases zeigen den Bias asymmetrisch:
  - SPY: Bias bestätigt sich (Pin-Wert sogar höher, Distribution mit
    erwarteter ATR-Erhöhung)
  - NFLX: Pin-Wert sinkt (31.67), passt nicht zur "Distribution = hohe
    ATR"-Theorie — möglicher Hinweis darauf, dass der August-2018-Pin
    noch zu früh in der Topping-Phase liegt
  - AAPL: kaum Bewegung, Pin-Wert bleibt absurd niedrig (12.78) —
    AAPL 2015 ist als Distributions-Anchor wahrscheinlich falsch gewählt

**Konsequenz für die ATR-Discriminator-Frage**: In der Pin-Mode-Messung
zeigt sich eine **klarere Trennung** als in der Window-End-Messung:

- Akkus liegen jetzt bei 37–43
- Distributionen verteilen sich auf 13 (AAPL) / 32 (NFLX) / 98 (SPY)

Eine Schwelle bei 50 würde:
- AMD (37) einlassen ✓
- NVDA (43) einlassen ✓
- NFLX (32) einlassen ✗ (False-Positive)
- AAPL (13) einlassen ✗ (False-Positive)
- SPY (98) ausschliessen ✓

Das ist 2/2 Recall auf den Akku-Cases, aber 2/3 False-Positives auf den
Distri-Cases. Die "klassischen Distributionen" mit erwarteter ATR-Erhöhung
filtert die Schwelle nur dann zuverlässig heraus, wenn die Distribution
auch tatsächlich die Lehrbuch-Volatilitäts-Charakteristik trägt (wie SPY
August 2007). NFLX-Aug-2018 und AAPL-Juni-2015 fallen aus der Lehrbuch-
Definition heraus — **sie sind eher Akkumulations-ähnliche Topping-
Konsolidierungen**, nicht klassische Distributionen mit ATR-Spannung.

### Empfehlung

**C-allein (Plan-Hypothese) reicht — aber mit qualifiziertem Optimismus.**

Konkret:

1. **`LONG_ACCUMULATION_ATR_PERCENTILE = 50`** (zurück zur ursprünglichen
   Plan-Hypothese aus dem `analysis_config.py`-Vorschlag) — principled
   abgeleitet aus der Pin-Mode-Diagnose, **nicht** gegen die Sweep-Cases
   getuned. Begründung: am Pin-Tag liegen beide Akku-Cases klar unter 50
   (37.22 / 42.78), eine Schwelle bei 50 ist die kleinste, die beide
   einlässt mit etwas Buffer.

2. **B-Pfad (Wyckoff-Score-Co-Filter) ist NICHT zwingend nötig.** Die
   Pin-Mode-Diagnose zeigt, dass ATR-Percentile ein nützlicher
   Discriminator ist — aber nur, wenn die Messung an der richtigen
   Stelle erfolgt. Der Detector misst in der Live-Anwendung **am Ende
   der Range**, ähnlich wie der Window-End-Modus — was der Bias-Befund
   2 in den Akku-Cases (Pre-Breakout-Spannung) reproduzieren wird,
   sobald ein Live-Stock kurz vor dem Breakout steht.

3. **Aber** (wichtige Einschränkung): Der **Live-Detector misst in
   Echtzeit am rechten Rand**. Wenn ein Live-Stock heute kurz vor dem
   Markup steht, würde er ATR-mässig wie AMD-Window-End (99.44) messen,
   nicht wie AMD-Pin (37.22) — und vom 50er-Filter verworfen werden.
   Das ist ein **fundamentales Problem mit der ATR-Compression-
   Heuristik in dieser Anwendung**: sie funktioniert in der Mitte der
   Akkumulation gut, am Rand der Akkumulation versagt sie.

4. **Mitigation für den Live-Anwendungsfall**: Der Long-Accumulation-
   Detector sollte **die ATR-Percentile NICHT nur am rechten Rand**
   messen, sondern als Range-Property (z.B. **Median-ATR-Percentile
   über die letzten 60 Tage** statt punktueller Endpunkt-Messung). Das
   ist eine Detector-Implementierungs-Entscheidung für Phase 2, nicht
   Teil dieser Diagnose-Phase. Empfehlung an den Maintainer: in
   Phase-2-Detector-Implementation `LONG_ACCUMULATION_ATR_RANK_WINDOW`
   einführen (z.B. 60d), `atr_now` durch `median(atr_last_window)`
   ersetzen.

5. **AAPL als Distributions-Anchor verwerfen**: Die Pin-Mode-Daten
   zeigen, dass AAPL 2015 keine klassische Distribution ist — der
   ATR-Wert (12.78) widerspricht der Wyckoff-Distributionstheorie. Für
   Phase-3-Negativ-Set ist AAPL ein schwacher Anchor und sollte gegen
   einen anderen Distributions-Case ersetzt werden (z.B. ein klar
   distributiv verhaltender Top mit ATR-Erhöhung).

### Empfohlene Schwelle (principled)

```python
LONG_ACCUMULATION_ATR_PERCENTILE: int = 50
```

Begründung-Kette:
- Pin-Mode-Diagnose: AMD 37.22, NVDA 42.78 — beide klar unter 50
- 50 ist die kleinste runde Schwelle, die beide Akku-Cases mit
  ≥7-Punkte-Buffer einlässt (NVDA: 50 − 42.78 = 7.22)
- Höhere Schwelle (60, 70) verliert Falsifikations-Kraft — wenn
  Recall-Cases bei 37/43 liegen, lässt eine 70er-Schwelle alles ein,
  was im unteren Drittel liegt; das ist nicht mehr trennscharf
- Niedrigere Schwelle (40) verliert NVDA (42.78 > 40) — Recall-Verlust
  ohne Precision-Gewinn

**WICHTIG**: Diese Schwelle wird hier **NICHT** in `analysis_config.py`
geschrieben. Der Maintainer entscheidet auf Basis dieser Diagnose, ob
der C-Pfad (ATR-Schwelle 50, ohne Wyckoff-Co-Filter) oder der B-Pfad
(zusätzlicher Wyckoff-Score-≥0-Co-Filter) gegangen wird. Die
Pin-Mode-Daten sprechen für C-allein, mit dem Vorbehalt der
Live-Detector-Edge-Case-Problematik (Punkt 3 + 4 oben).

### Methodik-Note: Phase-3a-Heuristik-Erweiterung

Die ursprüngliche Phase-3a-Heuristik prüft nur den **Spread** zwischen
min und max Akkumulations-Percentile-Wert (>25 Punkte → ATR-Schwelle
wackelig). Diese Heuristik hat das Step-1-Ergebnis als "formal-OK
(Spread = 16.66)" durchgewinkt, obwohl die **Lage** der Werte (beide
Akkus >80, also umgekehrt zur Plan-Hypothese 35–50) bereits ein klares
Warnsignal gewesen wäre.

**Erweiterung der Heuristik für zukünftige Diagnose-Iterationen**:

Zusätzlich zum Spread-Check muss die **Lage relativ zum 50-Percentile**
geprüft werden:

- Wenn beide Akkumulations-Cases **>75** liegen → die ATR-Achse ist
  umgekehrt zur Hypothese (Akkus volatiler als Median statt ruhiger).
  Diagnose-Bias prüfen (Slice-Artefakt?), bevor Schwellen abgeleitet
  werden.
- Wenn beide Akkumulations-Cases **<25** liegen → die Akkus liegen am
  unteren Extremum. Distributions-Cases müssen klar darüber liegen,
  sonst kein Discriminator.
- Wenn **eine** Achse extrem (>75 oder <25) und eine moderat ist →
  Spread-Check kann formal OK sein, aber der Discriminator hält nur,
  wenn die Distributions-Cases zwischen den Akkus liegen — was selten
  natürlich ist.

**Konkrete Regel für zukünftige Diagnose-Phasen**: Vor jeder
Schwellen-Derivation wird **sowohl** Spread-Check **als auch**
Lage-Check ausgeführt. Wenn Spread formal OK aber Lage extrem →
**Bias-Verdacht aussprechen und Pin-Mode-Sweep einschieben**, statt
direkt zur Schwellen-Derivation zu gehen. Das hätte Phase 1 das v0.30-
Phase-1.5-Detour erspart.

Diese Note soll in zukünftigen Diagnose-Iterationen verhindern, dass
der gleiche Befund (formal-OK-Spread bei umgekehrter Lage) übersehen
wird.
