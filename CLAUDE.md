# OpenFolio

Open Source Portfolio Manager für systematisches Investieren mit regelbasierter Marktanalyse.

## Tech Stack

- **Backend**: Python 3.12, FastAPI (async, 2 Uvicorn Workers + uvloop), SQLAlchemy 2.0 (asyncpg), Alembic
- **Worker**: Separater Background-Prozess (APScheduler) für Kurs-Refresh (60s intraday), Snapshots, Alerts, Earnings
- **Frontend**: React 18, Vite, Tailwind CSS (Dark Theme), Recharts, React Router v6, Lucide Icons
- **Datenbank**: PostgreSQL 16 (shared_buffers 4GB, work_mem 64MB, max_connections 200)
- **Cache**: Redis 7 (shared zwischen API-Workers und Background-Worker, 512MB, allkeys-lru)
- **Infra**: Docker Compose (7 Container: db, redis, backend, worker, frontend via nginx, uptime-kuma + optional monitoring)
- **Monitoring**: Prometheus (Metriken), Grafana + Loki (Dashboards + Logs), Uptime Kuma (Uptime-Checks)
- **Externe APIs**: yfinance, CoinGecko, FRED API, FMP API (Free Tier), Gold.org, multpl.com (Shiller PE)

## Befehle

### Docker (Production)
```bash
./init.sh                       # Erstmalige Einrichtung (generiert .env, erstellt Admin)
docker compose up -d --build    # Starten (db, redis, backend, worker, frontend, uptime-kuma)
docker compose logs -f backend  # Backend-Logs (JSON-Format)
docker compose logs -f worker   # Worker-Logs (Refresh, Snapshots, Alerts)
docker compose exec backend alembic upgrade head  # Migrationen
docker compose exec db pg_dump -U finance finance > backup.sql  # Backup
```

### Monitoring (optional)
```bash
docker compose -f docker-compose.monitoring.yml up -d  # Prometheus + Grafana + Loki
```

Frontend: http://localhost:5173 (nginx) | Backend: http://localhost:8000 | API Docs: http://localhost:8000/docs
Uptime Kuma: http://localhost:3001 | Grafana: http://localhost:3000 | Metrics: http://localhost:8000/metrics

### Backend lokal
```bash
cd backend
pip install -r requirements.txt
python seed.py          # Datenbank initialisieren + Admin erstellen
uvicorn main:app --reload
```

### Frontend lokal
```bash
cd frontend
npm install
npm run dev             # Dev-Server auf :5173
npm run build           # Production Build → dist/
```

### Tests
```bash
cd backend
pytest tests/ -v --cov=. --cov-report=term-missing
```

### Alembic
```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1    # Letzte Migration rückgängig
```

## Reports & Analysen

- **Diagnose-Reports, Architektur-Reviews, Audit-Ergebnisse** immer als separate `.md` Datei im Projektroot erstellen (z.B. `TTWROR_DIAGNOSE.md`, `ARCHITECTURE_REVIEW.md`), NICHT nur im Chat ausgeben.
- Reports sollen eigenständig lesbar sein (mit Kontext, Daten, Empfehlungen).
- Nach Erstellung: Report-Datei committen (Conventional Commit: `docs: add ...`).

## Git Konventionen

- **Conventional Commits**: feat:, fix:, refactor:, docs:, chore:, perf:
- **Sprache**: Dokumentation + UI auf Deutsch, Code auf Englisch
- **Error Messages**: User-facing HTTPException-Details auf Deutsch, Log-Messages auf Englisch
- **Type Hints**: Alle öffentlichen Service-Funktionen haben Type Annotations (Python 3.10+ Syntax)
- **Branch**: main (production)

## Architektur

