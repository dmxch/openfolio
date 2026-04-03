# Screening — Smart Money Tracker

## Vision

Eigenständiger Bereich in OpenFolio, der US-Aktien nach institutioneller Aktivität scannt und Kandidaten zur Übernahme in die Watchlist vorschlägt. Discovery-Tool vor dem bestehenden Watchlist → Setup Score → Kauf Workflow.

## Workflow

```
Screening           →  Watchlist          →  Setup Score       →  Kauf
Smart Money Tracker    (bestehend)            18 Punkte            Portfolio
scannt auf Knopfdruck  User übernimmt         (bestehend)          (bestehend)
                       selektiv
```

## Datenquellen (alle gratis, kein API-Key nötig)

### Phase 1 — Getestet & validiert

| Quelle | Methode | Bulk? | Speed | Signal |
|--------|---------|-------|-------|--------|
| OpenInsider Cluster Buys | HTML-Scrape `openinsider.com/latest-cluster-buys` | Ja, 1 Request | ~2s | Insider-Cluster (≥2 Insider kaufen gleichzeitig) |
| OpenInsider Grosse Käufe | HTML-Scrape Screener (>$500k, 30d) | Ja, 1 Request | ~2s | Grosse Einzelkäufe |
| FINRA Short Volume | CSV-Download `cdn.finra.org` (1 File = alle Symbole) | Ja, 14 Files | ~10s | Short-Ratio 14-Tage-Trend |
| SEC EDGAR 8-K Buybacks | EFTS Volltextsuche "share repurchase" | Ja, 1 Request | ~3s | Aktienrückkauf-Ankündigungen |

### Phase 2 — Getestet & validiert

| Quelle | Methode | Bulk? | Speed | Signal |
|--------|---------|-------|-------|--------|
| Capitol Trades | RSC-Scrape `capitoltrades.com` (Next.js Streaming) | Ja, 3 Pages | ~5s | Congressional Trading (Kongresskäufe) |
| Dataroma Real-Time | HTML-Scrape `dataroma.com/m/rt.php` | Ja, 1 Request | ~2s | Superinvestor-Käufe (Icahn, Buffett, Einhorn etc.) |
| Dataroma Grand Portfolio | HTML-Scrape `dataroma.com/m/g/portfolio_b.php` | Ja, 1 Request | ~2s | Superinvestor-Konsens (82 Investoren, Top-Holdings) |
| SEC EDGAR 13D/13G | Submissions API pro Aktivist (`data.sec.gov`) | Pro Investor | ~3s × 15 | Aktivisten-Beteiligungen (5%+ Positionen) |

### Phase 3 — Getestet & validiert

| Quelle | Methode | Bulk? | Speed | Signal |
|--------|---------|-------|-------|--------|
| SEC Fails-to-Deliver | ZIP-Download `sec.gov` (halbe-Monats-Files) | Ja, 1 File | ~3s | FTD-Squeeze-Kandidaten |
| Unusual Volume | yfinance (bereits im Stack) | Per-Ticker | ~30s für ~150 Kandidaten | Volumen-Anomalien |

### Verworfene Quellen

| Quelle | Grund |
|--------|-------|
| FMP (Financial Modeling Prep) | Legacy-API abgeschaltet seit Aug 2025, Key wertlos |
| QuiverQuant | $25/Mo, nicht FOSS-kompatibel |
| Finnhub (per-Ticker) | 60 req/min, zu langsam für 1000+ Ticker im Bulk-Scan |
| yfinance Options (Bulk) | Per-Ticker, kein Bulk, 30-80 Min. für 1000 Ticker |
| FINRA ATS Dark Pool (Detail) | API liefert nur veraltete Daten (2023), nicht aktuell per-Security |
| CBOE Put/Call CSV | CDN blockiert Downloads (403 Forbidden) |
| House/Senate Stock Watcher S3 | Endpoints geben 403 zurück |

