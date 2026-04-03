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

## Datenquellen (alle gratis)

| Quelle | Methode | Bulk? | Key | Phase |
|--------|---------|-------|-----|-------|
| FINRA Short Volume | CSV-Download `cdn.finra.org` (1 File = alle Symbole) | Ja | Keiner | 1 |
| OpenInsider Cluster Buys | HTML-Scrape (vorfiltrierte Cluster-Buy-Tabelle) | Ja | Keiner | 1 |
| FMP Insider RSS | REST API `/v4/insider-trading-rss-feed` (Bulk-Feed) | Ja | Vorhanden | 1 |
| FMP Senate Disclosure | REST API `/v4/senate-disclosure` (Bulk-Feed) | Ja | Vorhanden | 2 |
| SEC EDGAR Form 4 | Daily Index Files + XML Parsing | Ja | Keiner | 2 |

**Keine Paid-APIs.** Alles FOSS-kompatibel.

### Verworfene Quellen

- **Finnhub**: Per-Ticker (kein Bulk), 60 req/min = 17 Min. für 1000 Ticker → zu langsam
- **QuiverQuant**: API kostet $25/Mo → nicht FOSS-kompatibel
- **yfinance Options**: Per-Ticker, kein Bulk → 30-80 Min. für 1000 Ticker

## Smart Money Score (0–5)

| Signal | Quelle | Bedingung | Gewicht |
|--------|--------|-----------|---------|
| Insider Cluster Buy | OpenInsider | ≥2 Insider-Käufe in 60 Tagen, Total ≥ $500k | 2 Punkte |
| Insider-Käufe (breit) | FMP Insider RSS | Kauf-Transaktionen in letzten 30 Tagen | 1 Punkt |
| Short Squeeze Kandidat | FINRA Short Volume | Short-Ratio-Anstieg ≥ 20% in 14 Tagen | 1 Punkt |
| Congressional Buy | FMP Senate Disclosure | Kauf durch Senator in ≤30 Tagen (Phase 2) | 1 Punkt |

Score-Farbe: Neutral blau (nicht grün/rot). Keine implizite Kaufempfehlung.

## Scan-Mechanismus

- **Manueller Trigger**: Button "Jetzt scannen" (kein Automatismus)
- **Universum**: Russell 1000+ (FINRA deckt alle US-Symbole ab)
- **Geschwindigkeit**: ~20 Sekunden via Bulk-Feeds (nicht per-Ticker)
- **Progress-Anzeige**: Live-Fortschritt pro Datenquelle mit Zählern

### Progress-UI beim Scan

```
Screening läuft...

████████████░░░░░░░░░░░░░░░░  3 von 4 Quellen

✓ FINRA Short Volume         11'842 Aktien geladen
✓ OpenInsider Cluster Buys   47 Cluster erkannt
◌ FMP Insider Transaktionen  wird geladen...
○ Congressional Trading      ausstehend

Über 1'000 US-Aktien werden nach institutioneller
Aktivität durchsucht.

                                         [Abbrechen]
```

### Fehlertoleranz

Wenn eine Quelle fehlschlägt, läuft der Rest weiter. Amber-Banner: "1 von X Datenquellen nicht verfügbar. Ergebnisse können unvollständig sein."

## UI-Design

### Navigation

Sidebar-Eintrag "Screening" (Icon: `Radar`) zwischen Watchlist und Transaktionen.

### Seitenstruktur `/screening`

```
┌─────────────────────────────────────────────────────────────┐
│  Smart Money Tracker                    [Jetzt scannen]     │
│  Institutionelles Interesse in US-Aktien                    │
├─────────────────────────────────────────────────────────────┤
│  ⚠ Dieses Tool zeigt beobachtbare Marktaktivität.          │
│    Es handelt sich um keine Handlungsempfehlung.            │
├─────────────────────────────────────────────────────────────┤
│  Score ≥ [1▾]  Signaltyp: [Alle▾]   Stand: 03.04.2026     │
├─────────────────────────────────────────────────────────────┤
│  47 Aktien                                                  │
│                                                             │
│  Ticker  Name         Sektor  Score    Signale  Preis   +   │
│  NVDA    NVIDIA Corp  Tech    ████░ 4  [I][S]   $892   [+] │
│  AAPL    Apple Inc    Tech    ███░░ 3  [I]      $169   [+] │
│                                                             │
│  ▼ NVDA expandiert:                                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Insider-Käufe: CEO $1.2M (15. Mrz), CFO $800k (12.)│    │
│  │ Short Interest: +28% in 14 Tagen, DTC: 7.2          │    │
│  │                            [Zur Watchlist ▸]         │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Tabellen-Spalten

| Spalte | Sortierbar |
|--------|------------|
| Ticker (Link zu /stock/[TICKER]) | Ja |
| Name | Nein |
| Sektor | Ja |
| Score (Balken 1-5 + Zahl) | Ja (default desc) |
| Signale (Icon-Badges: [I] Insider, [S] Short, [C] Congress) | Nein |
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

### Phase 1 — MVP

**Backend:**
- `SmartMoneyResult` DB-Modell + Alembic-Migration
- `smart_money_service.py`: FINRA Short Volume + OpenInsider Scrape + FMP Insider RSS
- `POST /api/screening/scan` → startet Scan, gibt `scan_id` zurück
- `GET /api/screening/scan/{id}/progress` → Polling-Endpoint für Fortschritt
- `GET /api/screening/results` → paginiert, filterbar

**Frontend:**
- Route `/screening`, Seite `Screening.jsx`
- `ScreeningTable.jsx` (analog WatchlistTable)
- `SmartMoneyScoreBar.jsx` (Segment-Balken)
- `ScanProgress.jsx` (Fortschritts-Overlay)
- Sidebar-Eintrag

### Phase 2

- FMP Senate Disclosure (Congressional Trading)
- SEC EDGAR Form 4 (breitere Insider-Abdeckung)
- Row-Expand Detail-Panel
- Sektor-Filter

### Phase 3 (optional)

- 13F Institutional Holdings (SEC EDGAR, quartalsweise)
- ETF Fund Flows
- Historische Signal-Ansicht
- CSV-Export

## Technische Entscheidungen

- **Scan on-demand** (Button), kein Scheduler-Job
- **Bulk-Feeds** statt per-Ticker-Abfragen (~20s statt ~17min)
- **Polling** für Progress (GET alle 2s), kein SSE (einfacher durch Nginx)
- **Score hardcoded** (nicht konfigurierbar in MVP)
- **Disclaimer persistent** (nicht wegklickbar)
- **Signal-Sprache neutral**: "Institutionelles Interesse" statt "Kaufsignal"

## Heilige Dateien

Keine der geschützten Dateien wird berührt:
- `portfolio_service.py`, `recalculate_service.py`, `price_service.py` — unverändert
- `performance_history_service.py`, `total_return_service.py` — unverändert
- Scoring/Breakout-Logik — unverändert