```
backend/
  api/              # FastAPI Router (aufgeteilt nach Domäne)
    auth.py         # Register, Login, MFA, Password Reset, Sessions
    portfolio.py    # Portfolio Summary (Haupt-Endpoint)
    positions.py    # Position CRUD, Typ-Zuweisung, Recalculate
    performance.py  # History, Monatsrenditen, XIRR, Allocation, Earnings
    stoploss.py     # Stop-Loss Verwaltung (Status, Update, Batch)
    market.py       # Marktklima, Sektor-Rotation, Macro-Indikatoren
    analysis.py     # Watchlist, Scoring, Resistance, MRS-History, Breakouts, Levels
    transactions.py # CRUD, Suche, Filter, Auto-Create Position bei neuem Ticker
    imports.py      # CSV/PDF Import (Swissquote, Relai, Custom Profile)
    stock.py        # Stock Detail, Fundamentals, Key-Metrics, News, Ticker-Suche (Autocomplete)
    settings.py     # User Settings, SMTP, API Keys
    etf_sectors.py  # ETF Sektorverteilung
    admin.py        # User-Verwaltung, Invite Codes, Registration Mode
    alerts.py       # Portfolio Alerts, Price Alerts
    precious_metals.py  # Edelmetall CRUD (Gold, Silber, Platin, Palladium), Position-Sync
    private_equity.py   # Direktbeteiligungen CRUD (Holdings, Bewertungen, Dividenden), Position-Sync
    real_estate.py      # Immobilien CRUD, Hypotheken, Ausgaben/Einnahmen
    taxonomy.py         # Sektor/Industry-Taxonomie (FINVIZ) für Frontend
  services/         # Business Logic
    auth_service.py         # JWT, bcrypt, Fernet Encryption, TOTP
    portfolio_service.py    # Portfolio Summary, Allocations (NICHT ÄNDERN ohne Freigabe)
    recalculate_service.py  # Position Recalculation (NICHT ÄNDERN ohne Freigabe)
    price_service.py        # Kursabfragen: yfinance, CoinGecko, Gold.org (NICHT ÄNDERN ohne Freigabe)
    scoring_service.py      # 21-Punkte Setup Score (ohne Makro-Gate)
    stock_scorer.py         # Technische + Fundamentale Kriterien
    market_analyzer.py      # S&P 500 Analyse, Technische Indikatoren
    sector_analyzer.py      # SPDR ETF Sektor-Rotation (mit Einzel-Ticker Retry)
    macro_indicators_service.py  # FRED API, Shiller PE, Credit Spread, Crash-Indikatoren
    macro_gate_service.py   # Makro-Gate Berechnung (7 gewichtete Checks)
    cache_service.py        # Preis-Cache Refresh, Batch Downloads
    cache.py                # Redis-backed Cache mit In-Memory Fallback
    fundamental_service.py  # Fundamental-Kennzahlen aus yfinance (Revenue, Margins, D/E, PE, FCF, ROIC, EPS, EPS Growth)
    industry_averages.py    # Statische Branchendurchschnitte (~80 Industries + 11 Sektoren)
    chart_service.py        # MRS-History, Donchian Breakout-Detection, Support/Resistance Levels
    performance_history_service.py # Modified Dietz Monatsrenditen, XIRR Jahresrenditen
    performance_service.py  # Performance Waterfall, TWR, IRR
    history_service.py      # Portfolio-Wert-Rekonstruktion, Benchmark-Vergleich
    snapshot_service.py     # Tägliche Portfolio-Snapshots (parallelisiert, Batch-Upsert, Redis-Preise)
    snapshot_trigger.py     # Auto-Regenerierung bei historischen Positionen/Transaktionen (Background)
    total_return_service.py # Gesamtrendite (XIRR), YTD, Realisierte Gewinne
    import_service.py       # CSV Import-Wizard (Column-Mapping, Profile)
    swissquote_parser.py    # Swissquote CSV/PDF Parser (Latin-1, Teilausführungen, ISIN-Mapping)
    ibkr_parser.py          # Interactive Brokers Flex Query CSV Parser (22 Börsen-Mappings)
    pocket_parser.py        # Pocket (pocketbitcoin.com) CSV Parser (BTC-Käufe, CHF)
    transaction_service.py  # Transaktionseffekte auf Position (Buy/Sell/Dividend)
    stock_service.py        # Company Profile, Fundamentaldaten (yfinance + FMP API)
    dividend_service.py     # Dividenden-Historie, erwartete CHF-Ausschüttungen
    earnings_service.py     # Nächstes Earnings-Datum (yfinance, gecacht)
    alert_service.py        # Portfolio-Alert-Generierung (Stop-Loss, Limits, Verluste)
    price_alert_service.py  # Preis-Alarm-Checks + E-Mail-Benachrichtigung
    breakout_alert_service.py   # Watchlist Breakout-Alerts (Donchian 20d) + E-Mail
    benchmark_service.py        # Benchmark-Index Monatsrenditen (S&P 500, 5J, 24h Cache)
    etf_200dma_alert_service.py # ETF 200-DMA Kaufsignal-Alerts + E-Mail (Worker-Job 22:35 CET)
    private_equity_service.py   # Direktbeteiligungen: CRUD, Summary, Position-Sync, Verschlüsselung
    property_service.py     # Immobilien-Logik: Summary, Hypotheken-Amortisation, Detail, SARON-Zinsberechnung
    user_service.py         # User-Löschung (CASCADE über alle User-Tabellen)
    audit_service.py        # Admin Audit-Log (log_admin_action)
    sector_mapping.py       # FINVIZ Industry→Sector Mapping (~160 Industries), ETF 200-DMA Whitelist (27 Ticker), is_broad_etf()
    email_service.py        # SMTP (aiosmtplib), Alert-E-Mails
    api_utils.py            # httpx + tenacity Retry-Wrapper
  middleware/       # FastAPI Middleware
    metrics.py      # Prometheus Metriken (Request Count, Latency, Active Requests)
  models/           # SQLAlchemy Models
    position.py             # Positionen (Aktien, ETFs, Crypto, Commodities, Cash, Vorsorge, Private Equity)
    transaction.py          # Buy/Sell/Dividend/Fee Transaktionen
    precious_metal_item.py  # Physische Edelmetalle (Typ, Form, Gewicht, Seriennummer)
    private_equity.py       # Direktbeteiligungen (Holdings, Valuations, Dividends)
    property.py             # Immobilien, Hypotheken, Ausgaben, Einnahmen
    user.py                 # User, RefreshToken, UserSettings
    portfolio_snapshot.py   # Tägliche Portfolio-Snapshots
    price_cache.py          # OHLCV Preis-Cache
    price_alert.py          # Preis-Alarme
    watchlist.py            # Watchlist-Einträge
    watchlist_tag.py        # Watchlist-Tags (farbig, many-to-many)
    alert_preference.py     # Alert-Benachrichtigungspräferenzen
    etf_sector_weight.py    # ETF Sektor-Gewichtungen
    fx_transaction.py       # Forex-Transaktionen (Broker-Import)
    import_profile.py       # CSV Import-Profile
    macro_indicator_cache.py # Makro-Indikator-Cache
    app_config.py           # Globale Key-Value Config (shared zwischen Containern)
    app_setting.py          # App-Einstellungen, Invite Codes
    smtp_config.py          # SMTP-Konfiguration (verschlüsselt)
    admin_audit_log.py      # Admin Audit-Log Einträge
    backup_code.py          # MFA Backup-Codes (bcrypt-gehasht)
    password_reset_token.py # Passwort-Reset Tokens
  constants/        # sectors.py (FINVIZ Industry→Sector Mapping)
  tests/            # pytest Test Suite
  worker.py         # Background Worker (APScheduler, Kurs-Refresh, Snapshots, Alerts, ETF 200-DMA Alerts 22:35 CET)
  logging_config.py # Structured JSON Logging Konfiguration
frontend/
  src/
    components/     # React Components (inkl. CommandPalette, StockHeatmap, GlossarTooltip, OnboardingTour, OnboardingChecklist, DisclaimerBanner)
    contexts/       # React Contexts (AuthContext, DataContext)
    pages/          # Route Pages (lazy-loaded via React.lazy, inkl. Hilfe, Legal, Disclaimer, Terms, Imprint)
    hooks/          # Custom Hooks (useApi, useEscClose, useOnlineStatus, useFocusTrap)
    data/           # Statische Daten (glossary.js — 107 Finanzbegriffe, helpContent.js — 31 Hilfe-Artikel)
    lib/            # Utilities (format.js — Zahlen, Datum, Währung; tradingview.js — Symbol-Mapping yfinance→TradingView)
monitoring/         # Monitoring Konfiguration
  prometheus.yml    # Prometheus Scrape Config
  loki/             # Loki Log-Aggregation Config
  grafana/          # Grafana Datasources + Alerting Provisioning
```

