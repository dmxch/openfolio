# Design-Dokument: EPS-Scanner (Quartals-Gewinn-Scanner)

**Version:** 0.2 — 2026-06-22
**Status:** Entwurf, ausstehend Maintainer-Freigabe
**Autor:** Design-Agent (OpenFolio) + Record-Quarter-Ergaenzung (Maintainer-Input)
**Geltungsbereich:** Additives Feature — beruehrt KEINE Performance-/Renditeberechnung (HEILIGE Regeln 1, 11)

---

## Inhaltsverzeichnis

1. Problem & Personas
2. User Stories (INVEST-konform)
3. Acceptance Criteria (Gherkin/BDD)
4. MoSCoW-Scope
5. RICE-Priorisierung
6. Datenmodell
7. API-Contract
8. Worker-Job-Spezifikation
9. Frontend-Komponentenliste & Layout
10. Offene Fragen fuer den Maintainer

---

## 1. Problem & Personas

### Problem

Es gibt keinen schnellen Weg, im S&P-500-Universum Aktien zu identifizieren,
deren Quartalsgewinne (EPS) sich in einem jungen, beschleunigenden Aufwartstrend
befinden — dem Kernmuster hinter Felix Preens "Super-Quartal"-Konzept (auch bekannt
als "Power Move"). Aktuell muss ein Nutzer einzelne Aktien manuell recherchieren;
ein systematischer Scan fehlt komplett.

### Personas

| Persona | Beschreibung | Dringlichkeit |
|---|---|---|
| **Self-Hosted-Investor** | Betreibt eigene OpenFolio-Instanz, systematischer Regelinvestor, will EPS-Momentum fruehzeitig erkennen | Hoch |
| **Power-User** | Kombiniert EPS-Signal mit vorhandenem Smart-Money-Score | Mittel |
| **Einsteiger** | Will verstehen, was "Super-Quartal" bedeutet; braucht Erklaerungstexte | Niedrig |

---

## 2. User Stories (INVEST-konform)

### Story 1 — EPS-Verlauf je Aktie einsehen

**Als** Self-Hosted-Investor
**moechte ich** fuer jede Aktie im S&P 500 die letzten 8 Quartals-EPS-Werte
in einer Tabelle sehen,
**damit** ich visuell beurteilen kann, ob ein Unternehmen konsistent wachsende
Gewinne pro Aktie ausweist.

*INVEST-Check: Independent (steht allein), Negotiable (Anzahl Quartale
konfigurierbar), Valuable (Kernanwendungsfall), Estimable (~3 Tage Impl.),
Small (ein Endpoint + eine Tabellenspaltengruppe), Testable (klare
Acceptance Criteria unten).*

---

### Story 2 — Super-Quartal-Filter anwenden

**Als** Self-Hosted-Investor
**moechte ich** die Ergebnistabelle auf Aktien filtern, deren juengstes
Quartal die Super-Quartal-Kriterien erfuellt,
**damit** ich zielgerichtet in EPS-Beschleunigungsmomente einsteigen kann,
ohne 500 Zeilen manuell zu pruefen.

---

### Story 3 — YoY-Wachstum + Streak-Count ablesen

**Als** Power-User
**moechte ich** neben den rohen EPS-Werten den YoY-Wachstumsprozentsatz
des juengsten Quartals und die Anzahl der Quartale mit positivem YoY-Wachstum
("Streak") sehen,
**damit** ich nicht nur den absoluten EPS-Wert, sondern die Wachstumsdynamik
beurteilen kann.

---

### Story 4 — Staleness und Coverage-Luecken erkennen

**Als** Self-Hosted-Investor
**moechte ich** sehen, wenn Daten fehlen oder veraltet sind,
**damit** ich weiss, welchen Aktien ich nicht blind vertrauen darf.

---

### Story 5 — Record-Quartal-Filter anwenden

**Als** Self-Hosted-Investor
**moechte ich** die Tabelle auf Aktien filtern, deren juengstes Quartal
einen neuen 8-Quartals-EPS-Rekord darstellt (hoeher als jedes der 8
vorangegangenen Quartale),
**damit** ich Aktien finde, die ein absolutes Gewinn-Niveau-Hoch erreicht
haben — Felix Preens "Record-Quarter" aus dem IPO-Webinar. Dies ist ein
ABSOLUTES Niveau-Signal (anders als das Super-Quartal, das relative
YoY-Beschleunigung misst); beide koexistieren als getrennte Filter + Badges.

*INVEST-Check: Independent (eigene Boolean-Spalte, unabhaengig vom
Super-Quartal), Negotiable (Fensterbreite konfigurierbar), Valuable
(zweites Kern-Setup aus dem Webinar), Estimable (~0.5 Tag zusaetzlich,
nutzt vorhandene EPS-Reihe), Small, Testable (AC-7).*

---

## 3. Acceptance Criteria (Gherkin/BDD)

### AC-1: EPS-Reihe wird geladen und angezeigt

