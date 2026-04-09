# SCOPE: Smart Money Screener V2

**Status:** Design-freigegeben, bereit zur Implementierung  
**Datum:** 2026-04-09  
**Maintainer:** Harry  
**Design-Agent:** Claude (Sonnet 4.6)  
**Bezug:** Bestehender Screener in `backend/services/screening/` + `frontend/src/pages/Screening.jsx`

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

Score-Cap: `max(0, min(score, 10))`. V2 erweitert um 5 Blöcke ohne diesen Cap
zu ändern — neue Signale passen sich in dasselbe Schema ein.

---

## Implementierungs-Reihenfolge (bestätigt)

1. Block 1 — CFTC COT (komplett isoliert, Null-Risiko für bestehenden Screener)
2. Block 2 — TRACE Credit-Stress (Enrichment-Muster, bekanntes Risiko)
3. Block 3 — 13F Q/Q-Diffs via SEC EDGAR (neue Tabelle, mittleres Risiko)
4. Block 4 — 13D Brief-Parsing (Anreicherung ohne neue Tabelle, niedriges Risiko)
5. Block 5 — SIX Insider (Non-US Universum-Expansion, höchstes Regressions-Risiko)

Begründung für Reihenfolge: Identisch mit der Vorgabe des Maintainers. Kein
Grund zur Änderung — die Isolation von Block 1 erlaubt einen sicheren ersten
Commit, und Block 5 profitiert davon, dass das yfinance-Enrichment in Blöcken
2–4 bereits stabilisiert wurde. Die 13F-Tabelle (Block 3) ist Voraussetzung für
nichts anderes und kann parallel zu Block 2 entwickelt werden, aber sequenziell
ist sicherer für ein Ein-Personen-Projekt.

---

## Block 1: CFTC COT — Macro/Positioning Tab

### Problem

Der Screener deckt nur Equity-Mikro-Signale ab. Positionierung institutioneller
Akteure in Futures-Märkten (Gold, Öl, USD, Bonds) ist ein unabhängiges
Makro-Signal, das den Equity-Screener nicht kontaminieren darf.

### User Story

**Als** Self-Hosted-Investor  
**möchte ich** die aktuelle Positionierung der Commercials und Managed Money in
den wichtigsten Futures-Märkten auf einen Blick sehen  
**damit** ich Extrempositionierungen (z.B. Commercials in Gold auf 52-Wochen-Tief
Short) als Kontra-Signal zu meinem Equity-Screening in Beziehung setzen kann

### Acceptance Criteria

**AC-1: COT-Daten werden wöchentlich geladen**
- Given: Freitag ist vergangen und CFTC hat den neuen Report publiziert
- When: Der APScheduler-Job `cot_refresh` läuft (Samstag 09:00 Zürich)
- Then: `macro_cot_snapshots` enthält einen neuen Eintrag pro Instrument mit
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
  hervorgehoben (rot = ≥ 90, grün = ≤ 10)

**AC-4: Fehlende Daten werden graceful behandelt**
- Given: CFTC-CSV nicht erreichbar
- When: Job läuft
- Then: Letzter bekannter Snapshot bleibt erhalten, `last_error` im Job-State
  wird gesetzt, keine Exception die den Worker stoppt

### Scope (MoSCoW)

**Must (MVP):**
- Instrumente: GC (Gold), SI (Silber), CL (WTI Crude), DX (US Dollar Index),
  ZN (10-Year Treasury Note)
- Quelle: CFTC Legacy Combined Report, CSV-Download
- Tabelle `macro_cot_snapshots` mit historischen Wochenwerten
- 52-Wochen-Perzentil für Commercials und Managed Money
- Frontend-Tab "Macro / Positioning" in `Screening.jsx`
- APScheduler-Job Samstag 09:00 Zürich
- Config-Dict in Service (Instrument → CFTC-Market-Code)

**Should (v1):**
- Historischer Chart (Recharts LineChart) für ausgewähltes Instrument
- Disaggregated Report als Alternative zu Legacy (getrennte Producer/Swap/MM-Kategorien)

**Could (Later):**
- User-konfigurierbare Instrument-Liste via Settings
- Alert wenn Extremzone erreicht wird
- Korrelationsanzeige COT-Extremposition → nachfolgende Preis-Performance

**Won't:**
- Integration in Equity-Screener-Score (COT ist Makro, nicht Equity-Mikro)
- Automatische Handlungsempfehlungen

### API-Shape

**Neuer Endpoint:**

```
GET /api/screening/macro/cot
Response:
{
  "updated_at": "2026-04-04T21:00:00Z",    // letzter erfolgreicher Job-Run
  "report_date": "2026-04-01",              // CFTC-Stichtag (Dienstag)
  "instruments": [
    {
      "code": "GC",
      "name": "Gold (COMEX)",
      "report_date": "2026-04-01",
      "commercial_net": -142300,
      "commercial_net_pct_52w": 23.4,       // Perzentil 0-100
      "mm_net": 198400,
      "mm_net_pct_52w": 71.2,
      "oi_total": 562000,
      "is_extreme_commercial": false,       // true wenn pct <= 10 oder >= 90
      "is_extreme_mm": false
    }
  ]
}
```

**Kein neuer POST-Endpoint** — COT wird ausschliesslich durch Worker-Job befüllt.

### DB-Änderungen

**Neue Tabelle `macro_cot_snapshots`:**

```sql
CREATE TABLE macro_cot_snapshots (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument  VARCHAR(10)  NOT NULL,   -- "GC", "SI", "CL", "DX", "ZN"
    report_date DATE         NOT NULL,   -- CFTC-Stichtag (Dienstag)
    commercial_long  BIGINT,
    commercial_short BIGINT,
    commercial_net   BIGINT  GENERATED ALWAYS AS (commercial_long - commercial_short) STORED,
    mm_long          BIGINT,
    mm_short         BIGINT,
    mm_net           BIGINT  GENERATED ALWAYS AS (mm_long - mm_short) STORED,
    oi_total         BIGINT,
    -- Perzentile werden zur Laufzeit berechnet, nicht gespeichert
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (instrument, report_date)
);
CREATE INDEX ix_macro_cot_instrument_date ON macro_cot_snapshots (instrument, report_date DESC);
```

Alembic-Migration: neue Datei `alembic/versions/xxxx_add_macro_cot_snapshots.py`

**Neues Model:** `backend/models/macro_cot.py` (SQLAlchemy Mapped-Class)

**Neuer Service:** `backend/services/screening/cot_service.py`
- `fetch_and_store_cot(db)` — Download + Parse + Persist
- `get_cot_summary(db) -> list[dict]` — letzter Snapshot + Perzentile

