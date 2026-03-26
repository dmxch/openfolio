# OpenFolio

> Open Source Portfolio Manager für systematisches Investieren

## Features

### Portfolio-Tracking
- **Aktien & ETFs** — Kurs, Performance, Stop-Loss, Δ Stop, MRS, Setup-Score
- **Crypto** — BTC via CoinGecko (CHF-Preise), Relai/Pocket CSV-Import
- **Edelmetalle** — Physische Barren/Münzen mit Seriennummern, Hersteller, Lagerort, Spot-Preis-Bewertung
- **Cash & Konti** — Bank, IBAN, Währung, Saldo in Kontowährung + CHF-Umrechnung
- **Vorsorge** — Säule 3a/PK mit Anbieter-Tracking
- **Immobilien** — Renditeberechnung, Hypotheken (Fest/SARON mit dynamischer Marge-Berechnung), Ausgaben/Einnahmen
- **Direktbeteiligungen** — Private Equity / KMU-Beteiligungen mit jährlicher Steuerwert-Bewertung, Dividendenhistorie, Verrechnungssteuer

### Scoring-System
- **Setup-Score** — 21-Punkte Kauf-Checkliste (Moving Averages, Donchian Breakout, MRS, Fundamentals mit Branchenvergleich)
- **Donchian Channel Breakout** — 20-Tage-Hoch Breakout mit Volumen-Bestätigung (≥1.5× Avg)
- **Branchenvergleich** — D/E, Margins, PE vs. Industrie-Durchschnitt (~80 Industries)
- **ETF 200-DMA Kaufsignal** — 27 breite Index-ETFs (VOO, QQQ, VWRL, SWDA, CHSPI...) unter 200-DMA = Kaufsignal
- **Makro-Gate** — 7-Punkte-Check des Gesamtmarkts (informativer Indikator auf der Markt & Sektoren Seite)
- **Signal-Logik** — KAUFKRITERIEN ERFÜLLT / BEOBACHTUNGSLISTE / BEOBACHTEN / KEIN SETUP

### Marktanalyse
- **Marktklima** — S&P 500 Trend, VIX-Regime (Risk-On/Off), Crash-Indikatoren
- **Heatmap** — TradingView Heatmap nach Sektor/Marktkapitalisierung
- **Sektor-Rotation** — SPDR ETF Tabelle mit 1T/1W/1M/3M Performance
- **Makro-Indikatoren** — Shiller PE, Buffett Indicator, Credit Spread, Zinsstrukturkurve (FRED API)
- **Öl-Markt** — WTI + Brent Öl, WTI-Brent Spread (farbcodiert)

### Aktien-Detailansicht
- **TradingView Chart** — Interaktiver Candlestick mit SMA(20/50/150/200), BB, RSI, S/R Toggles, Symbol-Mapping für alle Börsen (.SW, .L, .DE, etc.), Fallback bei nicht verfügbaren Symbolen
- **Fundamental-Karten** — Revenue, Margins, D/E, PE, FCF, Market Cap mit Branchenvergleich (via yfinance)
- **Stockanalysis Links** — Deep-Dive Charts für Revenue, Financials, Dividenden (Yahoo Finance Fallback für Nicht-US-Ticker)
- **Support & Resistance** — 52W-Hoch/Tief + historische Pivot-Levels
- **Mansfield RS** — Relative Stärke vs. S&P 500

### Risikomanagement
- **Stop-Loss** — Pflicht für Satellite (5-12%, Trailing), optional für Core (fundamentaler Verkaufstrigger statt technischem Stop)
- **Schwur 1 (differenziert)** — Satellite: 150-DMA = Verkaufstrigger. Core: 150-DMA = Fundamental-Check. ETF: 200-DMA = Kaufsignal.
- **Alerts** — Klickbare Portfolio-Alerts (150-DMA, Stop-Proximity, Earnings, Sektor-Limits, Makro-Gate Ampel, ETF 200-DMA Kaufsignal)
- **ETF 200-DMA Alert** — Benachrichtigung wenn breite Index-ETFs (27 Ticker) unter 200-DMA fallen, mit E-Mail (täglich 22:35 CET)
- **Preis-Alarme** — Watchlist-basiert mit E-Mail-Benachrichtigung
- **Kauf-Checklisten** — Pflicht-Bestätigung vor jedem Trade (Core: Fundamental-Check, Satellite: Stop-Loss Pflicht)

### Performance
- **XIRR/MWR** — Geldgewichtete Rendite (Jahres-Totals, YTD, Gesamtrendite)
- **Modified Dietz** — Zeitgewichtete Monatsrenditen mit Cashflow-Gewichtung
- **Monatsrenditen-Heatmap** — Monatliche Performance (Modified Dietz) + Jahres-Total (XIRR)
- **Gesamtrendite-Karte** — Absoluter Gewinn/Verlust (CHF) + Annualisierte Rendite (MWR %) + YTD
- **Realisierte Gewinne** — Verkaufshistorie mit P&L