```gherkin
Given ein eingeloggter Nutzer oeffnet /eps-scanner
  And die Worker-Job-Daten sind aktuell (juengster Fetch < 7 Tage)
When die Seite ladet
Then zeigt die Tabelle pro Zeile (Ticker, Name, bis zu 8 Quartals-EPS-Werte,
     YoY-Wachstum juengstes Quartal, Streak-Count)
  And Quartale sind chronologisch von aeltester (links) zu juengster (rechts) angeordnet
  And positive EPS-Werte erscheinen in Standard-Textfarbe,
      negative in Danger-Farbe (mindestens 4.5:1 Kontrast, WCAG 2.2 AA)
```

### AC-2: Super-Quartal-Kriterien erfuellt — Filter

```gherkin
Given ein Nutzer aktiviert den Toggle "Nur Super-Quartale"
When das Frontend die Ergebnisse neu ladet
Then werden nur Aktien angezeigt, bei denen ALLE folgenden Bedingungen zutreffen:
     (a) juengstes-Q-YoY-Wachstum >= super_quarter_yoy_threshold (Default: 25%)
     (b) juengstes-Q-YoY-Wachstum >= Median der 3 vorherigen berechneten
         YoY-Wachstumsraten + super_quarter_acceleration_margin (Default: 5 Prozentpunkte)
     (c) Basis-EPS (Vorjahrquartal) > 0 (Turnaround-Rows werden separat
         als "Turnaround" gekennzeichnet, aber nicht als Super-Quartal gefiltert)
     (d) kein outlier_flag = true fuer das juengste Quartal
  And die Kriterien-Schwellen sind im UI als Info-Tooltip sichtbar
  And das Label lautet "Super-Quartal-Kriterien erfuellt" (KEINE imperative Anweisung)
```

**Backtest-Gate (ENTSCHIEDEN, siehe OF-1):**
Der Super-Quartal-Toggle ist ab v1 aktiv, traegt aber einen persistenten
Disclaimer: "Schwellenwerte (25% / +5pp) sind Arbeits-Defaults, noch nicht
durch Forward-Return-Backtest validiert" (Tooltip am Toggle + am [SQ]-Badge).
Gemaess feedback_signal_weights_need_backtest.md werden die Schwellen damit
NICHT als validiertes Signal kommuniziert. Record-Quartal braucht keinen
Disclaimer (deterministisch).

---

### AC-3: Turnaround-Kennzeichnung bei negativer Basis

```gherkin
Given Ticker XYZ hat im Vorjahrquartal EPS = -0.40 und im juengsten Quartal EPS = +0.30
When der Scanner die YoY-Wachstumsrate berechnet
Then ist yoy_growth_pct = null (nicht berechnet — Division durch negative Basis)
  And yoy_flag = "turnaround" (negative → positive) oder "neg_to_neg" (beide negativ)
     oder "pos_to_pos" (beide positiv, Standardfall)
  And die Tabellenzelle zeigt statt einer Prozentzahl das Badge "Turnaround"
  And der Super-Quartal-Filter schliesst diesen Ticker aus (Bedingung c oben)
```

---

### AC-4: Outlier-Guard bei Einmaleffekten

```gherkin
Given Ticker GEV hat im juengsten Quartal EPS = 17.44 (Divest-Einmaleffekt)
     und die Median-EPS der letzten 6 Quartale (ohne juengstes) = 0.52
When der Scanner den outlier_flag berechnet
Then ist outlier_flag = true, weil juengstes-Q-EPS > 5x Median der 6 Vorquartale
  And die Tabellenzelle traegt ein Warnzeichen mit Tooltip "Moeglicher Einmaleffekt"
  And der Super-Quartal-Filter schliesst diesen Ticker aus
  And alle anderen Berechnungen (YoY-Wachstum, Streak) werden trotzdem angezeigt
```

Der Multiplikator "5x" ist ein konfigurierbarer Guard-Schwellwert
(outlier_eps_multiplier, Default = 5.0). Kein Backtest erforderlich, da
Guard ein Ausschlusskritierium, kein Score-Gewicht ist.

---

### AC-7: Record-Quartal (neues 8-Quartals-Hoch)

```gherkin
Given Ticker XYZ hat als juengstes Quartal EPS = 1.40
  And die 8 unmittelbar davorliegenden Quartale haben als Maximum EPS = 1.21
When der Scanner record_quarter berechnet
Then ist record_quarter = true, weil juengstes-Q-EPS STRIKT > Max(8 Vorquartale)
  And die Zeile traegt das Badge "Record-Quartal" ([RQ])
  And wenn der Nutzer den Toggle "Nur Record-Quartale" aktiviert,
      werden ausschliesslich Rows mit record_quarter = true angezeigt

Given das juengste Quartal ist ein Record, ist aber zugleich outlier_flag = true
      (z.B. SOLV 7.22 vs Median 0.40 — Divestitur-Einmaleffekt)
When die Zeile dargestellt wird
Then loest record_quarter weiterhin aus (Badge [RQ] erscheint)
  And das [RQ]-Badge traegt ein zusaetzliches Warnzeichen "moeglicher Einmaleffekt"
  And der Nutzer behaelt die Entscheidung (kein stilles Wegfiltern)

Given das juengste Quartal ist ein Record und mindestens ein Quartal im
      8er-Fenster war negativ, das juengste ist positiv
When die Zeile dargestellt wird
Then traegt das [RQ]-Badge ein Sub-Badge "Turnaround" (Verlust → Gewinn)
```