## Smart Money Score (0–10)

| Signal | Gewicht | Begründung |
|--------|---------|------------|
| **Insider Cluster Buy** | 3 Punkte | Stärkstes Signal — ≥2 Insider kaufen gleichzeitig denselben Ticker |
| **Superinvestor kauft** (Dataroma/13D) | 2 Punkte | Buffett, Icahn, Ackman, Einhorn etc. positionieren sich |
| **Share Buyback** (8-K Ankündigung) | 2 Punkte | Firma kauft eigene Aktien — Management glaubt an Unterbewertung |
| **Grosser Insider-Kauf** (>$500k einzeln) | 1 Punkt | Einzelner Insider mit signifikantem Commitment |
| **Congressional Buy** | 1 Punkt | Politischer Informationsvorsprung, aber 45-Tage-Reporting-Delay |
| **Short-Ratio-Anstieg** (14d Trend) | 1 Punkt | Squeeze-Potenzial / Kontrarian-Signal |

Score-Farbe: Neutral blau (nicht grün/rot). Keine implizite Kaufempfehlung.

### Superinvestor-Tracking (SEC EDGAR Submissions API)

15+ bekannte Aktivisten/Superinvestoren werden über `data.sec.gov/submissions/CIK{}.json` getrackt. Getestet mit Ergebnis:

| Investor | 2026 Filings | Typen |
|----------|-------------|-------|
| Carl Icahn | 7 | 13D/A, 13F-HR |
| Berkshire Hathaway (Buffett) | 2621 | 13F-HR, 13G/A, 13G |
| Trian Fund Management | 40 | 13F-HR, 13G/A, 13G |
| ValueAct Capital | 22 | 13G, 13G/A, 13F-HR |
| Baupost Group (Klarman) | 6 | 13F-HR, 13G/A, 13G |
| Appaloosa Management | 3 | 13D, 13G/A, 13F-HR |
| Elliott Management | 2 | 13G/A, 13F-HR |
| Greenlight Capital (Einhorn) | 2 | 13G, 13F-HR |
| u.a. Pershing Square, Third Point, Tiger Global, Bridgewater | je 1 | 13F-HR |

Die 13D/13G XML-Filings enthalten die Zielunternehmen (`issuerName`, `issuerCIK`, `CUSIP`).

## Scan-Mechanismus