### Import & Transaktionen
- **Universeller CSV-Import** — 5-Schritt-Wizard mit Column/Type-Mapping
- **Swissquote** — Auto-Erkennung, Forex-Paare, Teilausführungen, ISIN-Mapping
- **Interactive Brokers** — Flex Query CSV, Auto-Erkennung, 22 Börsen-Mappings
- **Pocket** — Auto-Erkennung, Bitcoin-Käufe (pocketbitcoin.com, CHF)
- **Relai** — Auto-Erkennung, Bitcoin-Käufe (CHF)
- **Manuelle Transaktionen** — Ticker-Autocomplete mit yfinance-Suche, Positionen werden automatisch erstellt
- **Dividende erfassen** — Schnell-Erfassung direkt aus dem Drei-Punkte-Menü (⋮) jeder Aktie/ETF-Position
- **Import-Profile** — Mappings speichern und wiederverwenden
- **Historische FX-Kurse** — Automatischer Lookup für Fremdwährungs-Transaktionen via yfinance
- **Auto-Branchen-Zuweisung** — Industry und Sektor werden nach Import automatisch via yfinance gesetzt

### Watchlist
- **Donchian Breakout-Signale** — 20d-Channel Breakout, Volumen-Bestätigung, Setup-Score
- **Breakout-Alerts** — Automatische E-Mail bei Donchian-Breakout (täglich nach Marktschluss, 7-Tage-Deduplizierung)
- **Mansfield RS** — Relative Stärke vs. S&P 500
- **Tags** — Farbige Tags mit Autocomplete, Filter
- **Preis-Alarme** — Pro Ticker konfigurierbar

### Hilfe & Glossar
- **Hilfe-Seite** — 31 Artikel in 8 Kategorien, Sidebar-Navigation, Suche, Deep-Links
- **Glossar** — 107 Finanzbegriffe mit Hover-Tooltips in der gesamten App (55+ Integrationen)
- **Accessibility** — Focus Trapping in Modals, Skip-to-Content, ARIA Labels, htmlFor auf allen Formularen

### Onboarding
- **Interaktive Tour** — 7-Schritt Guided Tour für neue User mit Spotlight-Effekt und blauem Glow
- **Checkliste** — Persistente Fortschritts-Checkliste auf der Portfolio-Seite
- **Viewport-Safe Tooltips** — Automatische Positionierung innerhalb des sichtbaren Bereichs

### Sicherheit
- **JWT** — Access Token (15 Min) + Refresh Token (30 Tage, Rotation, Rate Limited)
- **MFA** — TOTP (Google Authenticator) + Backup-Codes. Pflicht für Admins, optional für normale User
- **Verschlüsselung** — Fernet (AES-256) für API Keys, SMTP-Passwörter, PII (IBAN, Notizen, Seriennummern)
- **Datenschutz** — Admin kann keine Portfolio-Daten sehen, Audit-Log für Admin-Aktionen
- **Session-Management** — Aktive Sitzungen verwalten, alle abmelden
- **Rate Limiting** — Redis-backed, Login/Register/Password-Reset/Refresh geschützt
- **Security Headers** — HSTS, CSP (TradingView/CoinGecko Allowlist), X-Frame-Options
- **Metrics** — Prometheus /metrics (authentifiziert), kein direkter Backend-Port
- **Limits** — Max 200 Watchlist-Einträge, 100 Preis-Alarme pro User

### Rechtliches & Compliance
- **Disclaimer** — Keine Anlageberatung, keine Gewähr, eigenes Risiko
- **AGB / Nutzungsbedingungen** — 15 Abschnitte (Haftung, Datenschutz, Gerichtsstand Schweiz)
- **Impressum** — Pflichtangaben nach UWG Art. 3 / TMG § 5
- **Konsolidierte Rechtliches-Seite** — Disclaimer, Datenschutz, AGB, Impressum mit Anchor-Navigation
- **Registrierung** — Nutzungsbedingungen- und Disclaimer-Checkbox Pflicht
- **Signal-Sprache** — Neutral formuliert ("Kaufkriterien erfüllt" statt "Kaufsignal")
- **Disclaimer-Banner** — Dezent auf allen Signal- und Scoring-Seiten
- **Steuer-Disclaimer** — Bei Performance und realisierten Gewinnen

### Code-Qualität
- **Type Hints** — Alle öffentlichen Service-Funktionen annotiert (Python 3.10+)
- **Error Messages** — Alle User-facing Fehlermeldungen auf Deutsch
- **Pydantic Validation** — Field Constraints auf allen API-Eingaben (ge=0, gt=0, min/max_length)
- **5-Phasen Audit** — Security, Performance, Code Quality, UX/A11y, Architecture (37 Findings umgesetzt)

## Schnellstart

### Voraussetzungen