**Definition record_quarter (serverseitig):**

```
window = quarters[-9:-1]   # bis zu 8 Quartale VOR dem juengsten (exkl. juengstes)
record_quarter = len(window) >= 1
                 AND latest_eps > max(q.eps for q in window)   # strikt >

record_quarter_outlier  = record_quarter AND outlier_flag       # reuse aus AC-4
record_quarter_turnaround = record_quarter
                            AND latest_eps > 0
                            AND min(q.eps for q in window) < 0
```

Hinweise:
- Record-Quartal ist ein ABSOLUTES Niveau-Signal, unabhaengig vom
  Super-Quartal (Story 2) und von der YoY-Beschleunigung. Beide Flags
  koennen gleichzeitig oder einzeln gesetzt sein.
- Fensterbreite (8) ist als Service-Konstante definiert; bei < 8
  verfuegbaren Vorquartalen wird gegen das vorhandene Fenster verglichen
  (z.B. nur 5 Vorquartale → Record vs. diese 5). Falls 0 Vorquartale
  existieren, ist record_quarter = false.
- KEIN Backtest erforderlich: record_quarter ist ein deterministisches
  Filter/Badge, KEIN Score-Gewicht. Falls es je in `scoring_service.py`
  einfliessen soll → Forward-Return-Backtest gem.
  feedback_signal_weights_need_backtest.md (analog Super-Quartal).

---

### AC-5: Staleness-Anzeige

```gherkin
Given Ticker JPM hat <6 Quartale in der DB (Finnhub-Luecke, yfinance-Fallback auch leer)
When die Zeile in der Tabelle dargestellt wird
Then erscheint ein Staleness-Badge "< 6Q" in Muted-Farbe
  And ein Tooltip erklaert "Weniger als 6 Quartale verfuegbar — Finnhub deckt
      den Finanzsektor nicht ab; yfinance-Fallback wird verwendet"
  And die Zeile wird weiterhin angezeigt (kein silent-Drop)
```

```gherkin
Given ein Ticker wurde zuletzt vor mehr als 14 Tagen gefetcht
When die Zeile in der Tabelle dargestellt wird
Then traegt die Staleness-Spalte ein Warnzeichen "Veraltet (>14T)"
  And ein Tooltip zeigt das letzte Fetch-Datum an
```

---

### AC-6: Multi-User-Isolation der Filter-Einstellungen

```gherkin
Given Nutzer A stellt den YoY-Schwellwert auf 40%
  And Nutzer B hat den Standardwert 25%
When beide Nutzer gleichzeitig den Scanner laden
Then sieht Nutzer A seine 40%-Filterung
  And Nutzer B seine 25%-Filterung
  And EPS-Rohdaten (universe-global) sind identisch fuer beide
```

---

## 4. MoSCoW-Scope

### Must (MVP — v1.0)

- Worker-Job: taeglich EPS-Reihen fuer S&P-500-Universum fetchen
  (Finnhub `basic_financials` primaer, yfinance-Fallback fuer ~65
  Finanzsektor-Ticker)
- DB-Modell `eps_quarterly` mit Zeitreihenspeicherung
- API `GET /api/eps-scanner/results` mit Server-seitiger Filterung
- Frontend-Page `/eps-scanner`: Tabelle mit 8 EPS-Spalten, YoY-Wachstum,
  Streak-Count, Staleness-Badge
- Super-Quartal-Boolean-Toggle (serverseitig gefiltert)
- Record-Quartal-Boolean-Toggle (neues 8-Q-Hoch, serverseitig gefiltert) +
  [RQ]-Badge inkl. Outlier-Warnung + Turnaround-Sub-Badge
- Turnaround-Flag + Outlier-Guard-Flag in DB + UI
- S&P-500-Symbolliste als statische Datei im Backend

### Should (v1.1)

- User-seitige Konfiguration der Filter-Schwellenwerte (YoY-Threshold,
  Acceleration-Margin) mit Persistenz in `user_settings`
- Sortierung der Tabelle nach YoY-Wachstum, Streak-Count, Ticker
- Manueller Refresh-Button (triggert Worker-Job on-demand fuer Admin)
- Sektor-Filter (analog SmartMoneyFilters)

### Could (v1.2 und spaeter)

- Mini-Sparkline-Chart der 8-Quartals-EPS-Reihe (Recharts BarChart,
  Analogie zu MiniChartTooltip)
- Kombination EPS-Scanner x Smart-Money-Score (JOIN auf ScreeningResult)
- Download als CSV (analog Report-Vault-Pattern)
- Historische Super-Quartal-Heatmap (welche Sektoren hatten historisch
  die meisten Super-Quartale)

### Won't (explizit ausgeschlossen)

- EPS-Scanner fliesst NICHT in Performance-/Renditeberechnung ein
- NICHT in `portfolio_service.py`, `recalculate_service.py`,
  `price_service.py`, `utils.py` — HEILIGE Regeln 1, 11
- Keine Prognose-/Forecast-Daten (nur Reported EPS, kein Estimate-Vergleich
  — das ist Scope der EstimateRevision-Pipeline)