### Frontend-Impact

**Betroffene Dateien:**
- `frontend/src/pages/Screening.jsx` — Tab-Struktur hinzufügen

**Neue Komponente:**
- `frontend/src/components/CotMacroPanel.jsx`
  - Props: `{ instruments: [...], updatedAt: string }`
  - Tabelle mit Instrument-Zeilen
  - Inline-Perzentil-Bar (CSS, keine externe Library)
  - Farbmarkierung Extremzonen: `text-danger` bei ≥ 90, `text-success` bei ≤ 10
  - ARIA: `role="table"`, `aria-label="COT Positionierung"`, Spalten-Headers mit `scope="col"`

**Tab-Integration in `Screening.jsx`:**

```jsx
// Bestehend: <ScreenerResults />
// Neu: zwei Tabs
const [activeTab, setActiveTab] = useState('screener') // 'screener' | 'macro'

// Tab-Bar über dem bestehenden Content, nicht als neue Route
<div role="tablist" aria-label="Screener-Ansicht">
  <button role="tab" aria-selected={activeTab === 'screener'} ...>Smart Money Screener</button>
  <button role="tab" aria-selected={activeTab === 'macro'} ...>Macro / Positioning</button>
</div>
{activeTab === 'screener' && <ScreenerResults />}
{activeTab === 'macro' && <CotMacroPanel />}
```

### Worker-Job

```python
# worker.py — in main():
scheduler.add_job(
    _refresh_cot_data,
    CronTrigger(hour=9, minute=0, day_of_week="sat", timezone="Europe/Zurich"),
    id="cot_refresh",
)
```

### UI-Labels (Schweizer Deutsch, neutral)

| Key | Label | Beschreibung |
|-----|-------|-------------|
| `commercial_net_pct_52w` | "Commercials Netto (52w-Pzt.)" | Position der Hedger im 52-Wochen-Vergleich |
| `mm_net_pct_52w` | "Managed Money Netto (52w-Pzt.)" | Position spekulativer Fonds im 52-Wochen-Vergleich |
| Extremzone ≤ 10 | "Extremes Short-Exposure der Commercials" | Kein "Kaufsignal" |
| Extremzone ≥ 90 | "Extremes Long-Exposure der Commercials" | Kein "Verkaufssignal" |

### Quellen-URLs

- **CFTC Legacy Combined Report (aktuell):**
  `https://www.cftc.gov/dms/files/dea/cotarchives/[year]/futures/deacot[MMDDYY].zip`
- **Direktlink aktuellste Woche:**
  `https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm`
- **Programmatischer Download (aktuell, alle Instrumente in einer CSV):**
  `https://www.cftc.gov/files/dea/history/fut_fin_txt_[year].zip`
- **Historisch bulk (1986–today), alle Jahres-ZIPs:**
  `https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm`

Market-Codes für CFTC-CSV-Filter (Spalte "Market_and_Exchange_Names"):
- Gold: `GOLD - COMMODITY EXCHANGE INC.`
- Silber: `SILVER - COMMODITY EXCHANGE INC.`
- WTI Crude: `CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE`
- US Dollar Index: `U.S. DOLLAR INDEX - ICE FUTURES U.S.`
- 10-Year Treasury: `10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE`

### Gewicht-Begründung

Kein Gewicht im Equity-Score — COT ist ein separates Makro-Panel. Kein
Plus/Minus in `ScreeningResult.score`.

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| CFTC ändert CSV-Format | niedrig | mittel | Version in Spaltenheader prüfen, Test-CSV einchecken |
| ZIP-Download-URL ändert sich jährlich (Jahreszahl im Pfad) | hoch | niedrig | Dynamische Jahr-Erkennung im Service |
| Kein Daten-Update nach US-Feiertagen | mittel | niedrig | `last_error` protokollieren, kein Alert |
| Frontend-Tab bricht bestehenden Screener | sehr niedrig | mittel | Neuer State ist lokal, kein Einfluss auf Scan-Flow |

**Audit-Checks:**
- `macro_cot_snapshots` UNIQUE-Constraint verhindert Duplikate
- Perzentil-Berechnung bei < 52 Wochen Data graceful (z.B. zeigen was vorhanden)
- Worker-Job wirft keine unkontrollierten Exceptions (try/except-Wrapper Pflicht)

---

## Block 2: TRACE Credit-Stress

### Problem

Der Screener sieht Aktien mit positiven Equity-Signalen, ignoriert aber ob der
Bond-Markt desselben Emittenten gleichzeitig unter Stress steht. Credit-Spread-
Ausweitungen bei Unternehmensanleihen sind ein härteres Warnsignal als Short-
Ratio-Bewegungen.

### User Story

**Als** Self-Hosted-Investor  
**möchte ich** sehen ob die Unternehmensanleihen eines Tickers im Screener
gleichzeitig unter Credit-Stress stehen  
**damit** ich Equity-Signale mit gebotener Vorsicht behandle wenn der Bond-Markt
das Unternehmen bereits mit höheren Spreads bewertet

### Acceptance Criteria

**AC-1: Enrichment nur für scored Ticker**
- Given: Ein Scan hat positive Ergebnisse (score >= 1)
- When: `enrich_credit_stress(scored_tickers)` läuft nach den Primary Sources
- Then: Nur Ticker in `scored` werden gegen TRACE geprüft — kein separates Universum

**AC-2: Spread-Blowout erkennen**
- Given: Für einen Ticker sind Bond-Trades via TRACE abrufbar
- When: Der Spread der letzten 5 Handelstage > 200% des 30-Tage-Durchschnitts
- Then: `credit_stress` Signal wird gesetzt mit `spread_bps`, `spread_avg_30d`,
  `spread_ratio`, `bond_count`, `as_of_date`; Score erhält −2

**AC-3: Kein Fehler bei fehlendem CUSIP-Mapping**
- Given: Für einen Ticker existiert kein Eintrag im CUSIP-Mapping
- When: `enrich_credit_stress` läuft
- Then: Ticker wird still übersprungen, kein Fehler, kein Signal gesetzt

### Scope (MoSCoW)

**Must (MVP):**
- Enrichment-Service `backend/services/screening/trace_credit_service.py`
- CUSIP-zu-Ticker-Mapping via FMP `/v4/cusip/{cusip}` Endpoint (reverse-lookup)
  oder manuell gepflegtes Dict für Top-100-Screener-Kandidaten
