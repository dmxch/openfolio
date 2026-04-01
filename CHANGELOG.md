# Changelog

Alle wichtigen Änderungen an OpenFolio werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.21.13] — 2026-04-01

### Behoben
- Performance: FX-Rates und Close-Series-Prefetch in portfolio_service.py parallelisiert via asyncio.gather (H-1)

## [0.21.12] — 2026-04-01

### Behoben
- Docs: Datenschutzseite um 3 neue PII-Felder ergänzt — Hypothekenbank, Mietername, PE-Firmendaten (DRIFT-4)
- Docs: helpContent.js — D/E Ratio nicht mehr als Setup-Score-Kriterium bezeichnet (DRIFT-1)
- Docs: helpContent.js — Makro-Gate als informativer Indikator statt Kaufblocker beschrieben (DRIFT-2)
- Docs: helpContent.js — MRS-Kriterien von "zwei" auf "drei" korrigiert (MRS > 0, > 0.5, > 1.0) (DRIFT-3)
- Docs: helpContent.js — Kauf-Checkliste Fundamentals-Verweis aktualisiert (DRIFT-5)
- Docs: CLAUDE.md — Rate-Limit-Zähler von 77 auf 109 Decorators aktualisiert, PII-Liste ergänzt (DRIFT-6)

## [0.21.11] — 2026-04-01

### Behoben
- Security: Mortgage.bank und PropertyIncome.tenant werden jetzt mit Fernet verschluesselt (PII), Alembic-Migration String->Text (MED-1)
- Security: fred_api_key in UserSettings von String(500) auf Text geaendert — Alembic-Migration (MED-2)
- Security: FRED API-Key wird jetzt 5 Min gecacht statt bei jedem Call aus DB geladen (M-2)
- Architecture: Rate Limit (60/min) auf /api/portfolio/summary (M10)
- Architecture: Export-Logik aus settings.py Router in settings_service.py verschoben (M9)
- Performance: Grafana alerts.yml — email Contact-Point entfernt, verhindert Restart-Loop ohne SMTP (H-3)
- Performance: close:{ticker} Cache-TTL fuer 1y/2y/5y Perioden von 900s auf 86400s erhoeht (L-2)
- Performance: crypto_metrics cache.set mit explizitem TTL 900s (L-1)
- UX: WatchlistTable Notizen-Textarea mit aria-label (F-A11)
- UX: teal-Farbe als "etf" Design-Token in tailwind.config.js registriert (F-A12)
- UX: StockDetail — 3 Panels mit catch { /* ignore */ } zeigen jetzt Fallback-Meldung bei Fehler (K4)
- Docs: CLAUDE.md + README.md — Hilfe-Artikel (31->37), Finanzbegriffe (107->~120) aktualisiert (D-COUNT)

## [0.21.10] — 2026-04-01

### Behoben
- Performance: N+1 MA-Berechnungen in /api/alerts behoben — Broad-ETF-Tickers werden jetzt vorgefiltert, prefetched und in einem Thread berechnet (C-1)
- Performance: N+1 DB-Queries in batch_stop_loss behoben — alle Positionen werden jetzt in einer Query mit IN() geladen (C-2)
- Performance: Portfolio-Summary Cache-TTL von 30s auf 60s erhoeht, passend zum Frontend-Polling-Intervall (M-1)
- Security: Rate Limiter auf 12 fehlenden Auth-Endpoints (logout, MFA, change-password, delete-account, sessions, force-change-password) (AUTH-RL)
- Security: ConfirmRequest in imports.py verwendet jetzt typisierte Pydantic Models statt list[dict] (HIGH-2)
- Security: Worker-Heartbeat von /tmp nach /app/data/ verschoben (MED-4)
- Architecture: _decrypt_field Duplikation in property_service.py entfernt — verwendet jetzt encryption_helpers.decrypt_field (H3)
- UX: Settings-Tabs mit ARIA tablist/tab/aria-selected Pattern (F-A09)
- UX: AlertPopover mit useEscClose und Toast-Fehlermeldungen statt stiller console.error (F-A10)
- Docs: helpContent.js auf 18-Punkte-Scoring aktualisiert (war 21 Punkte) — 6 Stellen korrigiert (D-CRIT)
- Docs: glossary.js — ROE-Duplikat entfernt, Modified Dietz hinzugefuegt, 3 veraltete Eintraege korrigiert (D-GLOSS)

