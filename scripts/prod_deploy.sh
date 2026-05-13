#!/usr/bin/env bash
#
# Production-Deploy für Bucket-Feature (Migrations 063/064/065).
#
# Auf 10.10.70.10 ausführen, im Projekt-Root (wo docker-compose.yml liegt).
#
# Was es macht:
#   1. Vollständiges DB-Backup mit Timestamp
#   2. Git pull origin main
#   3. Backend rebuild → Migration läuft automatisch via Entrypoint
#   4. Migration-Verifikation (alembic head, positions_ohne_bucket=0, etc.)
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

bold "=== OpenFolio Bucket-Deploy ==="
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
BACKUP_FILE="$BACKUP_DIR/prod-pre-buckets-$(date +%Y%m%d-%H%M).sql"
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
git log --oneline "$PREV_HEAD..origin/main" | head -5
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
docker compose exec -T db psql -U "$PG_USER" "$PG_DB" -c "
SELECT version_num AS alembic_head FROM alembic_version;
SELECT 'positions_ohne_bucket' AS check, COUNT(*) AS n FROM positions WHERE bucket_id IS NULL
UNION ALL SELECT 'positions_total', COUNT(*) FROM positions
UNION ALL SELECT 'buckets_system', COUNT(*) FROM buckets WHERE kind='system' AND deleted_at IS NULL
UNION ALL SELECT 'buckets_user_active', COUNT(*) FROM buckets WHERE kind='user' AND deleted_at IS NULL
UNION ALL SELECT 'users_mit_position_type',
    (SELECT COUNT(DISTINCT user_id) FROM positions WHERE position_type IN ('core','satellite'));
"

NULL_BUCKETS=$(docker compose exec -T db psql -U "$PG_USER" "$PG_DB" -tAc \
    "SELECT COUNT(*) FROM positions WHERE bucket_id IS NULL;" | tr -d '[:space:]')
if [ "$NULL_BUCKETS" != "0" ]; then
    red "FEHLER: $NULL_BUCKETS Positionen ohne bucket_id — Migration unvollständig."
    yellow "Rollback empfohlen."
    exit 1
fi

VERSION=$(docker compose exec -T db psql -U "$PG_USER" "$PG_DB" -tAc \
    "SELECT version_num FROM alembic_version;" | tr -d '[:space:]')
if [ "$VERSION" != "065" ]; then
    red "FEHLER: alembic head ist $VERSION, erwartet 065."
    exit 1
fi
green "  Alembic head=065, alle Positionen haben bucket_id."
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
yellow "Manuelle Verifikation im Browser:"
echo "  - openfolio.cc aufrufen, einloggen"
echo "  - Wenn du position_type='core'|'satellite' hattest: Onboarding-Modal"
echo "    erscheint einmalig → 'Buckets behalten und ansehen'"
echo "  - Settings → Buckets prüfen"
echo "  - Position bearbeiten → Bucket-Dropdown sichtbar"
echo
yellow "Rollback (falls Probleme):"
echo "  docker compose stop backend worker"
echo "  docker compose exec -T db psql -U $PG_USER -c \"DROP DATABASE \\\"$PG_DB\\\"; CREATE DATABASE \\\"$PG_DB\\\";\""
echo "  cat $BACKUP_FILE | docker compose exec -T db psql -U $PG_USER $PG_DB"
echo "  git reset --hard $PREV_HEAD"
echo "  docker compose up -d --build"
