# SCOPE: Smart Money Screener V4

**Status:** Design-freigegeben, bereit zur Implementierung
**Datum:** 2026-04-09
**Maintainer:** Harry
**Design-Agent:** Claude (Sonnet 4.6)
**Bezug:** Bestehender Screener in `backend/services/screening/` + `frontend/src/pages/Screening.jsx`
**Vorgaenger:** SCOPE_SMART_MONEY_V3.md (bleibt als Historien-Dokument erhalten)

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

Score-Cap: `max(0, min(score, 10))`. V4 erweitert um 6 Bloecke (Block 0a, 0b, 1–5) ohne
diesen Cap zu aendern — neue Signale passen sich in dasselbe Schema ein.

---

## Implementierungs-Reihenfolge V4

**Reihenfolge:**

1. **Block 0a — Retention + Harness-Skelett** (neu, Pre-Requisite fuer alle anderen Bloecke)
2. **Block 1 — CFTC COT** (isoliert, kein Einfluss auf bestehenden Screener)
3. **Block 4 — 13D Brief-Volltext** (vorgezogen: niedrigstes Risiko, reine Anreicherung eines bestehenden Signals, keine neue Tabelle)
4. **Block 3 — 13F Q/Q-Diffs** (hoechster verifizierter Wert — mit Konsens-Architektur und harter CIK-Verifikations-Pre-Condition; startet mit provisional-Gewichten)
5. **Block 5 — SIX Discovery-Spike (1 Tag)** → bei Erfolg: Implementation. Bei Negativ: zurueckstellen oder streichen.
6. **Block 2 — TRACE Discovery-Spike (1 Tag)** → bei Erfolg: Implementation. Bei Negativ: Block 2 streichen, durch FRED-Sektor-Spreads im Macro-Tab ersetzen.
7. **Block 0b — Gewichts-Validierung** (+90 Tage nach Block 0a Live, kein Implementations-Block)

**Begruendung fuer die Reihenfolge:**

V2 verwendete "bekanntes Risiko zuerst" als Ordnungsprinzip. V3/V4-Prinzip:
verifizierter Wert zuerst, unverifizierte Quellen bekommen Discovery-Spikes mit
klarem Abbruch-Kriterium und Fallback-Plan. Block 4 wird vorgezogen weil es
Anreicherung eines bestehenden Signals ist (keine neue Tabelle, kein neues Gewicht,
minimales Regressionsrisiko).

Block 0a ist Pre-Requisite: liefert die Infrastruktur fuer Retention und Harness-Skelett.
Block 0b ist kein Implementations-Block, sondern ein Review-Block — seine Pre-Condition
ist "90 Tage History vorhanden", nicht "Code fertig". Er kann erst nach Block 0a Live
sinnvoll ausgefuehrt werden.

---

## Block 0a: Retention + Harness-Skelett (Pre-Requisite)

### Bestaetigter Befund (kein Unbekanntes mehr)

**Offene Frage A-0 aus V3 ist geschlossen. Befund: Worst Case.**

Untersuchte Stellen:

- `backend/api/screening.py:44-59` — `start_scan` loescht explizit alle
  abgeschlossenen Scans ausser dem neuesten:
  `select(ScreeningScan).where(status.in_(["completed","error"])).order_by(desc(started_at)).offset(1)`
  — alles ab dem zweiten Scan wird via `db.delete()` weggeworfen, inkl. CASCADE
  auf ScreeningResult.
- `backend/services/screening/screening_service.py:277` — `run_scan` loescht alle
  ScreeningResult-Rows vor jedem Insert (auch innerhalb desselben Scans).
- `backend/models/screening.py:33` — `ScreeningResult.scan_id` hat `ondelete="CASCADE"`.

**Konsequenz:** Zum Launch-Zeitpunkt existieren null historische Signal-Snapshots.
Der Backtest-Harness kann bei V4-Launch NICHTS validieren. Block 0a muss zuerst
die Retention-Infrastruktur aufbauen, damit History ueberhaupt akkumuliert werden kann.

### Problem

Fuenf neue Signale mit Gewichten bis +3 werden eingefuehrt. Ohne Validation gegen
historische Forward-Returns sind diese Gewichte Ratespiele. Ein falsches Gewicht
schadet dem Screening-Ergebnis ohne dass der Maintainer es merkt. Vor der Validation
muss jedoch erst History akkumuliert werden — das erfordert eine Retention-Aenderung
und ein Harness-Skelett, das beim Launch einsatzbereit ist, aber noch "insufficient data"
meldet.

### User Story

**Als** Maintainer
**moechte ich** dass Scan-Ergebnisse ueber mehrere Monate akkumuliert werden und
ein Backtest-Tool bereitsteht, das diese History auswertet
**damit** ich nach 90 Tagen neue Signal-Gewichte gegen echte Forward-Returns validieren
kann, bevor ich sie produktiv verwende

### Acceptance Criteria

**AC-0a-1: Scan-Ergebnisse werden retained, nicht ueberschrieben**
- Given: Ein neuer Scan wird gestartet
- When: `start_scan` ausgefuehrt wird
- Then: Bestehende ScreeningScan-Eintraege mit Status "completed" oder "error"
  bleiben erhalten (kein `.offset(1)`-Delete mehr). Scans aelter als 365 Tage
  werden durch einen Cleanup-Job entfernt.

**AC-0a-2: Cleanup-Job entfernt nur alte Scans**
- Given: ScreeningScan-Tabelle enthaelt Eintraege
- When: Cleanup-Job laeuft (taeglich, Zeitpunkt konfigurierbar)
- Then: Scans mit `started_at < now() - interval '365 days'` werden geloescht
  (inkl. CASCADE auf ScreeningResult). Neuere Scans bleiben unveraendert.

**AC-0a-3: Harness-Skelett laeuft ohne Exception, auch bei leerer History**
- Given: ScreeningResult-Tabelle enthaelt weniger als 50 Eintraege
- When: `python -m backend.services.screening.backtest_harness --config default`
  ausgefuehrt wird