- TRACE-Daten via FINRA TRACE Market Breadth API (free, kein Key nötig)
- Schwellwert: `spread_ratio >= 2.0` (aktueller Spread ≥ 2× 30-Tage-Avg)
  UND mindestens 3 Bond-Trades in letzten 5 Tagen (Rauschunterdrückung)
- Integration in `screening_service.py` als 9. Enrichment-Schritt

**Should (v1):**
- Ticker→CUSIP-Map aus SEC EDGAR XBRL-Daten aufbauen (kostenlos, kein FMP nötig)
- Peer-Group-Spread-Vergleich (Sektor-Median)

**Could (Later):**
- Automatischer CUSIP-Refresh via SEC EDGAR täglich

**Won't:**
- Eigene Bond-Datenbank aufbauen
- Realtime-Prices für Bonds

### API-Shape

Kein neuer Endpoint. Das Signal `credit_stress` erscheint in `ScreeningResult.signals`
und wird von `GET /api/screening/results` automatisch mitgeliefert.

**Signal-Shape im `signals`-JSONB:**

```json
"credit_stress": {
  "spread_bps": 485,
  "spread_avg_30d_bps": 210,
  "spread_ratio": 2.31,
  "bond_count": 7,
  "as_of_date": "2026-04-07",
  "cusip_count": 3
}
```

### DB-Änderungen

Keine neue Tabelle. Das Signal wird in `ScreeningResult.signals` (JSONB) gespeichert
— identisch mit `unusual_volume`. Kein Schema-Change, keine Alembic-Migration.

### Frontend-Impact

**Betroffene Dateien:**
- `frontend/src/pages/Screening.jsx` — `SIGNAL_CONFIG` erweitern

```js
credit_stress: {
  label: 'Kredit-Stress',
  glossar: 'Kredit-Stress',
  short: 'K',
  icon: AlertTriangle,
  description: 'Bond-Spreads des Emittenten stark ausgeweitet — Warnsignal (−2 Punkte)',
  type: 'warning'
}
```

Erweiterter Detail-Block in `ExpandedRow`:
```jsx
{key === 'credit_stress' && (
  <span className="text-text-muted ml-2">
    Spread {data.spread_bps}bp vs. Ø {data.spread_avg_30d_bps}bp (30T)
    &nbsp;—&nbsp;{data.spread_ratio}× Ausweitung, {data.bond_count} Anleihen
    {data.as_of_date ? ` (Stand: ${data.as_of_date})` : ''}
  </span>
)}
```

**Keine neue Komponente nötig** — integriert sich in bestehendes `SignalBadge` + `ExpandedRow`.

### Worker-Jobs

Kein neuer APScheduler-Job. Credit-Stress ist Teil des Scan-Flows (on-demand).

### UI-Labels (Schweizer Deutsch, neutral)

| Key | Label | Beschreibung |
|-----|-------|-------------|
| `credit_stress` | "Kredit-Stress" | Bond-Spreads des Emittenten ausgeweitet |
| Warnung | "Erhöhter Spread bei Unternehmensanleihen" | Nicht "Pleiterisiko" o.ä. |

### Quellen-URLs

- **FINRA TRACE Market Breadth (free, kein API-Key):**
  `https://api.finra.org/data/group/otcmarket/name/tradeReport`
  Dokumentation: `https://developer.finra.org/docs`
- **FINRA TRACE Corporate Bond Search:**
  `https://api.finra.org/data/group/otcmarket/name/weeklySummary`
- **FMP CUSIP Lookup (API-Key nötig, FMP-Plan abhängig):**
  `https://financialmodelingprep.com/api/v4/cusip/{cusip}?apikey=KEY`
- **SEC EDGAR XBRL Viewer (alternative CUSIP-Quelle, free):**
  `https://data.sec.gov/submissions/CIK{cik}.json` (enthält EntityType, nicht direkt CUSIP)

**Offene Frage B-1:** FINRA TRACE API für Individual-Bond-Trades (nicht nur Markt-Aggregat)
benötigt ggf. FINRA-Account oder ist auf Aggregat-Ebene limitiert. Der Maintainer muss
prüfen ob `https://api.finra.org/data/group/otcmarket/name/tradeReport` tatsächlich
Issuer-level Spread-Daten liefert oder ob nur Aggregat-Statistiken verfügbar sind.
Falls TRACE-API zu granular oder nicht verfügbar: Fallback auf FRED Corporate Spread Indices
(ICE BofA spreads via FRED, aber nur Sektor-Aggregate, nicht issuer-spezifisch).

**Offene Frage B-2:** Ticker-zu-CUSIP-Mapping ist das grösste technische Risiko.
FMP `/v4/cusip/{cusip}` macht Reverse-Lookup (CUSIP→Ticker), nicht Forward.
Empfehlung: EDGAR Company-Facts API prüfen ob sie CUSIPs enthält, oder
manuelles Seed-Dict für die 50–100 häufigsten Screener-Kandidaten.

### Gewicht-Begründung

`credit_stress = −2`: Stärker als `short_trend` (−1) und `ftd` (−1) weil:
- Bond-Markt ist informationseffizienter als Equity-Short-Markt
- Professionelle Credit-Investoren sehen Bilanzen früher als Equity-Screener
- Spread-Blowout (2× 30-Tage-Avg) ist ein selteneres, spezifischeres Signal als
  Short-Ratio-Anstieg von 20% (SHORT_TREND_MIN_CHANGE)
- Relativer Vergleich: `insider_cluster` (+3) rechtfertigt ein stärkeres Gegensignal
  als die aktuellen −1-Warnings

Diskussion: −2 kann einen `insider_cluster`-Score von 3 auf 1 drücken. Das ist
gewollt — wenn der Bond-Markt und Insider gegensätzliche Signale senden, soll
der Screener ambivalent bleiben (Score 1 = nicht herausgefiltert, aber kein
starkes Signal).

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| TRACE-API liefert kein Issuer-Level-Spread | hoch | hoch | Fallback: FRED-Sektorspreads (dann kein per-Ticker-Signal möglich); Block vorerst nicht ausliefern |
| CUSIP-Mapping für relevante Ticker fehlt | mittel | mittel | Graceful Skip, Log Warning, kein Fehler |
| FMP API-Key nicht konfiguriert | mittel | mittel | Service gibt leeres Dict zurück, kein Score-Impact |
| Score-Cap bei 10 wird durch −2 nicht negativ | sehr niedrig | niedrig | `max(0, score + weight)` bereits im Service |