- Keine automatische Trade-Empfehlung ("Kaufen", "Verkaufen" verboten
  — HEILIGE Regel 10)
- Kein internationales Universum (nur S&P 500 US-Equities in v1)

---

## 5. RICE-Priorisierung

```
Reach:      350 User × 0.4 (40% nutzen Screening-Features aktiv) = 140
Impact:     3 (stark — schliesst echten Workflow-Gap)
Confidence: 0.8 (Spike verifiziert Datenquelle + Coverage)
Effort:     5 Tage (1 Dev)

RICE = (140 × 3 × 0.8) / 5 = 67.2
```

Zum Vergleich: Verbesserungen an bestehenden Screening-Filtern liegen bei
RICE ~30–45. EPS-Scanner ist damit hoechste Prioritaet im Screening-Cluster.

---

## 6. Datenmodell

### 6.1 Neue Tabelle: `eps_quarterly`

```python
# backend/models/eps_quarterly.py

class EpsQuarterly(Base):
    """Persistierte EPS-Zeitreihe (Quarterly Reported EPS) pro Ticker.

    Jede Row = ein Quartal eines Tickers.
    Quelle: Finnhub basic_financials (primaer) oder yfinance (Fallback).
    Universe-global — kein user_id.
    """
    __tablename__ = "eps_quarterly"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # period_end = Quartalsenddatum (YYYY-MM-DD), wie von Finnhub geliefert.
    # Achtung: verschiedene Unternehmen haben unterschiedliche Fiskalquartale.
    eps: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # source: "finnhub" | "yfinance"
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker", "period_end", name="uq_eps_quarterly_ticker_period"),
        Index("ix_eps_quarterly_ticker_period", "ticker", "period_end"),
        Index("ix_eps_quarterly_fetched", "ticker", "fetched_at"),
    )
```

**Keine user_id** — EPS-Rohdaten sind universe-global. Filter-Einstellungen
(YoY-Threshold etc.) leben in `user_settings` (dort user_id-scoped).

### 6.2 Erweiterung `user_settings` (Alembic-Migration)

Drei neue nullable-Spalten:

```
eps_scanner_yoy_threshold:       Numeric(6,2), nullable, default=25.0
eps_scanner_acceleration_margin: Numeric(6,2), nullable, default=5.0
eps_scanner_outlier_multiplier:  Numeric(6,2), nullable, default=5.0
```

Werte aus diesen Spalten werden verwendet, wenn der User eine eigene
Einstellung gespeichert hat. Fehlt der Wert (NULL), gelten die hardcodierten
Service-Defaults (25.0 / 5.0 / 5.0).

### 6.3 Statische S&P-500-Symbolliste

Pfad: `backend/services/screening/sp500_universe.py`

Inhalt: Python-Modul mit Konstante `SP500_TICKERS: list[str]` — 503 Symbole
(Stand SPDR ETF / Wikipedia, Stand Quartalsende).

Quelle fuer initiale Befuellung: Wikipedia-Seite "List of S&P 500 companies"
(via `pandas.read_html` in einem Einmal-Script, Ergebnis dann statisch eingecheckt).
Keine Live-Abfrage zur Laufzeit (zu fragil; quartalsweise manuell aktualisieren).

Der EPS-Scanner-Universe-Resolver ist eine eigenstaendige Funktion
`resolve_sp500_universe() -> list[str]`, die aus der statischen Liste liest.
Sie ist NICHT an `resolve_equity_universe()` aus `screening/universe.py` gekoppelt
(andere Semantik: dort Portfolio+Watchlist, hier fest S&P 500).

---

## 7. API-Contract

### 7.1 Haupt-Endpoint

```
GET /api/eps-scanner/results
```

**Auth:** JWT (Depends get_current_user) — identisch zu allen anderen geschuetzten Endpoints.

**Query-Parameter:**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `super_quarter_only` | bool | false | Filtert auf Super-Quartal-Kriterien-erfuellt-Rows |
| `record_quarter_only` | bool | false | Filtert auf Record-Quartal-Rows (neues 8-Q-Hoch) |
| `min_quarters` | int (2..8) | 6 | Mindestanzahl verfuegbarer Quartale |
| `sector` | str (optional) | — | GICS-Sektor (multi-value per mehrfach-Angabe) |
| `sort_by` | str | `yoy_growth` | `ticker`, `yoy_growth`, `streak_count`, `latest_eps` |
| `sort_asc` | bool | false | Aufsteigend sortieren |
| `page` | int (>=1) | 1 | Seite |
| `per_page` | int (1..200) | 50 | Zeilen pro Seite |

Die User-eigenen Schwellenwerte (yoy_threshold, acceleration_margin,
outlier_multiplier) werden serverseitig aus `user_settings` des
authentifizierten Users gelesen — kein Query-Parameter. Dadurch sind
sie sitzungsuebergreifend persistent ohne Client-State.

**Response-Shape:**

