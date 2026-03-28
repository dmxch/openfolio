# Changelog

Alle wichtigen Änderungen an OpenFolio werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.20.0] — 2026-03-28

### Hinzugefügt
- Rate Limiting auf allen ~60 schreibenden Endpoints (POST/PUT/PATCH/DELETE) — 30/min für CRUD, 5/min für rechenintensive Operationen
- CoinGecko Rate-Limiter (max 25 Calls/Minute mit Sliding-Window)
- DataContext Error-State: Netzwerkfehler werden geloggt und im Context verfügbar gemacht
- PriceCache Index auf `date`-Spalte für schnellere Queries
- Alembic-Migration 034 für PriceCache-Index
- Zentralisierte Encryption-Helpers (`services/encryption_helpers.py`)
- Shared Pydantic-Schemas (`api/schemas.py`) und Constants (`constants/limits.py`)

### Behoben
- Silent Exception in `price_service.py` — yfinance-Fehler werden jetzt geloggt (debug)
- Silent Exceptions in `utils.py` (FX-Rate, MRS, Close-Series) — alle mit Logging
- Silent Exceptions in `portfolio_service.py` (MA-Status, MRS-Lookup)
- Silent Exception in `stock.py` — yfinance Ticker-Fallback-Lookup
- User-Löschung: Private Equity Holdings und AdminAuditLog werden jetzt korrekt mitgelöscht
- nginx `/assets/` Location: Security Headers (HSTS, CSP, X-Frame-Options etc.) fehlten — nginx vererbt `add_header` nicht bei eigenen Direktiven
- `validate-reset-token` akzeptiert jetzt Pydantic-Model statt unvalidiertem `dict`
- `/api/errors` Body auf 10 KB limitiert
- CORS: `OPTIONS` aus `allow_methods` entfernt (wird automatisch von CORSMiddleware behandelt)

### Geändert
- `_encrypt_field`/`_decrypt_field`/`_decrypt_and_mask_iban` aus 7 Dateien in zentrale `services/encryption_helpers.py` konsolidiert
- `RecalculateRequest` aus `positions.py` und `performance.py` in `api/schemas.py` konsolidiert
- `MAX_POSITIONS_PER_USER`/`MAX_TRANSACTIONS_PER_USER` in `constants/limits.py` zentralisiert
- PriceCache-Query in daily-change Endpoint: nur benötigte Ticker statt alle laden
- Earnings-Refresh: parallel mit Semaphore (max 5 concurrent) statt sequentiell
- Alerts: Moving Averages nur für Broad-Index-ETFs berechnen (nicht alle Watchlist-Items)
- PE Holdings Count: `select(func.count())` statt `len(scalars.all())`

## [0.19.5] — 2026-03-27

### Entfernt
- Fundamentaldaten-Sektion komplett entfernt (Revenue, Margins, D/E, PE, PEG, FCF, Market Cap, ROIC, EPS, EPS Growth) — yfinance-Daten weichen systematisch von StockAnalysis ab und sind für Investitionsentscheidungen unzuverlässig
- 4 Fundamental-Kriterien aus dem Setup-Score entfernt (Umsatz steigend, EPS steigend, ROE > 15%, D/E unter Branche Ø) — Score von 22 auf 18 rein technische Kriterien reduziert
- `fundamental_service.py` gelöscht, API-Endpoints `/stock/{ticker}/key-metrics` und `/stock/{ticker}/fundamentals` entfernt
- Bollinger Bands Toggle "BB(20)" aus der TradingView-Chart Indikator-Leiste entfernt

### Hinzugefügt
- Aktien-Detailseite: Link zu StockAnalysis (US-Aktien) bzw. Yahoo Finance (Nicht-US) für Fundamentaldaten
- ETFs zeigen "ETF Holdings & Zusammensetzung" mit Link zu Yahoo Finance Holdings
- Backend: `quoteType` Feld im Company-Profile-Endpoint für ETF-Erkennung
- TradingView Chart: RSI standardmässig aktiv

