# SCOPE: Smart Money Screener V3

**Status:** Design-freigegeben, bereit zur Implementierung
**Datum:** 2026-04-09
**Maintainer:** Harry
**Design-Agent:** Claude (Sonnet 4.6)
**Bezug:** Bestehender Screener in `backend/services/screening/` + `frontend/src/pages/Screening.jsx`
**Vorgaenger:** SCOPE_SMART_MONEY_V2.md (bleibt als Historien-Dokument erhalten)

---

## Kontext und Ausgangslage

Der bestehende Screener orchestriert 9 parallele Quellen und aggregiert Signale
ticker-zentrisch in `ScreeningResult.signals` (JSONB). Gewichte heute:

| Signal-Key        | Gewicht | Typ        |
|-------------------|---------|------------|
| `insider_cluster` | +3      | positiv    |
| `superinvestor`   | +2      | positiv    |
| `buyback`         | +2      | positiv    |
| `large_buy`       | +1      | positiv    |
| `congressional`   | +1      | positiv    |
| `short_trend`     | −1      | Warnung    |
| `ftd`             | −1      | Warnung    |
| `unusual_volume`  | 0       | informativ |

Score-Cap: `max(0, min(score, 10))`. V3 erweitert um 6 Bloecke (Block 0–5) ohne
diesen Cap zu aendern — neue Signale passen sich in dasselbe Schema ein.

---

## Implementierungs-Reihenfolge V3 (Value-First statt Risk-First)

**Reihenfolge:**

1. **Block 0 — Backtest-Harness** (neu, Pre-Requisite fuer alle anderen Bloecke)
2. **Block 1 — CFTC COT** (isoliert, kein Einfluss auf bestehenden Screener)
3. **Block 4 — 13D Brief-Volltext** (vorgezogen: niedrigstes Risiko, reine Anreicherung eines bestehenden Signals, keine neue Tabelle)
4. **Block 3 — 13F Q/Q-Diffs** (vorgezogen: hoechster verifizierter Wert — aber mit substanziell ueberarbeiteter Konsens-Architektur und harter CIK-Verifikations-Pre-Condition)
5. **Block 5 — SIX Discovery-Spike (1 Tag)** → bei Erfolg (API-Endpunkt verifiziert): Implementation. Bei Negativ: zurueckstellen oder streichen.
6. **Block 2 — TRACE Discovery-Spike (1 Tag)** → bei Erfolg (Issuer-Level-Spreads bestaetigt): Implementation. Bei Negativ: Block 2 streichen, durch FRED-Sektor-Spreads im Macro-Tab ersetzen (kein per-Ticker-Signal).

**Begruendung fuer die neue Reihenfolge:**

V2 verwendete "bekanntes Risiko zuerst" als Ordnungsprinzip und stellte TRACE
(Block 2) vor 13F (Block 3). Das ist falsch gedacht. Bekanntes Risiko ist nicht
dasselbe wie akzeptables Risiko. TRACE hat ein ~70% Wahrscheinlichkeit, kein
Issuer-Level-Spread zu liefern (benoetigt sonst MarketAxess, ICE Data Services
oder Bloomberg — kostenpflichtig). 13F via EDGAR ist dagegen eine verifizierte,
kostenlose, stabile Quelle.

V3-Prinzip: verifizierter Wert zuerst, unverifizierte Quellen bekommen
Discovery-Spikes mit klarem Abbruch-Kriterium und Fallback-Plan. Niemals
eine Quelle implementieren, bevor die Verfuegbarkeit der Daten bestaetigt ist.

Block 4 wird vorgezogen weil es Anreicherung eines bestehenden Signals ist
(keine neue Tabelle, kein neues Gewicht, minimales Regressionsrisiko) und
unmittelbar nach Block 1 sicher durchfuehrbar ist.