## Authentifizierung

- **JWT**: Access Token (15 Min) + Refresh Token (30 Tage, Rotation)
- **MFA**: TOTP + Backup-Codes (bcrypt-gehasht in DB). Pflicht für Admins, optional für normale User (Onboarding-Checkliste)
- **Passwort**: bcrypt (Cost 12), Min 12 / Max 128 Zeichen, Gross+Klein+Zahl+Sonderzeichen Pflicht, Common-Password-Blacklist
- **Rate Limiting**: slowapi auf Login (10/15min/IP), Register (5/h/IP), Redis-backed (distributed)
- **Verschlüsselung**: Fernet (AES-256) für API Keys, SMTP Passwort, TOTP Secrets, PII (IBAN, Bankname, Seriennummer, Lagerort, Notizen, Immobilien-Name/Adresse) — verschlüsselte Felder immer `Text` (nie `String(N)`)
- **Admin**: `is_admin` Flag, erster User via init.sh
- **Registrierung**: Modes: open / invite_only / disabled

## Scoring-System

### Makro-Gate (7 gewichtete Checks, max 9 Punkte — NUR informativ auf Markt & Sektoren)
| Check | Gewicht |
|---|---|
| S&P 500 über 150-DMA | 2 |
| S&P 500 HH/HL | 1 |
| VIX unter 20 | 2 |
| Sektor stark (1M > 0%) | 1 |
| Shiller PE unter 30 | 1 |
| Buffett Indicator unter 150% | 1 |
| Zinsstruktur nicht invertiert | 1 |

Wird auf der Markt & Sektoren Seite angezeigt. Beeinflusst NICHT die Einzelaktien-Signale.

### Setup-Score (22 Kriterien)
- Moving Averages (7): Preis > MA50/150/200, MA50 > MA150/200, MA150 > MA200, MA200 steigend
- Breakout (5, Donchian Channel): 20d-Hoch Breakout (2×), Volumen ≥1.5× Avg, über 150-DMA, max 25% unter 52W-Hoch, ≥30% über 52W-Tief
- Relative Stärke (3): MRS > 0, MRS > 0.5 (stark), MRS > 1.0 (Sektor-Leader)
- Volumen & Liquidität (2): MCap > 2 Mrd, Avg Volume > 200k
- Fundamentals (4): Umsatz wächst (YoY), EPS wächst, ROE > 15%, D/E unter Branchenvergleich (Industry Avg)
- Trendwende (1): 3-Punkt-Umkehr erkannt (nur relevant unter 150-DMA — drei tiefere Tiefs + höheres Tief)

Qualität: ≥70% STARK, 45-69% MODERAT, <45% SCHWACH

### Signal-Logik (vereinfacht — ohne Makro-Gate)

Das Makro-Gate beeinflusst NICHT mehr die Einzelaktien-Signale. Es wird weiterhin auf der Markt & Sektoren Seite als informativer Indikator angezeigt.

| Setup | Breakout | Signal |
|---|---|---|
| STARK (≥70%) | ✅ | KAUFKRITERIEN ERFÜLLT |
| STARK | ❌ | BEOBACHTUNGSLISTE |
| MODERAT (45-69%) | — | BEOBACHTEN |
| SCHWACH (<45%) | — | KEIN SETUP |

### ETF 200-DMA Kaufsignal
Broad Index-ETFs auf der Whitelist (27 Ticker: VOO, VTI, SPY, QQQ, ACWI, VWRL, SWDA, CHSPI, etc.):
- Unter 200-DMA = ETF_KAUFSIGNAL — unabhängig von allen anderen Kriterien
- Über 200-DMA = normale Signal-Logik
- Matching auf Basis-Ticker (VWRL.SW → VWRL → Match)
- TradingView-Symbol-Mapping: VWRL.SW → SIX:VWRL

## Core/Satellite-System

- **Core**: Langfristig, Quality, quartalsweises Review. Stop-Loss optional (entfernbar). Verkauf nur bei fundamentalem Bruch (These gebrochen, Moat zerstört, FCF sinkt).
- **Satellite**: Taktisch, Breakout, enger Stop (5-12%), wöchentliches Review. Technischer Stop-Loss ist Pflicht (nicht entfernbar).
- Ziel: 70% Core / 30% Satellite
- Jede Position braucht `position_type`: core oder satellite

## HEILIGE Regeln (NIEMALS brechen)