**Audit-Checks:**
- Service muss ohne CUSIP-Map vollständig fehlerfrei durchlaufen (leeres Ergebnis ok)
- `spread_ratio` darf nie NaN oder Inf sein (Division-by-zero Guard)
- Enrichment kommt nach Score-Filter (`score >= 1`), nicht davor

---

## Block 3: 13F Q/Q-Diffs via SEC EDGAR

### Problem

`dataroma_scraper.py` liefert aggregierte Grand-Portfolio-Daten, aber keine
strukturierten Q/Q-Positions-Änderungen. Ein Positionsaufbau durch Burry oder
Klarman ist fundamental anders zu bewerten als eine gleichbleibende Position.

### User Story

**Als** Self-Hosted-Investor  
**möchte ich** sehen welche Fonds aus meiner Watchlist einen Ticker in ihrem
letzten 13F-Filing neu aufgebaut, aufgestockt, reduziert oder geschlossen haben  
**damit** ich die Richtung des Smart-Money-Interesses (nicht nur Bestand) in mein
Screening einbeziehen kann

### Acceptance Criteria

**AC-1: Neue Positions werden korrekt erkannt**
- Given: Fund A hatte Ticker X im vorigen Quartal nicht in `fund_holdings_snapshot`
- When: Neues 13F-Filing enthält Ticker X
- Then: Signal `superinvestor_13f` mit `action: "new_position"` und Score +3

**AC-2: Aufstockungen werden korrekt erkannt**
- Given: Fund A hatte 100 Shares von Ticker X
- When: Neues 13F enthält 125 Shares (+25%)
- Then: Signal `superinvestor_13f` mit `action: "added"`, `change_pct: 25.0` und Score +1
  (Schwellwert: >= +20% um Rauschen zu vermeiden)

**AC-3: Reduktionen werden als Warnung angezeigt**
- Given: Fund A hatte 100 Shares von Ticker X
- When: Neues 13F enthält 75 Shares (−25%)
- Then: Signal `superinvestor_13f` mit `action: "reduced"`, `change_pct: -25.0` und Score −1
  (Schwellwert: >= 20% Reduktion)

**AC-4: Schliessungen sind informativ, kein Score-Impact**
- Given: Fund A hatte Ticker X im Portfolio
- When: Neues 13F erwähnt Ticker X nicht mehr
- Then: Signal `superinvestor_13f` mit `action: "closed"`, Score ±0
  (Rationale: Timing unbekannt — Closing könnte Wochen vor Filing sein)

**AC-5: Täglicher EDGAR-Check, Diff nur bei neuem Filing**
- Given: EDGAR wird täglich geprüft
- When: Kein neues Filing seit letztem Check
- Then: Kein neuer Snapshot, kein Diff, kein Signal-Update

### Scope (MoSCoW)

**Must (MVP):**
- Neue Tabelle `fund_holdings_snapshot` (letzte bekannte Position pro Fund/Ticker)
- Service `backend/services/screening/sec_13f_service.py`
  - `fetch_latest_13f(cik, fund_name) -> list[dict]` — EDGAR XML-Parse
  - `compute_diffs(db, cik, new_holdings) -> list[dict]` — Q/Q-Vergleich
  - `store_snapshot(db, cik, holdings, filing_date)` — Snapshot überschreiben
- Integration in `screening_service.py` als paralleler Scraper (ersetzt dataroma nicht,
  ergänzt es — beide Signale können koexistieren unter verschiedenen Keys)
- Fund-Liste (siehe unten) als `TRACKED_13F_FUNDS` Dict in Service
- APScheduler-Job täglich 08:00 Zürich für EDGAR-Check

**Should (v1):**
- `superinvestor_13f` Sub-Key `funds` (Liste welche Fonds welche Action haben)
- Unterscheidung zwischen "frisches Filing (< 30 Tage)" und "altes Filing (> 30 Tage)"

**Could (Later):**
- Historische Diff-Tabelle (alle Quartale, nicht nur letzter Stand)
- Aggregierter "Conviction Score" über mehrere Fonds hinweg

**Won't:**
- Real-time 13F Parsing (Filing kommt mit 45d Lag — unrealistisch)
- Alle ~5000 13F-Filer tracken (Out of scope für Ein-Personen-Projekt)

### Fund-Liste mit CIKs (recherchiert)

| Fund | Manager | CIK |
|------|---------|-----|
| Berkshire Hathaway | Warren Buffett | 0001067983 |
| Scion Asset Management | Michael Burry | 0001649339 |
| Pershing Square Capital | Bill Ackman | 0001336528 |
| Appaloosa Management | David Tepper | 0001656456 |
| Pabrai Investment Fund | Mohnish Pabrai | 0001173334 |
| Third Point LLC | Dan Loeb | 0001350694 |
| Elliott Investment Management | Paul Singer | 0001061768 |
| Baupost Group | Seth Klarman | 0001067983 |

**Hinweis:** Baupost Group nutzt CIK 0001421461 für 13F-Filings (separates
Reporting-Vehicle). Berkshire's 13F-CIK ist 0001067983. Pabrai: CIK muss gegen
EDGAR verifiziert werden (`https://efts.sec.gov/LATEST/search-index?q=%22Pabrai%22&dateRange=custom&startdt=2024-01-01&forms=13F-HR`).

**Offene Frage C-1:** Baupost Group (Klarman) ist bekannt dafür, Extensions zu
beantragen und 13F teilweise confidentally zu behandeln. CIK 0001421461 muss
gegen EDGAR verifiziert werden. Ebenso Pabrai — der hat mehrere Entities.

**Offene Frage C-2:** Elliott Management (Singer) ist oft in Non-US-Positionen
aktiv. Deren 13F deckt nur US-Equities ab. Das ist bekannt und ok für diesen
Screener.

### API-Shape

Kein neuer Endpoint für den Scan. Das Signal erscheint in `ScreeningResult.signals`.

**Neuer Endpoint für direkten Fund-Lookup (optional, Should):**

```
GET /api/screening/13f/fund/{cik}
Response:
{
  "cik": "0001649339",
  "fund_name": "Scion Asset Management (Burry)",
  "last_filing_date": "2026-02-14",
  "holdings": [
    { "ticker": "GOOGL", "shares": 150000, "value_usd": 21000000,
      "action": "new_position", "change_pct": null }
  ]
}
```

**Signal-Shape im `signals`-JSONB:**

```json
"superinvestor_13f": {
  "action": "new_position",
  "fund": "Scion Asset Management (Burry)",
  "shares": 150000,
  "value_usd": 21000000,
  "filing_date": "2026-02-14",
  "change_pct": null,
  "all_actions": [
    { "fund": "Pershing Square (Ackman)", "action": "added", "change_pct": 34.2 }
  ]
}
```