## [0.21.9] — 2026-04-01

### Hinzugefügt
- Tests: test_recalculate_service.py — 19 Tests für gewichteten Durchschnittspreis, realisierte P&L, Teilverkäufe, Fractional Shares, Edge Cases (H5)
- Tests: test_price_service.py — 20 Tests für 4-Layer-Preisauflösung (Cache → DB → Live → Fallback), VIX-Grenzwerte, Crypto/Gold-Preise (H5)
- Tests: test_portfolio_service.py — 31 Tests für MA-Status-Badges, MRS, Market-Value-Berechnung aller Asset-Typen, Allocation-Bucketing (H5)

## [0.21.8] — 2026-04-01

### Behoben
- Security: CSP in nginx verschärft — /api/ und /assets/ Locations haben jetzt restriktive CSPs ohne unsafe-eval/unsafe-inline; root CSP dokumentiert warum TradingView-Widgets unsafe-eval/unsafe-inline erfordern (MED-2)
- Architecture: Settings.jsx von 1231 auf 51 Zeilen aufgeteilt — 6 Tab-Komponenten in eigene Dateien unter pages/settings/ extrahiert (M1)
- Architecture: Verbleibende grosse Dateien (ImportWizard 1190, Transactions 925, ImmobilienWidget 855) als kohäsive Einheiten dokumentiert — kein künstliches Splitting (M1)
- Architecture: Backend-Services über 500 Zeilen geprüft — swissquote_parser, alert_service, macro_indicators_service, cache_service, settings_service sind kohäsive Module ohne sinnvolle Splitpunkte; heilige Dateien nicht betroffen (M2)

## [0.21.7] — 2026-04-01

### Behoben
- Markt & Sektoren: HTTP 500 behoben — fehlender AsyncSession-Import in macro_indicators_service.py

### Hinzugefügt
- Tests: test_sector_mapping.py — 18 Tests für ETF-Whitelist, is_broad_etf(), FINVIZ-Taxonomie-Integrität (H5)
- Tests: test_encryption_helpers.py — 12 Tests für encrypt/decrypt Roundtrip, Legacy-Fallback, IBAN-Maskierung (H5)
- Tests: test_swissquote_parser.py — 30 Tests für CSV-Erkennung, Typ-Mapping, Datum-Parsing, Ticker-Mapping, Teilausführungs-Aggregation (H5)
- Tests: test_stock_scorer.py — 16 Tests für Signal-Bestimmung, Breakout-Trigger, Formatierungs-Helfer (H5)
- Tests: test_scoring_service.py — 5 Tests für assess_ticker Signal-Logik, ETF 200-DMA Override, Cache (H5)

## [0.21.6] — 2026-04-01

### Behoben
- Architecture: settings.py Router von 733 auf 267 Zeilen refactored — Business-Logik und DB-Queries in neuen settings_service.py extrahiert (H4, M4)
- Accessibility: aria-label auf 17 Inputs ohne programmatische Labels in 8 Komponenten (ImportWizard, WatchlistTable, StopLossWizard, EtfSectorPanel, EditPositionModal, Hilfe, Glossar, Transactions) (F-A04)
- Accessibility: text-muted Farbe von #64748b auf #7a8ba3 aufgehellt — Kontrastratio auf bg-card von 3.84:1 auf 5.27:1 verbessert, besteht jetzt WCAG AA fuer kleine Schriftgroessen (F-A07)

## [0.21.5] — 2026-04-01