1. **Performance-Berechnung NICHT ändern** ohne explizite Freigabe vom Maintainer
   - Betrifft: portfolio_service.py, recalculate_service.py, price_service.py, utils.py
   - cost_basis_chf = historischer CHF-Wert zum Kaufzeitpunkt (inkl. Gebühren)
   - value_chf = shares × current_price × fx_rate
   - perf_pct = ((value_chf / cost_basis_chf) - 1) × 100

2. **MRS-Berechnung**: EMA(13) auf Weekly-Daten, Benchmark ^GSPC — nicht ändern

3. **Breakout-Logik**: Donchian Channel 20d — current_price > 20-Tage-Hoch (KEINE Toleranz, strict >), Volumen ≥ 1.5× 20d-Avg

4. **Immobilien** NICHT in liquide Performance einrechnen

5. **Vorsorge** NICHT in liquides Vermögen einrechnen

6b. **Private Equity / Direktbeteiligungen** NICHT in liquide Performance einrechnen
   - Komplett aus Snapshots, History, Daily Change, XIRR, Monatsrenditen ausgeschlossen
   - Erscheint nur im Gesamtvermögen (via Position-Sync mit `AssetType.private_equity`, `PricingMode.manual`)
   - `current_price` = NULL wenn keine Valuation hinterlegt, sonst `gross_value_per_share`
   - Keine Transaktionen (Wert wird via `sync_position()` aus Valuations berechnet)

6. **yfinance**: Thread-safe Wrapper verwenden (`yf_download()` in cache_service.py)
   - Jeder Call über `asyncio.to_thread(yf_download, ...)`
   - NIEMALS direkt `yf.download()` in async Context
   - Kurs-Refresh läuft NUR im Worker-Container (alle 60s intraday), NIE in API-Requests

7. **Alle HTTP-Calls**: httpx.AsyncClient (nicht requests)

8. **Alle SMTP**: aiosmtplib (nicht smtplib)

9. **Schwur 1 (150-DMA) — differenziert nach Positions-Typ**:
   - **Satellite**: Harter Verkaufstrigger. Unter 150-DMA = sofort verkaufen.
   - **Core**: Beobachtung. Unter 150-DMA = Fundamental-Check (These noch intakt?), kein automatischer Verkauf.
   - **ETF (Broad Index)**: Unter 200-DMA = Kaufsignal (überstimmt Makro-Gate).

## SARON-Hypothek

- **Marge** (`margin_rate`): Fix, von der Bank festgelegt (z.B. 0.78%)
- **SARON-Leitzins**: Variabel, automatisch von SNB geholt (Worker-Refresh)
- **Effektiver Zinssatz** = `max(margin_rate, margin_rate + saron_rate)` — Floor auf Marge
- `calculate_effective_rate(mortgage, saron_rate)` in `property_service.py` — zentrale Berechnung
- Bei SARON mit `margin_rate`: `interest_rate` speichert den zuletzt berechneten effektiven Zins (Cache/Display)
- Bei SARON ohne `margin_rate` (Legacy): Fallback auf `interest_rate`
- Bei Fest/Variable: `interest_rate` direkt, `margin_rate` ist NULL
- Frontend: Formular zeigt "Marge %" bei SARON, "Zinssatz %" bei Fest/Variable

## Private Equity / Direktbeteiligungen

- **Drei Tabellen:** `private_equity_holdings` (Beteiligung), `private_equity_valuations` (jährliche Steuerwert-Bewertung), `private_equity_dividends` (Dividendenhistorie)
- **PII verschlüsselt:** `company_name`, `uid_number`, `register_nr`, `notes` (Fernet AES-256)
- **Position-Sync:** Jede Holding erstellt eine synthetische Position (`AssetType.private_equity`, `PricingMode.manual`, Ticker `PE_{id[:8]}`)
- **current_price:** Neuester `gross_value_per_share` aus Valuations, NULL wenn keine Valuation existiert
- **cost_basis:** `purchase_price_per_share × num_shares` (oder `nominal_value` als Fallback)
- **Netto-Steuerwert:** `gross_value × (1 - discount_pct/100)` — Pauschalabzug für Minderheitsbeteiligte (Default 30%)
- **Dividenden:** Auto-Berechnung: `gross = dps × num_shares`, `wht = gross × wht_pct/100`, `net = gross - wht`
- **Performance-Ausschluss:** Komplett aus Snapshots, History, Daily Change, XIRR, Monatsrenditen, total_return_service ausgeschlossen
- **Sektor-Chart:** Eigene Kategorie "Private Equity" (in `TYPE_TO_SECTOR`, nicht in `SECTOR_EXCLUDED_TYPES`)
- **Liquid/Total Toggle:** PE in `ILLIQUID_TYPES` — ausgeblendet in liquider Ansicht
- **API:** 12 Endpoints unter `/api/private-equity` (Holdings CRUD + Valuations CRUD + Dividends CRUD)
- **Per-User Limits:** 20 Holdings, 50 Valuations/Holding, 50 Dividenden/Holding

## ETF 200-DMA Alert

- **Alert-Kategorie:** `etf_200dma_buy` — "ETF unter 200-DMA (Kaufkriterien)"
- **Whitelist:** 27 Broad-Index-ETFs in `sector_mapping.ETF_200DMA_WHITELIST`, gemeinsam mit `scoring_service.py`
- **Prüfung:** Positionen + Watchlist, `is_broad_etf(ticker)` + `ma_detail.above_ma200 == False`
- **Severity:** `positive` (grün, TrendingUp-Icon) — nicht warning/danger
- **E-Mail:** Worker-Job täglich 22:35 CET, 24h Deduplizierung via Cache-Key
- **Signal-Sprache:** "Kaufkriterien gemäss Strategie erfüllt" (nicht "Kaufsignal")

## TradingView Symbol-Mapping

