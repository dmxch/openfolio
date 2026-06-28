# Handover — T-Bill-/Geldmarkt-ETFs als Cash (v0.47) Prod-Deploy

**Datum:** 2026-06-25
**Feature:** Branch `feat/tbill-etf-count-as-cash` → `main`
**Betrifft Prod:** ja — **Migration 086 muss laufen** (läuft automatisch via Entrypoint).

---

## Was deployed wird

Neues Flag `positions.count_as_cash`. Eine ETF-Position mit `count_as_cash = TRUE`
bleibt eine regulär bepreiste Wertschrift — Marktwert = `Anteile × Kurs × FX`,
Performance/PnL unverändert (HEILIGE Regel 1 unberührt) —, wird aber als **Cash**
klassifiziert:

- Anlageklassen-Allokation (`by_type` → `cash`)
- Cash-Quote sowie Portfolio- und Bucket-Snapshots (`cash_chf`)
- aus der Core/Satellite-Aufteilung ausgenommen

UI: Checkbox „Als Cash zählen (Geldmarkt-/T-Bill-ETF)" im Add-/Edit-Dialog (nur bei
Typ ETF) + „Cash"-Badge in der Portfolio-Tabelle. External API in Parität
(`count_as_cash` in Create/Update-Body und in jeder Position-Response).

**Migration 086** (`086_position_count_as_cash`): additives
`ADD COLUMN count_as_cash boolean NOT NULL DEFAULT false`. Kein Backfill, kein
Lock-Risiko, forward-only safe, Downgrade (`DROP COLUMN`) vorhanden.

---

## ⚠️ Migrations-Reihenfolge prüfen

Falls Prod **Migration 085** (External-API-UI-Parität, v0.46) noch nicht hatte,
zieht `alembic upgrade head` **085 und 086** in einem Rutsch. Beide sind sicher.
Vor dem Deploy prüfen, was ansteht:

```bash
docker compose exec -T backend alembic history -r current:head
```

---

## Deploy (auf 10.10.70.10, im Projekt-Root)

Migration läuft **automatisch** via `backend/entrypoint.sh` (`alembic upgrade head`
beim Containerstart). Das generische Deploy-Skript deckt alles ab:

```bash
./scripts/prod_deploy.sh
```

Ablauf: DB-Backup → `git pull origin main` → Backend-Rebuild (Migration via
Entrypoint) → Verifikation `DB-Head == Code-Head` (Abbruch bei Mismatch) →
Frontend/Worker-Rebuild → Health-Smoke-Test. Frontend-Rebuild ist nötig (Checkbox +
Badge). Bei jedem Fehler: Stop + Rollback-Anleitung am Skript-Ende.

---

## Nachprüfung (manuell, nach dem Skript)

```bash
PG_USER=$(grep '^POSTGRES_USER=' .env | cut -d= -f2)   # prod: openfolio
PG_DB=$(grep '^POSTGRES_DB=' .env | cut -d= -f2)        # prod: openfolio

# (a) Head == 086
docker compose exec -T backend alembic current           # erwartet: 086 (head)

# (b) Spalte existiert (Beweis, dass 086 griff)
docker compose exec -T db psql -U "$PG_USER" "$PG_DB" -tAc \
  "SELECT 1 FROM information_schema.columns WHERE table_name='positions' AND column_name='count_as_cash';" \
  | grep -q 1 && echo "086 OK" || echo "FEHLT — 086 nicht angewandt!"

# (c) Health == 0.47.0
curl -sf http://127.0.0.1:8000/api/health | grep -o '"version":"[^"]*"'
```

### Optional: End-to-End-Smoke-Test der API

Braucht ein **write-scoped** API-Token und wegen Cloudflare einen eigenen
User-Agent:

```bash
WRITE_KEY=ofk_...
curl -s -X POST https://openfolio.cc/api/v1/external/positions \
  -H "X-API-Key: $WRITE_KEY" -H "User-Agent: openfolio-deploy-check/1.0" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"IB01.L","name":"iShares T-Bill 0-3m","type":"etf","count_as_cash":true,"shares":10,"cost_basis_chf":1000}'
# Response muss "count_as_cash": true enthalten → danach Throwaway-Position wieder löschen.
```

---

## Rollback

```bash
docker compose stop backend worker
git reset --hard <PREV_HEAD>      # vom Skript am Ende ausgegeben
docker compose up -d --build
# Falls die Migration zurückgerollt werden muss:
docker compose exec -T backend alembic downgrade -1   # DROP COLUMN count_as_cash
```

Da additiv und ohne Backfill ist das ein risikoarmer Deploy.