### Behoben
- Security: forgot-password Rate Limiter von In-Memory TTLCache auf Redis-backed slowapi umgestellt — kein split-brain mehr bei 2 Uvicorn Workers (HIGH-2)
- Security: X-Frame-Options von SAMEORIGIN auf DENY geaendert in allen nginx Location-Blocks (MED-1)
- Security: totp_secret Spaltentyp von String(255) auf Text geaendert — verschluesselte Felder muessen Text sein (MED-3, Alembic Migration 035)
- Architecture: INFLOW_TYPES/OUTFLOW_TYPES nach constants/cashflow.py extrahiert — Code-Duplikation in 3 Services beseitigt (H2)
- Architecture: Worker-Container Health Check hinzugefuegt — Docker erkennt jetzt haengende Worker (MED-6)
- Architecture: PostgreSQL Memory-Limit von 16GB auf 4GB reduziert — passend zu shared_buffers 1GB (M7)
- Quality: request_id in allen HTTPException-Responses — neuer Exception-Handler in main.py (QA-15, M5)
- Accessibility: aria-expanded auf allen Dropdown-Triggern (MoreVertical-Buttons, Filter-Toggle, Kalender) in 9 Dateien (F-A05)
- Accessibility: aria-live Regionen auf LoadingSpinner, CacheStatus, Skeleton, AlertsBanner — Screen-Reader erfahren von Statusaenderungen (F-A03)

## [0.21.4] — 2026-04-01

### Behoben
- Architecture: breakout_alert_service.py erstellt — Worker-Job fuer Watchlist Breakout-Alerts (Donchian 20d + Volumenbestaetigung) funktioniert jetzt korrekt (C1)
- Accessibility: useFocusTrap in alle 15 Modals mit role="dialog" eingebaut — Tab-Fokus bleibt jetzt im Dialog (F-A01, WCAG 2.4.3)
- Accessibility: useScrollLock in alle Modals eingebaut — Hintergrund scrollt nicht mehr bei offenem Dialog (F-A02)
- Accessibility: text-slate-400 durch text-text-secondary ersetzt in 13 Stellen — konsistentes Theming, besserer Kontrast bei kleinen Schriftgroessen (F-A06)
- Security: Unbenutzte ANTHROPIC_API_KEY aus docker-compose.yml entfernt (LOW-1)
- Quality: Silent Exception in stock.py _yf_search() behoben — Logging hinzugefuegt (QA-18)

## [0.21.3] — 2026-04-01

### Behoben
- Security: Per-User-Limits auf allen erstellbaren Entitäten — Edelmetalle (200), Immobilien (20), Hypotheken (10/Immobilie), Ausgaben/Einnahmen (500/Immobilie), Watchlist-Tags (50), Import-Profile (20)
- Quality: 27 ungenutzte Imports entfernt in 17 Dateien (api/ und services/) — kein Dead Code mehr
- Quality: Alle Limits zentralisiert in constants/limits.py

## [0.21.2] — 2026-04-01

### Behoben
- Security: Rate Limiter auf allen POST/PUT/PATCH/DELETE Endpoints (positions, imports, analysis, stock, market) — CRIT-2, CRIT-3
- Security: Rate Limiter auf rechenintensive GET Endpoints (market climate, sectors, scores, stock search/profile/news, analysis MRS/breakouts/levels/reversal/score) — 5-30/min je nach Aufwand
- Security: Pydantic Constraints (ge, gt, le, min_length, max_length) auf allen numerischen und String-Feldern in 10 Routern (positions, transactions, alerts, precious_metals, real_estate, analysis, settings, imports) — CRIT-5
- Quality: Silent Exception Handler behoben — Logging hinzugefügt in encryption_helpers, property_service, price_service (crypto, VIX) — CRIT-6

## [0.21.1] — 2026-04-01

### Behoben
- Security: 11 Backend-CVEs behoben — cryptography 44.0.0 -> 46.0.6, pyjwt 2.9.0 -> 2.12.1, python-multipart 0.0.20 -> 0.0.22, requests 2.32.3 -> 2.32.5, FastAPI 0.115.6 -> 0.121.3 (inkl. starlette 0.50.0)
- Security: 1 Frontend-CVE behoben — picomatch (ReDoS + Method Injection) via npm audit fix

## [0.21.0] — 2026-03-30