- **Shared Utility:** `frontend/src/lib/tradingview.js` — `toTradingViewSymbol(yfinanceTicker)`
- **Mapping:** `.SW`→`SIX:`, `.L`→`LSE:`, `.DE`→`XETR:`, `.PA`→`EPA:`, `.AS`→`AMS:`, `.MI`→`MIL:`, `.TO`→`TSX:`, `.V`→`TSXV:`, `.HK`→`HKEX:`, `.T`→`TSE:`, `.AX`→`ASX:`
- **Verwendet in:** `TradingViewChart.jsx` (Hauptchart), `MiniChartTooltip.jsx` (Hover-Preview)
- **Fallback:** Wenn TradingView kein Chart liefert → "Chart nicht verfügbar" mit Link zu TradingView

## Benchmark-Vergleich (Monatsrenditen-Heatmap)

- **Service:** `benchmark_service.py` — berechnet Monatsrenditen aus yfinance-Kursdaten (5 Jahre)
- **Endpoint:** `GET /api/portfolio/benchmark-returns?ticker=^GSPC`
- **Default:** S&P 500 (^GSPC), vorbereitet für weitere Indizes (^IXIC, ^STOXX50E, ^SSMI)
- **Berechnung:** Einfache Monatsrendite `(close_end / close_start - 1) × 100`, Jahres-Total = kompoundierte Monatsrenditen
- **Cache:** Redis 24h (`benchmark_monthly:{ticker}`)
- **Frontend:** Muted Zeile unter jeder Jahreszeile in der Heatmap, neutraler grauer Hintergrund (nicht grün/rot wie Portfolio-Zeilen) — Farbe = Portfolio, Grau = Benchmark

## Fundamental-Kennzahlen (Detailseite)

- **Service:** `fundamental_service.py` — 11 Karten auf der Aktien-Detailseite
- **Karten:** Revenue, Gross Margin, D/E, Dividende, Net Margin, FCF, PE Ratio, Market Cap, ROIC, EPS (TTM), EPS Growth
- **ROIC Fallback-Kette:** `returnOnCapital` → `returnOnInvestedCapital` → `operatingIncome / (equity + longTermDebt)` → `returnOnEquity` (Label wechselt zu "ROE")
- **Branchenvergleich:** ~160 Industries + 11 Sektoren in `industry_averages.py` (D/E, Margins, PE, ROE)
- **Cache:** Redis 24h (`key_metrics:{ticker}`)

## Entwicklungsstandards (aus Pre-Release Audit)

Diese Standards gelten für JEDE Code-Änderung. Sie basieren auf dem 5-Phasen Security/Performance/Quality/UX/Architecture Audit vom 20.03.2026.

### Security
- **Kein Endpoint ohne Auth**: Jeder neue Endpoint braucht `Depends(get_current_user)` oder explizit dokumentierte Begründung warum nicht
- **Rate Limiting**: Jeder neue POST/PUT/PATCH/DELETE Endpoint braucht `@limiter.limit()` — Login-artige: 10/15min, CRUD: 30/min, Reads: 60/min
- **IDOR-Schutz**: JEDE DB-Query die User-Daten liest/schreibt MUSS `user_id == current_user.id` filtern — keine Ausnahmen
- **Input-Validierung**: Pydantic Models mit Constraints (`ge=0`, `gt=0`, `max_length`) auf ALLEN numerischen und String-Feldern
- **Secrets**: Nie hardcoden. Fernet für API-Keys, SMTP, TOTP, IBAN. Environment-Variablen für alles andere.
- **Keine `requests` Library**: Alle HTTP-Calls über `httpx.AsyncClient` (Projekt-Regel). Falls sync nötig: `httpx` sync Client, nicht `requests`.
- **Temp-Dateien**: Nie in `/tmp` — eigenes Verzeichnis unter `/app/data/` mit 0o700 Permissions
- **CORS**: Nur explizit benötigte Methods und Headers erlauben, nie `["*"]`
- **Per-User-Limits**: Neue erstellbare Entitäten (Alerts, Watchlist, etc.) brauchen ein per-User Maximum

### Datenschutz
- **PII immer verschlüsseln**: Neue Felder die persönliche Daten enthalten (Bankverbindungen, Adressen, Seriennummern, Notizen, Kontaktdaten) MÜSSEN mit Fernet (AES-256) verschlüsselt gespeichert werden. Nur Felder die der Background Worker für Berechnungen braucht (Ticker, Shares, Preise, Transaktionen) dürfen Klartext sein.
- **Admin darf keine User-Daten sehen**: Neue Admin-Endpunkte oder -Ansichten dürfen KEINE Portfolio-Daten, Kontostände, Transaktionen, Notizen oder andere persönliche Finanzdaten exponieren. Nur Verwaltungsdaten (E-Mail, Status, MFA, Anzahl Positionen).
- **Audit-Log**: Jede neue Admin-Aktion muss im Audit-Log protokolliert werden (`log_admin_action()`).
- **Keine Telemetrie, kein Tracking**: Keine Analytics, keine Nutzungsdaten, keine externen Tracking-Scripts. OpenFolio sendet nur Ticker-Symbole an externe APIs — niemals persönliche Daten.
- **Datenschutzseite aktuell halten**: Bei JEDER Änderung die beeinflusst welche Daten gespeichert, übertragen oder verarbeitet werden, MUSS die Datenschutzseite (`/datenschutz`) geprüft und ggf. angepasst werden.
- **Datenminimierung**: Nur Daten speichern die für die Funktionalität nötig sind. Keine "nice-to-have" Datensammlung.
- **Löschung**: Alle neuen User-Daten müssen bei Account-Löschung mitgelöscht werden (CASCADE DELETE oder explizite Lösch-Logik).