- Then: Warning-Ausgabe "Insufficient data — snapshot collection started [datum],
  retry in 90 days". Kein Fehler, kein Crash. CSV-Output mit Hinweis auf fehlende Daten.

**AC-0a-4: Signal-Rekonstruktions-Logiken implementiert**
- Given: Harness laeuft gegen beliebige History-Groesse
- When: `--weights-override {"superinvestor_13f_consensus": 2}` uebergeben wird
- Then: Scores werden mit diesen Gewichten neu berechnet, kein Fehler

**AC-0a-5: Forward-Return-Berechnung technisch korrekt**
- Given: Mindestens 50 Snapshots vorhanden
- When: Harness mit 30/60/90-Tage-Fenster laeuft
- Then: Fuer jedes Score-Bucket (0, 1–2, 3–4, 5–6, 7+) wird der durchschnittliche
  Forward-Return berechnet und gegen SPY-Baseline gestellt. Output als CSV.

### Empfehlung: Retention-Option B

**Option A:** Neue Tabelle `screening_history` (Snapshot pro Scan, denormalisierte
Signale als JSONB). Sauberer, aber mehr Arbeit (neue Migration, neues Model,
Harness liest aus anderer Tabelle).

**Option B:** `.offset(1)`-Loeschlogik in `start_scan` entfernen und durch
Retention-by-age ersetzen ("behalte alle Scans der letzten 365 Tage, Cleanup-Job
loescht aeltere"). Weniger Arbeit, ScreeningScan/ScreeningResult wachsen mit
jedem Scan.

**Empfehlung: Option B.**

Begruendung: Bei ~50–200 Results pro Scan und 1 Scan/Tag sind das ueber 365 Tage
maximal ~73k Rows — vernachlaessigbar. Speicherplatz ist quasi frei; 365 Tage geben
dem Backtest ein ausreichend langes Forward-Return-Fenster (bis zu 90d Lookback)
plus mehrere Quartalszyklen fuer die Konsens-Signal-Validierung. Option B erfordert keine neue Tabelle,
keine neue Abstraktionsschicht, und der Harness liest weiterhin aus den
bestehenden ScreeningResult-Eintraegen. Der einzige Code-Eingriff ist das Entfernen
der `.offset(1)`-Zeile und das Hinzufuegen eines Cleanup-Jobs.

### Abgrenzung Block 0a vs. Block 0b

**Block 0a validiert KEINE Gewichte.** Block 0a liefert ausschliesslich:
1. Retention-Infrastruktur (History akkumuliert sich)
2. Harness-Skelett (technisch funktionsfaehig, meldet "insufficient data" beim Launch)

**Block 0b** validiert die Gewichte — aber erst wenn 90 Tage History vorhanden sind.

### Scope (MoSCoW)

**Must (MVP):**
- Alembic-Migration `alembic/versions/XXX_screening_history_retention.py`: kein
  Schema-Aenderung (Option B benoetigt keine neue Tabelle), aber Kommentar und
  Cleanup-Job-Konfiguration dokumentiert
- Entfernen der `.offset(1)`-Loeschlogik in `backend/api/screening.py:44-59`
- Entfernen des Pre-Insert-Deletes in `backend/services/screening/screening_service.py:277`
- Cleanup-Job im Worker: loescht Scans aelter als 365 Tage (APScheduler, taeglich)
- `backend/services/screening/backtest_harness.py` — CLI-Tool-Skelett mit:
  - Liest ScreeningResult + ScreeningScan aus DB
  - Signal-Rekonstruktions-Logiken (alle bestehenden + neuen Signale)
  - Forward-Return-Berechnung via yf_download (asyncio.to_thread)
  - Score-Bucket-Aggregation
  - Konfigurierbare Gewichte via `--weights-override` (JSON oder YAML)
  - "Insufficient data"-Warning bei < 50 Snapshots
  - CSV-Output `backtest_output_YYYYMMDD.csv`

**Should (v1):**
- Hit-Rate pro einzelnem Signal-Key (nicht nur Gesamt-Score)
- Vergleich zweier Gewichts-Konfigurationen nebeneinander (A/B)
- HTML-Report optional

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
   b. Berechne Return nach 30/60/90 Tagen (Total Return, auto_adjust=True)
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

### Offene Fragen (Block 0a)

**A-0** — GESCHLOSSEN. Befund dokumentiert oben: History wird aktuell NICHT
akkumuliert. Retention-Fix ist Kernaufgabe von Block 0a.

**A-1:** Total Return oder Price-Return fuer Forward-Return-Berechnung?
Empfehlung: Total Return via `auto_adjust=True` (ist bereits Default des yf_patch Wrappers).

### Gewicht-Begruendung

Kein eigenes Gewicht — Block 0a ist reine Mess-Infrastruktur.

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| Retention-Aenderung bricht bestehende Screener-Logic | niedrig | mittel | Existing Tests laufen lassen, kein Schema-Change |
| yfinance-Rate-Limiting bei vielen Ticker-Lookups | mittel | niedrig | Batch-Sleep zwischen Requests, asyncio.to_thread |
| Survivorship Bias (delisted Ticker fehlen in yfinance) | mittel | mittel | Dokumentieren als bekannte Einschraenkung im Report-Header |

---

## Block 0b: Gewichts-Validierung (Review-Block, +90 Tage nach Block 0a Live)

**Status: Review-Block. Kein Implementations-Block. Pre-Condition: 90 Tage History vorhanden.**

### Abgrenzung

Block 0b ist kein Software-Implementierungs-Block. Er ist ein geplanter
Review-Termin mit konkret definierten Aktionen.

Pre-Condition: **nicht** "Code fertig", sondern "90 Tage History in ScreeningResult
akkumuliert". Das ist fruestmoeglichst ~90 Tage nach Block 0a Live-Schaltung.

### Vorgehen

1. Backtest-Harness gegen akkumulierte History ausfuehren
2. Forward-Return-Report pro Signal / Score-Bucket generieren
3. Output auswerten: "Signal X mit Gewicht Y → Forward-Return 30/60/90d vs SPY-Baseline"
4. Pro Signal mit Status `provisional` (siehe Gesamt-Gewichts-Uebersicht): pruefen ob
   hoeherer Score tatsaechlich mit besserem Forward-Return korreliert
5. Bei negativem Effekt: Gewicht senken oder Schwelle anheben
6. Konkrete Anpassungen als separate Fix-Tasks nachziehen

### Scope (MoSCoW)

**Must:**
- Harness-Ausfuehrung gegen echte 90-Tage-History
- Report fuer alle `provisional`-Signale: `superinvestor_13f_consensus`,
  `superinvestor_13f_single`, `credit_stress` (falls live), `six_insider` (falls live)
- Report fuer alle `legacy`-Signale: `superinvestor`, `buyback`, `large_buy`,
  `congressional`, `short_trend`, `ftd`, `unusual_volume` — Aufwand null
  (Harness laeuft ohnehin gegen alle Score-Buckets), Erkenntnis potenziell hoch
  (vielleicht ist `congressional = +1` historisch falsch gewichtet)
- Entscheidung: Gewichte beibehalten, senken oder Signal deaktivieren

**Won't:**
- Neue Software-Aenderungen (diese folgen als separater Fix-Task wenn noetig)
- Launch-Blocker fuer irgendein vorheriges Block (Block 0b ist kein Gate)

---

## Block 1: CFTC COT — Macro/Positioning Tab

*(Inhalt unveraendert gegenueber V3 — Block 1 ist isoliert und benoetigt keine
Revision. Aus V3 unveraendert uebernommen.)*

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

**AC-5: Kein Backtest-Gate (COT ist Makro-Panel)**
- Given: Block 0a ist implementiert
- When: COT-Signal live geschaltet wird
- Then: Kein Score-Einfluss — dieser Check ist formal und entfaellt als Gate.
  COT laeuft separat im Macro-Tab, kein Equity-Score-Einfluss.

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

### Gewicht-Begruendung

Kein Gewicht im Equity-Score — COT ist ein separates Makro-Panel.

---

## Block 4: 13D Brief-Parsing (Aktivisten-Anreicherung)

*(Vorgezogen. Inhalt gegenueber V3 unveraendert.)*

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

**AC-4: Tags aendern keinen Score (formal)**
- Given: Block 0a ist implementiert
- When: Block 4 live geschaltet wird
- Then: Tags sind `enrichment_only` — kein Score-Einfluss. Kein Backtest-Gate
  erforderlich.

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

### Gewicht-Begruendung

Kein neues Gewicht. Tags sind informativ-anreichend (`enrichment_only`).

---

## Block 3: 13F Q/Q-Diffs via SEC EDGAR (Konsens-Architektur)

*(Vollstaendig neu geschrieben gegenueber V2. Konsens-Ansatz statt Single-Fund-Gewichtung.
Harte CIK-Verifikations-Pre-Condition. Neuer Datenfluss: erst aggregieren, dann projizieren.
V4: AC-9 als Post-Launch-Review umformuliert, Quartal-Definition praezisiert.)*

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
**moechte ich** sehen ob mehrere getrackte Fonds einen Ticker in ihrem letzten
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
- Given: Nur Fund A (1 von 20) hat Ticker X neu aufgebaut, Quartal ist aggregations-bereit
- When: Konsens-Aggregation laeuft
- Then: `superinvestor_13f_single` mit `action: "new_position"`, `consensus_count: 1`,
  Score +1 (informativ, nicht +3)

**AC-3: Multi-Fund Konsens bei neuer Position**
- Given: Mindestens 3 Fonds haben Ticker X im selben Quartal neu aufgebaut,
  Quartal ist aggregations-bereit (Tag 75 nach Q-Ende)
- When: Konsens-Aggregation laeuft
- Then: `superinvestor_13f_consensus` mit `action: "new_position"`, `consensus_count: >= 3`,
  Score +3

**AC-4: Aufstockung Single-Fund vs. Konsens**
- Given: 1 Fund hat Ticker X um >20% aufgestockt, Quartal aggregations-bereit
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

**AC-9: Quartal-Aggregations-Fenster eingehalten**
- Given: Ein Quartal ist abgeschlossen
- When: `compute_consensus_signal` fuer dieses Quartal aufgerufen wird
- Then: Aggregation erfolgt erst am Tag 75 nach Q-Ende (siehe Quartal-Definition unten).
  Vor diesem Stichtag: nur `superinvestor_13f_single` aktiv. Ab Tag 75: Konsens
  einmalig berechnet, weitere Late-Filer fuer dieses Quartal ignoriert.

**AC-9 Post-Launch-Review (Follow-up-Task-Kandidat, kein Launch-Blocker):**

_90 Tage nach Block-3-Live-Schaltung wird der Backtest-Harness gegen die
akkumulierten Signale gefahren. Bei negativem oder neutralem Forward-Return-Effekt
fuer Konsens-new_position: Konsens-Schwelle auf ≥4 anheben oder new_position-Gewicht
von +3 auf +2 senken. Der Review-Task wird als Follow-up in die Task-Liste eingetragen,
nicht als Launch-Blocker._

**Begruendung fuer die Trennung von Launch-Gate und Review:**
Zum Launch-Zeitpunkt existieren null historische Signal-Snapshots fuer `superinvestor_13f`.
Block 3 kann den Backtest nicht bestehen, bevor der Backtest ueberhaupt Daten hat.
Das ist kein Designfehler — es ist die ehrlichste Handhabung. Block 3 startet mit
`provisional`-Gewichten (siehe Gesamt-Gewichts-Uebersicht) und wird nach 90 Tagen
nachvalidiert. Wer auf einen vorab-validierten Backtest wartet, wuerde Block 3 auf
unbestimmte Zeit blokkieren.

### Quartal-Definition fuer 13F-Konsens (V4-Prazisierung)

13F-Filings kommen gestaffelt zwischen Tag 30 und Tag 75 nach Q-Ende rein (45d
Filing-Deadline plus moegliche Extensions). Ohne explizite Regel wuerde der Konsens-Check
wackeln, wenn ein Spaet-Einreicher nachtraeglich die Konsens-Schwelle erfuellt.

**Explizite Regeln:**

- "Quartal X gilt als aggregations-bereit am **Tag 75 nach Q-Ende**" (30 Tage nach
  der 45d-Filing-Deadline — genug Puffer fuer Extensions).
- Vor Tag 75: einzelne new_position-Signale sind als `superinvestor_13f_single`
  sichtbar (Status: single-fund, Score +1). Der Konsens-Check laeuft noch nicht.
- Zwischen Tag 45 und Tag 75: `superinvestor_13f_single` ist aktiv,
  `superinvestor_13f_consensus` ist `pending`.
- **Ab Tag 75: Konsens wird einmalig berechnet und gesetzt. Weitere Late-Filer
  werden fuer dieses Quartal ignoriert.** Dadurch ist der Konsens-Score deterministisch
  und wackelt nicht mehr.
- Naechstes Quartal startet den Zyklus neu.

**Quartal-Stichtage (Beispiele):**

| Quartal | Q-Ende | Tag 45 (frueheste Deadline) | Tag 75 (Aggregations-Stichtag) |
|---------|--------|-----------------------------|---------------------------------|
| Q4 2025 | 31. Dez 2025 | 14. Feb 2026 | 16. Maerz 2026 |
| Q1 2026 | 31. Maerz 2026 | 15. Mai 2026 | 14. Juni 2026 |
| Q2 2026 | 30. Juni 2026 | 14. Aug 2026 | 13. Sep 2026 |

**Hinweis:** Einige Manager (z.B. Klarman/Baupost) beantragen regelmaessig
Confidential Treatment Extensions. Fuer diese Fonds kann der Stichtag faktisch
spaeter liegen. Tag 75 deckt die grosse Mehrheit ab; wer nach Tag 75 einreicht,
wird fuer das entsprechende Quartal ignoriert.

### CIK-Verifikations-Pre-Condition (harte Anforderung)

**Das folgende Verifikations-Skript MUSS ausgefuehrt werden bevor Block 3
implementiert wird. Kein CIK darf aus Memory uebernommen werden.**

**Verifikations-Methode:**

Fuer jeden Fund-Namen in der Liste: EDGAR Full-Text-Search aufrufen:

```
https://efts.sec.gov/LATEST/search-index?q="[FUND_NAME]"&dateRange=custom&startdt=2024-01-01&forms=13F-HR
```

**Alternativ:** EDGAR Company-Search:
```
https://www.sec.gov/cgi-bin/browse-edgar?company=[FUND_NAME]&CIK=&type=13F-HR&dateb=&owner=include&count=10&search_text=&action=getcompany
```

**Skript-Output:** `fund_cik_verification.json` mit Status `verified` oder
`not_found` oder `multiple_matches` pro Fund.

**Fund-Liste mit CIK-Status (V4 — alle unverifiziert bis Skript laeuft, 1:1 aus V3):**

| Fund | Manager | CIK (V2-Angabe) | V4-Status |
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

### Konsens-Gewichts-Tabelle V4

| Action | Single-Fund (1–2 Fonds) | Konsens (≥3 Fonds, selbes Quartal) |
|--------|------------------------|-------------------------------------|
| `new_position` | +1 (informativ, `superinvestor_13f_single`) | +3 (Edge durch Konsens, `superinvestor_13f_consensus`) |
| `added` (>20% aufgestockt) | 0 (Confounder: Rebalancing, Tax-Loss) | +2 |
| `reduced` (>20% reduziert) | 0 (zu viele Confounder) | −1 |
| `closed` | 0 (Timing unbekannt, 45d-Lag) | −1 |

Alle 13F-Gewichte haben Status `provisional` bis Block 0b gelaufen ist.

### Architektur-Aenderung: Aggregations-First-Datenfluss

V2 hatte: "pro Fund pro Ticker ein Signal" (falsch).
V3/V4 haben: "erst aggregieren, dann projizieren" (korrekt).

```
sec_13f_service.py — Datenfluss:

1. fetch_all_13f_filings(db) — laedt alle neuen Filings fuer alle 10-20 tracked CIKs
2. fuer jeden CIK: parse_13f_xml(filing) → list[HoldingRow(ticker, shares, value_usd)]
3. store_snapshot(db, cik, holdings, filing_date) → upsert in fund_holdings_snapshot
4. compute_diffs_all_funds(db, quarter) → fuer jedes (fund_cik, ticker):
   vergleiche neuen Snapshot mit Vorquartal → (action, change_pct)
   Ergebnis: List[FundDiff(fund_cik, ticker, action, change_pct, filing_date)]
5. check_quarter_ready(quarter) → True erst ab Tag 75 nach Q-Ende
   Vor Tag 75: nur superinvestor_13f_single-Signale setzen (Score +1)
   Ab Tag 75: Konsens-Aggregation einmalig ausfuehren
6. aggregate_by_ticker(diffs) → gruppiere nach ticker:
   {
     "AAPL": {
       "new_position": ["Scion", "ThirdPoint", "Pershing"],
       "added":        ["Berkshire"],
       "reduced":      [],
       "closed":       []
     }
   }
7. project_signal(ticker_agg) → setzt superinvestor_13f_consensus oder
   superinvestor_13f_single + Score basierend auf Konsens-Tabelle
```

**Keine Pro-Fund-Signale** — nur ticker-zentrischer Konsens-Score.

### API-Shape

**Signal-Shape im `signals`-JSONB (V4, ticker-zentrisch):**

Konsens-Signal (ab Tag 75, ≥3 Fonds):
```json
"superinvestor_13f_consensus": {
  "action": "new_position",
  "consensus_count": 3,
  "funds": [
    { "fund": "Scion Asset Management", "action": "new_position", "filing_date": "2026-02-14" },
    { "fund": "Third Point LLC", "action": "new_position", "filing_date": "2026-02-10" },
    { "fund": "Pershing Square Capital", "action": "new_position", "filing_date": "2026-02-20" }
  ],
  "quarter": "2025-Q4",
  "quarter_ready_date": "2026-03-16",
  "score_applied": 3
}
```

Single-Fund-Signal (vor Tag 75 oder < 3 Fonds):
```json
"superinvestor_13f_single": {
  "action": "new_position",
  "consensus_count": 1,
  "funds": [
    { "fund": "Scion Asset Management", "action": "new_position", "filing_date": "2026-02-14" }
  ],
  "quarter": "2025-Q4",
  "quarter_status": "pending",
  "score_applied": 1
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

**Zwei Signal-Config-Eintraege** (einer fuer Single, einer fuer Konsens):
```js
superinvestor_13f_single: {
  label: '13F Einzelfonds',
  short: 'F1',
  icon: User,
  description: 'SEC 13F: Einzelner getrackter Fonds hat Position veraendert (informativ, Konsens-Pruefung ausstehend)',
  type: 'positive'
},
superinvestor_13f_consensus: {
  label: '13F Konsens',
  short: 'FC',
  icon: Users,
  description: 'SEC 13F Q/Q-Konsens: Mindestens 3 getrackte Fonds mit gleicher Positions-Aenderung (Quartal aggregations-bereit)',
  type: 'positive'
}
```

ExpandedRow zeigt `consensus_count`, Quartal-Status und Fund-Liste:
```jsx
{(key === 'superinvestor_13f_consensus' || key === 'superinvestor_13f_single') && (
  <span className="text-text-muted ml-2">
    {data.action_label} — {data.consensus_count} {data.consensus_count === 1 ? 'Fonds' : 'Fonds'}
    {data.quarter ? ` (${data.quarter})` : ''}
    {data.quarter_status === 'pending' && (
      <span className="ml-1 text-xs text-warning">(Konsens-Pruefung ausstehend bis Quartalsstichtag)</span>
    )}
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

### Gewicht-Begruendung (V4 Konsens-Tabelle)

Vollstaendige Begruendung in AC-2 bis AC-6 und Konsens-Gewichts-Tabelle oben.
Zusammenfassung: Single-Fund-Signale sind aufgrund des 45-Tage-Lags und der
individuellen Manager-Hit-Rate-Streuung nur informativ (+1). Konsens ueber
≥3 Fonds kompensiert das Lag durch den Mehrheits-Effekt und rechtfertigt +3.
Beide Gewichte sind `provisional` bis Block 0b gelaufen ist.

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| CIK-Verifikation ergibt weniger als 10 verifizierte Fonds | mittel | mittel | Konsens-Schwelle auf ≥2 Fonds senken, nicht auf ≥3 |
| EDGAR XML-Schema aendert sich | niedrig | hoch | Schema-Version in Parse-Funktion loggen, Test-Fixture einchecken |
| Baupost nutzt vertrauliche 13F (Confidential Treatment) | hoch | mittel | Fund aus Liste streichen wenn keine public 13F vorhanden |
| Klarman/Baupost reicht regelmaessig nach Tag 75 ein (Extensions) → wird systematisch aus Konsens ausgeschlossen, taucht ggf. nur in `_single` auf | hoch | niedrig | Dokumentiert und akzeptiert; kein Code-Workaround. Konsequenz der Tag-75-Regel, kein Bug. |
| 45-Tage-Lag wird als "frisches Signal" missinterpretiert | mittel | mittel | `quarter` und `filing_date` im Signal anzeigen |
| Konsens-Score zeigt in Block 0b keinen positiven Effekt | niedrig | hoch | Gewichte senken (provisional-Status erlaubt das, kein Revert noetig) |

**Audit-Checks:**
- `compute_diffs_all_funds` muss idempotent sein
- `aggregate_by_ticker` muss ohne Fehler laufen wenn 0 Fonds einen Ticker haben
- `check_quarter_ready` muss Tag-75-Stichtag korrekt berechnen
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
Signal-Key `six_insider`, Gewicht +3, Status `provisional` beim Launch.

**Post-Launch-Review-AC (Follow-up-Task-Kandidat, kein Launch-Blocker):**
_90 Tage nach Block-5-Live-Schaltung: Backtest-Harness gegen `six_insider`-History.
Bei negativem Forward-Return-Effekt: Gewicht auf +2 senken. Review-Task in Task-Liste
eintragen._

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
**Wahrscheinlichkeit Erfolg:** ~30%.
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

**Bei Erfolg:** Signal-Key `credit_stress`, Gewicht −2, Status `provisional` beim Launch.

**Post-Launch-Review-AC (Follow-up-Task-Kandidat, kein Launch-Blocker):**
_90 Tage nach Block-2-Live-Schaltung: Backtest-Harness gegen `credit_stress`-History.
`−2` muss zeigen dass betroffene Ticker tatsaechlich underperformt haben.
Bei neutralem Effekt: Gewicht auf −1 senken. Review-Task in Task-Liste eintragen._

**Gewicht-Begruendung bei Erfolg:** `credit_stress = −2` (V2-Begruendung unveraendert gueltig).

---

## Signal-Verfuegbarkeits-Matrix pro Universum

*(Unveraendert aus V3.)*

Wenn Block 5 (SIX) live geht, haben CH-Ticker strukturell einen niedrigeren
Maximal-Score als US-Ticker, weil `superinvestor_13f_consensus`, `congressional`,
`activist` und `credit_stress` (falls erfolgreich) alle US-only sind.

| Signal | US (NYSE/NASDAQ) | CH (.SW) |
|--------|-----------------|---------|
| `insider_cluster` (Form-4) | ✓ | — |
| `large_buy` (Form-4) | ✓ | — |
| `six_insider` (SER) | — | ✓ (nach Spike) |
| `superinvestor_13f_consensus` (EDGAR) | ✓ | — |
| `superinvestor_13f_single` (EDGAR) | ✓ | — |
| `superinvestor` (Dataroma) | ✓ | — |
| `activist` (13D) | ✓ | — |
| `buyback` (SEC) | ✓ | (separat pruefen — OR § 663 SCO ist anders strukturiert als SEC Form 10b-18) |
| `congressional` (CapitolTrades) | ✓ | — |
| `credit_stress` (TRACE) | ✓ (falls Spike erfolgreich) | — |
| `short_trend` (FINRA) | ✓ | — |
| `ftd` (SEC) | ✓ | — |
| `unusual_volume` (yfinance) | ✓ | ✓ (mit `MIN_ABSOLUTE_VOLUME_CH = 5_000`) |

**Empfehlung: Option B — expliziter UI-Hinweis ohne Normalisierung.**
(Begruendung unveraendert aus V3: Schein-Vergleichbarkeit durch Normalisierung
waere schlimmer als transparente Asymmetrie.)

---

## Gesamt-Gewichts-Uebersicht nach V4

### Standard-Signale

| Signal-Key | Gewicht | Neu in V4 | Status | Aenderung vs. V2 |
|------------|---------|-----------|--------|-----------------|
| `insider_cluster` | +3 | — | `validated` | unveraendert |
| `six_insider` | +3 | Block 5 (nach Spike) | `provisional` | unveraendert |
| `superinvestor` | +2 | — | `legacy` | unveraendert |
| `buyback` | +2 | — | `legacy` | unveraendert |
| `large_buy` | +1 | — | `legacy` | unveraendert |
| `congressional` | +1 | — | `legacy` | unveraendert |
| `activist` (13D Tags) | 0 | Block 4 | `enrichment_only` | Tags sind informativ, kein Score |
| `unusual_volume` | 0 | — | `legacy` | unveraendert |
| `short_trend` | −1 | — | `legacy` | unveraendert |
| `ftd` | −1 | — | `legacy` | unveraendert |
| `credit_stress` | −2 | Block 2 (nach Spike) | `provisional` | unveraendert |
| COT (Makro-Tab) | n/a | Block 1 | `n/a` | separates Panel, kein Equity-Score |

### 13F-Signale (Konsens-Matrix)

| Action | Signal-Key | Gewicht | Status |
|--------|------------|---------|--------|
| `new_position`, ≥3 Fonds | `superinvestor_13f_consensus` | +3 | `provisional` |
| `added` >20%, ≥3 Fonds | `superinvestor_13f_consensus` | +2 | `provisional` |
| `new_position`, 1–2 Fonds | `superinvestor_13f_single` | +1 | `provisional` |
| `reduced` >20%, 1–2 Fonds | `superinvestor_13f_single` | 0 | `provisional` |
| `closed`, 1–2 Fonds | `superinvestor_13f_single` | 0 | `provisional` |
| `reduced` >20%, ≥3 Fonds | `superinvestor_13f_consensus` | −1 | `provisional` |
| `closed`, ≥3 Fonds | `superinvestor_13f_consensus` | −1 | `provisional` |

**Status-Legende:**

| Status | Bedeutung |
|--------|-----------|
| `validated` | Signal wurde durch Backtest-Harness gegen Forward-Returns geprueft und positiv befunden. Beim Launch: nur `insider_cluster` (breit in Academic Research belegt). |
| `legacy` | Bestandssignal aus V1 — laeuft mit historischer Begruendung, wurde aber nicht gegen Forward-Returns validiert. Block 0b prueft diese Signale mit, nicht nur die provisorischen. Bei negativem Effekt: Gewicht anpassen als Follow-up-Task. |
| `provisional` | Signal ist neu in V3/V4, live und im Score aktiv, aber Gewicht wird durch Block 0b nachvalidiert und ggf. angepasst. Kein Show-Stopper fuer Launch. |
| `n/a` | Signal ist nicht im Equity-Score (laeuft separat im Macro-Tab) |
| `enrichment_only` | Signal aendert keinen Score, reichert nur bestehende Signale an |

**Bewusste Entscheidung bezueglich provisorischer Gewichte:** Bis Block 0b
gelaufen ist, sind alle neuen Signale unvalidiert. Das ist kein Designfehler —
es ist die ehrlichste Handhabung. Ohne Retention (Block 0a) gibt es keine History,
ohne History gibt es keinen Backtest, ohne Backtest gibt es keine validierten Gewichte.
Der `provisional`-Status plus geplantes Post-Launch-Review (Block 0b, +90 Tage)
ist der einzig moegliche und ehrlichste Weg fuer ein Ein-Personen-Projekt mit
Null-Snapshot-Ausgangslage.

---

## Offene Fragen (Zusammenfassung V4)

| ID | Block | Frage | Status V4 |
|----|-------|-------|-----------|
| A-0 | Backtest | Wie viele ScreeningResult-Eintraege existieren? Akkumulierend oder ueberschreibend? | **GESCHLOSSEN** — Worst Case bestaetigt: History existiert nicht. Retention-Fix ist Block 0a. |
| A-1 | Backtest | Total Return oder Price-Return fuer Forward-Return-Berechnung? | Offen (Empfehlung: Total Return via auto_adjust=True) |
| B-1 | TRACE | FINRA TRACE API liefert Issuer-Level Bond Spreads oder nur Aggregate? | Offen — blockiert Block 2 (Discovery-Spike) |
| B-2 | TRACE | Ticker→CUSIP-Mapping: FMP, EDGAR oder manuell? | Offen — blockiert Block 2 |
| C-1 | 13F | Alle CIKs unverifiziert — Verifikations-Skript als Pre-Condition | Offen — blockiert Block 3 |
| C-2 | 13F | Baupost CIK in V2 war Berkshire-CIK (Copy-Paste-Fehler) — korrekter CIK offen | Offen |
| C-3 | 13F | Baupost (Klarman) beantragt oft Extensions und vertrauliche 13F — Fund moeglicherweise streichen | Mittel |
| D-1 | SIX | `price_usd`-Feld fuer CHF-Ticker: leer lassen oder spaeter umbenennen? | Offen |
| D-2 | SIX | SIX SER API-Endpunkt verifizieren via Browser-DevTools (Discovery-Spike) | Offen — blockiert Block 5 |
| D-3 | SIX | `MIN_ABSOLUTE_VOLUME_CH = 5_000` fuer `.SW`-Ticker | Mittel |

---

## WCAG 2.2 AA Compliance (neue Komponenten)

*(Unveraendert aus V3.)*

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
- `short`-Text fuer `superinvestor_13f_single` ist "F1", fuer `superinvestor_13f_consensus` "FC"

**CH-Ticker-Hinweis (Option B):**
- Tooltip-Text muss auch fuer Screen-Reader zugaenglich sein: `aria-label` auf Badge

---

## Nielsen-Heuristiken (neue UI-Elemente)

| Heuristik | Anwendung |
|-----------|-----------|
| #1 Sichtbarkeit Systemstatus | COT-Tab zeigt `updated_at`-Timestamp; `filing_date`, `quarter` und `quarter_status` in 13F-Signal anzeigen (45d-Lag und Pending-Status transparent machen) |
| #4 Konsistenz und Standards | Neue Signals folgen exakt `SIGNAL_CONFIG`-Pattern, `SignalBadge` wiederverwendet |
| #6 Fehler-Praevention | Discovery-Spikes verhindern Implementation unverifizierter Quellen; Tag-75-Regel verhindert wackelnde Konsens-Scores |
| #7 Flexibilitaet und Effizienz | `consensus_count` als Zahl sichtbar — Power-User sieht sofort Staerke des Signals |
| #8 Aesthetik und Minimalismus | Tags in Block 4 als kleine Pills; CH-Hinweis als dezentes Badge, nicht als Modal |
| #9 Hilfe beim Erkennen von Fehlern | CH-Ticker-Hinweis erklaert strukturelle Score-Asymmetrie; `provisional`-Status in Signal-Uebersicht zeigt offen was noch nicht validiert ist |

---

## Post-Launch-Review-Tasks (Zusammenfassung aller Follow-up-Kandidaten)

Diese ACs sind **keine Launch-Blocker**. Sie werden als Follow-up-Tasks in die
Task-Liste eingetragen, sobald der jeweilige Block live ist.

| Task | Ausloesender Block | Zeitpunkt | Aktion bei negativem Befund |
|------|-------------------|-----------|------------------------------|
| Block-3-Gewichts-Review | Block 3 Live | +90 Tage | Konsens-Schwelle ≥4 oder new_position von +3 auf +2 |
| Block-5-Gewichts-Review | Block 5 Live (falls Spike erfolgreich) | +90 Tage | `six_insider` von +3 auf +2 |
| Block-2-Gewichts-Review | Block 2 Live (falls Spike erfolgreich) | +90 Tage | `credit_stress` von −2 auf −1 |
| Block-0b-Vollvalidierung | Block 0a Live | +90 Tage | Alle `provisional`-Signale reviewen, ggf. Fix-Tasks |

---

## CHANGELOG

### V2 → V3

#### Korrektur 1: Reihenfolge umgedreht — Value-First statt Risk-First

**V2 sagte:** Block 2 (TRACE) vor Block 3 (13F), Begruendung "bekanntes Risiko zuerst".
Block-Reihenfolge: COT → TRACE → 13F → 13D → SIX.

**V3 sagte:** Block 4 (13D) vor Block 3 (13F), und beide Discovery-Spikes ans Ende.
Block-Reihenfolge: Backtest-Harness → COT → 13D → 13F → SIX-Spike → TRACE-Spike.

**Weil:** Bekanntes Risiko ist nicht dasselbe wie akzeptables Risiko. TRACE hat
~70% Wahrscheinlichkeit zu scheitern. 13F via EDGAR ist verifizierte, kostenlose Quelle.

---

#### Korrektur 2: Block 3 — 13F als Konsens-Signal, nicht Single-Fund

**V2 sagte:** `superinvestor_13f` new_position = +3 fuer jeden einzelnen Fund.

**V3 sagte:** new_position Single-Fund = +1; new_position Konsens ≥3 = +3.
Neuer Datenfluss: erst alle Fonds aggregieren, dann ticker-zentrisch projizieren.

---

#### Korrektur 3: Block 3 — Fund-CIKs zwingend gegen EDGAR verifizieren

**V2 sagte:** Baupost Group CIK = 0001067983 (Copy-Paste-Fehler, das ist Berkshire).

**V3 sagte:** Alle CIKs explizit als `unverifiziert` markiert. Verifikations-Skript
als harte Pre-Condition. Baupost-Fehler explizit dokumentiert.

---

#### Korrektur 4: Universum-Verfuegbarkeits-Matrix

**V2 sagte:** Nichts. Keine Erwaehnung der Signal-Asymmetrie zwischen US und CH.

**V3 sagte:** Neuer Abschnitt mit vollstaendiger Matrix (12 Signale × 2 Universen).
Empfehlung Option B (UI-Hinweis statt Normalisierung).

---

#### Korrektur 5: Block 0 — Backtest-Harness als neuer Pre-Requisite-Block

**V2 sagte:** Nichts. Fuenf neue Signale mit Gewichten bis +3 ohne Validation.

**V3 sagte:** Neuer Block 0 als harter Gate. Alle anderen Bloecke haben Backtest-Gate
als Acceptance Criteria.

---

### V3 → V4

#### Modifikation 1: Block 0 in zwei Phasen aufgeteilt (Block 0a und Block 0b)

**V3 sagte:** Block 0 ist Pre-Requisite fuer alle anderen Bloecke. Offene Frage A-0:
Wie viele ScreeningResult-Eintraege existieren?

**V4 sagt:** Offene Frage A-0 ist geschlossen — Worst Case bestaetigt. Drei Code-Stellen
belegen dass History nicht akkumuliert wird:
- `backend/api/screening.py:44-59`: `.offset(1)`-Delete in `start_scan`
- `backend/services/screening/screening_service.py:277`: Pre-Insert-Delete in `run_scan`
- `backend/models/screening.py:33`: `ondelete="CASCADE"` auf `ScreeningResult.scan_id`

Block 0 wird aufgeteilt:
- **Block 0a**: Retention-Fix (Option B: `.offset(1)`-Delete entfernen, 365-Tage-Cleanup-Job)
  plus Harness-Skelett (laeuft beim Launch, meldet "insufficient data", ist einsatzbereit).
  Empfehlung Option B begruendet: max ~73k Rows ueber 365 Tage, keine neue Tabelle noetig.
- **Block 0b**: Gewichts-Validierung, +90 Tage nach Block 0a Live. Kein Implementations-Block,
  sondern Review-Block mit Pre-Condition "90 Tage History vorhanden".

**Neue Reihenfolge-Uebersicht:** Block 0a → Block 1 → Block 4 → Block 3 → Block 5-Spike
→ Block 2-Spike → Block 0b (Review, +90 Tage).

---

#### Modifikation 2: Status-Spalte in Gesamt-Gewichts-Uebersicht

**V3 sagte:** Einheitliche Tabelle ohne Validierungs-Status.

**V4 sagt:** Neue `Status`-Spalte mit vier Werten: `validated`, `provisional`, `n/a`,
`enrichment_only`. Alle neuen Signale (13F, SIX, TRACE) sind `provisional`. Bestandssignale
(`insider_cluster`, `superinvestor`, `buyback`, `large_buy`, `congressional`, `short_trend`,
`ftd`, `unusual_volume`) sind `validated`. COT ist `n/a`. Activist-Tags sind `enrichment_only`.

Tabellenformat gesplittet in "Standard-Signale" und "13F-Signale (Konsens-Matrix)"
fuer bessere Lesbarkeit.

---

#### Modifikation 3: AC-9 in Block 3 als Post-Launch-Review umformuliert

**V3 sagte:** AC-9 als Launch-Gate: "Backtest-Harness zeigt positiven Forward-Return-Effekt
fuer Konsens ≥3 new_position" — das ist ein zirkulaeres Gate, weil beim Launch keine
13F-History in ScreeningResult existiert.

**V4 sagt:** AC-9 ist kein Launch-Gate mehr. Formulierung: "90 Tage nach Block-3-Live
wird der Harness gegen akkumulierte Signale gefahren. Bei negativem Effekt: Schwelle
auf ≥4 oder Gewicht auf +2 senken. Follow-up-Task, kein Blocker." Gleiches Muster
in Block 5 und Block 2 angewendet. Bewusste Entscheidung explizit als solche im
Dokument dokumentiert (nicht als Luecke).

---

#### Modifikation 4: Quartal-Definition fuer 13F-Konsens praezisiert

**V3 sagte:** "≥3 Fonds im selben Quartal" — ohne Definition wann ein Quartal
als geschlossen gilt.

**V4 sagt:** Explizite Regel: Quartal gilt als aggregations-bereit am **Tag 75 nach
Q-Ende**. Vor Tag 75: nur `superinvestor_13f_single` aktiv (+1). Zwischen Tag 45 und
Tag 75: Konsens ist `pending`. Ab Tag 75: Konsens einmalig berechnet, Further Late-Filer
fuer dieses Quartal ignoriert (deterministisch, kein Wackeln). Quartal-Stichtag-Tabelle
mit Beispielen Q4 2025 bis Q2 2026 hinzugefuegt. Signal-Keys entsprechend praezisiert:
`superinvestor_13f_single` und `superinvestor_13f_consensus` (statt generisches
`superinvestor_13f`).

---

## V4-Inline-Patch (Post-Review, kein eigenes Dokument)

Nach V4-Freigabe wurden drei kleine Rest-Korrekturen direkt in V4 eingearbeitet,
ohne eigenes V4.1-Dokument zu erzeugen. Die Aenderungen sind zu klein fuer einen
eigenen Changelog-Eintrag, aber transparenz-halber hier dokumentiert:

1. **Retention 180 → 365 Tage.** Begruendung: Storage quasi frei (max ~73k Rows),
   laengeres Forward-Return-Fenster plus mehrere Quartalszyklen fuer die Konsens-
   Signal-Validierung in Block 0b. Betrifft AC-0a-1, AC-0a-2, Empfehlung-Text,
   Must-Scope, und die V3→V4-Changelog-Zeile zu Block 0a.

2. **Klarman/Baupost-Tag-75-Risiko explizit dokumentiert.** Neue Zeile in der
   Risiko-Matrix von Block 3: die Tag-75-Regel schliesst Klarman systematisch aus
   dem Konsens aus, weil Baupost regelmaessig Extensions beantragt. Das ist kein
   Bug, sondern eine dokumentierte Konsequenz der deterministischen Aggregation.
   Massnahme: "dokumentiert, akzeptiert".

3. **Neuer Status-Wert `legacy` eingefuehrt.** Die Status-Spalte hatte
   `validated` suggeriert dass Bestandssignale wie `superinvestor` (Dataroma),
   `buyback`, `large_buy`, `congressional`, `short_trend`, `ftd`, `unusual_volume`
   gegen Forward-Returns geprueft sind — das ist nicht der Fall. Sie laufen mit
   historischer Begruendung, aber ohne Backtest. Neuer Wert `legacy` macht das
   transparent. Nur `insider_cluster` bleibt `validated` (breit in Academic
   Research belegt). Konsequenz: Block 0b prueft auch alle `legacy`-Signale mit
   (Aufwand null, Harness laeuft ohnehin gegen alle Buckets).

---

*Dokument-Ende. V4 ersetzt V3 als aktives Scope-Dokument. V3 bleibt als Historien-Dokument erhalten.*
*Pfad: `/home/harry/projects/openfolio/SCOPE_SMART_MONEY_V4.md`*