### Geändert
- Setup-Score Schwellen bleiben prozentual gleich (≥70% STARK, 45-69% MODERAT, <45% SCHWACH)
- Glossar: Setup-Score Beschreibung aktualisiert (18 Kriterien, rein technisch)
- CLAUDE.md und README.md an neue Architektur angepasst

## [0.17.4] — 2026-03-27

### Hinzugefügt
- PEG Ratio als neue Fundamental-Karte auf der Aktien-Detailseite (PE Ratio / Earnings Growth)
- Farbcodierung: Grün < 1.0 (potenziell unterbewertet), Gelb 1.0–2.0 (fair), Rot > 2.0 (potenziell überbewertet)
- Backend: Primär `pegRatio` aus yfinance, Fallback-Berechnung aus `trailingPE / earningsGrowth`
- Glossar-Eintrag für PEG Ratio mit GlossarTooltip

## [0.17.3] — 2026-03-27

### Behoben
- S&P 500 Kurs im Marktklima-Widget zeigte 119.52 statt ~5'500 — korrupter In-Memory-Cache bereinigt
- `prefetch_close_series`: Single-Ticker mit `group_by="ticker"` schlug fehl wegen MultiIndex-Spaltenstruktur (KeyError auf `data["Close"]`)
- Sanity-Check für S&P 500 Kurs von >100 auf >1'000 angehoben (S&P war seit 2014 nie unter 1'000)

## [0.17.2] — 2026-03-27

### Geändert
- Monatsrenditen-Heatmap: Benchmark-Zeile (S&P 500) in neutralem Grau statt grün/rot — klare visuelle Trennung zwischen Portfolio (farbig) und Benchmark (grau)

## [0.17.1] — 2026-03-26

### Behoben
- Benchmark-Heatmap: yfinance MultiIndex-Columns korrekt geflattened — S&P 500 Zeile wird jetzt angezeigt

## [0.17.0] — 2026-03-26

### Hinzugefügt
- Monatsrenditen-Heatmap: Benchmark-Zeile (S&P 500) unter jeder Jahreszeile — zeigt Index-Monatsrenditen zum Vergleich
- Neuer Endpoint `GET /api/portfolio/benchmark-returns?ticker=^GSPC` mit 24h Redis-Cache
- Neuer Service `benchmark_service.py` berechnet Monatsrenditen aus yfinance-Kursdaten (5 Jahre Historie)

## [0.16.1] — 2026-03-26

### Behoben
- ROIC: Erweiterte Fallback-Kette (returnOnCapital → returnOnInvestedCapital → Financials-Berechnung → ROE als Annäherung)
- ROIC: Label wechselt automatisch zu "ROE" wenn nur Eigenkapitalrendite verfügbar ist
- EPS: Zeigt jetzt Währungssymbol (z.B. "$8.52" statt "8.52")

### Hinzugefügt
- Glossar: Neue Einträge für ROIC, ROE, EPS Growth mit GlossarTooltip auf den Fundamental-Karten

## [0.16.0] — 2026-03-26

### Hinzugefügt
- Aktien-Detailseite: Drei neue Fundamental-Kennzahlen — ROIC (Return on Invested Capital), EPS (TTM), EPS Growth (YoY)
- ROIC: Berechnet aus yfinance returnOnCapital oder operatingIncome / (totalAssets - currentLiabilities)
- Farbcodierung: ROIC grün > 12%, gelb 8–12%, rot < 8%; EPS grün wenn positiv; EPS Growth grün wenn wachsend

## [0.15.6] — 2026-03-26

### Behoben
- Direktbeteiligungen-Widget: Farbige Linie (emerald) an der oberen Kante hinzugefügt — konsistent mit allen anderen Portfolio-Widgets

## [0.15.5] — 2026-03-26

### Hinzugefügt
- Aktien & ETFs: "Dividende erfassen" im Drei-Punkte-Menü (⋮) — öffnet Transaktionsformular mit Typ Dividende vorausgewählt

## [0.15.4] — 2026-03-26