### Performance
- **Kein N+1**: Nie in einer Schleife einzelne DB-Queries ausführen. Immer Batch-Load, dann in-memory verarbeiten.
- **Cache-First**: Häufig abgerufene Daten (Preise, FX-Rates, Scores) immer über `cache.py` (Redis → In-Memory Fallback). Neue Cache-Keys mit sinnvollem TTL.
- **Cache-Invalidierung**: Jeder Write-Endpoint der Portfolio-Daten ändert MUSS `invalidate_portfolio_cache(user_id)` aus `api.portfolio` aufrufen. Betrifft: positions, transactions, imports, precious_metals, stoploss. Ohne Invalidierung sehen User bis zu 30s veraltete Daten.
- **yfinance Thread-Safety**: NUR über `yf_download()` Wrapper via `asyncio.to_thread()`. NIEMALS direkt `yf.download()` in async Context. KEINE `httpx.Client` Session an `yf.Ticker()` übergeben (inkompatibel mit yfinance `proxies` kwarg).
- **Edelmetall-Positionen**: Shares werden NUR über `_sync_position()` aus `precious_metal_items` berechnet. `recalculate_service.py` überspringt `AssetType.commodity` Positionen (keine Transaktionen). Worker schreibt `current_price` für `gold_org=true` Positionen.
- **Import: Auto-Enrichment**: Nach Import werden FX-Kurse (historisch via yfinance Batch) und Industry/Sector (via yfinance `.info` + FINVIZ Mapping) automatisch gesetzt.
- **Kurs-Refresh nur zu Marktzeiten**: Worker prüft `is_extended_hours()` bevor Refresh läuft
- **Batch-INSERTs**: Bei mehr als 10 Rows immer Bulk-Insert (`pg_insert().values(list)`) statt Loop
- **Connection Pool**: Async 20+20, Sync 5+10. Nicht erhöhen ohne Grund.
- **Frontend-Polling**: DataContext pollt alle 60s, nicht häufiger. Für Echtzeit: Server-Sent Events evaluieren.

### Code Quality
- **Keine Silent Exceptions**: Jeder `except Exception` Block MUSS mindestens `logger.warning("...", exc_info=True)` enthalten. Kein `pass`, kein stilles `return None`.
- **Error Messages auf Deutsch**: Alle User-facing `HTTPException(detail="...")` auf Deutsch. Log Messages bleiben Englisch.
- **Type Hints**: Alle öffentlichen Service-Funktionen brauchen vollständige Typ-Annotationen (Parameter + Return Type)
- **Pydantic für alle Inputs**: Kein `dict` als Request Body. Immer ein typisiertes Pydantic Model mit Validierungs-Constraints.
- **Consistent Error Format**: `{"detail": "Fehlermeldung", "request_id": "..."}` — nie nur ein String
- **HTTP Status Codes**: 400 für Client-Fehler, 404 für nicht gefunden, 422 für Validation, 502 für Upstream-Fehler (yfinance, CoinGecko). Nicht alles als 400 zurückgeben.
- **Kein Dead Code**: Keine auskommentierten Blöcke, keine ungenutzten Imports, keine TODO-Kommentare ohne Ticket/Issue

### UX / Accessibility
- **Jedes `<input>` braucht ein Label**: `htmlFor` + `id` Verknüpfung. Placeholder-only Inputs brauchen `aria-label` oder `sr-only` Label.
- **Modals**: `role="dialog"`, `aria-modal="true"`, `aria-label`, Focus Trapping (useFocusTrap), Escape zum Schliessen (useEscClose), Scroll Lock (useScrollLock)
- **Dropdowns in overflow-Containern**: React Portal (`createPortal`) verwenden statt `position: absolute`. Beispiel: Admin UserActions (`PortalDropdown`), GlossarTooltip.
- **Onboarding Tour**: Spotlight via einzelnem `box-shadow` Layer (opacity 0.35, NICHT doppelt). Tooltip-Position wird nach Render gemessen und an Viewport-Grenzen geclampt (16px Abstand).
- **Dynamischer Content**: Toast/Notifications brauchen `aria-live="polite"`. Validation Errors brauchen `role="alert"`.
- **Responsive**: Jede neue Tabelle/Komponente muss auf Mobile (< 768px) funktionieren. Weniger wichtige Spalten mit `hidden md:table-cell` ausblenden.
- **Mindest-Fontgrösse**: 12px für alle wichtigen Informationen. 10-11px nur für sekundäre Metadaten.
- **Farbkontraste**: Muted Text (`text-muted`) nie unter 12px. Für kleine Texte `text-secondary` verwenden.
- **Loading States**: Jede neue Seite/Komponente braucht einen Skeleton-Loader oder Spinner während Daten laden. Nie einen falschen Zwischenwert als Fallback zeigen.
- **Lazy-Loading**: Jede `React.lazy()` Route MUSS in `<Suspense fallback={...}>` gewrapped sein. Ohne Suspense crasht die App bei Client-Side-Navigation. ErrorBoundary fängt stale Chunk-Fehler (nach Deployment) und reloaded automatisch.
- **Empty States**: Jede neue Liste/Tabelle braucht eine "Noch keine Einträge"-Meldung.
- **Keyboard Navigation**: Alle interaktiven Elemente per Tab erreichbar. Context-Menus auch per Enter/Space öffenbar.
- **GlossarTooltip**: Neue Fachbegriffe in der UI mit `<GlossarTooltip>` wrappen und in `glossary.js` eintragen.

