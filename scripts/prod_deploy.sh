#!/usr/bin/env bash
#
# Generischer Production-Deploy (Release-agnostisch).
#
# Auf 10.10.70.10 ausführen, im Projekt-Root (wo docker-compose.yml liegt).
#
# Was es macht:
#   1. Vollständiges DB-Backup mit Timestamp
#   2. Git pull origin main
#   3. Backend rebuild → Migration läuft automatisch via Entrypoint
#   4. Migration-Verifikation (DB-Head == Code-Head, dynamisch — KEINE
#      hartkodierten Revisionen; die Bucket-Ära-Version dieses Scripts
#      prüfte head==065 und eine nie existente Spalte position_type und
#      brach damit jeden späteren Deploy ab)
#   5. Frontend + Worker rebuild
#   6. Smoke-Check (Health-Endpoint)
#
# Bei jedem kritischen Fehler: STOP, kein weiterer Schritt. Rollback-Anleitung
# wird am Ende ausgegeben falls etwas schief geht.

set -euo pipefail

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

PROJECT_ROOT="$(pwd)"
if [ ! -f "$PROJECT_ROOT/docker-compose.yml" ]; then
    red "FEHLER: docker-compose.yml nicht im aktuellen Verzeichnis."
    red "Wechsle ins Projekt-Verzeichnis und führe das Skript erneut aus."
    exit 1
fi

PG_USER=$(grep '^POSTGRES_USER=' "$PROJECT_ROOT/.env" | cut -d= -f2)
PG_DB=$(grep '^POSTGRES_DB=' "$PROJECT_ROOT/.env" | cut -d= -f2)

if [ -z "$PG_USER" ] || [ -z "$PG_DB" ]; then
    red "FEHLER: POSTGRES_USER oder POSTGRES_DB nicht in .env gefunden."
    exit 1
fi

bold "=== OpenFolio Production-Deploy ==="
echo "  POSTGRES_USER: $PG_USER"
echo "  POSTGRES_DB:   $PG_DB"
echo "  Verzeichnis:   $PROJECT_ROOT"
echo

# ---------------------------------------------------------------------------
# Schritt 1: DB-Backup
# ---------------------------------------------------------------------------
bold "[1/6] DB-Backup..."
BACKUP_DIR=/var/backups/openfolio
sudo mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/prod-pre-deploy-$(date +%Y%m%d-%H%M).sql"
docker compose exec -T db pg_dump -U "$PG_USER" "$PG_DB" | sudo tee "$BACKUP_FILE" > /dev/null
SIZE=$(sudo du -h "$BACKUP_FILE" | cut -f1)
if [ ! -s "$BACKUP_FILE" ]; then
    red "FEHLER: Backup-Datei ist leer ($BACKUP_FILE)"
    exit 1
fi
green "  Backup OK: $BACKUP_FILE ($SIZE)"
echo

# ---------------------------------------------------------------------------
# Schritt 2: Code holen
# ---------------------------------------------------------------------------
bold "[2/6] Git pull..."
PREV_HEAD=$(git rev-parse HEAD)
git fetch origin
git log --oneline -5 "$PREV_HEAD..origin/main" || true
git pull origin main
NEW_HEAD=$(git rev-parse HEAD)
green "  Code: $PREV_HEAD -> $NEW_HEAD"
echo

# ---------------------------------------------------------------------------
# Schritt 3: Backend rebuild + Migration (auto via Entrypoint)
# ---------------------------------------------------------------------------
bold "[3/6] Backend rebuild + Migration..."
docker compose build backend 2>&1 | tail -5
docker compose up -d backend
sleep 8
# Schau in Logs ob Migration sauber lief
MIGRATIONS=$(docker compose logs backend --since 60s 2>&1 | grep -E "Running upgrade|Migrations complete|ERROR" | tail -10)
echo "$MIGRATIONS"
if echo "$MIGRATIONS" | grep -qi "ERROR"; then
    red "FEHLER in Migrationen — STOP. Siehe Output oben."
    yellow "Rollback: siehe Anleitung am Ende dieses Skripts."
    exit 1