### DB-Änderungen

**Neue Tabelle `fund_holdings_snapshot`:**

```sql
CREATE TABLE fund_holdings_snapshot (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fund_cik      VARCHAR(15)   NOT NULL,
    fund_name     VARCHAR(200)  NOT NULL,
    ticker        VARCHAR(30)   NOT NULL,
    shares        BIGINT        NOT NULL,
    value_usd     BIGINT,
    filing_date   DATE          NOT NULL,
    period_date   DATE          NOT NULL,  -- Q-Ende-Datum aus 13F
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (fund_cik, ticker)               -- nur letzter bekannter Stand pro Fund/Ticker
);
CREATE INDEX ix_fund_holdings_ticker ON fund_holdings_snapshot (ticker);
CREATE INDEX ix_fund_holdings_fund ON fund_holdings_snapshot (fund_cik, filing_date DESC);
```

Alembic-Migration: `alembic/versions/xxxx_add_fund_holdings_snapshot.py`

**Neues Model:** `backend/models/fund_holdings.py`

### Frontend-Impact

**Betroffene Dateien:**
- `frontend/src/pages/Screening.jsx` — `SIGNAL_CONFIG` erweitern

```js
superinvestor_13f: {
  label: '13F Positionsänderung',
  glossar: '13F Positionsänderung',
  short: 'F',
  icon: Users,
  description: 'SEC 13F Q/Q-Änderung durch getrackten Fonds',
  type: 'positive'  // kann auch 'warning' sein je nach action
}
```

Action-spezifische Labels im `ExpandedRow`:
- `new_position` → "Neue Position eröffnet"
- `added` → "Position aufgestockt (+X%)"
- `reduced` → "Position reduziert (−X%)" — type: warning in Anzeige
- `closed` → "Position geschlossen" — neutral, kein Score-Impact sichtbar

### Worker-Jobs

```python
# worker.py
scheduler.add_job(
    _refresh_13f_holdings,
    CronTrigger(hour=8, minute=0, timezone="Europe/Zurich"),
    id="sec_13f_refresh",
)
```

Der Job prüft täglich ob neue 13F-Filings auf EDGAR vorhanden sind. Tatsächliche
neue Diffs entstehen nur ~4× pro Jahr nach Q-Ende (Filing-Deadline: 45 Tage nach
Q-Ende: 15. Feb, 15. Mai, 15. Aug, 15. Nov).

### UI-Labels (Schweizer Deutsch, neutral)

| Key | Label | Beschreibung |
|-----|-------|-------------|
| `new_position` | "Neue Position eröffnet" | Erstmaliges Auftreten im Filing |
| `added` | "Position aufgestockt" | Erhöhung um ≥20% |
| `reduced` | "Position reduziert" | Reduktion um ≥20% — Warnsignal |
| `closed` | "Position geschlossen" | Nicht mehr im Filing — informativ |

### Gewicht-Begründung

| Action | Gewicht | Begründung |
|--------|---------|-----------|
| `new_position` | +3 | Gleichgestellt mit `insider_cluster` — eine Neu-Position durch Burry oder Klarman ist ebenso bedeutsam wie mehrere Insider-Käufe. 13F-Pflichtmeldungen sind zuverlässiger als Dataroma-Scraping. |
| `added` | +1 | Aufstockung ist ein schwächeres Signal als Neu-Position — der Fund hatte die Thesis bereits, erhöht aber die Conviction. Gleichgestellt mit `large_buy` (einzelner Insider-Kauf). |
| `reduced` | −1 | Symmetrisch zu `short_trend` und `ftd` — ein gleichgewichtiges Warnsignal. Stärker als 0 aber nicht −2, weil Reduktionen oft taktisch sind (Rebalancing, nicht Thesis-Änderung). |
| `closed` | 0 | Kein Score-Impact: Timing zwischen Position-Schliessung und Filing kann 45+ Tage betragen. Das Schliessen könnte bei viel höherem Kurs erfolgt sein als zum Filing-Datum erkennbar. Informativ für den User, aber kein verlässliches Signal. |

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| EDGAR XML-Schema ändert sich | niedrig | hoch | Schema-Version in Parse-Funktion loggen, Test-Fixture einchecken |
| Fund nutzt mehrere CIKs (Baupost) | mittel | mittel | Alle bekannten CIKs in Config, Union der Holdings |
| UNIQUE-Constraint `(fund_cik, ticker)` korrekt? Bei Fund-Rename? | niedrig | niedrig | fund_cik ist stabiler als fund_name — ok |
| 45-Tage-Lag wird als "frisches Signal" missinterpretiert | mittel | mittel | `filing_date` im Signal anzeigen, User muss einschätzen |
| `dataroma`-Signal und `superinvestor_13f`-Signal für denselben Ticker | mittel | niedrig | Beide koexistieren unter verschiedenen Keys, kein Score-Konflikt |

**Audit-Checks:**
- `compute_diffs` muss idempotent sein (zweimal ausgeführt → kein doppelter Score)
- Test: Neues Fund-Holdings-Snapshot ohne vorigen → alles `new_position`
- Test: Gleicher Snapshot nochmal → kein Diff
- Test: Fund complett leer im neuen Filing → alle bisherigen Positionen `closed`

---

## Block 4: 13D Brief-Parsing (Aktivisten-Anreicherung)

### Problem