- **Manueller Trigger**: Button "Jetzt scannen" (kein Automatismus)
- **Universum**: Alle US-Symbole (FINRA deckt 11'400+ Symbole ab)
- **Geschwindigkeit Phase 1**: ~20 Sekunden (4 Bulk-Quellen)
- **Geschwindigkeit Phase 2**: ~40 Sekunden (+3 Quellen + Aktivisten-Tracking)
- **Progress-Anzeige**: Live-Fortschritt pro Datenquelle mit Zählern

### Progress-UI beim Scan

```
Screening läuft...

████████████████░░░░░░░░░░░░  5 von 7 Quellen

✓ FINRA Short Volume            11'842 Aktien geladen
✓ OpenInsider Cluster Buys      47 Cluster erkannt
✓ OpenInsider Grosse Käufe      73 Ticker gefunden
✓ SEC Buyback-Ankündigungen     454 Filings durchsucht
✓ Dataroma Superinvestoren      10 Käufe erkannt
◌ Capitol Trades                wird geladen...
○ Aktivisten-Tracking (SEC)     ausstehend

Über 11'000 US-Aktien werden nach institutioneller
Aktivität durchsucht.

                                         [Abbrechen]
```

### Fehlertoleranz

Wenn eine Quelle fehlschlägt, läuft der Rest weiter. Amber-Banner: "X von Y Datenquellen nicht verfügbar. Ergebnisse können unvollständig sein."

## UI-Design

### Navigation

Sidebar-Eintrag "Screening" (Icon: `Radar`) zwischen Watchlist und Transaktionen.

### Seitenstruktur `/screening`

```
┌─────────────────────────────────────────────────────────────────┐
│  Smart Money Tracker                       [Jetzt scannen]      │
│  Institutionelles Interesse in US-Aktien                        │
├─────────────────────────────────────────────────────────────────┤
│  ⚠ Dieses Tool zeigt beobachtbare Marktaktivität.              │
│    Es handelt sich um keine Handlungsempfehlung.                │
├─────────────────────────────────────────────────────────────────┤
│  Score ≥ [1▾]  Signaltyp: [Alle▾]     Stand: 03.04.2026       │
├─────────────────────────────────────────────────────────────────┤
│  47 Aktien                                                      │
│                                                                 │
│  Ticker  Name           Sektor   Score      Signale     Preis   │
│  NVDA    NVIDIA Corp    Tech     ████████░ 8 [I][B][S]  $892 [+]│
│  CVI     CVR Energy     Energy   ██████░░ 6  [I][A]     $21  [+]│
│  AAPL    Apple Inc      Tech     ████░░░░ 4  [I][C]     $169 [+]│
│                                                                 │
│  ▼ NVDA expandiert:                                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ [I] Insider Cluster: 3 Insider kauften in 30 Tagen      │   │
│  │     CEO $1.2M (15. Mrz), CFO $800k (12. Mrz)           │   │
│  │ [B] Buyback: Rückkaufprogramm $25B angekündigt (8-K)    │   │
│  │ [S] Short-Trend: Ratio +28% in 14 Tagen                │   │
│  │                                                          │   │
│  │                                   [Zur Watchlist ▸]      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Signal-Badges (Icon-Legende)

| Badge | Signal | Farbe |
|-------|--------|-------|
| [I] | Insider (Cluster oder Gross-Kauf) | `text-primary` (blau) |
| [B] | Buyback (Aktienrückkauf) | `text-primary` |
| [S] | Short-Trend (Ratio-Anstieg) | `text-primary` |
| [A] | Aktivist/Superinvestor | `text-primary` |
| [C] | Congressional (Kongresskauf) | `text-primary` |
| [F] | Fails-to-Deliver (Phase 3) | `text-primary` |

Alle Badges in neutralem Blau — keine Rot/Grün-Kodierung, keine Kaufempfehlung.

### Tabellen-Spalten

| Spalte | Sortierbar |
|--------|------------|
| Ticker (Link zu /stock/[TICKER]) | Ja |
| Name | Nein |
| Sektor | Ja |
| Score (Segment-Balken 0–10 + Zahl) | Ja (default desc) |
| Signale (Icon-Badges) | Nein |
| Preis (USD) | Nein |
| Zur Watchlist (BookmarkPlus Button) | Nein |

### "Zur Watchlist" Flow

1. Klick auf BookmarkPlus → Inline-Modal (Ticker, Name, Sektor vorausgefüllt)
2. `POST /api/analysis/watchlist` (bestehender Endpoint)
3. Toast "NVDA zur Watchlist hinzugefügt"
4. Button wechselt zu BookmarkCheck (disabled)

### Leere Zustände

- Noch nie gescannt: "Drücke 'Jetzt scannen' um US-Aktien nach Smart-Money-Aktivität zu durchsuchen."
- Alle weggefiltert: "Keine Aktien entsprechen den gewählten Filtern." + [Filter zurücksetzen]
- API-Fehler: Amber-Banner mit letztem gültigem Datum

## Phasenplan

### Phase 1 — MVP (~3-4 Wochen)

**4 Quellen, Score 0–7, Scan ~20s**

**Backend:**
- `SmartMoneyResult` DB-Modell + Alembic-Migration
- `screening_service.py`: Orchestriert Scan, aggregiert Score
- `openinsider_scraper.py`: Cluster Buys + Grosse Käufe
- `finra_short_service.py`: 14-Tage Short Volume Trend
- `sec_buyback_service.py`: 8-K Buyback-Suche via EFTS
- `POST /api/screening/scan` → startet Scan, gibt `scan_id` zurück
- `GET /api/screening/scan/{id}/progress` → Polling-Endpoint
- `GET /api/screening/results` → paginiert, filterbar

**Frontend:**
- Route `/screening`, Seite `Screening.jsx`
- `ScreeningTable.jsx` (analog WatchlistTable)
- `SmartMoneyScoreBar.jsx` (Segment-Balken 0–10)
- `ScanProgress.jsx` (Fortschritts-Overlay)
- `SignalBadge.jsx` (Icon-Badges für Signaltypen)
- Sidebar-Eintrag "Screening" mit Radar-Icon

### Phase 2 (~2-3 Wochen)

**+3 Quellen, Score 0–10, Scan ~40s**

- `capitoltrades_scraper.py`: Congressional Trading via RSC Scrape
- `dataroma_scraper.py`: Superinvestor Real-Time + Grand Portfolio
- `activist_tracker.py`: SEC EDGAR 13D/13G für 15+ Aktivisten
- Row-Expand Detail-Panel mit Rohdaten pro Signal
- Sektor-Filter, Score-Filter

### Phase 3 (optional)

- SEC Fails-to-Deliver als Bonus-Warnung
- Unusual Volume Enrichment (yfinance, nur für Kandidaten)
- AI-gestützte Sentiment-Analyse auf 8-K/10-K Filings (LLM)
- Historische Signal-Ansicht
- CSV-Export

## Technische Entscheidungen

- **Scan on-demand** (Button "Jetzt scannen"), kein Scheduler-Job
- **Bulk-Feeds** statt per-Ticker-Abfragen (~20-40s statt Stunden)
- **Polling** für Progress (GET alle 2s), kein SSE (einfacher durch Nginx)
- **Score hardcoded** (nicht konfigurierbar in MVP)
- **Disclaimer persistent** (nicht wegklickbar)
- **Signal-Sprache neutral**: "Institutionelles Interesse" statt "Kaufsignal"
- **Alle Scraper verwenden httpx** (wie in CLAUDE.md vorgeschrieben)
- **SEC EDGAR Requests** mit User-Agent Header inkl. Email (Pflicht)

## Heilige Dateien

Keine der geschützten Dateien wird berührt:
- `portfolio_service.py`, `recalculate_service.py`, `price_service.py` — unverändert
- `performance_history_service.py`, `total_return_service.py` — unverändert
- Scoring/Breakout-Logik — unverändert

## API Spike Ergebnisse (2026-04-03)

Alle Quellen wurden real getestet. Detaillierte Ergebnisse in `SCREENING_API_SPIKE.md`.

### Validierte Datenmengen

| Quelle | Einträge | Qualität |
|--------|----------|----------|
| FINRA Short Volume | 11'400 Symbole/Tag, 14 Tage = 160k Datenpunkte | Exzellent |
| OpenInsider Cluster Buys | ~100 Cluster-Buys (60 Tage) | Sehr gut (vorfiltriert) |
| OpenInsider Grosse Käufe | ~73 Ticker (30 Tage, >$500k) | Gut |
| SEC EDGAR 8-K Buybacks | ~454 Filings (30 Tage) | Gut (Ticker in Filing-Metadaten) |
| Capitol Trades | ~36 Trades (90 Tage), 25 Ticker | Mittel (paginiert, RSC-Format) |
| Dataroma Real-Time | ~10-25 Superinvestor-Transaktionen | Gut (inkl. Icahn, Ackman) |
| Dataroma Grand Portfolio | 100 Top-Holdings, 82 Investoren | Sehr gut (Konsens-Signal) |
| SEC 13D/13G | 12/16 getrackte Aktivisten aktiv in 2026 | Gut (XML-Parsing nötig) |
| SEC FTD | 56'000 Zeilen/Halbmonat | Gut (ZIP-Download) |