### Behoben
- Private Equity: Unrealisierter Gewinn/Verlust und investiertes Kapital werden jetzt aus der Gesamtrendite-Karte ausgeschlossen (total_return_service.py)
- Private Equity: PE-Positionen fliessen nicht mehr in MWR-Fallback-Berechnung ein
- Private Equity: Komplett aus Snapshot-Berechnungen entfernt (war faelschlicherweise als cost_basis inkludiert, verursachte -89K Phantom-Cashflow in XIRR)
- Private Equity: Aus Portfolio-History-Berechnung entfernt (history_service.py)
- Snapshots regeneriert nach PE-Entfernung (727 Snapshots, sauber)
- XIRR Diagnose-Report erstellt (XIRR_DIAGNOSE.md): 11.36% annualisiert, plausibel, alle 12 PE-Ausschluss-Stellen verifiziert

## [0.15.3] — 2026-03-26

### Behoben
- Private Equity: Wird jetzt korrekt aus allen liquiden Performance-Berechnungen ausgeschlossen (Heute, Gesamtrendite, YTD, Monatsrenditen, XIRR, Snapshots)
- Private Equity: current_price bleibt NULL wenn keine Bewertung hinterlegt ist (kein falscher −90K Verlust mehr)
- Private Equity: In Liquides Vermögen, Daily Change, History und Snapshot-Berechnung gleich behandelt wie Vorsorge/Immobilien

## [0.15.2] — 2026-03-26

### Geändert
- UI Polish: Alle Portfolio-Widgets an das Design des Direktbeteiligungen-Widgets angeglichen — grössere Titel, farbige Icons, ausgefüllte Add-Buttons

## [0.15.1] — 2026-03-26

### Behoben
- Direktbeteiligungen: Drei-Punkte-Menü (⋮) auf jeder Holding-Zeile mit Aktionen "Bewertung hinzufügen", "Dividende hinzufügen", "Bearbeiten", "Löschen"

## [0.15.0] — 2026-03-26

### Hinzugefügt
- Neues Widget: Direktbeteiligungen / Private Equity — nicht-börsenkotierte Unternehmensbeteiligungen mit jährlicher Steuerwert-Bewertung und Dividendenhistorie
- Private Equity: Drei neue Tabellen (Holdings, Valuations, Dividends) mit Fernet-Verschlüsselung für PII
- Private Equity: Vollständige CRUD-API mit 12 Endpoints (Holdings, Bewertungen, Dividenden)
- Private Equity: Position-Sync für Gesamtvermögen-Tracking (analog Edelmetalle)
- Private Equity: Automatische Berechnung von Netto-Steuerwert (Pauschalabzug) und Dividenden-Beträgen (Verrechnungssteuer)
- Private Equity: Detail-Ansicht mit Bewertungshistorie, Dividendenhistorie und Kennzahlen
- Private Equity: Eigene Kategorie "Private Equity" im Sektor-Chart
- Private Equity: Wird NICHT in liquide Performance eingerechnet (wie Vorsorge/Immobilien)

## [0.14.0] — 2026-03-26

### Hinzugefügt
- Neue Alert-Kategorie: "ETF unter 200-DMA (Kaufkriterien)" — benachrichtigt wenn breite Index-ETFs (27-Ticker Whitelist) unter die 200-Tage-Linie fallen
- ETF 200-DMA Alerts prüfen sowohl Portfolio-Positionen als auch Watchlist-Einträge
- E-Mail-Benachrichtigung für ETF 200-DMA Alerts (aktivierbar in Einstellungen, tägliche Deduplizierung)
- Worker-Job für ETF 200-DMA E-Mail-Alerts (täglich 22:35 CET nach US-Marktschluss)
- Positiver Alert-Stil (grün, TrendingUp-Icon) für Kaufkriterien-Alerts

### Geändert
- ETF 200-DMA Whitelist aus `scoring_service.py` in gemeinsame Konstante `sector_mapping.py` extrahiert (DRY)

## [0.13.0] — 2026-03-26

### Hinzugefügt
- Portfolio-Sektorchart: ETF-Sektorgewichtungen werden aufgelöst — OEF, CHSPI, EIMI verteilen ihren Marktwert anteilig auf die hinterlegten Sektoren statt als "Multi-Sector" zu klumpen

