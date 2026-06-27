# OpenFolio

Open Source Portfolio Manager für systematisches Investieren mit regelbasierter Marktanalyse.

## Tech Stack

Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 (asyncpg), Alembic, Redis 7, PostgreSQL 16
Worker: APScheduler (Kurs-Refresh 60s, Snapshots, Alerts, Earnings, COT Weekly, 13F Daily, Screening-Cleanup, Branchen-Stale-Check Weekly, Dividend-Detection Daily 09:30, Dividend-Digest Weekly So 09:00)
Frontend: React 18, Vite, Tailwind CSS (Dark Theme), Recharts, Lucide Icons
Infra: Docker Compose (db, redis, backend, worker, frontend/nginx, uptime-kuma)
APIs: yfinance, CoinGecko, FRED, FMP, Gold.org, multpl.com, SEC EDGAR, CFTC, SIX SER

## Befehle

```bash
docker compose up -d --build              # Starten
docker compose logs -f backend            # Logs
docker compose exec backend alembic upgrade head  # Migrationen
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test  # Tests
cd frontend && npm run build              # Frontend Build
```

## Architektur

```
backend/
  api/           # FastAPI Router (27 Dateien, aufgeteilt nach Domäne)
  services/      # Business Logic (97 Dateien, inkl. screening/ und macro/)
  models/        # SQLAlchemy Models (41 Dateien)
  middleware/    # Request Middleware (Metrics)
  constants/     # Limits, Sectors
  alembic/       # DB-Migrationen
  tests/         # pytest Suite
  auth.py        # JWT Auth
  config.py      # Settings / Env
  db.py          # DB Session & Engine
  worker.py      # APScheduler Background Worker
  utils.py       # Shared Helpers
  yf_patch.py    # yfinance Wrapper (yf_download)
  seed.py        # Initialdaten
frontend/src/
  pages/         # Route Pages (lazy-loaded)
  components/    # React Components
  contexts/      # AuthContext, DataContext
  hooks/         # useApi, useEscClose, useFocusTrap
  data/          # glossary.js, helpContent.js
  lib/           # format.js, tradingview.js
```

## Git-Konventionen

- Conventional Commits: feat:, fix:, refactor:, docs:, chore:, perf:
- UI + Docs auf Deutsch, Code auf Englisch
- Schweizer Deutsch: kein ß, immer ss. ä/ö/ü korrekt
- Error Messages: User-facing auf Deutsch, Logs auf Englisch
- Type Hints auf allen öffentlichen Service-Funktionen
- Branch: main (production)

## Korrektheits-Invarianten (das Vertrauen in die Zahlen)

Diese Definitionen dürfen sich nicht **still** ändern — Nutzer vergleichen Zahlen über die Zeit;
ein subtiler Bruch ist unsichtbar und zerstört Vertrauen dauerhaft. Ändern ist erlaubt, wenn:
(a) Definition / historische Vergleichbarkeit bleibt erhalten oder wird bewusst migriert,
(b) ein Test fängt den Bruch (Golden-Master, siehe `tests/test_golden_master_calculations.py`),
(c) bei echter Bedeutungsänderung: kurze Rückfrage beim Maintainer.

1. **Rendite-Definitionen** (`portfolio_service.py`, `recalculate_service.py`, `price_service.py`, `utils.py`)
   - cost_basis_chf = historischer CHF-Wert zum Kaufzeitpunkt (inkl. Gebühren)
   - value_chf = shares × current_price × fx_rate
   - perf_pct = ((value_chf / cost_basis_chf) − 1) × 100
   - Monatlich = Modified Dietz; Jahres/YTD-Total = XIRR (MWR) — `performance_history_service.py`, `total_return_service.py`

2. **Assetklassen-Ausschluss**: Immobilien, Vorsorge und Private Equity zählen NICHT zur liquiden
   Performance / zum liquiden Vermögen — komplett ausgeschlossen aus Snapshots, History, Daily Change, XIRR, Monatsrenditen.

3. **Signal-Definitionen** (Parameter sind **tunebar**, aber nur mit Forward-Return-Backtest — keine stille Änderung)
   - MRS = EMA(13) auf Weekly-Daten, Benchmark ^GSPC
   - Breakout = Donchian Channel 20d, current_price > 20-Tage-Hoch (strict >), Volumen ≥ 1.5× 20d-Avg

→ **Schutz durch Tests, nicht durch Verbot**: Golden-Master-Tests auf diese Outputs sind das Ziel — sie machen Definitions-Drift sichtbar und geben gleichzeitig die Freiheit, drumherum zu refactoren. Wo sie noch fehlen, hier vorsichtig arbeiten und im Zweifel rückfragen.

## Konventionen (normale Standards)

- yfinance NUR über `yf_download()` Wrapper via `asyncio.to_thread()`, nie direkt im async Context
- Alle HTTP-Calls über httpx (nicht requests); alle SMTP über aiosmtplib (nicht smtplib)
- Signal-Sprache neutral: "Kaufkriterien erfüllt" statt "Kaufsignal", "Verkaufskriterien erreicht"
  statt "Verkaufen!". Keine imperativen Anweisungen in der UI.

## Qualitätssicherung

Kein Merge ohne gruenen `@openfolio-audit`. Agents: audit, fixer, release, design. Skills in `.claude/skills/`.
Diagnose-Reports als separate `.md` im Projektroot committen.