```json
{
  "as_of": "2026-06-22T06:00:00Z",
  "data_refreshed_at": "2026-06-22T04:17:33Z",
  "thresholds": {
    "super_quarter_yoy_pct": 25.0,
    "acceleration_margin_pp": 5.0,
    "outlier_multiplier": 5.0
  },
  "results": [
    {
      "ticker": "NVDA",
      "name": "NVIDIA Corp.",
      "sector": "Information Technology",
      "quarters": [
        { "period_end": "2024-04-28", "eps": 0.61, "source": "finnhub" },
        { "period_end": "2024-07-28", "eps": 0.68, "source": "finnhub" },
        { "period_end": "2024-10-27", "eps": 0.81, "source": "finnhub" },
        { "period_end": "2025-01-26", "eps": 0.89, "source": "finnhub" },
        { "period_end": "2025-04-27", "eps": 1.04, "source": "finnhub" },
        { "period_end": "2025-07-27", "eps": 1.21, "source": "finnhub" },
        { "period_end": "2025-10-26", "eps": 0.93, "source": "finnhub" },
        { "period_end": "2026-01-25", "eps": 1.40, "source": "finnhub" }
      ],
      "latest_eps": 1.40,
      "yoy_growth_pct": 57.3,
      "yoy_flag": "pos_to_pos",
      "streak_count": 6,
      "super_quarter": true,
      "record_quarter": true,
      "record_quarter_outlier": false,
      "record_quarter_turnaround": false,
      "outlier_flag": false,
      "data_age_days": 0,
      "quarter_count": 8
    }
  ],
  "total": 312,
  "page": 1,
  "per_page": 50
}
```

**YoY-Berechnungsregeln (serverseitig):**

```
basis_eps    = quarters[-5].eps  (5 Quartale zurueck, d.h. Vorjahresquartal)
current_eps  = quarters[-1].eps  (juengstes Quartal)

yoy_flag Logik:
  if basis_eps > 0 and current_eps > 0:  yoy_flag = "pos_to_pos"
  if basis_eps > 0 and current_eps <= 0: yoy_flag = "pos_to_neg"
  if basis_eps < 0 and current_eps > 0:  yoy_flag = "turnaround"
  if basis_eps < 0 and current_eps <= 0: yoy_flag = "neg_to_neg"
  if basis_eps == 0:                     yoy_flag = "zero_basis"

yoy_growth_pct Logik:
  if yoy_flag == "pos_to_pos":
      yoy_growth_pct = (current_eps - basis_eps) / abs(basis_eps) * 100
      (kein Cap — extreme Werte erscheinen im UI als ">500%"-Clamp-String,
       Rohdaten bleiben erhalten)
  else:
      yoy_growth_pct = null
```

**Streak-Count-Definition:**

```
Fuer jedes Quartal i (i = 4..len-1) berechne YoY mit quarters[i-4] als Basis.
Zaehle alle i, fuer die yoy_flag[i] == "pos_to_pos" AND yoy_growth_pct[i] > 0.
streak_count = dieser Zaehler ueber das gesamte verfuegbare Fenster.
```

**Super-Quartal-Kriterien (alle vier muessen erfuellt sein):**

```
A: yoy_flag == "pos_to_pos"                         (keine Turnaround/Neg-Rows)
B: yoy_growth_pct >= super_quarter_yoy_threshold     (Default 25%)
C: yoy_growth_pct >= median(vorherige_3_yoy_wachstumsraten) + acceleration_margin
   (Median wird aus den 3 letzten berechneten pos_to_pos-YoY-Rates berechnet,
    exkl. juengstes Quartal; wenn weniger als 2 Vorwerte = Kriterium C entfaellt,
    nur A+B+D werden geprueft)
D: outlier_flag == false
```

**Record-Quartal-Berechnung (serverseitig, unabhaengig von Super-Quartal):**

```
window = quarters[:-1][-8:]   # bis zu 8 Quartale VOR dem juengsten
record_quarter            = len(window) >= 1 AND latest_eps > max(q.eps for q in window)
record_quarter_outlier    = record_quarter AND outlier_flag
record_quarter_turnaround = record_quarter AND latest_eps > 0 AND min(q.eps for q in window) < 0
```

Record-Quartal ist ein absolutes Niveau-Hoch (kein YoY), feuert auch bei
Outlier (dann mit Warn-Sub-Badge), kein Backtest noetig (Filter/Badge,
kein Score-Gewicht).

### 7.2 Schwellenwert-Endpoint (User-spezifisch)

```
GET  /api/eps-scanner/thresholds
PATCH /api/eps-scanner/thresholds
```

`PATCH` Body:

```json
{
  "super_quarter_yoy_pct": 30.0,
  "acceleration_margin_pp": 8.0,
  "outlier_multiplier": 4.0
}
```

Validierung: alle Werte > 0, `super_quarter_yoy_pct` max 200,
`outlier_multiplier` max 20. Speichert in `user_settings`-Spalten (s. 6.2).

### 7.3 Daten-Freshness-Endpoint

```
GET /api/eps-scanner/status
```

Response:

```json
{
  "last_job_run": "2026-06-22T04:17:33Z",
  "tickers_total": 503,
  "tickers_fetched": 498,
  "tickers_finnhub": 434,
  "tickers_yfinance_fallback": 64,
  "tickers_missing": 5,
  "missing_tickers": ["SOLV", "..."],
  "finnhub_key_configured": true,
  "job_status": "completed"
}
```

---

## 8. Worker-Job-Spezifikation

### 8.1 Job-Name und Trigger