### Behoben
- TradingView Mini-Widget (Portfolio-Tabelle, Watchlist): Symbol-Mapping für .SW-Ticker (z.B. CHSPI.SW → SIX:CHSPI) — bisher wurde der rohe yfinance-Ticker übergeben
- TradingView-Widgets: Graceful Fallback bei nicht verfügbaren Symbolen (z.B. EIMI.L) — Mini-Widget zeigt "Chart nicht verfügbar", Hauptchart zeigt Fallback mit Link zu TradingView

### Geändert
- TradingView Symbol-Mapping in gemeinsame Utility-Funktion `toTradingViewSymbol()` extrahiert (DRY)

## [0.12.0] — 2026-03-25

### Hinzugefügt
- Immobilien: SARON-Hypotheken mit Marge — dynamische Zinsberechnung (Marge + SARON-Leitzins, Floor auf Marge)
- Immobilien: Effektiver Zinssatz wird im Hypothek-Formular live berechnet und in der Tabelle angezeigt
- Immobilien: Hypothek-Tabelle zeigt bei SARON Subtext "Marge X.XXX%"

## [0.11.0] — 2026-03-25

### Hinzugefügt
- Transaktionen: Ticker-Autocomplete mit Suche (bestehende Positionen + yfinance) ersetzt Positions-Dropdown
- Transaktionen: Positionen werden automatisch erstellt wenn Ticker neu ist (gleicher Flow wie CSV-Import)
- Transaktionen: Erweiterte Währungsauswahl (JPY, SEK, NOK, DKK, AUD, HKD, SGD)
- API: Neuer Endpoint `GET /api/stock/search?q=...` für Ticker-Suche
- Pocket (pocketbitcoin.com) CSV-Import mit Auto-Detection (nur BTC-Käufe, deposit/withdrawal werden übersprungen)
- Watchlist: Resistance-Level (Breakout) manuell setzen über Crosshair-Button im Actions-Bereich

### Geändert
- Watchlist: "Ticker analysieren" öffnet jetzt die volle Detailseite (Chart, Fundamentals, Score) statt nur den Score inline
- Portfolio: Resistance-Level aus dem Positions-Editor entfernt (jetzt nur noch über Watchlist)

## [0.10.0] — 2026-03-25

### Hinzugefügt
- Portfolio: "Position hinzufügen" Button bei Aktien & ETFs und Crypto mit Weiterleitung zu Transaktionen
- Portfolio: Empty States bei leeren Aktien/ETF- und Crypto-Tabellen mit Buttons "Transaktion erfassen" und "CSV importieren"
- Immobilien: Dreipunkte-Menü (⋮) als Mobile-Alternative zum Rechtsklick-Kontextmenü
- Immobilien: "Immobilie löschen" Option im Kontextmenü
- Changelog-Seite unter /changelog mit Versions-Link im Footer

### Behoben
- Immobilien: Netto-Berechnung rechnete Hypothekarkosten doppelt ein (Ausgaben + Zinsen/Amortisation statt nur Ausgaben)

## [0.9.0] — 2026-03-25

### Hinzugefügt
- IBKR Flex Query CSV-Import (Auto-Erkennung, 22 Börsen-Mappings)
- 3-Punkt-Umkehr-Erkennung im Setup-Score (Kriterium #19)
- Versionsnummer im Footer
- Self-Hosting-Dokumentation (Reverse Proxy, CORS, Override)

### Behoben
- JPY-Dividenden wurden nicht in CHF umgerechnet
- Portfolio-Daten nach Import/Erfassung erst nach Hard Refresh sichtbar
- Fresh Install: Fehlende Tabellen bei erstmaliger DB-Erstellung
- Admin-User Race Condition bei mehreren Uvicorn-Workers
- Immobilien-Akkordeon per Default aufgeklappt

### Geändert
- CORS_ORIGINS aus Environment statt hardcoded
- Backend-Port auf localhost für Reverse Proxy
- Score-System: 18 → 19 Kriterien (alle 4 Strategy-Regeln implementiert)
