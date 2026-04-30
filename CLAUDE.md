# OpenFolio

Open Source Portfolio Manager für systematisches Investieren mit regelbasierter Marktanalyse.

## Tech Stack

Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 (asyncpg), Alembic, Redis 7, PostgreSQL 16
Worker: APScheduler (Kurs-Refresh 60s, Snapshots, Alerts, Earnings, COT Weekly, 13F Daily, Screening-Cleanup, Branchen-Stale-Check Weekly)
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
  api/           # FastAPI Router (22 Dateien, aufgeteilt nach Domäne)
  services/      # Business Logic (67 Dateien, inkl. screening/ und macro/)
  models/        # SQLAlchemy Models (28 Dateien)
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

## HEILIGE Regeln (NIEMALS brechen)

1. **Performance-Berechnung NICHT ändern** ohne explizite Freigabe vom Maintainer
   - Betrifft: `portfolio_service.py`, `recalculate_service.py`, `price_service.py`, `utils.py`
   - cost_basis_chf = historischer CHF-Wert zum Kaufzeitpunkt (inkl. Gebühren)
   - value_chf = shares × current_price × fx_rate
   - perf_pct = ((value_chf / cost_basis_chf) - 1) × 100

2. **MRS-Berechnung**: EMA(13) auf Weekly-Daten, Benchmark ^GSPC — nicht ändern

3. **Breakout-Logik**: Donchian Channel 20d — current_price > 20-Tage-Hoch (strict >), Volumen ≥ 1.5× 20d-Avg

4. **Immobilien** NICHT in liquide Performance einrechnen

5. **Vorsorge** NICHT in liquides Vermögen einrechnen

6. **Private Equity** NICHT in liquide Performance einrechnen
   - Aus Snapshots, History, Daily Change, XIRR, Monatsrenditen komplett ausgeschlossen

7. **yfinance**: NUR über `yf_download()` Wrapper via `asyncio.to_thread()`. NIEMALS direkt in async Context.

8. **Alle HTTP-Calls**: httpx (nicht requests)

9. **Alle SMTP**: aiosmtplib (nicht smtplib)

10. **Signal-Sprache neutral**: "Kaufkriterien erfüllt" statt "Kaufsignal", "Verkaufskriterien erreicht" statt "Verkaufen!". Keine imperativen Anweisungen in der UI.

11. **Renditeberechnung**: Monatlich = Modified Dietz, Jahres/YTD-Total = XIRR (MWR). `performance_history_service.py` und `total_return_service.py` NUR mit Freigabe ändern.

## Qualitätssicherung

Kein Merge ohne gruenen `@openfolio-audit`. Agents: audit, fixer, release, design. Skills in `.claude/skills/`.
Diagnose-Reports als separate `.md` im Projektroot committen.