```
Job-ID:    refresh_eps_quarterly
Trigger:   CronTrigger, taglich 04:00 Uhr Zuerich (vor daily_refresh, nach Boersenende US)
Timeout:   900s (15 Min; 500 Ticker × Finnhub-60-calls/min-Limit = ~9 Min fuer Finnhub
           + Puffer fuer yfinance-Fallback-Batch)
Advisory-Lock: JA (identisch zu daily_refresh-Pattern, eigene Lock-ID z.B. 123456790)
```

### 8.2 Algorithmus

```
1. Lade SP500_TICKERS aus sp500_universe.py (503 Symbole)
2. Finnhub-Batch (primaer):
   a. Lade Settings.FINNHUB_SYSTEM_API_KEY (env-backed, OF-5). Fehlt der Key:
      WARNING loggen, Finnhub-Batch ueberspringen, alle Ticker in Fallback-Liste.
   b. Iteriere SP500_TICKERS mit Rate-Limiter: maximal 55 Calls/min
      (Puffer unter 60-Limit des Free-Tiers)
      URL: GET https://finnhub.io/api/v1/stock/metric?metric=all&symbol={ticker}&token={key}
      Feld: response["series"]["quarterly"]["eps"] (Array [{period, v}])
   c. Fuer jeden Ticker: upsert alle Quartale in eps_quarterly via ON CONFLICT DO UPDATE
   d. Ticker mit leerer/fehlender eps-Serie → in Fallback-Liste aufnehmen
3. yfinance-Fallback (fuer Ticker aus Finnhub-Fallback-Liste, erwartet ~65 Finanzsektor):
   a. Semaphore = 3 (PFLICHT — HEILIGE Regel aus feedback_yfinance_burst_429.md)
   b. asyncio.to_thread(lambda: yf.Ticker(t).get_earnings_dates(limit=16))
      → liefert DataFrame mit "Reported EPS" je Quartal
   c. Upsert in eps_quarterly (source="yfinance")
4. Schreibe Job-Status in AppSetting-Eintrag "eps_scanner_last_run" (JSON:
   last_run, tickers_total, tickers_fetched, tickers_finnhub,
   tickers_yfinance_fallback, tickers_missing, missing_tickers[])
5. Logging: INFO pro Batch, WARNING pro Fallback-Ticker, ERROR bei komplettem
   Job-Fehlschlag
```

### 8.3 Upsert-Semantik

```sql
INSERT INTO eps_quarterly (id, ticker, period_end, eps, source, fetched_at)
VALUES (...)
ON CONFLICT (ticker, period_end) DO UPDATE
  SET eps = EXCLUDED.eps,
      source = EXCLUDED.source,
      fetched_at = EXCLUDED.fetched_at
```

Begruendung: Korrekturen seitens Finnhub (Restatements) sollen
automatisch uebernommen werden. Keine Versionierung in v1.

### 8.4 Liveness-Monitoring

Heartbeat-Pattern wie bestehende Worker-Jobs: nach erfolgreichem
Job-Abschluss `fetched_at`-Timestamp in DB schreiben. Staleness-
Check-Logik im `GET /api/eps-scanner/status`-Endpoint gibt `job_status:
"stale"` zurueck, wenn `last_job_run` > 30 Stunden zurueck liegt
(gem. feedback_scheduled_jobs_need_liveness.md).

---

## 9. Frontend-Komponenten & Layout

### 9.1 Neue Route und Navigation

- Route: `/eps-scanner` in `App.jsx` (lazy-loaded analog SmartMoney)
- Sidebar-Eintrag: `{ to: '/eps-scanner', label: 'EPS-Scanner', icon: TrendingUp }`
  (Lucide-Icon `TrendingUp`, passt semantisch zu Gewinnwachstum)
  Einfuegen nach "Smart Money", vor "Report-Vault"

### 9.2 Komponentenliste

| Komponente | Pfad | Beschreibung |
|---|---|---|
| `EpsScanner` | `pages/EpsScanner.jsx` | Page-Komponente, laedt Daten via useApi, haelt Filter-State |
| `EpsFilters` | `components/EpsFilters.jsx` | Linke Sidebar: Toggle Super-Quartal, Sektor-Checkboxen, Sortierung |
| `EpsTable` | `components/EpsTable.jsx` | Haupttabelle: Ticker, Name, EPS-Spalten, YoY, Streak, Badges |
| `EpsQuarterCell` | `components/EpsQuarterCell.jsx` | Einzelne Zelle: EPS-Wert, farbcodiert (positiv/negativ/null) |
| `EpsYoyBadge` | `components/EpsYoyBadge.jsx` | YoY-Wachstums-Prozent-Badge oder Turnaround-/Neg-Pill |
| `EpsStalenessTag` | `components/EpsStalenessTag.jsx` | Staleness- und Coverage-Warnung (< 6Q / >14T) |
| `EpsThresholdSettings` | `components/EpsThresholdSettings.jsx` | Inline-Formular in Filters-Sidebar fuer User-Schwellenwerte (Should) |

### 9.3 Tabellen-Layout

Desktop-Tabellenbreite (Tool ist Desktop-only per `project_desktop_only.md`):