### Architecture
- **Business Logic in Services**: API-Router nehmen Request entgegen, rufen Service auf, geben Response zurück. Keine DB-Queries oder Berechnungen direkt im Router (max 5 Zeilen Logik).
- **Ein Router pro Domäne**: positions.py, performance.py, stoploss.py etc. Kein 900-Zeilen God-Router.
- **URL-Konsistenz**: Alle position-bezogenen Endpoints nutzen UUID (`{position_id}`), nicht Ticker. Ticker nur als Query-Parameter oder im Request Body.
- **Docker**: Multi-Stage Builds, Non-Root User, Health Checks auf allen Services, Resource Limits
- **nginx**: Alle Security Headers in JEDEM Location-Block (nginx vererbt `add_header` nicht). CSP Header pflegen wenn neue externe Domains eingebunden werden.
- **Shared Docker Image**: Worker nutzt dasselbe Image wie Backend, nicht separat bauen.
- **Alembic-Migration**: Jede Schema-Änderung über Alembic. Nie manuell in der DB.
- **Renditeberechnung**: Monatlich = Modified Dietz, Jahres/YTD-Total = XIRR (MWR). Nie geometrische Verkettung von Tagesrenditen für Jahreswerte.
- **.gitignore**: Verzeichnis-Regeln immer mit `/` prefixen (z.B. `/data/` statt `data/`), damit nur das Root-Verzeichnis ignoriert wird — sonst werden gleichnamige Unterverzeichnisse wie `frontend/src/data/` versehentlich ausgeschlossen.

### Checkliste für neue Features
Bevor ein neues Feature als "fertig" gilt, diese Punkte prüfen:
1. Auth + Rate Limiting auf allen neuen Endpoints
2. IDOR-Schutz (user_id Filter) in allen neuen Queries
3. Pydantic Model mit Constraints für alle neuen Inputs
4. Error Messages auf Deutsch
5. Type Hints auf allen neuen Service-Funktionen
6. Kein Silent Exception Handling
7. Labels auf allen neuen Form-Inputs (htmlFor + id)
8. Responsive Layout (Mobile-Test)
9. Loading + Empty States
10. Neue Fachbegriffe im Glossar + Tooltip
11. Datenschutz: Neue persönliche Daten verschlüsselt? Datenschutzseite aktualisiert? Admin blind?
12. Signal-Sprache neutral? Keine imperativen Kauf-/Verkaufsanweisungen (→ "Kaufkriterien erfüllt", nicht "Kaufsignal")
13. `npm run build` + `pytest tests/ -v` bestehen

### Rechtliches & Signal-Sprache
- **Signal-Texte neutral formulieren**: "Kaufkriterien erfüllt" statt "Kaufsignal", "Verkaufskriterien erreicht" statt "Verkaufstrigger"
- **Marktklima-Texte neutral**: "Marktumfeld: Positiv (Risk-On)" statt "Voll investiert, Satellite aufbauen"
- **Keine imperativen Anweisungen**: "verkaufe sofort" oder "kaufe nicht" sind verboten in der UI
- **DisclaimerBanner**: Auf jeder Seite mit Signalen, Scoring oder Marktklima einfügen
- **Steuer-Disclaimer**: Bei Performance-Karten und realisierten Gewinnen
- **Rechtliche Seiten**: `/rechtliches` (konsolidiert, mit Anchors), `/nutzungsbedingungen` (vollständige AGB)
- **Öffentliche Routes**: `/datenschutz`, `/disclaimer`, `/impressum` — erreichbar ohne Login (für Login/Register-Seiten)
- **Registrierung**: Nutzungsbedingungen- und Disclaimer-Checkbox ist Pflicht

## Renditeberechnung (Drei Methoden)

- **Monatsrenditen** (Heatmap-Zellen): Modified Dietz — `R = (V_end - V_start - ΣCF) / (V_start + Σ(w_i × CF_i))`, gewichtet Cashflows nach Zeitpunkt im Monat
- **Jahresrenditen** (Heatmap Total-Spalte): XIRR (Money-Weighted Return) — geldgewichtete Rendite, berücksichtigt Zeitpunkt und Höhe aller Cashflows
- **YTD / Gesamtrendite**: XIRR de-annualisiert für Teilperioden
- **Gesamtrendite-Karte**: Drei Bereiche getrennt: Absoluter Gewinn/Verlust (CHF), Annualisierte Rendite (MWR %), YTD
- **XIRR-Implementierung**: Newton-Raphson + Bisection Fallback, keine externen Dependencies
- **Cashflow-Quellen**: Dual-Source (Transactions + Snapshot `net_cash_flow_chf` für manuelle Änderungen)
- **Erlaubte Änderungen**: `performance_history_service.py` und `total_return_service.py` NUR mit Freigabe vom Maintainer

## Formatierung