- [Docker](https://docs.docker.com/get-docker/) und Docker Compose v2
- Git
- **VM-Betrieb**: Virtuelle Maschinen müssen mit CPU-Host-Passthrough laufen (`--cpu host` bei QEMU/KVM), da NumPy SSE4/AVX-Instruktionen benötigt

### Installation

```bash
git clone https://github.com/dmxch/openfolio.git
cd openfolio
./init.sh
```

Öffne danach [http://localhost](http://localhost) im Browser.

Das Setup-Script generiert alle nötigen Secrets, erstellt einen Admin-Account und startet die Container.

### Manuelle Installation

1. `.env` erstellen (siehe [`.env.example`](.env.example))
2. `docker compose up -d --build`
3. Öffne [http://localhost](http://localhost)

### Monitoring (optional)

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

### Ports

| Service | URL | Beschreibung |
|---------|-----|-------------|
| Frontend (nginx) | http://localhost:5173 | Haupt-UI |
| Backend API | http://localhost:8000 | API + Swagger Docs unter /docs |
| Uptime Kuma | http://localhost:3001 | Uptime-Monitoring |
| Grafana | http://localhost:3000 | Dashboards (optional, via monitoring compose) |
| Prometheus Metrics | http://localhost:8000/metrics | Prometheus-Format |

## Tech Stack

| Komponente | Technologie |
|-----------|------------|
| Frontend | React 18, Vite, Tailwind CSS (Dark Theme), Recharts, Lucide Icons |
| Backend | Python 3.12, FastAPI (async, 2 Uvicorn Workers + uvloop), SQLAlchemy 2.0, asyncpg, Alembic |
| Worker | Separater Background-Prozess (APScheduler) für Kurs-Refresh, Snapshots, Alerts |
| Datenbank | PostgreSQL 16 (tuned: shared_buffers 4GB, work_mem 64MB) |
| Cache | Redis 7 (shared zwischen Workers, 512MB, allkeys-lru) |
| Kursdaten | yfinance, CoinGecko, Gold.org, FMP API, FRED API |
| Monitoring | Prometheus + Grafana + Loki (optional), Uptime Kuma |
| Infra | Docker Compose (7 Container: db, redis, backend, worker, frontend, uptime-kuma + optional monitoring) |

## Konfiguration

| Variable | Beschreibung | Default |
|----------|-------------|---------|
| `ADMIN_EMAIL` | E-Mail des Admin-Accounts | — |
| `ADMIN_PASSWORD` | Passwort des Admin-Accounts | — |
| `FMP_API_KEY` | Financial Modeling Prep API Key (optional, US-Fundamentaldaten) | — |
| `FRED_API_KEY` | Federal Reserve API Key (optional, Makro-Indikatoren) | — |
| `GRAFANA_USER` | Grafana Admin-User (optional) | admin |
| `GRAFANA_PASSWORD` | Grafana Admin-Passwort (optional) | openfolio |

Weitere Variablen (Datenbank, JWT, Encryption) werden automatisch von `init.sh` generiert.

## Deployment hinter Reverse Proxy

Für den Betrieb mit eigener Domain hinter einem Reverse Proxy (Nginx, Caddy, Traefik):

### 1. `.env` anpassen

```bash
CORS_ORIGINS=https://deine-domain.com
FRONTEND_URL=https://deine-domain.com
```

### 2. Individuelle Anpassungen via Override

Für weitere Anpassungen (Port-Bindings, zusätzliche Env-Vars) eine Override-Datei erstellen:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
# Werte anpassen, dann: docker compose up -d --build
```

Die `docker-compose.override.yml` wird automatisch von Docker Compose geladen und ist in `.gitignore` ausgeschlossen.

### 3. Nginx-Beispielkonfiguration

```nginx
server {
    listen 443 ssl;
    server_name deine-domain.com;

    ssl_certificate     /etc/letsencrypt/live/deine-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/deine-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Hinweise

- **SSL**: [Let's Encrypt](https://letsencrypt.org/) (Certbot) oder [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) sind gängige Optionen.
- **VM-Betrieb**: Virtuelle Maschinen müssen mit CPU-Host-Passthrough laufen (`--cpu host` bei QEMU/KVM), da NumPy SSE4/AVX-Instruktionen benötigt.
- **Backend-Port**: Ist standardmässig nur auf `127.0.0.1:8000` gebunden — nicht von aussen erreichbar, aber für den lokalen Reverse Proxy zugänglich.

## Update

```bash
git pull
docker compose up -d --build
```

## Backup

```bash
docker compose exec db pg_dump -U finance finance > backup_$(date +%Y%m%d).sql
```

## Restore

```bash
cat backup_20260318.sql | docker compose exec -T db psql -U finance finance
```

## Mitwirken

Pull Requests und Issues sind willkommen! Lies bitte zuerst die [Contributing Guidelines](CONTRIBUTING.md).

- **Bug melden**: [Issue erstellen](https://github.com/dmxch/openfolio/issues/new?template=bug_report.yml)
- **Feature vorschlagen**: [Issue erstellen](https://github.com/dmxch/openfolio/issues/new?template=feature_request.yml)
- **Fragen**: [GitHub Discussions](https://github.com/dmxch/openfolio/discussions)

### Gute erste Beiträge
- Tests schreiben (Coverage erweitern)
- Accessibility verbessern (ARIA, Keyboard-Navigation)
- Mobile UX (Responsive Tabellen)
- Neue Broker-Import-Profile
- Dokumentation erweitern

## Lizenz

MIT