```
| Ticker | Name       | Q1   | Q2   | Q3   | Q4   | Q5   | Q6   | Q7   | Q8   | YoY%  | Streak | Flags    |
| ------ | ---------- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ----- | ------ | -------- |
| NVDA   | NVIDIA ... | 0.61 | 0.68 | 0.81 | 0.89 | 1.04 | 1.21 | 0.93 | 1.40 | +57%  | 6      | [SQ]     |
| GEV    | GE Vern... | 0.44 | 0.51 | ...  | ...  | ...  | ...  | 17.4 | 1.20 | +135% | 4      | [!] [SQ] |
| JPM    | JPMorgan...| ...  | ...  | ...  | ...  | ...  | ...  | ...  | 4.44 | —     | —      | [<6Q]    |
```

**Spalten-Reihenfolge:** Aeltestes Quartal links, juengstes rechts.
Spalten-Header zeigen das Quartalsenddatum (gekuerzt: "Q3 '25").

**Farbcodierung EpsQuarterCell:**
- Positiver EPS: `text-text-primary` (Standard)
- Negativer EPS: `text-danger` (Rot, min. 4.5:1 auf Dark-Hintergrund, WCAG 2.2 AA)
- Kein EPS (null): `—` in `text-text-muted`

**Flags-Spalte (Chips, Analogie zu SignalChip in SmartMoneyGrid):**
- `[SQ]` = Super-Quartal-Kriterien erfuellt (blau/primary)
- `[RQ]` = Record-Quartal, neues 8-Q-EPS-Hoch (gruen/success);
  mit ⚠ wenn record_quarter_outlier (moeglicher Einmaleffekt);
  mit Sub-Pill "Turnaround" wenn record_quarter_turnaround (Verlust → Gewinn)
- `[!]` = Outlier-Flag (gelb/warning)
- `[T]` = Turnaround YoY (violett/neutral)
- `[<6Q]` = Weniger als 6 Quartale (muted)
- `[Veraltet]` = data_age_days > 14 (orange)

### 9.4 Filter-Sidebar (EpsFilters)

```
[Toggle] Nur Super-Quartale
         Super-Quartal-Kriterien erfuellt (?-Tooltip mit Erklaerung)

[Toggle] Nur Record-Quartale
         Juengstes Quartal = neues 8-Q-EPS-Hoch (?-Tooltip mit Erklaerung)
         (kombinierbar mit Super-Quartal-Toggle: AND-Verknuepfung)

[Label] Min. Quartale verfuegbar
[Dropdown] 4 / 6 / 8

[Label] Sektoren
[Checkbox] Information Technology
[Checkbox] Health Care
[Checkbox] Financials
[Checkbox] ... (alle GICS-Sektoren aus Response)

[Label] Sortieren nach
[Radio] YoY-Wachstum (desc) — Default
[Radio] Streak-Count (desc)
[Radio] Juengster EPS (desc)
[Radio] Ticker (asc)
```

### 9.5 WCAG 2.2 AA & Nielsen-Heuristiken

**WCAG:**
- Alle interaktiven Elemente (Toggle, Checkboxen, Radio) mit sichtbarem
  Fokus-Ring (mindestens 3px offset, Analogie zu bestehenden Tailwind-Klassen
  `focus:ring-2 focus:ring-primary`)
- Alle farbcodierten EPS-Werte haben `aria-label` mit Kontext:
  `aria-label="EPS Q3 2025: -0.44, negativ"`
- Tabelle mit `role="table"`, `scope="col"` auf Spalten-Headern,
  `scope="row"` auf Ticker-Spalte
- Sortierbare Spalten-Header: `aria-sort="descending"` / `"ascending"` / `"none"`
- Tooltips via `title`-Attribut (Mindeststandard) + optionales `aria-describedby`
  fuer Outlier- und Turnaround-Flags

**Nielsen-Heuristiken (Checkliste):**
- H1 Systemstatus: Lade-Spinner (Analogie PageLoader), Staleness-Badge
  in der Status-Bar ("Zuletzt aktualisiert: 22.06.2026, 04:17")
- H5 Fehlerpraevention: Thresholds-Formular mit Validierungshinweisen
  vor dem Speichern
- H6 Recognition over Recall: Spalten-Header wiederholen das Quartalsdatum,
  kein blosser "Q1..Q8"
- H8 Aesthetics: Maximal 13 Spalten; keine weiteren Spalten ohne Maintainer-
  Freigabe — Tabelle wird sonst auf Desktop zu breit
- H10 Hilfe/Dokumentation: Info-Icon neben "Super-Quartal-Kriterien erfuellt"
  oeffnet Glossar-Tooltip mit Erklaerung (analog bestehende G-Komponente)

---

## 10. Offene Fragen fuer den Maintainer

### OF-1 (ENTSCHIEDEN 2026-06-22) — Backtest-Gate fuer Schwellenwerte

**Maintainer-Entscheidung: Super-Quartal-Toggle geht sofort live, ABER mit
sichtbarem Disclaimer "Schwellenwert in Pruefung — noch nicht backtest-validiert".**