fi
green "  Migration OK."
echo

# ---------------------------------------------------------------------------
# Schritt 4: Migration-Verifikation
# ---------------------------------------------------------------------------
bold "[4/6] DB-Verifikation..."
# Code-Head dynamisch aus dem frisch gebauten Backend-Image ermitteln —
# nie hartkodieren (Lektion aus der Bucket-Ära-Version dieses Scripts).
CODE_HEAD=$(docker compose exec -T backend alembic heads 2>/dev/null | awk '{print $1}' | head -1)
DB_HEAD=$(docker compose exec -T db psql -U "$PG_USER" "$PG_DB" -tAc \
    "SELECT version_num FROM alembic_version;" | tr -d '[:space:]')
echo "  Code-Head: ${CODE_HEAD:-?}  DB-Head: ${DB_HEAD:-?}"
if [ -z "$CODE_HEAD" ] || [ "$DB_HEAD" != "$CODE_HEAD" ]; then
    red "FEHLER: alembic-Head-Mismatch (DB=$DB_HEAD, Code=$CODE_HEAD)."
    yellow "Rollback: siehe Anleitung am Ende dieses Skripts."
    exit 1
fi

# Informative Sanity-Counts (kein Abort — nur Sichtprüfung)
docker compose exec -T db psql -U "$PG_USER" "$PG_DB" -c "
SELECT 'positions_total' AS check, COUNT(*) AS n FROM positions
UNION ALL SELECT 'positions_ohne_bucket', COUNT(*) FROM positions WHERE bucket_id IS NULL
UNION ALL SELECT 'users_total', COUNT(*) FROM users;
"
green "  Alembic-Head $DB_HEAD == Code-Head."
echo

# ---------------------------------------------------------------------------
# Schritt 5: Frontend + Worker rebuild
# ---------------------------------------------------------------------------
bold "[5/6] Frontend + Worker rebuild..."
docker compose up -d --build frontend worker 2>&1 | tail -8
sleep 5
docker compose ps --format "table {{.Name}}\t{{.Status}}"
echo

# ---------------------------------------------------------------------------
# Schritt 6: Smoke-Test
# ---------------------------------------------------------------------------
bold "[6/6] Health-Smoke-Test..."
HEALTH=$(curl -sf http://127.0.0.1:8000/api/health 2>&1 || echo "FAIL")
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    green "  /api/health OK: $HEALTH"
else
    red "FEHLER: Health-Endpoint nicht OK: $HEALTH"
    exit 1
fi
echo

# Worker-Logs auf neue Crons prüfen
SCHEDULER=$(docker compose logs worker --tail=50 2>&1 | grep -i "Scheduler started" | tail -1)
if [ -n "$SCHEDULER" ]; then
    green "  Worker: $SCHEDULER"
fi
echo

bold "=== Deploy erfolgreich ==="
green "Backup: $BACKUP_FILE"
green "HEAD:   $NEW_HEAD"
echo
yellow "Manuelle Verifikation:"
echo "  - curl -s http://127.0.0.1:8000/api/health | grep version  (== Release-Version?)"
echo "  - openfolio.cc aufrufen, einloggen, Dashboard prüfen"
echo "  - Release-spezifische One-offs siehe CHANGELOG/Handover"
echo
yellow "Rollback (falls Probleme):"
echo "  docker compose stop backend worker"
echo "  docker compose exec -T db psql -U $PG_USER -c \"DROP DATABASE \\\"$PG_DB\\\"; CREATE DATABASE \\\"$PG_DB\\\";\""
echo "  cat $BACKUP_FILE | docker compose exec -T db psql -U $PG_USER $PG_DB"
echo "  git reset --hard $PREV_HEAD"
echo "  docker compose up -d --build"