- **CHF**: Apostroph-Trenner (CHF 156'095)
- **Prozente**: 1-2 Dezimalstellen mit Vorzeichen (+1.23%, -4.56%)
- **Datum**: DD.MM.YYYY (Schweizer Format)
- **Zahlen**: User-Setting (CH: 1'000.00, DE: 1.000,00, EN: 1,000.00)

## Datenbank

- **Connection Pool**: async pool_size=20, max_overflow=20 | sync pool_size=5, max_overflow=10
- **PostgreSQL Tuning**: shared_buffers=1GB, effective_cache_size=3GB, work_mem=64MB, max_connections=200
- **Indizes**: Auf allen FKs, häufigen WHERE-Clauses, Composite-Indizes für User+Ticker/Date
- **FK Constraints**: ON DELETE CASCADE auf allen user-abhängigen Tabellen
- **Scheduler**: PostgreSQL Advisory Locks (multi-instance-safe), läuft im separaten Worker-Container
- **Cache**: Redis 7 (shared) für JSON-serialisierbare Daten + In-Memory für pandas Series (Stampede Prevention via per-key Locks)

## Caching-Architektur

- **Redis (shared)**: JSON-serialisierbare Daten (Preise, FX-Rates, Marktdaten, Scores, Sektor-Rotation)
- **In-Memory (per Worker)**: Nicht-serialisierbare Daten (pandas Series für Close-Serien, Moving Averages)
- **`cache.py`**: Transparenter Layer — `cache.get()`/`cache.set()` prüft automatisch ob Redis oder In-Memory
  - JSON-serialisierbar (dict, list, str, int, float) → Redis + lokaler Memory
  - Nicht-serialisierbar (pandas Series) → nur lokaler Memory
  - `cache.get()` prüft zuerst lokalen Memory, dann Redis
- **Refresh-State**: In `app_config` DB-Tabelle (shared zwischen allen Workers)
- **Portfolio-Summary**: Redis-backed (TTL 30s, shared zwischen Workers)
- **In-Memory LRU**: OrderedDict mit O(1) Eviction (maxsize=1000)

## Externe API Regeln

- **yfinance**: Batch-Download, Thread-safe Wrapper, `progress=False`, `threads=False`
- **CoinGecko**: BTC direkt in CHF, Free Tier Rate Limits beachten
- **FRED API**: Optional (Key in Settings), für Buffett/Unemployment/Yield Curve
- **FMP API**: Free Tier 250 calls/Tag, nur US-Aktien Fundamentals
- **Alle Calls**: Timeouts (15s), Retry mit Exponential Backoff (tenacity), 429-Handling

## Docker

- Multi-Stage Builds (Frontend: nginx, Backend: python-slim)
- Container läuft als Non-Root (appuser)
- Health Checks auf allen Services
- Secrets aus .env (NIE hardcoded, Default-Secrets werden beim Start abgelehnt, DB-Default-Passwort Warnung)
- **Container**: db (PostgreSQL), redis, backend (2 Uvicorn Workers), worker (shared Image), frontend (nginx), uptime-kuma
- **Optional**: Prometheus + Grafana + Loki via `docker-compose.monitoring.yml`
- **Backend**: 4GB RAM, 3 CPU | **Worker**: 2GB RAM, 2 CPU | **DB**: shared_buffers 1GB
- **Security Headers**: HSTS, CSP, X-Frame-Options, X-Content-Type-Options (nginx, inkl. /api/ Location)
- **Backend Port**: Nur auf 127.0.0.1 exponiert (für lokalen Reverse Proxy), nicht von aussen erreichbar
- **Logging**: Structured JSON (python-json-logger) mit Request-ID, Latency, Service-Name
- **Metriken**: Prometheus `/metrics` Endpoint (Request Count, Latency Histogramm, Active Requests)

## Industry/Sektor Mapping

- ~160 Industries (FINVIZ-Taxonomie) + Custom (Commodities, Crypto, Cash, Pension, Multi-Sector)
- Industry → Sector automatisch abgeleitet (Konstante in constants/sectors.py)
- ETFs: Multi-Sektor-Verteilung über etf_sector_weights Tabelle

## Import (Swissquote)

- CSV: Latin-1 Encoding, Semikolon-Trennzeichen
- Teilausführungen werden aggregiert (gleiche order_id + Ticker)
- Symbol-Mapping über ISIN (CH→.SW, IE/LU/GB→.L, CA+CAD→.TO)
- Bonds werden übersprungen (%-Zeichen im Stückpreis)
- Preview vor Import (nie direkt in DB schreiben)

## Import (Interactive Brokers)

- CSV: UTF-8, Komma-Trennzeichen (Flex Query Export)
- Auto-Detection über Header-Kombination (Symbol + AssetClass + Buy/Sell + IBCommission)
- Nur STK und ETF importiert; CASH/OPT/FUT/BOND/WAR/CFD werden übersprungen (mit Summary)
- Symbol-Mapping über ListingExchange → yfinance-Suffix, Fallback auf ISIN-Prefix
- Teilausführungen: Gleiches Datum + Symbol + Richtung → gewichteter Durchschnitt
- Gebühren: abs(IBCommission) + Taxes
- Datumsformat: YYYYMMDD oder YYYY-MM-DD
- Preview vor Import (nie direkt in DB schreiben)

## Import (Pocket)

- CSV: UTF-8, Semikolon-Trennzeichen
- Drei Zeilentypen: deposit (Einzahlung, skip), exchange (BTC-Kauf, importiert), withdrawal (Wallet-Transfer, skip)
- Nur `exchange`-Zeilen werden als Buy-Transaktionen importiert
- Ticker immer BTC-USD, Währung CHF, Preis-Quelle CoinGecko
- total_chf = cost.amount + fee.amount
- Datumsformat: ISO 8601 (z.B. 2024-12-20T11:11:08.000Z)
- Auto-Detection über Header: type;date;reference;price.currency;price.amount;...
- Preview vor Import (nie direkt in DB schreiben)

## Release-Workflow (IMMER befolgen)

Bei JEDEM Commit der Features oder Bugfixes enthält:

1. **CHANGELOG.md** aktualisieren — neuen Eintrag unter der aktuellen Version hinzufügen
   - "Hinzugefügt" für neue Features
   - "Behoben" für Bugfixes
   - "Geändert" für Änderungen an bestehendem Verhalten

2. **Version bumpen** in `frontend/package.json`:
   - Bugfix → Patch (0.9.0 → 0.9.1)
   - Neues Feature → Minor (0.9.1 → 0.10.0)
   - Breaking Change → Major (0.x → 1.0)

3. **Commit-Message** mit Version: `fix: JPY dividend conversion (v0.9.1)` oder `feat: 3-point reversal (v0.10.0)`

Dies gilt ab sofort für ALLE Commits. Kein Feature oder Bugfix ohne Changelog-Eintrag und Version-Bump.
