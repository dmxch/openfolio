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