Block 0 ist Pre-Requisite: Bloecke 1, 3, 4, 5 duerfen erst nach Block 0 live
geschaltet werden (jeder Block hat ein Acceptance Criteria "Gewicht durch
Backtest-Harness validiert").

---

## Block 0: Backtest-Harness (Pre-Requisite)

### Problem

Fuenf neue Signale mit Gewichten bis +3 werden eingefuehrt. Ohne Validation gegen
historische Forward-Returns sind diese Gewichte Ratespiele. Ein falsches Gewicht
(z.B. `superinvestor_13f` new_position = +3, aber tatsaechlich Hit-Rate unter
50%) schadet dem Screening-Ergebnis ohne dass der Maintainer es merkt.

### User Story

**Als** Maintainer
**moechte ich** neue Signal-Gewichte gegen historische Forward-Returns validieren
**damit** ich sicherstellen kann, dass ein hoeherer Score tatsaechlich mit
besseren Forward-Returns korreliert, bevor neue Signale live gehen und
Portfolio-Entscheidungen beeinflussen

### Acceptance Criteria

**AC-0: Harness laeuft ohne Exception gegen vorhandene Snapshot-Daten**
- Given: `ScreeningResult`-Tabelle enthaelt mindestens 30 Eintraege mit
  unterschiedlichen Tickers und Scan-Daten
- When: `python -m backend.services.screening.backtest_harness --config default`
  ausgefuehrt wird
- Then: Kein Fehler, Output als CSV oder HTML-Report

**AC-1: Forward-Returns werden pro Score-Bucket gemessen**
- Given: Historische `ScreeningResult`-Snapshots mit `score` und `scan_date`
- When: Harness laeuft mit 30/60/90-Tage-Fenster
- Then: Fuer jedes Score-Bucket (0, 1–2, 3–4, 5–6, 7+) wird der durchschnittliche
  Forward-Return berechnet und gegen SPY-Baseline gestellt

**AC-2: Konfigurierbare Gewichte**
- Given: Ein alternatives Gewichts-Dict `{"superinvestor_13f_new": 1, ...}`
- When: Harness mit `--weights-override` ausgefuehrt wird
- Then: Scores werden mit diesen Gewichten neu berechnet, Forward-Returns
  neu gemessen — Vergleich Default vs. Override moeglich

**AC-3: Neue Signale validiert bevor Live-Schaltung**
- Given: Harness-Report liegt vor
- When: Maintainer Block 1, 3, 4 oder 5 live schalten will
- Then: Fuer jedes neue Signal muss der Report zeigen dass hoeherer Score
  → bessere Forward-Returns (oder konservativere Gewichte waehlen)

**AC-4: Graceful Degradation bei wenig Historiendaten**
- Given: Weniger als 1 Quartal an Snapshots vorhanden
- When: Harness laeuft
- Then: Warning-Ausgabe "Zu wenig Daten fuer statistisch signifikante
  Validation — Snapshot-Sammlung laeuft seit [datum], Wiederholung in 1 Quartal"
  — kein Fehler, kein Crash

### Scope (MoSCoW)

**Must (MVP):**
- `backend/services/screening/backtest_harness.py` — CLI-Tool (nicht in API)
- Liest historische `ScreeningResult`-Eintraege aus der Datenbank
- Berechnet 30/60/90-Tage-Forward-Returns per Ticker via yfinance (historische
  Preise, asynchron ueber `asyncio.to_thread`)
- Misst Return pro Score-Bucket, normalisiert gegen SPY-Baseline
- Output: CSV-Datei (`backtest_output_YYYYMMDD.csv`) UND optionaler HTML-Report
- Konfigurierbare Gewichte via Parameter-Dict oder YAML-Override-File
- Minimum-Daten-Check: weniger als 50 Snapshots → Warning und Abbruch

**Should (v1):**
- Hit-Rate pro einzelnem Signal-Key (nicht nur Gesamt-Score)
- Vergleich zweier Gewichts-Konfigurationen nebeneinander (A/B)

**Could (Later):**
- Integration in CI-Pipeline (automatischer Report nach jedem neuen Quartal)
- Sharpe-Ratio-Berechnung pro Score-Bucket

**Won't:**
- UI-Integration (Tool fuer den Maintainer, nicht fuer den End-User)
- Realtime-Backtesting
- Automatische Gewichts-Optimierung (zu viel Overfitting-Risiko)

### Implementation-Skizze

```
backend/services/screening/backtest_harness.py

Datenfluss:
1. Lade alle ScreeningResult-Eintraege mit score, signals, scan_date, ticker
2. Gruppiere nach scan_date (eindeutige Scan-Laeufe)
3. Fuer jedes (ticker, scan_date)-Paar:
   a. Lade historische Preise: yf_download(ticker, start=scan_date, end=scan_date+91d)
   b. Berechne Return nach 30/60/90 Tagen
   c. Berechne SPY-Return fuer gleichen Zeitraum (Baseline)
   d. Excess-Return = ticker_return - spy_return
4. Gruppiere Eintraege nach score-Bucket (0, 1-2, 3-4, 5-6, 7+)
5. Berechne mittleren Excess-Return und Hit-Rate (% positiver Excess-Returns)
   pro Bucket und Zeitfenster
6. Optional: Wiederhole mit alternativen Gewichten, vergleiche Buckets

Output-CSV-Spalten:
score_bucket | n_tickers | avg_excess_return_30d | hit_rate_30d |
avg_excess_return_60d | hit_rate_60d | avg_excess_return_90d | hit_rate_90d
```

### Offene Fragen

**Offene Frage A-0 (kritisch):** Wie viele historische `ScreeningResult`-Eintraege
existieren aktuell? Falls die Tabelle nicht persistent alle Scan-Ergebnisse
speichert (sondern nur den letzten Scan ueberschreibt), ist kein sinnvoller
Backtest moeglich. In dem Fall: Harness jetzt trotzdem bauen, aber gleichzeitig
sicherstellen dass `ScreeningResult`-Eintraege mit `scan_date` akkumuliert werden
(nicht ueberschrieben). Validation der Gewichte erst nach ~1 Quartal nachreichen.
Bis dahin: konservativere Default-Gewichte (alle neuen Signale auf 50% ihres
V3-Zielgewichts).

**Offene Frage A-1:** Sollen Forward-Returns adjustiert werden fuer Splits und
Dividenden (total return) oder nur Price-Return? Empfehlung: Total Return via
`auto_adjust=True` in yf_download (ist bereits der Default des yf_patch Wrappers).

### Gewicht-Begründung

Kein eigenes Gewicht — Block 0 ist reine Mess-Infrastruktur.

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| Zu wenig Snapshot-Daten fuer sinnvollen Backtest | hoch | mittel | Warning + Abbruch, Sammlung starten, 1 Quartal warten |
| yfinance-Rate-Limiting bei vielen Ticker-Lookups | mittel | niedrig | Batch-Sleep zwischen Requests, asyncio.to_thread |
| Survivorship Bias (delisted Ticker fehlen in yfinance) | mittel | mittel | Dokumentieren als bekannte Einschraenkung im Report-Header |

---

## Block 1: CFTC COT — Macro/Positioning Tab

*(Inhalt unveraendert gegenueber V2 — Block 1 ist isoliert und benoetigt keine
Revision. Aus V2 unveraendert uebernommen.)*

### Problem

Der Screener deckt nur Equity-Mikro-Signale ab. Positionierung institutioneller
Akteure in Futures-Maerkten (Gold, Oel, USD, Bonds) ist ein unabhaengiges
Makro-Signal, das den Equity-Screener nicht kontaminieren darf.

### User Story

**Als** Self-Hosted-Investor
**moechte ich** die aktuelle Positionierung der Commercials und Managed Money in
den wichtigsten Futures-Maerkten auf einen Blick sehen
**damit** ich Extrempositionierungen (z.B. Commercials in Gold auf 52-Wochen-Tief
Short) als Kontra-Signal zu meinem Equity-Screening in Beziehung setzen kann

### Acceptance Criteria

**AC-1: COT-Daten werden woechentlich geladen**
- Given: Freitag ist vergangen und CFTC hat den neuen Report publiziert
- When: Der APScheduler-Job `cot_refresh` laeuft (Samstag 09:00 Zuerich)
- Then: `macro_cot_snapshots` enthaelt einen neuen Eintrag pro Instrument mit
  `report_date`, `commercial_net`, `managed_money_net`, `oi_total`,
  `commercial_net_pct_52w`, `mm_net_pct_52w`

**AC-2: Extrempositionierung wird korrekt berechnet**
- Given: Mindestens 52 Wochen historische Daten sind vorhanden
- When: `commercial_net_pct_52w` wird berechnet
- Then: Wert = (aktuell − 52w-Min) / (52w-Max − 52w-Min) × 100, Bereich 0–100,
  Extremzone = ≤ 10 oder ≥ 90

**AC-3: Frontend zeigt Macro-Tab**
- Given: User ist auf `/screening`
- When: User klickt auf Tab "Macro / Positioning"
- Then: Tabelle mit den konfigurierten COT-Instrumenten, je Zeile:
  Instrument-Name, Report-Datum, Commercial Net (absolut + Perzentil-Bar),
  Managed Money Net (absolut + Perzentil-Bar), Extremzonen farblich
  hervorgehoben (rot = ≥ 90, gruen = ≤ 10)

**AC-4: Fehlende Daten werden graceful behandelt**
- Given: CFTC-CSV nicht erreichbar
- When: Job laeuft
- Then: Letzter bekannter Snapshot bleibt erhalten, `last_error` im Job-State
  wird gesetzt, keine Exception die den Worker stoppt

**AC-5: Gewicht durch Backtest-Harness validiert**
- Given: Block 0 ist implementiert und hat genug Snapshot-Daten
- When: COT-Signal (kein Equity-Gewicht) live geschaltet wird
- Then: Block 0 Report bestätigt kein Score-Einfluss (COT ist Makro-Panel,
  dieser Check ist formal, nicht inhaltlich)

### Scope (MoSCoW)

**Must (MVP):**
- Instrumente: GC (Gold), SI (Silber), CL (WTI Crude), DX (US Dollar Index),
  ZN (10-Year Treasury Note)
- Quelle: CFTC Legacy Combined Report, CSV-Download
- Tabelle `macro_cot_snapshots` mit historischen Wochenwerten
- 52-Wochen-Perzentil fuer Commercials und Managed Money
- Frontend-Tab "Macro / Positioning" in `Screening.jsx`
- APScheduler-Job Samstag 09:00 Zuerich
- Config-Dict in Service (Instrument → CFTC-Market-Code)

**Should (v1):**
- Historischer Chart (Recharts LineChart) fuer ausgewaehltes Instrument
- Disaggregated Report als Alternative zu Legacy

**Could (Later):**
- User-konfigurierbare Instrument-Liste via Settings
- Alert wenn Extremzone erreicht wird

**Won't:**
- Integration in Equity-Screener-Score (COT ist Makro, nicht Equity-Mikro)
- Automatische Handlungsempfehlungen

### API-Shape

```
GET /api/screening/macro/cot
Response:
{
  "updated_at": "2026-04-04T21:00:00Z",
  "report_date": "2026-04-01",
  "instruments": [
    {
      "code": "GC",
      "name": "Gold (COMEX)",
      "report_date": "2026-04-01",
      "commercial_net": -142300,
      "commercial_net_pct_52w": 23.4,
      "mm_net": 198400,
      "mm_net_pct_52w": 71.2,
      "oi_total": 562000,
      "is_extreme_commercial": false,
      "is_extreme_mm": false
    }
  ]
}
```

### DB-Aenderungen

```sql
CREATE TABLE macro_cot_snapshots (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument  VARCHAR(10)  NOT NULL,
    report_date DATE         NOT NULL,
    commercial_long  BIGINT,
    commercial_short BIGINT,
    commercial_net   BIGINT  GENERATED ALWAYS AS (commercial_long - commercial_short) STORED,
    mm_long          BIGINT,
    mm_short         BIGINT,
    mm_net           BIGINT  GENERATED ALWAYS AS (mm_long - mm_short) STORED,
    oi_total         BIGINT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (instrument, report_date)
);
CREATE INDEX ix_macro_cot_instrument_date ON macro_cot_snapshots (instrument, report_date DESC);
```

Alembic-Migration: `alembic/versions/xxxx_add_macro_cot_snapshots.py`

**Neues Model:** `backend/models/macro_cot.py`

**Neuer Service:** `backend/services/screening/cot_service.py`

### Frontend-Impact

**Neue Komponente:** `frontend/src/components/CotMacroPanel.jsx`
- ARIA: `role="table"`, `aria-label="COT Positionierung"`, `<th scope="col">`
- Farbkodierung niemals allein ohne Text-Label (WCAG 1.4.1)

**Tab-Integration:**
```jsx
const [activeTab, setActiveTab] = useState('screener')
<div role="tablist" aria-label="Screener-Ansicht">
  <button role="tab" aria-selected={activeTab === 'screener'} ...>Smart Money Screener</button>
  <button role="tab" aria-selected={activeTab === 'macro'} ...>Macro / Positioning</button>
</div>
```

### Worker-Job

```python
scheduler.add_job(
    _refresh_cot_data,
    CronTrigger(hour=9, minute=0, day_of_week="sat", timezone="Europe/Zurich"),
    id="cot_refresh",
)
```

### Quellen-URLs

- CFTC Legacy Combined: `https://www.cftc.gov/files/dea/history/fut_fin_txt_[year].zip`
- Market-Codes: Gold = `GOLD - COMMODITY EXCHANGE INC.`, Silber = `SILVER - COMMODITY EXCHANGE INC.`, WTI = `CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE`, DX = `U.S. DOLLAR INDEX - ICE FUTURES U.S.`, ZN = `10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE`

### Gewicht-Begründung

Kein Gewicht im Equity-Score — COT ist ein separates Makro-Panel.

---

## Block 4: 13D Brief-Parsing (Aktivisten-Anreicherung)

*(Vorgezogen von Position 4 auf Position 3 in der Implementierungs-Reihenfolge.
Inhalt gegenueber V2 unveraendert.)*

**Reihenfolge-Begruendung:** Block 4 hat das niedrigste Risiko aller Bloecke
(keine neue Tabelle, keine neuen Gewichte, Anreicherung eines bestehenden Signals),
benoetigt keine Discovery-Spike-Validation und blockiert nichts. Er kann direkt
nach Block 1 implementiert werden.

### Problem

Das bestehende `activist`-Signal sagt nur "Aktivist mit 5%+ Beteiligung".
Der eigentliche Katalysator steht in Item 4 des 13D-Filings ("Purpose of
Transaction"): Boardsitz, strategischer Review, Spinoff-Forderung, etc.

### User Story

**Als** Self-Hosted-Investor
**moechte ich** beim Activist-Signal die ersten Zeilen des Purpose-of-Transaction
direkt im Screener sehen
**damit** ich ohne SEC-Website-Besuch einschaetzen kann ob der Aktivist eine
operative Veraenderung anstrebt oder nur eine passive grosse Position aufgebaut hat

### Acceptance Criteria

**AC-1: `letter_excerpt` wird fuer 13D-Filings extrahiert**
- Given: Ein 13D-Filing hat ein XML-Primary-Doc mit Item 4
- When: `_resolve_13d_target` verarbeitet das Filing
- Then: `result` enthaelt `letter_excerpt` (erste 500 Zeichen von Item 4 Plain-Text,
  HTML-Tags entfernt)

**AC-2: `purpose_tags` werden per Keyword-Matching gesetzt**
- Given: `letter_excerpt` enthaelt Keywords
- When: Item 4 Text geparst
- Then: `purpose_tags` enthaelt relevante Tags aus definierter Liste,
  mindestens ein Tag oder leeres Array

**AC-3: Fehlende Item-4-Sektion bricht nichts**
- Given: 13D-Filing hat kein strukturiertes Item 4 (manche aeltere Filings sind PDFs)
- When: Parser findet keinen Item-4-Content
- Then: `letter_excerpt = ""` und `purpose_tags = []`, kein Fehler

**AC-4: Backtest-Gate (formal)**
- Given: Block 0 ist implementiert
- When: Block 4 live geschaltet wird
- Then: Block 0 Report bestaetigt dass Tags keine Score-Aenderung verursachen
  (Tags sind informativ, kein Gewicht — dieser Check ist formal)

### Scope (MoSCoW)

**Must (MVP):**
- Erweiterung `activist_tracker.py` — `_resolve_13d_target` gibt `letter_excerpt`
  und `purpose_tags` zurueck
- Keyword-Dict (10–15 Tags, Regex-basiert, kein LLM)
- Anzeige im Screener-ExpandedRow

**Should (v1):**
- Tag-Filter in Screener-UI (nur Aktivisten mit `board_representation` zeigen)

**Could (Later):**
- HTML-to-plaintext via BeautifulSoup

**Won't:**
- LLM-basiertes Tagging
- Volltext-Speicherung der Briefe

### Keyword-Tags

| Tag | Regex-Pattern (case-insensitive) |
|-----|----------------------------------|
| `board_representation` | `board seat\|board member\|director\|board representation` |
| `strategic_review` | `strategic review\|strategic alternative\|explore.*sale\|sale process` |
| `spinoff` | `spin.?off\|separation\|divestiture\|divest` |
| `buyback_demand` | `share repurchase\|buyback\|return.*capital\|capital return` |
| `management_change` | `management change\|replace.*ceo\|new.*management\|leadership change` |
| `merger_opposition` | `oppose.*merger\|against.*acquisition\|block.*deal` |
| `going_private` | `going private\|privatization\|take.*private` |
| `dividend_demand` | `special dividend\|dividend increase\|return.*dividend` |
| `passive_investment` | `investment purposes\|long.?term\|passive\|no current plans` |

### API-Shape

Kein neuer Endpoint. `activist`-Signal in `ScreeningResult.signals` erhaelt neue Sub-Keys:

```json
"activist": {
  "investor": "Elliott Management",
  "form": "13D",
  "filing_date": "2026-03-15",
  "letter_excerpt": "The Reporting Person acquired the Shares for investment purposes and intends to seek board representation...",
  "purpose_tags": ["board_representation", "strategic_review"]
}
```

### DB-Aenderungen

Keine neue Tabelle, keine Alembic-Migration.

### Frontend-Impact

```jsx
{key === 'activist' && (
  <div>
    <span className="text-text-muted ml-2">
      {data.investor || 'Aktivist'} &mdash; {data.form || '13D/13G'}
      {data.filing_date ? ` (${data.filing_date})` : ''}
    </span>
    {data.purpose_tags?.length > 0 && (
      <div className="flex gap-1 mt-1 ml-2 flex-wrap">
        {data.purpose_tags.map(tag => (
          <span key={tag} className="text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded">
            {PURPOSE_TAG_LABELS[tag] || tag}
          </span>
        ))}
      </div>
    )}
    {data.letter_excerpt && (
      <p className="text-xs text-text-muted mt-1 ml-2 italic line-clamp-2">
        "{data.letter_excerpt}"
      </p>
    )}
  </div>
)}
```

### Gewicht-Begründung

Kein neues Gewicht. Tags sind informativ-anreichend.

---

## Block 3: 13F Q/Q-Diffs via SEC EDGAR (Konsens-Architektur)

*(Vollstaendig neu geschrieben gegenueber V2. Konsens-Ansatz statt Single-Fund-Gewichtung.
Harte CIK-Verifikations-Pre-Condition. Neuer Datenfluss: erst aggregieren, dann projizieren.)*

### Problem

`dataroma_scraper.py` liefert aggregierte Grand-Portfolio-Daten, aber keine
strukturierten Q/Q-Positions-Aenderungen. V2 behandelte eine neue Position durch
einen einzelnen Fonds (z.B. Burry) als gleichwertig mit einem Insider-Cluster
(mehrere Officers, Realtime, Form-4). Das ist nicht zu rechtfertigen:

- 13F hat 45 Tage Lag — die Position ist seit bis zu 2 Monaten alt.
- Hit-Rate-Streuung zwischen Managern ist erheblich (Burry: viele Fehlcalls;
  Klarman: konservativ und Extensions-beantragend; Tepper: taktisch).
- Form-4-Insider wissen es zuerst. 13F-Filer 45 Tage spaeter. Symmetrische
  Gewichtung ist nicht zu rechtfertigen.
- Single-Fund-Signal ist Rauschen. Der einzige Weg, den 45-Tage-Lag zu
  kompensieren, ist Konsens ueber mehrere Manager.

### User Story

**Als** Self-Hosted-Investor
**moechte ich** sehen ob mehrere getracknte Fonds einen Ticker in ihrem letzten
13F-Quartal gleichzeitig neu aufgebaut oder aufgestockt haben
**damit** ich Konsens-Interesse des Smart Money erkenne und das 45-Tage-Lag
durch den Mehrheits-Effekt kompensiere

### Acceptance Criteria

**AC-1: Aggregation vor Projektion**
- Given: Fund A und Fund B haben beide Ticker X in Q1 neu aufgebaut,
  Fund C hat aufgestockt
- When: `compute_consensus_signal(db, ticker, quarter)` laeuft
- Then: Service aggregiert zuerst alle 20 getrackten Fonds fuer Ticker X
  in diesem Quartal (Zaehler: wie viele Fonds welche Action haben),
  DANN setzt Signal und Gewicht basierend auf Konsens-Schwelle.
  NICHT: "pro Fund pro Ticker ein separates Signal"

**AC-2: Single-Fund neue Position ist informativ, kein hoher Score**
- Given: Nur Fund A (1 von 20) hat Ticker X neu aufgebaut
- When: Konsens-Aggregation laeuft
- Then: `superinvestor_13f` mit `action: "new_position"`, `consensus_count: 1`,
  Score +1 (informativ, nicht +3)

**AC-3: Multi-Fund Konsens bei neuer Position**
- Given: Mindestens 3 Fonds haben Ticker X im selben Quartal neu aufgebaut
- When: Konsens-Aggregation laeuft
- Then: `superinvestor_13f` mit `action: "new_position"`, `consensus_count: >= 3`,
  Score +3 (echter Edge, Lag kompensiert durch Konsens)

**AC-4: Aufstockung Single-Fund vs. Konsens**
- Given: 1 Fund hat Ticker X um >20% aufgestockt
- When: Aggregation laeuft
- Then: Score 0 (zu viele Confounder: Tax-Loss, Rebalancing, Liquiditaet)

- Given: ≥ 3 Fonds haben Ticker X im selben Quartal um >20% aufgestockt
- When: Aggregation laeuft
- Then: Score +2

**AC-5: Reduktion und Schliessung Single-Fund haben kein Score-Impact**
- Given: 1 Fund hat Ticker X um >20% reduziert oder geschlossen
- When: Aggregation laeuft
- Then: Score 0 (Confounder: Rebalancing, Tax-Loss, Timing unbekannt)

**AC-6: Konsens-Reduktion und Schliessung**
- Given: ≥ 3 Fonds haben Ticker X reduziert oder geschlossen
- When: Aggregation laeuft
- Then: Score −1

**AC-7: Taeglich EDGAR-Check, Diff nur bei neuem Filing**
- Given: EDGAR wird taeglich geprueft
- When: Kein neues Filing seit letztem Check
- Then: Kein neuer Snapshot, kein Diff, kein Signal-Update

**AC-8: CIK-Verifikation als harte Pre-Condition**
- Given: Block 3 soll implementiert werden
- When: Implementierung startet
- Then: Verifikations-Skript wurde ausgefuehrt und alle CIKs in `TRACKED_13F_FUNDS`
  wurden gegen EDGAR bestaetigt. Kein unverifizierter CIK in Produktion.

**AC-9: Backtest-Gate**
- Given: Block 0 ist implementiert und hat ausreichend Snapshot-Daten
- When: Block 3 live geschaltet wird
- Then: Backtest-Harness zeigt dass `consensus_count >= 3 / new_position (+3)`
  einen positiven Forward-Return-Effekt hat. Falls nicht: Gewicht auf +2 senken
  und erneut validieren.

### CIK-Verifikations-Pre-Condition (harte Anforderung)

**Das folgende Verifikations-Skript MUSS ausgefuehrt werden bevor Block 3
implementiert wird. Kein CIK darf aus Memory uebernommen werden.**

**Verifikations-Methode:**

Fuer jeden Fund-Namen in der Liste: EDGAR Full-Text-Search aufrufen:

```
https://efts.sec.gov/LATEST/search-index?q="[FUND_NAME]"&dateRange=custom&startdt=2024-01-01&forms=13F-HR
```

Die Antwort enthaelt `hits.hits[].`_source.period_of_report`,
`hits.hits[].`_source.entity_name`, `hits.hits[].`_source.file_num`,
und den CIK aus `hits.hits[].`_id` oder dem Dateinamen.

**Alternativ:** EDGAR Company-Search:
```
https://www.sec.gov/cgi-bin/browse-edgar?company=[FUND_NAME]&CIK=&type=13F-HR&dateb=&owner=include&count=10&search_text=&action=getcompany
```

**Skript-Output:** `fund_cik_verification.json` mit Status `verified` oder
`not_found` oder `multiple_matches` pro Fund.

**Fund-Liste mit CIK-Status (V3 — alle unverifiziert bis Skript laeuft):**

| Fund | Manager | CIK (V2-Angabe) | V3-Status |
|------|---------|-----------------|-----------|
| Berkshire Hathaway | Warren Buffett | 0001067983 | unverifiziert — muss durch Verifikations-Skript bestaetigt werden |
| Scion Asset Management | Michael Burry | 0001649339 | unverifiziert — muss durch Verifikations-Skript bestaetigt werden |
| Pershing Square Capital | Bill Ackman | 0001336528 | unverifiziert — muss durch Verifikations-Skript bestaetigt werden |
| Appaloosa Management | David Tepper | 0001656456 | unverifiziert — muss durch Verifikations-Skript bestaetigt werden |
| Pabrai Investment Fund | Mohnish Pabrai | 0001173334 | unverifiziert — muss durch Verifikations-Skript bestaetigt werden |
| Third Point LLC | Dan Loeb | 0001350694 | unverifiziert — muss durch Verifikations-Skript bestaetigt werden |
| Elliott Investment Management | Paul Singer | 0001061768 | unverifiziert — muss durch Verifikations-Skript bestaetigt werden |
| Baupost Group | Seth Klarman | 0001067983 (V2-Angabe) | FEHLER IN V2 — dieser CIK ist Berkshire Hathaway, nicht Baupost. Baupost CIK unverifiziert — muss durch Verifikations-Skript ermittelt werden. |
| Fairholme Capital | Bruce Berkowitz | — | CIK nicht in V2 enthalten — durch Verifikations-Skript hinzufuegen oder streichen |
| Gotham Asset Management | Joel Greenblatt | — | CIK nicht in V2 enthalten — durch Verifikations-Skript hinzufuegen oder streichen |

**Hinweis zum V2-Fehler:** In V2 wurde Baupost Group faelschlicherweise mit
CIK 0001067983 angegeben — das ist Berkshire Hathaways CIK. Copy-Paste-Fehler.
Baupost nutzt vermutlich ein separates Reporting-Vehicle, der korrekte CIK muss
zwingend via EDGAR-Suche ermittelt werden.

**Ziel:** 10–20 verifizierte Fonds in `TRACKED_13F_FUNDS`. Lieber 10 verifizierte
als 20 unverified.

### Konsens-Gewichts-Tabelle V3

| Action | Single-Fund (1–2 Fonds) | Konsens (≥3 Fonds, selbes Quartal) |
|--------|------------------------|-------------------------------------|
| `new_position` | +1 (informativ) | +3 (echter Edge, Lag kompensiert) |
| `added` (>20% aufgestockt) | 0 (Confounder: Rebalancing, Tax-Loss) | +2 |
| `reduced` (>20% reduziert) | 0 (zu viele Confounder) | −1 |
| `closed` | 0 (Timing unbekannt, 45d-Lag) | −1 |

**Begruendung Single-Fund `new_position = +1` statt +3 (V2):**
45 Tage Lag bedeutet die Position wurde zwischen Q-Ende und Filing-Datum
aufgebaut — bei guenstigen Bedingungen bis zu 90 Tage vor dem Signal.
Ein einzelner Fonds-Manager (auch Burry) hat eine dokumentierte Hit-Rate
unter 60% ueber mehrere Jahre. Das rechtfertigt +1 (informativ), nicht +3.

**Begruendung `reduced` Single-Fund = 0:**
Reduktionen haben zu viele Confounder (Tax-Loss-Harvesting, Liquiditaets-
bedarf, Rebalancing zu Quartals-Ende). Ohne Konsens-Kontext ist eine
Reduktion kein verwertbares Signal.

### Architektur-Aenderung: Aggregations-First-Datenfluss

V2 hatte: "pro Fund pro Ticker ein Signal" (falsch).
V3 hat: "erst aggregieren, dann projizieren" (korrekt).

```
sec_13f_service.py — neuer Datenfluss:

1. fetch_all_13f_filings(db) — laedt alle neuen Filings fuer alle 10–20 tracked CIKs
2. fuer jeden CIK: parse_13f_xml(filing) → list[HoldingRow(ticker, shares, value_usd)]
3. store_snapshot(db, cik, holdings, filing_date) → upsert in fund_holdings_snapshot
4. compute_diffs_all_funds(db, quarter) → fuer jedes (fund_cik, ticker):
   vergleiche neuen Snapshot mit Vorquartal → (action, change_pct)
   Ergebnis: List[FundDiff(fund_cik, ticker, action, change_pct, filing_date)]
5. aggregate_by_ticker(diffs) → gruppiere nach ticker:
   {
     "AAPL": {
       "new_position": ["Scion", "ThirdPoint", "Pershing"],
       "added":        ["Berkshire"],
       "reduced":      [],
       "closed":       []
     }
   }
6. project_signal(ticker_agg) → setzt superinvestor_13f-Signal + Score
   basierend auf Konsens-Tabelle (AC-2 bis AC-6)
```

**Keine Pro-Fund-Signale** — nur ticker-zentrischer Konsens-Score.

### API-Shape

**Signal-Shape im `signals`-JSONB (V3, ticker-zentrisch):**

```json
"superinvestor_13f": {
  "action": "new_position",
  "consensus_count": 3,
  "funds": [
    { "fund": "Scion Asset Management", "action": "new_position", "filing_date": "2026-02-14" },
    { "fund": "Third Point LLC", "action": "new_position", "filing_date": "2026-02-10" },
    { "fund": "Pershing Square Capital", "action": "new_position", "filing_date": "2026-02-20" }
  ],
  "quarter": "2025-Q4",
  "score_applied": 3
}
```

**Optionaler Fund-Lookup-Endpoint (Should):**
```
GET /api/screening/13f/fund/{cik}
```

### DB-Aenderungen

```sql
CREATE TABLE fund_holdings_snapshot (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_cik      VARCHAR(15)   NOT NULL,
    fund_name     VARCHAR(200)  NOT NULL,
    ticker        VARCHAR(30)   NOT NULL,
    shares        BIGINT        NOT NULL,
    value_usd     BIGINT,
    filing_date   DATE          NOT NULL,
    period_date   DATE          NOT NULL,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (fund_cik, ticker)
);
CREATE INDEX ix_fund_holdings_ticker ON fund_holdings_snapshot (ticker);
CREATE INDEX ix_fund_holdings_fund ON fund_holdings_snapshot (fund_cik, filing_date DESC);
```

Alembic-Migration: `alembic/versions/xxxx_add_fund_holdings_snapshot.py`

### Frontend-Impact

```js
superinvestor_13f: {
  label: '13F Konsens',
  glossar: '13F Konsens',
  short: 'F',
  icon: Users,
  description: 'SEC 13F Q/Q-Konsens: Anzahl getrackter Fonds mit gleicher Positions-Aenderung',
  type: 'positive'
}
```

ExpandedRow zeigt `consensus_count` und Fund-Liste:
```jsx
{key === 'superinvestor_13f' && (
  <span className="text-text-muted ml-2">
    {data.action_label} — {data.consensus_count} {data.consensus_count === 1 ? 'Fonds' : 'Fonds'}
    {data.quarter ? ` (${data.quarter})` : ''}
    {data.funds?.length > 0 && `: ${data.funds.map(f => f.fund).join(', ')}`}
  </span>
)}
```

### Worker-Job

```python
scheduler.add_job(
    _refresh_13f_holdings,
    CronTrigger(hour=8, minute=0, timezone="Europe/Zurich"),
    id="sec_13f_refresh",
)
```

### Gewicht-Begründung (V3 Konsens-Tabelle)

Vollstaendige Begruendung in AC-2 bis AC-6 und Konsens-Gewichts-Tabelle oben.
Zusammenfassung: Single-Fund-Signale sind aufgrund des 45-Tage-Lags und der
individuellen Manager-Hit-Rate-Streuung nur informativ (+1). Konsens ueber
≥3 Fonds kompensiert das Lag durch den Mehrheits-Effekt und rechtfertigt +3.

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| CIK-Verifikation ergibt weniger als 10 verifizierte Fonds | mittel | mittel | Konsens-Schwelle auf ≥2 Fonds senken, nicht auf ≥3 |
| EDGAR XML-Schema aendert sich | niedrig | hoch | Schema-Version in Parse-Funktion loggen, Test-Fixture einchecken |
| Baupost nutzt vertrauliche 13F (Confidential Treatment) | hoch | mittel | Fund aus Liste streichen wenn keine public 13F vorhanden |
| 45-Tage-Lag wird als "frisches Signal" missinterpretiert | mittel | mittel | `quarter` und `filing_date` im Signal anzeigen |
| Backtest zeigt kein positives Signal fuer Konsens-Score | niedrig | hoch | Gewichte senken, nicht ignorieren |

**Audit-Checks:**
- `compute_diffs_all_funds` muss idempotent sein
- `aggregate_by_ticker` muss ohne Fehler laufen wenn 0 Fonds einen Ticker haben
- CIK-Verifikations-Skript muss `verified`-Status fuer alle CIKs in Produktion zeigen

---

## Block 5: SIX Insider — Discovery-Spike

**Status: Discovery-Spike. Noch nicht implementieren.**

**Discovery-Spike-Aufwand:** 1 Tag.
**Ziel:** API-Endpunkt verifizieren und Datenformat pruefen.
**Abbruch-Kriterium:** Kein maschinenlesbarer Endpunkt auffindbar → Block 5 zurueckstellen oder streichen.
**Fallback:** Kein Ersatz-Block (SIX ist Optional fuer CH-Heimat-Bias).

**Discovery-Spike-Aufgaben:**
1. Browser-DevTools auf `https://www.ser-ag.com/en/resources/notifications-market-participants/management-transactions.html` — XHR-Calls dokumentieren
2. `https://rds.six-group.com/` — maschinenlesbarer Feed vorhanden?
3. SIX Official Notices: `https://www.six-group.com/en/products-services/the-swiss-stock-exchange/market-data/news-tools/official-notices.html` — XML/CSV verfuegbar?
4. Wenn Endpunkt gefunden: 10 Eintraege parsen, Ticker-Format dokumentieren
5. Wenn kein Endpunkt: Spike-Report mit "nicht verfuegbar" — Block 5 zurueckstellen

**Bei Erfolg:** Implementation wie in V2 Block 5 beschrieben (unveraendert).
Zusaetzliches Acceptance Criteria: Backtest-Gate (Block 0 muss `six_insider = +3`
validieren — analog zu `insider_cluster = +3`).

**Problem, User Story, Acceptance Criteria, Scope, API-Shape, DB-Aenderungen,
Frontend-Impact, Gewicht-Begruendung:** Unveraendert aus V2 Block 5 uebernehmen
wenn Discovery-Spike erfolgreich. Hier nicht wiederholt um das Dokument nicht mit
nicht-verifizierten Specs aufzublaehen.

**Hinweis `MIN_ABSOLUTE_VOLUME`:** Fuer `.SW`-Ticker muss `MIN_ABSOLUTE_VOLUME_CH = 5_000`
statt des US-Defaults gelten (SMI-Aktien haben strukturell niedrigeres Volumen).

---

## Block 2: TRACE Credit-Stress — Discovery-Spike

**Status: Discovery-Spike. Noch nicht implementieren.**

**Discovery-Spike-Aufwand:** 1 Tag.
**Ziel:** Bestaetigen ob FINRA TRACE API Issuer-Level-Spread-Daten liefert.
**Wahrscheinlichkeit Erfolg:** ~30%. Fuer Issuer-Level braucht man sonst
MarketAxess, ICE Data Services oder Bloomberg (alle kostenpflichtig).
**Abbruch-Kriterium:** TRACE liefert kein Issuer-Level-Spread → Block 2 streichen,
durch FRED-Sektor-Spreads im Macro-Tab ersetzen (kein per-Ticker-Signal moeglich).
**Fallback:** FRED ICE BofA Corporate Spread Indices als Sektor-Aggregate im
Macro-Tab (COT-Panel erweitern). Kein `credit_stress`-Signal pro Ticker.

**Discovery-Spike-Aufgaben:**
1. `https://api.finra.org/data/group/otcmarket/name/tradeReport` — Granularitaet pruefen
2. `https://developer.finra.org/docs` — Dokumentation lesen, Issuer-Level-Filter vorhanden?
3. Testcall mit bekanntem Issuer (z.B. AAPL-CUSIP 037833100) — Spread-Daten abrufbar?
4. Ticker-zu-CUSIP-Mapping-Machbarkeit pruefen (EDGAR XBRL oder FMP)
5. Wenn Issuer-Level bestaetigt: Implementation wie V2 Block 2.
   Wenn nicht: Fallback-Spec fuer FRED-Spreads im Macro-Tab schreiben.

**Bei Erfolg:** Implementation wie in V2 Block 2 beschrieben.
Zusaetzliches Acceptance Criteria: Backtest-Gate (`credit_stress = −2` muss zeigen
dass betroffene Ticker tatsaechlich underperformt haben).

**Gewicht-Begründung bei Erfolg:** `credit_stress = −2` (V2-Begruendung unveraendert gueltig).

---

## Signal-Verfuegbarkeits-Matrix pro Universum

**Neuer Abschnitt V3. In V2 komplett fehlend.**

Wenn Block 5 (SIX) live geht, haben CH-Ticker strukturell einen niedrigeren
Maximal-Score als US-Ticker, weil `superinvestor_13f`, `congressional`, `activist`
und `credit_stress` (falls erfolgreich) alle US-only sind.

| Signal | US (NYSE/NASDAQ) | CH (.SW) |
|--------|-----------------|---------|
| `insider_cluster` (Form-4) | ✓ | — |
| `large_buy` (Form-4) | ✓ | — |
| `six_insider` (SER) | — | ✓ (nach Spike) |
| `superinvestor_13f` (EDGAR) | ✓ | — |
| `superinvestor` (Dataroma) | ✓ | — |
| `activist` (13D) | ✓ | — |
| `buyback` (SEC) | ✓ | (separat pruefen — OR § 663 SCO ist anders strukturiert als SEC Form 10b-18) |
| `congressional` (CapitolTrades) | ✓ | — |
| `credit_stress` (TRACE) | ✓ (falls Spike erfolgreich) | — |
| `short_trend` (FINRA) | ✓ | — |
| `ftd` (SEC) | ✓ | — |
| `unusual_volume` (yfinance) | ✓ | ✓ (mit `MIN_ABSOLUTE_VOLUME_CH = 5_000`) |

**Folge der Asymmetrie:**

US-Ticker: bis zu 10 Signale verfuegbar (theoretisch)
CH-Ticker: maximal 3 Signale verfuegbar (`six_insider`, `unusual_volume`, evtl. `buyback`)

**Optionen:**

**Option A: Maximal-Score-Normalisierung pro Universum**
- Score_normalized = score_raw / max_possible_score_for_universe × 10
- US: max_possible = 16 → normalisiert auf 10
- CH: max_possible = 6 → normalisiert auf 10
- Pro: Scores sind direkt vergleichbar
- Contra: Komplexer im Service, schwer zu erklaeren im UI ("warum ist ein
  Score von 3 bei CH-Tickern gleichwertig mit 5 bei US-Tickern?"),
  Normalisierungs-Faktor aendert sich wenn neue Signale hinzukommen
- Reversibilitaet: Einbahn-Tuer (aendert semantische Bedeutung des Scores)

**Option B: Expliziter UI-Hinweis ohne Normalisierung**
- Score bleibt absolut (raw)
- Frontend zeigt fuer CH-Ticker: "Hinweis: Fuer Schweizer Titel sind
  weniger Signalquellen verfuegbar — Score nicht direkt vergleichbar mit US-Titeln"
- Pro: Einfach, ehrlich, kein Code-Komplexitaet im Score-Service
- Contra: User muss das verstehen und mental einrechnen
- Reversibilitaet: Zwei-Wege-Tuer (jederzeit durch A ersetzbar)

**Empfehlung: Option B.**

Begruendung: Das Ein-Personen-Projekt hat einen bekannten User (Maintainer selbst).
Die Asymmetrie ist strukturell und kann nicht durch Normalisierung behoben werden
(ein `six_insider`-Signal hat anderen Informationsgehalt als `insider_cluster +
activist + congressional`). Option A wuerde eine Schein-Vergleichbarkeit erzeugen.
Option B ist ehrlich und reversibler. Normalisierung kann spaeter nachgeruest werden
wenn das UI konfus wirkt.

**Implementation Option B:**
Im Frontend: `ScreeningResult.ticker.endsWith('.SW')` → Hinweis-Badge oder
Tooltip neben dem Score-Display.

---

## Gesamt-Gewichts-Uebersicht nach V3

| Signal-Key | Gewicht | Neu in V3 | Aenderung vs. V2 |
|------------|---------|-----------|-----------------|
| `insider_cluster` | +3 | — | unveraendert |
| `superinvestor_13f` new_position Konsens (≥3) | +3 | Block 3 | V2 hatte +3 fuer Single-Fund — jetzt nur bei Konsens |
| `six_insider` | +3 | Block 5 (nach Spike) | unveraendert |
| `superinvestor` | +2 | — | unveraendert |
| `buyback` | +2 | — | unveraendert |
| `superinvestor_13f` added Konsens (≥3) | +2 | Block 3 | neu (V2 hatte +1 fuer Single-Fund added) |
| `large_buy` | +1 | — | unveraendert |
| `congressional` | +1 | — | unveraendert |
| `superinvestor_13f` new_position Single-Fund (1–2) | +1 | Block 3 | NEU: V2 hatte +3 fuer Single-Fund — jetzt nur +1 |
| `unusual_volume` | 0 | — | unveraendert |
| `activist` (tags) | 0 | Block 4 (informativ) | unveraendert |
| `superinvestor_13f` closed (kein Konsens) | 0 | Block 3 | unveraendert |
| `short_trend` | −1 | — | unveraendert |
| `ftd` | −1 | — | unveraendert |
| `superinvestor_13f` reduced Konsens (≥3) | −1 | Block 3 | V2 hatte −1 fuer Single-Fund — jetzt nur bei Konsens |
| `superinvestor_13f` closed Konsens (≥3) | −1 | Block 3 | neu |
| `superinvestor_13f` reduced Single-Fund | 0 | Block 3 | NEU: V2 hatte −1 fuer Single-Fund — jetzt 0 |
| `credit_stress` | −2 | Block 2 (nach Spike) | unveraendert |

---

## Offene Fragen (Zusammenfassung V3)

| ID | Block | Frage | Prioritaet |
|----|-------|-------|------------|
| A-0 | Backtest | Wie viele ScreeningResult-Eintraege existieren? Akkumulierend oder ueberschreibend? | Hoch — blockiert Gewichts-Validation |
| A-1 | Backtest | Total Return oder Price-Return fuer Forward-Return-Berechnung? | Niedrig (Empfehlung: Total Return) |
| B-1 | TRACE | FINRA TRACE API liefert Issuer-Level Bond Spreads oder nur Aggregate? | Hoch — blockiert Block 2 |
| B-2 | TRACE | Ticker→CUSIP-Mapping: FMP, EDGAR oder manuell? | Hoch — blockiert Block 2 |
| C-1 | 13F | Alle CIKs unverifiziert — Verifikations-Skript als Pre-Condition | Hoch — blockiert Block 3 |
| C-2 | 13F | Baupost CIK in V2 war Berkshire-CIK (Copy-Paste-Fehler) — korrekter CIK offen | Hoch |
| C-3 | 13F | Baupost (Klarman) beantrag oft Extensions und vertrauliche 13F — Fund moeglicherweise streichen | Mittel |
| D-1 | SIX | `price_usd`-Feld fuer CHF-Ticker: leer lassen oder spaeter umbenennen? | Niedrig |
| D-2 | SIX | SIX SER API-Endpunkt verifizieren via Browser-DevTools (Discovery-Spike) | Hoch — blockiert Block 5 |
| D-3 | SIX | `MIN_ABSOLUTE_VOLUME_CH = 5_000` fuer `.SW`-Ticker | Mittel |

---

## WCAG 2.2 AA Compliance (neue Komponenten)

**`CotMacroPanel.jsx`:**
- `role="table"`, `<th scope="col">` fuer alle Spalten-Headers
- Perzentil-Bars: `aria-label="Perzentil: 23%"`
- Farbkodierung niemals allein ohne Text-Label (WCAG 1.4.1)
- Kontrast: `text-danger` und `text-success` ≥ 4.5:1 auf `bg-card`

**Tab-Komponente in `Screening.jsx`:**
- `role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`
- Keyboard-Navigation: Pfeil-Tasten zwischen Tabs (WCAG 2.1.1)
- Fokus-Ring: `focus-visible:ring-2`

**Signal-Badges:**
- `title`-Attribut auf jedem Badge
- `short`-Text fuer `six_insider` ist "CH" (2 Zeichen) — passt in `w-6 h-6`-Badge

**CH-Ticker-Hinweis (Option B):**
- Tooltip-Text muss auch fuer Screen-Reader zugaenglich sein: `aria-label` auf Badge

---

## Nielsen-Heuristiken (neue UI-Elemente)

| Heuristik | Anwendung |
|-----------|-----------|
| #1 Sichtbarkeit Systemstatus | COT-Tab zeigt `updated_at`-Timestamp; `filing_date` und `quarter` in 13F-Signal anzeigen (45d-Lag transparent machen) |
| #4 Konsistenz und Standards | Neue Signals folgen exakt `SIGNAL_CONFIG`-Pattern, `SignalBadge` wiederverwendet |
| #6 Fehler-Praevention | Discovery-Spikes verhindern Implementation unverifizierter Quellen |
| #7 Flexibilitaet und Effizienz | `consensus_count` als Zahl sichtbar — Power-User sieht sofort Staerke des Signals |
| #8 Aesthetik und Minimalismus | Tags in Block 4 als kleine Pills; CH-Hinweis als dezentes Badge, nicht als Modal |
| #9 Hilfe beim Erkennen von Fehlern | CH-Ticker-Hinweis erklaert strukturelle Score-Asymmetrie, kein generischer Fehler |

---

## CHANGELOG: V2 → V3

### Korrektur 1: Reihenfolge umgedreht — Value-First statt Risk-First

**V2 sagte:** Block 2 (TRACE) vor Block 3 (13F), Begruendung "bekanntes Risiko zuerst".
Block-Reihenfolge: COT → TRACE → 13F → 13D → SIX.

**V3 sagt:** Block 4 (13D) vor Block 3 (13F), und beide Discovery-Spikes (TRACE, SIX)
ans Ende. Block-Reihenfolge: Backtest-Harness → COT → 13D → 13F → SIX-Spike → TRACE-Spike.

**Weil:** Bekanntes Risiko ist nicht dasselbe wie akzeptables Risiko. TRACE hat
~70% Wahrscheinlichkeit zu scheitern (kein Issuer-Level-Spread ohne kostenpflichtige
Datenlieferanten). 13F via EDGAR ist verifizierte, kostenlose, stabile Quelle.
V3-Prinzip: verifizierter Wert zuerst, unverifizierte Quellen bekommen Discovery-Spikes
mit klarem Abbruch-Kriterium und Fallback-Plan.

---

### Korrektur 2: Block 3 — 13F als Konsens-Signal, nicht Single-Fund

**V2 sagte:** `superinvestor_13f` new_position = +3 fuer jeden einzelnen Fund.
Single-Burry-Position gleichgestellt mit Insider-Cluster.

**V3 sagt:** new_position Single-Fund = +1 (informativ); new_position Konsens ≥3 Fonds = +3.
Neuer Datenfluss: erst alle Fonds aggregieren, dann ticker-zentrisch projizieren.
Kein "pro Fund pro Ticker ein Signal" mehr.

**Weil:** 45d-Lag macht Single-Fund-Signale zu rauschreich. Hit-Rate-Streuung
zwischen Managern ist erheblich. Form-4-Insider sind frueher informiert als 13F-Filer.
Der einzige Weg den Lag zu kompensieren ist Konsens ueber mehrere Manager.
Gleiche Logik fuer `added`, `reduced`, `closed` — alle auf Konsens-Schwelle gehoben.

---

### Korrektur 3: Block 3 — Fund-CIKs zwingend gegen EDGAR verifizieren

**V2 sagte:** Baupost Group CIK = 0001067983 (im Fliesstext als eigene Angabe).
Im selben Dokument stand Berkshire Hathaway ebenfalls mit CIK 0001067983.
Copy-Paste-Fehler. Pabrai und weitere ebenfalls unverifiziert aus Memory uebernommen.

**V3 sagt:** Alle CIKs explizit als `unverifiziert` markiert. Verifikations-Skript
via EDGAR Full-Text-Search ist harte Pre-Condition fuer Block 3. Kein CIK darf
aus Memory in Produktion gehen. Baupost-CIK-Fehler explizit dokumentiert.

**Weil:** Ein falscher CIK wuerde Daten eines falschen Fonds laden und
falsche Signale erzeugen — schlimmstenfalls unbemerkt. Verifikation kostet
30 Minuten, verhindert systematischen Datenfehler.

---

### Korrektur 4: Universum-Verfuegbarkeits-Matrix

**V2 sagte:** Nichts. Keine Erwaehnung der Signal-Asymmetrie zwischen US und CH.

**V3 sagt:** Neuer Abschnitt "Signal-Verfuegbarkeits-Matrix pro Universum" mit
vollstaendiger Matrix (12 Signale × 2 Universen). Explizite Diskussion zweier
Optionen (Normalisierung vs. UI-Hinweis). Empfehlung: Option B (UI-Hinweis),
weil Schein-Vergleichbarkeit durch Normalisierung schlimmer waere als
transparente Asymmetrie.

**Weil:** CH-Ticker haben strukturell maximal 3 verfuegbare Signale vs. 10 bei
US-Tickern. Ohne explizites Statement wuerde niemand das merken und das Frontend
wuerde verwirrende Score-Diskrepanzen zeigen.

---

### Korrektur 5: Block 0 — Backtest-Harness als neuer Pre-Requisite-Block

**V2 sagte:** Nichts. Fuenf neue Signale mit Gewichten bis +3 ohne Validation.

**V3 sagt:** Neuer Block 0 als harter Gate vor allen anderen Bloecken.
`backend/services/screening/backtest_harness.py` — CLI-Tool das historische
ScreeningResult-Snapshots durchlaeuft, Signal-Sets mit konfigurierbaren Gewichten
neu berechnet, 30/60/90-Tage-Forward-Returns pro Score-Bucket misst, gegen
SPY-Baseline stellt. Alle anderen Bloecke haben als Acceptance Criteria:
"Gewicht durch Backtest-Harness validiert".

**Weil:** Ohne Backtest sind Gewichte Ratespiele. Ein falsches Gewicht
schadet dem Screening-Ergebnis ohne dass der Maintainer es merkt. Aufwand
~1 Tag. Offene Frage ob genug Snapshots vorhanden sind (A-0) — falls nein:
Harness jetzt bauen, Validation nach 1 Quartal nachholen, vorerst
konservativere Default-Gewichte.

---

*Dokument-Ende. V3 ersetzt V2 als aktiver Scope. V2 bleibt als Historien-Dokument erhalten.*
*Pfad: `/home/harry/projects/openfolio/SCOPE_SMART_MONEY_V3.md`*