Das bestehende `activist`-Signal sagt nur "Aktivist mit 5%+ Beteiligung".
Der eigentliche Katalysator steht in Item 4 des 13D-Filings ("Purpose of
Transaction"): Boardsitz, strategischer Review, Spinoff-Forderung, etc.

### User Story

**Als** Self-Hosted-Investor  
**möchte ich** beim Activist-Signal die ersten Zeilen des Purpose-of-Transaction
direkt im Screener sehen  
**damit** ich ohne SEC-Website-Besuch einschätzen kann ob der Aktivist eine
operative Veränderung anstrebt oder nur eine passive grosse Position aufgebaut hat

### Acceptance Criteria

**AC-1: `letter_excerpt` wird für 13D-Filings extrahiert**
- Given: Ein 13D-Filing hat ein XML-Primary-Doc mit Item 4
- When: `_resolve_13d_target` verarbeitet das Filing
- Then: `result` enthält `letter_excerpt` (erste 500 Zeichen von Item 4 Plain-Text,
  HTML-Tags entfernt)

**AC-2: `purpose_tags` werden per Keyword-Matching gesetzt**
- Given: `letter_excerpt` enthält Keywords
- When: Item 4 Text geparst
- Then: `purpose_tags` enthält relevante Tags aus definierter Liste (siehe unten),
  mindestens ein Tag oder leeres Array

**AC-3: Fehlende Item-4-Sektion bricht nichts**
- Given: 13D-Filing hat kein strukturiertes Item 4 (manche ältere Filings sind PDFs)
- When: Parser findet keinen Item-4-Content
- Then: `letter_excerpt = ""` und `purpose_tags = []`, kein Fehler

### Scope (MoSCoW)

**Must (MVP):**
- Erweiterung `activist_tracker.py` — `_resolve_13d_target` gibt `letter_excerpt`
  und `purpose_tags` zurück
- Keyword-Dict in Service (10–15 Tags, Regex-basiert, kein LLM)
- Anzeige im Screener-ExpandedRow

**Should (v1):**
- Tag-Filter in Screener-UI (nur Aktivisten mit `board_representation` zeigen)

**Could (Later):**
- HTML-to-plaintext für nicht-XML-Filings via BeautifulSoup

**Won't:**
- LLM-basiertes Tagging
- Volltext-Speicherung der Briefe (nur Excerpt)

### Keyword-Tags (Regex-basiert, Englisch)

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

Kein neuer Endpoint. Das `activist`-Signal in `ScreeningResult.signals` erhält
neue Sub-Keys.

**Erweitertes Signal-Shape:**

```json
"activist": {
  "investor": "Elliott Management",
  "form": "13D",
  "filing_date": "2026-03-15",
  "letter_excerpt": "The Reporting Person acquired the Shares for investment purposes and intends to seek board representation to advocate for a strategic review of the Issuer...",
  "purpose_tags": ["board_representation", "strategic_review"]
}
```

### DB-Änderungen

Keine neue Tabelle, keine Alembic-Migration.

`activist_tracker.py` gibt bereits ein Dict zurück — neue Keys `letter_excerpt`
und `purpose_tags` werden transparent durch `screening_service.py` in das
bestehende `signals["activist"]`-Feld übernommen.

### Frontend-Impact

**Betroffene Dateien:**
- `frontend/src/pages/Screening.jsx` — `ExpandedRow` für `activist`-Key erweitern

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

**Neue Konstante `PURPOSE_TAG_LABELS` in `Screening.jsx`:**

```js
const PURPOSE_TAG_LABELS = {
  board_representation: 'Verwaltungsratssitz',
  strategic_review: 'Strategische Überprüfung',
  spinoff: 'Abspaltung gefordert',
  buyback_demand: 'Aktienrückkauf gefordert',
  management_change: 'Managementwechsel gefordert',
  merger_opposition: 'Fusion/Übernahme abgelehnt',
  going_private: 'Privatisierung angestrebt',
  dividend_demand: 'Dividende gefordert',
  passive_investment: 'Passive Beteiligung',
}
```

### Worker-Jobs

Kein neuer Job. Block 4 ist Anreicherung innerhalb des bestehenden Scan-Flows.

### UI-Labels (Schweizer Deutsch, neutral)

Alle Tags sind in `PURPOSE_TAG_LABELS` bereits auf Deutsch — keine Imperative,
keine Handlungsanweisungen. Die Tags beschreiben was der Aktivist fordert, nicht
was der User tun soll.

### Gewicht-Begründung

Kein neues Gewicht. Das `activist`-Signal verwendet weiterhin `WEIGHT_SUPERINVESTOR = +2`
(geerbt vom bestehenden Code). Die Tags sind informativ-anreichend, nicht score-relevant.

Begründung: Tags können irreführend sein wenn Regex zu breit greift ("passive_investment"
steht in fast jedem boilerplate 13D). Score-Impact würde Regex-Robustheit erfordern die
nicht realistisch ohne LLM erreichbar ist.

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| Item-4-Text in HTML, nicht XML (ältere Filings) | mittel | niedrig | `letter_excerpt = ""`, graceful degradation |
| Keyword-Regex zu breit ("passive investment" überall) | hoch | niedrig | `passive_investment` explizit als niedrig-Priorität kennzeichnen in UI |
| 500-Zeichen-Excerpt schneidet mitten in Satz | niedrig | niedrig | Auf Satzende kürzen (`.` als Grenze), max 500 |
| Neue Felder brechen bestehenden `activist`-Signal-Consumer | sehr niedrig | niedrig | Alle neuen Keys sind Optional, Frontend prüft `data.purpose_tags?.length` |

**Audit-Checks:**
- `letter_excerpt` enthält keine HTML-Tags (`<[^>]+>` vollständig entfernt)
- `purpose_tags` ist immer Array (nie None)
- Bestehende Tests für `fetch_activist_positions` müssen weiterhin grün sein

---

## Block 5: SIX Insider (Swiss Management Transactions)

### Problem

OpenFolio ist primär für einen CH-Anleger mit Heimat-Bias. Schweizer Insiderkäufe
(Nestlé, Roche, Novartis) sind für den User relevanter als viele US-Signale,
werden aber aktuell komplett ignoriert.

### User Story

**Als** Self-Hosted-Investor mit Schweizer Heimat-Bias  
**möchte ich** meldepflichtige Management-Transactions an der SIX Swiss Exchange
im Smart Money Screener sehen  
**damit** ich Insider-Aktivität bei SMI/SMIM-Titeln genauso systematisch erfasse
wie bei US-Titeln

### Acceptance Criteria

**AC-1: SIX-Feed wird geparst**
- Given: SIX SER publiziert neue Management-Transaction-Meldungen
- When: `fetch_six_insider_transactions()` läuft
- Then: Liste mit `{ticker, company, transaction_type, shares, value_chf, filing_date}`
  — Ticker im Format `NESN.SW`, `ROG.SW`, etc.

**AC-2: Nur Käufe werden als positives Signal gewertet**
- Given: Eine Management-Transaction ist ein Verkauf
- When: Signal aggregiert wird
- Then: Kein `six_insider`-Signal gesetzt (Verkäufe = kein Signal, weder positiv noch negativ)

**AC-3: `.SW`-Ticker laufen durch Enrichment ohne Fehler**
- Given: Ein `.SW`-Ticker ist in `scored`
- When: `enrich_unusual_volume(scored_tickers)` läuft
- Then: yfinance-Call `yf_download("NESN.SW", ...)` liefert Daten oder None,
  kein Exception, kein Fehler der den gesamten Enrichment-Step stoppt

**AC-4: Sektorzuordnung für `.SW`-Ticker**
- Given: `NESN.SW` hat keinen Eintrag in der bestehenden Sektor-Mapping-Konstante
- When: `_ensure(ticker, ...)` in `screening_service.py` aufgerufen wird
- Then: Sektor wird von yfinance via `yf.Ticker("NESN.SW").info.get("sector")` nachgeladen
  oder leer gelassen — kein KeyError, kein Crash

### Scope (MoSCoW)

**Must (MVP):**
- Neuer Scraper `backend/services/screening/six_insider_service.py`
- Ticker-Normalisierung: SIX-Ticker → `.SW`-Suffix
- Filter: nur `transaction_type` = "Kauf" / "purchase" / "acquisition" (je nach API-Format)
- Integration in `screening_service.py` als 10. paralleler Scraper
- Defensives yfinance-Handling für `.SW`-Ticker in `unusual_volume_service.py`
  (bereits via `asyncio.to_thread` — muss nur Exception-handling prüfen)

**Should (v1):**
- Cluster-Erkennung: mehrere Insider desselben Unternehmens innerhalb 30 Tagen → erhöhter Score
- Wert-Filter: Minimum CHF 50'000 Transaktionswert

**Could (Later):**
- SPI-Erweiterung (alle SIX-kotierten, nicht nur SMI/SMIM)
- Separate `.SW`-Sektor-Map als Konstante in `constants/`

**Won't:**
- LSE, Euronext, HKEX (explizit ausgeschlossen)
- SIX-Verkäufe als Warnsignal (SIX-Verkäufe sind zu noisy, z.B. Steueroptimierung)

### API-Shape

Kein neuer Endpoint. `six_insider` erscheint in `ScreeningResult.signals`.

**Signal-Shape im `signals`-JSONB:**

```json
"six_insider": {
  "investor": "Mark Schneider",
  "role": "CEO",
  "transaction_type": "Kauf",
  "shares": 5000,
  "value_chf": 275000,
  "filing_date": "2026-04-03",
  "source": "SIX SER"
}
```

### DB-Änderungen

Keine neue Tabelle. Signal in `ScreeningResult.signals` (JSONB).

`ScreeningResult.price_usd` bleibt für CH-Ticker ungesetzt oder wird via
yfinance in CHF geliefert — Feld-Name ist missverständlich. **Offene Frage D-1:**
Soll `price_usd` für CH-Ticker leer bleiben oder umbenannt werden zu `price`
(Breaking Change)? Empfehlung: leer lassen für jetzt, für v1 Rename evaluieren.

### Frontend-Impact

**Betroffene Dateien:**
- `frontend/src/pages/Screening.jsx` — `SIGNAL_CONFIG` erweitern

```js
six_insider: {
  label: 'SIX Insider',
  glossar: 'SIX Insider',
  short: 'CH',
  icon: Users,
  description: 'Meldepflichtiger Insider-Kauf an der SIX Swiss Exchange (+3 Punkte)',
  type: 'positive'
}
```

Detail-Block:
```jsx
{key === 'six_insider' && (
  <span className="text-text-muted ml-2">
    {data.investor || 'Insider'}{data.role ? ` (${data.role})` : ''}
    {data.value_chf ? ` — CHF ${Number(data.value_chf).toLocaleString('de-CH')}` : ''}
    {data.filing_date ? ` (${data.filing_date})` : ''}
  </span>
)}
```

**`SCAN_SOURCES`-Array in `Screening.jsx`** erhält neuen Eintrag:
```js
{ source: 'six_insider', label: 'SIX Insider (Management-Transactions)' }
```

### Worker-Jobs

Kein neuer APScheduler-Job. SIX-Insider ist Teil des on-demand Scan-Flows.

### Quellen-URLs

**Offene Frage D-2 (kritisch):** Die SIX SER API-Struktur ist nicht öffentlich
dokumentiert. Zu prüfen:
- Haupt-Einstiegsseite: `https://www.ser-ag.com/en/resources/notifications-market-participants/management-transactions.html`
- Mögliche JSON-API hinter der Tabelle: Mit Browser-DevTools auf obige Seite
  prüfen welche API-Calls die Webseite macht (wahrscheinlich ein XHR zu einem
  Endpoint wie `https://www.ser-ag.com/api/management-transactions` oder ähnlich)
- Alternativ: SIX publiziert tägliche XML/CSV-Feeds unter `https://www.six-group.com/en/products-services/the-swiss-stock-exchange/market-data/news-tools/official-notices.html`
- SIX Regulatory Disclosure Services (RDS): `https://rds.six-group.com/` — enthält
  möglicherweise maschinenlesbaren Feed für Management Transactions

**Bis Frage D-2 geklärt ist, NICHT implementieren.** Die Quelle ist nicht
ausreichend verifiziert.

### Ticker-Normalisierungs-Regeln

| SIX-Format | yfinance-Format | Beispiel |
|------------|----------------|---------|
| `NESN` (4-stellig) | `NESN.SW` | Nestlé |
| `ROG` (3-stellig) | `ROG.SW` | Roche |
| `NOVN` | `NOVN.SW` | Novartis |
| `ABBN` | `ABBN.SW` | ABB |
| `ZURN` | `ZURN.SW` | Zurich Insurance |

Regel: `ticker.upper() + ".SW"` wenn kein Punkt im Ticker. Validierung: yfinance
gibt leeres DataFrame zurück wenn Ticker nicht gefunden — kein Crash.

### Regressionsrisiken `.SW`-Ticker im bestehenden Code

**`unusual_volume_service.py`:**
- `yf_download(ticker, period="25d")` — yfinance unterstützt `.SW`, aber CHF-Volumen
  ist anders skaliert. MIN_ABSOLUTE_VOLUME = 200'000 könnte für CH-Aktien zu hoch
  sein (SMI-Aktien haben oft viel niedrigeres Volumen als US-Midcaps).
- Fix: `MIN_ABSOLUTE_VOLUME_CH = 5_000` für `.SW`-Ticker, oder den Threshold
  deaktivieren für CH (Volume-Ratio bleibt, absolutes Minimum fällt weg).

**`screening_service.py` Score-Cap:**
- `max(0, min(score, 10))` — unverändert ok, kein CH-spezifisches Problem.

**`sector_mapping.py` (falls vorhanden):**
- Muss `.SW`-Ticker nicht kennen — `_ensure()` nimmt leeren Sektor und füllt
  via yfinance-Info nach, oder lässt leer. Kein Crash.

**`price_usd`-Feld in `ScreeningResult`:**
- CH-Aktien sind in CHF notiert, nicht USD. `price_usd = None` für `.SW`-Ticker
  ist die sicherste Option bis Frage D-1 entschieden ist.

### Gewicht-Begründung

`six_insider = +3` (analog `insider_cluster`):
- SIX-Pflichtmeldungen (Art. 56 BEHG) decken Direktoren, Senior Management, eng
  verbundene Personen — ähnlich breit wie US Form 4
- SIX-Meldungen sind weniger "noisy" als US-Form-4 weil die CH-Börse kleiner ist
  und weniger mechanische Tradingprogramme/ESO-Exercises die Insider-Daten
  verwässern
- Ein Kauf durch Nestlé-CEO ist mindestens so signifikant wie ein OpenInsider
  Cluster-Buy mit 2 Insidern
- Gleichgewichtung mit `insider_cluster` ist defensiv (nicht +4 oder +5), weil
  keine Cluster-Logik (mehrere Insider) implementiert ist — nur Einzeltransaktion

### Risiko-Matrix

| Risiko | Wahrscheinlichkeit | Impact | Massnahme |
|--------|-------------------|--------|-----------|
| SIX SER API-Endpunkt nicht auffindbar | hoch | hoch | Block 5 erst nach Klärung Frage D-2 starten |
| `.SW`-Ticker bricht `unusual_volume_service` bei MIN_ABSOLUTE_VOLUME | hoch | mittel | CH-spezifischer Volume-Threshold (Offene Frage D-3) |
| `price_usd`-Feld für CHF-Ticker semantisch falsch | mittel | niedrig | Leer lassen, später Rename evaluieren |
| Regression: bestehende US-Ticker werden durch `.SW`-Ticker-Handling beeinflusst | niedrig | hoch | Neues Handling explizit auf `.SW`-Suffix konditioniert, US-Pfad unverändert |
| SIX-Feed hat andere Ticker-Schreibweise als yfinance erwartet | mittel | mittel | Normalisierungstabelle im Service, manuelle Korrektur-Map |

**Audit-Checks:**
- `enrich_unusual_volume` läuft ohne Exception wenn `.SW`-Ticker übergeben werden
- Bestehende US-Ticker-Ergebnisse identisch vor/nach Block 5 (Regressionstest)
- `six_insider`-Service ohne SIX-API-Verbindung gibt `[]` zurück, kein Crash

---

## Gesamt-Gewichts-Übersicht nach V2

| Signal-Key | Gewicht | Neu in V2 |
|------------|---------|-----------|
| `insider_cluster` | +3 | — |
| `superinvestor_13f` (new_position) | +3 | Block 3 |
| `six_insider` | +3 | Block 5 |
| `superinvestor` | +2 | — |
| `buyback` | +2 | — |
| `superinvestor_13f` (added) | +1 | Block 3 |
| `large_buy` | +1 | — |
| `congressional` | +1 | — |
| `unusual_volume` | 0 | — |
| `activist` (tags) | 0 | Block 4 (informativ) |
| `superinvestor_13f` (closed) | 0 | Block 3 (informativ) |
| `short_trend` | −1 | — |
| `ftd` | −1 | — |
| `superinvestor_13f` (reduced) | −1 | Block 3 |
| `credit_stress` | −2 | Block 2 |

Maximaler theoretischer Score nach V2: 3+3+3+2+2+1+1+1 = 16, aber Cap bleibt
bei 10. Maximaler negativer Impact: −2−1−1−1 = −5. Ein Ticker mit nur positiven
Signalen kann also nicht mehr durch negative Signale unter 0 fallen.

---

## Offene Fragen (Zusammenfassung)

| ID | Block | Frage | Priorität |
|----|-------|-------|-----------|
| B-1 | TRACE | FINRA TRACE API liefert Issuer-Level Bond Spreads oder nur Aggregate? | Hoch — blockiert Block 2 |
| B-2 | TRACE | Ticker→CUSIP-Mapping: FMP, EDGAR oder manuell? | Hoch — blockiert Block 2 |
| C-1 | 13F | Baupost (Klarman) und Pabrai CIKs gegen EDGAR verifizieren | Mittel |
| C-2 | 13F | Elliott 13F deckt nur US-Equities (bekannt, ok) | Info |
| D-1 | SIX | `price_usd`-Feld für CHF-Ticker: leer lassen oder später umbenennen? | Niedrig |
| D-2 | SIX | SIX SER API-Endpunkt verifizieren via Browser-DevTools | Hoch — blockiert Block 5 |
| D-3 | SIX | `MIN_ABSOLUTE_VOLUME` für `.SW`-Ticker anpassen | Mittel |

---

## WCAG 2.2 AA Compliance (neue Komponenten)

**`CotMacroPanel.jsx`:**
- Tabelle: `role="table"`, `<th scope="col">` für alle Spalten-Headers
- Perzentil-Bars: `aria-label="Perzentil: 23%"` auf dem Bar-Element
- Farbkodierung (rot/grün) niemals allein ohne Text-Label (WCAG 1.4.1)
- Kontrast: `text-danger` und `text-success` müssen ≥ 4.5:1 auf `bg-card` haben

**Tab-Komponente in `Screening.jsx`:**
- `role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`
- Keyboard-Navigation: Pfeil-Tasten zwischen Tabs (WCAG 2.1.1)
- Fokus-Ring sichtbar (`focus-visible:ring-2`)

**Neue Signal-Badges:**
- `title`-Attribut auf jedem Badge (bereits im bestehenden `SignalBadge` vorhanden)
- `short`-Text für `six_insider` ist "CH" (2 Zeichen) — passt in `w-6 h-6`-Badge

---

## Nielsen-Heuristiken (neue UI-Elemente)

| Heuristik | Anwendung |
|-----------|-----------|
| #1 Sichtbarkeit Systemstatus | COT-Tab zeigt `updated_at`-Timestamp, SCAN_SOURCES-Array im Progress-Step für neue Quellen |
| #4 Konsistenz & Standards | Neue Signals folgen exakt `SIGNAL_CONFIG`-Pattern, `SignalBadge` wiederverwendet |
| #6 Fehler-Prävention | Block 5 (SIX) hat defensives Ticker-Handling, kein Crash bei unbekanntem Format |
| #8 Ästhetik & Minimalismus | Tags in Block 4 als kleine Pills, nicht als voller Text — Screener bleibt kompakt |
| #9 Hilfe beim Erkennen und Beheben von Fehlern | `credit_stress`-Warnung mit konkreten Zahlen (Spread-Ratio), nicht nur "Warnung" |

---

*Dokument-Ende. Scope freigegeben für sequenzielle Implementierung Block 1–5.*