Konkret:
- Beide Toggles (Super-Quartal + Record-Quartal) sind ab v1 aktiv.
- Der Super-Quartal-Toggle und sein [SQ]-Badge tragen einen persistenten
  Hinweis (Tooltip + Inline-Text): "Schwellenwerte (25% / +5pp) sind
  Arbeits-Defaults, noch nicht durch Forward-Return-Backtest validiert."
- Record-Quartal braucht KEINEN Disclaimer (deterministisch, kein Score-Gewicht).
- Backtest bleibt als Folge-Arbeit offen; nach Validierung wird der Disclaimer
  entfernt und ggf. die Defaults angepasst.

Damit ist die Signal-Weights-Need-Backtest-Regel eingehalten (keine
Kommunikation als validiertes Signal), das Feature aber sofort voll nutzbar.

---

### OF-2 — Kriterium C bei weniger als 2 Vorwerten

Wenn ein Ticker nur 5 Quartale hat, gibt es nur 1 berechneten YoY-Vorgaenger-
Wert. Kriterium C (Acceleration-Median) faellt dann weg (nur A+B+D gelten).
Ist das akzeptabel, oder soll in diesem Fall der Super-Quartal-Toggle
komplett aussetzen fuer diesen Ticker?

---

### OF-3 — Restatement-Handling

Finnhub liefert korrigierte EPS-Werte ohne explizites "restatement"-Flag.
Die Upsert-Semantik (DO UPDATE) ueberschreibt stillschweigend.
Ist das akzeptabel, oder soll eine Versions-/Audit-Spalte eingefuehrt werden?

---

### OF-4 — S&P-500-Listenpflege

Die statische `sp500_universe.py` wird bei S&P-500-Indexanpassungen
(ca. 4x jährlich) veraltet. Optionen:
- A: Manuelles Update durch Maintainer (minimaler Aufwand, leicht vernachlaessigt)
- B: Automatischer Pull via yfinance `pd.read_html` einmal wochentlich
  im Worker (fragil, da externes Scraping)
- C: Statische Datei + GitHub-Action-Reminder (Empfehlung: A fuer v1)

---

### OF-5 (ENTSCHIEDEN 2026-06-22) — Finnhub-Key fuer den Worker

**Maintainer-Entscheidung: System-Level-Finnhub-Key in der Backend-Config
(Environment-Variable), kein User-Key.**

Konkret:
- Neue Settings-Variable `FINNHUB_SYSTEM_API_KEY` in `config.py` (env-backed).
- Der Worker-Job nutzt ausschliesslich diesen Key fuer den Finnhub-Batch.
  Kein `_get_any_user_finnhub_key`-Lookup (entfaellt).
- Fehlt der Key (nicht gesetzt): Job loggt WARNING, ueberspringt den
  Finnhub-Batch und faellt auf yfinance fuer alle Ticker zurueck; der
  `/status`-Endpoint meldet `finnhub_key_configured: false`.
- Maintainer stellt einen (Free-Tier reicht: 60 Calls/min) Finnhub-Key bereit.

Damit ist der Job unabhaengig von User-Settings und auf Multi-User-Instanzen
deterministisch lauffaehig.

---

### OF-6 — YoY-Cap bei >500%

Soll `yoy_growth_pct` in der DB gecappt werden (z.B. max. 999.9),
oder soll der Rohwert gespeichert und nur im UI geclippt werden?
Letzteres ist reversibler (Empfehlung).

---

### OF-7 — Verhalten bei Fiscal-Year-Versatz

Verschiedene Unternehmen haben unterschiedliche Fiskalquartale.
"Vorjahresquartal" = 4 Perioden zurueck aus der Finnhub-Reihe (nicht
Kalender-Quartal). Das ist korrekt fuer Firmen mit Standard-Fiskalquartal,
kann aber bei Firmen mit verschobenem Fiscal Year (z.B. AAPL: Oktober-Ende)
zu suboptimalen YoY-Vergleichen fuehren.

Frage: Ist dieser Ansatz ("4 Perioden zurueck") fuer v1 akzeptabel,
oder soll der Service versuchen, Kalender-Quarter-Alignment herzustellen?

Empfehlung fuer v1: 4-Perioden-Ansatz — einfach, deterministisch,
Finnhub liefert konsistente Reihen je Unternehmen.

---

## Anhang: Abgrenzung zu bestehenden Features

| Feature | EPS-Scanner | Estimate-Revisions-Pipeline |
|---|---|---|
| Daten | Reported EPS (Vergangenheit) | Konsens-EPS-Schaetzungen (Zukunft) |
| Quelle | Finnhub basic_financials | FMP analyst-estimates |
| Granularitaet | Quartal (8 Rows/Ticker) | Taeglicher Snapshot (FY1/FY2) |
| Zweck | Gewinn-Momentum-Trend | Revisions-Signal fuer Smart-Money-Score |
| Beeinflusst Score | NEIN | JA (via screening_service.py) |
| Kill-Gate | NEIN (Feature, nicht Probe) | JA (2026-08-15) |

Die beiden Pipelines sind vollstaendig unabhaengig und teilen nur den
Finnhub-Key-Lookup-Pattern.

---

*Dieses Dokument definiert WAS gebaut wird, nicht WIE. Code-Implementation
obliegt dem Maintainer oder einem separaten Fixer-/Build-Agenten.*