### Geändert
- Performance: Market Climate API — 3 sequenzielle API-Calls parallelisiert mit `asyncio.gather()` (K-1)
- Performance: Macro-Gate — Climate-Daten werden einmal geladen und durchgereicht statt 3× redundant (K-2)
- Performance: Precious-Metals-Endpoint — 3 sequenzielle Calls parallelisiert (H-9)
- Performance: Crypto-Metrics-Endpoint — 4 API-Calls (CoinGecko, Fear&Greed, DXY, BTC ATH) parallelisiert (M-10)
- Performance: Price-Service — Event-Loop-Schutz verhindert blockierende yfinance/httpx-Calls im API-Request (K-4, H-5)
- Performance: In-Memory Cache von 1'000 auf 2'500 Einträge erhöht (M-1)
- Performance: nginx gzip-Kompression für SVG und Webfonts aktiviert (N-2)
- Performance: `fetch_all_indicators()` — 7 FRED/VIX-Calls parallel mit ThreadPoolExecutor, API-Key einmal geladen (H-2, M-4)
- Performance: `fetch_extra_indicators()` — 5 Calls (WTI, Brent, Fed Rate, USD/CHF) parallelisiert (H-3)
- Performance: `score_stock()` — `yf.Ticker().info` wird mit 24h TTL gecacht statt bei jedem Call neu geladen (K-3)
- Performance: `get_total_return()` akzeptiert vorgeladene Summary, vermeidet redundante Neuberechnung (H-4)
- Performance: Daily-Change — FX-Rates in einem Batch-Query geladen statt N+1 (M-8)
- Performance: StockDetail — Portfolio-Summary aus DataContext statt 2× separater API-Call, Score-Daten einmal geladen und geteilt (H-6)
- Performance: Portfolio-Seite — Waterfall-Loading: abhängige Endpoints erst nach Summary laden (H-7)
- Performance: DataContext STALE_MS von 60s auf 55s reduziert, verhindert Timing-Drift (N-1)
- Performance: `prefetch_close_series()` — nur noch 2y-Download, 1y wird aus letzten 252 Tagen abgeleitet (M-2)
- Performance: `calculate_xirr_for_period()` akzeptiert vorgeladene Snapshots/Transaktionen (M-3)
- Performance: Neuer `get_cached_prices_batch_sync()` — eine DB-Session für mehrere Ticker statt N einzelne (M-5)
- Performance: Watchlist PriceCache-Query auf letzte 7 Tage beschränkt statt alle historischen Daten (M-7)

## [0.20.1] — 2026-03-28

### Hinzugefügt
- MIT LICENSE-Datei im Repository-Root
- Datenschutzerklärung: TradingView, Gold.org, multpl.com als externe Dienste ergänzt
- Datenschutzerklärung: Differenzierte Rechtsgrundlagen pro Verarbeitungszweck (Art. 6 DSGVO)
- Datenschutzerklärung: Kontaktadresse für Datenschutzanfragen
- TradingView-Hinweis: IP-Übermittlung und DSGVO-Drittlandtransfer dokumentiert
- Yahoo Finance-Hinweis: yfinance-Verfügbarkeit nicht garantiert

### Behoben
- Impressum: Platzhalter durch echte Betreiberdaten ersetzt (Imprint.jsx + Legal.jsx)
- Signal-Sprache: "Verkaufen!" → "Verkaufskriterien erreicht" in alert_service.py
- Signal-Sprache: "kaufe nicht", "Dann kaufe" → neutrale Formulierungen in helpContent.js
- Signal-Sprache: "Kaufsignal"/"Verkaufssignal" → "Kaufkriterien erfüllt"/"Verkaufskriterien erreicht" in glossary.js
- Hilfe-Texte: Makro-Gate korrekt als "informativer Indikator" beschrieben (war fälschlich als "Blocker" dokumentiert)
- AGB: Änderungsklausel differenziert (wesentliche Änderungen → erneute Zustimmung)
- AGB: Hinweis "sollte von Anwalt geprüft werden" entfernt

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
