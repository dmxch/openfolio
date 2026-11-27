#!/usr/bin/env bash
#
# Generischer Production-Deploy (Release-agnostisch).
#
# Auf dem Prod-Host ausführen, im Projekt-Root (wo docker-compose.yml liegt).
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
# Bei jedem kritischen Fehler: STOP, kein weiterer Schritt. Die Rollback-Anleitung
# gibt der EXIT-Trap aus, auch wenn das Skript mitten im Lauf abbricht.
#
# Umgebungsvariablen (optional):
#   DEPLOY_WAIT_SECONDS  Wartezeit auf ein gesundes Backend (Default 900)
#   BACKUP_KEEP          Anzahl Pre-Deploy-Dumps, die bleiben. Ohne Angabe löscht
#                        das Skript keine Dumps.
#   BACKUP_DIR           Ordner für die Dumps (Default /var/backups/openfolio).
#                        Den Default und einen neu angelegten Ordner setzt das
#                        Skript auf Modus 700. Ein bestehender anderer Ordner
#                        behält seinen Modus.

set -euo pipefail

# Feste `umask 022` für den ganzen Lauf, unabhängig vom Konto des Betreibers:
# `git pull` schreibt geänderte Dateien mit der umask des Skripts, und
# `COPY . .` trägt den Modus ins Image. Der Prozess dort läuft nicht als root.
# Mit `umask 077` oder `027` könnte er die Dateien nicht lesen. Den Dump
# schützen `install -m 600` und `chmod 700` in Schritt 1.
umask 022

red(){ printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

PROJECT_ROOT="$(pwd)"
if [ ! -f "$PROJECT_ROOT/docker-compose.yml" ]; then
    red "FEHLER: docker-compose.yml nicht im aktuellen Verzeichnis."
    red "Wechsle ins Projekt-Verzeichnis und führe das Skript erneut aus."
    exit 1
fi

# `|| true`: ohne Treffer endet grep mit 1, und `set -e` beendete das Skript
# vor der Fehlermeldung darunter.
PG_USER=$(grep '^POSTGRES_USER=' "$PROJECT_ROOT/.env" | cut -d= -f2 || true)
PG_DB=$(grep '^POSTGRES_DB=' "$PROJECT_ROOT/.env" | cut -d= -f2 || true)

if [ -z "$PG_USER" ] || [ -z "$PG_DB" ]; then
    red "FEHLER: POSTGRES_USER oder POSTGRES_DB nicht in .env gefunden."
    exit 1
fi

BACKUP_FILE=""
BACKUP_OK=0
PREV_HEAD=""
BACKEND_STARTED=0

print_rollback() {
    yellow "Rollback (falls Probleme):"
    echo "  docker compose stop backend worker"
    # DROP DATABASE läuft nicht in einem Transaktionsblock, und psql fasst
    # mehrere Befehle in einem -c zu einer Transaktion zusammen: deshalb zwei
    # Aufrufe. -d postgres, weil niemand die DB löschen kann, mit der er
    # verbunden ist.
    echo "  docker compose exec -T db psql -U $PG_USER -d postgres -c 'DROP DATABASE \"$PG_DB\";'"
    echo "  docker compose exec -T db psql -U $PG_USER -d postgres -c 'CREATE DATABASE \"$PG_DB\";'"
    echo "  sudo cat $BACKUP_FILE | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U $PG_USER -d $PG_DB"
    echo "  git reset --hard $PREV_HEAD"
    echo "  docker compose up -d --build"
}

on_exit() {
    local rc=$?
    [ "$rc" -ne 0 ] || return 0
    echo
    red "=== Deploy abgebrochen (Exit $rc) ==="
    if [ "$BACKUP_OK" -ne 1 ]; then
        echo "  Abbruch vor dem Backup: Code und Datenbank sind unverändert."
    elif [ -z "$PREV_HEAD" ]; then
        echo "  Abbruch vor dem Code-Update: Code und Datenbank sind unverändert."
        echo "  Backup: $BACKUP_FILE"
    elif [ "$BACKEND_STARTED" -ne 1 ]; then
        # Die Migration läuft erst im Entrypoint des neuen Backends.
        echo "  Abbruch vor dem Start des neuen Backends: die Datenbank ist unverändert."
        echo "  Code zurücksetzen: git reset --hard $PREV_HEAD"
        echo "  Backup: $BACKUP_FILE"
    else
        echo "  Zuerst die Ursache prüfen: docker compose logs backend --tail=100"
        print_rollback
    fi
}
trap on_exit EXIT
trap 'red "FEHLER: Befehl in Zeile $LINENO ist fehlgeschlagen."' ERR

# Wartet, bis der Backend-Container «healthy» meldet. Der Entrypoint migriert,
# bevor uvicorn startet: der Healthcheck wird erst nach der Migration grün.
# «unhealthy» beendet das Warten nicht, denn Docker meldet das nach
# start_period und retries auch während einer langen Datenmigration. Ein
# Neustart des Containers beendet es: dann ist der Entrypoint gescheitert.
wait_for_backend() {
    local timeout="${DEPLOY_WAIT_SECONDS:-900}" interval=3
    local waited=0 cid info state="" health="" restarts="" base_restarts=""
    while :; do
        info=""
        cid=$(docker compose ps -aq backend 2>/dev/null | head -1 || true)
        if [ -n "$cid" ]; then
            info=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}}' "$cid" 2>/dev/null || true)
        fi
        if [ -n "$info" ]; then
            read -r state health restarts <<< "$info"
            [ -n "$base_restarts" ] || base_restarts="$restarts"
            if [ "$state" = "running" ] && [ "$health" = "healthy" ]; then
                return 0
            fi
            if [ "$restarts" != "$base_restarts" ] || [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
                red "  Backend-Container wurde beendet oder neu gestartet (Status: $state)."
                return 1
            fi
        fi
        if [ "$waited" -ge "$timeout" ]; then
            red "  Backend ist nach ${timeout}s nicht healthy (Status: ${state:-?}/${health:-?})."
            return 1
        fi
        sleep "$interval"
        waited=$((waited + interval))
    done
}

bold "=== OpenFolio Production-Deploy ==="
echo "  POSTGRES_USER: $PG_USER"
echo "  POSTGRES_DB:   $PG_DB"
echo "  Verzeichnis:   $PROJECT_ROOT"
echo

# ---------------------------------------------------------------------------
# Schritt 1: DB-Backup
# ---------------------------------------------------------------------------
bold "[1/6] DB-Backup..."
DEFAULT_BACKUP_DIR="/var/backups/openfolio"
BACKUP_DIR="${BACKUP_DIR:-$DEFAULT_BACKUP_DIR}"
# Modus 700 nur für den eigenen Ordner: den Default oder einen Ordner, den
# dieser Lauf anlegt. Ein bestehender anderer Ordner (etwa /tmp) behält seinen
# Modus: `chmod 700` sperrte dort alle anderen Nutzer aus.
BACKUP_DIR_IS_OWN=0
if [ "${BACKUP_DIR%/}" = "$DEFAULT_BACKUP_DIR" ] || ! sudo test -e "$BACKUP_DIR"; then
    BACKUP_DIR_IS_OWN=1
fi
sudo mkdir -p "$BACKUP_DIR"
if [ "$BACKUP_DIR_IS_OWN" -eq 1 ]; then
    sudo chmod 700 "$BACKUP_DIR"
else
    yellow "  Hinweis: $BACKUP_DIR besteht schon und behält seinen Modus. Die Dumps darin haben Modus 600."
fi
BACKUP_FILE="$BACKUP_DIR/prod-pre-deploy-$(date +%Y%m%d-%H%M).sql"
# Datei zuerst mit Modus 600 anlegen: `sudo tee` nimmt sonst die umask von
# root, und der Dump wäre während des Schreibens für alle lesbar.
sudo install -m 600 /dev/null "$BACKUP_FILE"
docker compose exec -T db pg_dump -U "$PG_USER" "$PG_DB" | sudo tee "$BACKUP_FILE" > /dev/null
# Dumps früherer Läufe entstanden ohne Rechte-Vorgabe.
sudo find "$BACKUP_DIR" -maxdepth 1 -type f -name 'prod-pre-deploy-*.sql' -exec chmod 600 {} +
# Prüfung über sudo: der eigene Ordner ist nur noch für root lesbar.
if ! sudo test -s "$BACKUP_FILE"; then
    red "FEHLER: Backup-Datei ist leer ($BACKUP_FILE)"
    exit 1
fi
SIZE=$(sudo du -h "$BACKUP_FILE" | cut -f1)
BACKUP_OK=1
green "  Backup OK: $BACKUP_FILE ($SIZE)"

# Rotation nur auf ausdrücklichen Wunsch: BACKUP_KEEP=N behält die N neuesten
# Pre-Deploy-Dumps. Der Zeitstempel im Namen sortiert chronologisch.
if [[ "${BACKUP_KEEP:-}" =~ ^[1-9][0-9]*$ ]]; then
    OLD_DUMPS=$(sudo find "$BACKUP_DIR" -maxdepth 1 -type f -name 'prod-pre-deploy-*.sql' \
        | sort -r | tail -n +"$((BACKUP_KEEP + 1))" || true)
    while IFS= read -r old_dump; do
        [ -n "$old_dump" ] || continue
        sudo rm -f -- "$old_dump"
        echo "  Alter Dump entfernt: $old_dump"
    done <<< "$OLD_DUMPS"
fi
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
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
BACKEND_STARTED=1
docker compose up -d backend
if ! wait_for_backend; then
    docker compose logs backend --since "$STARTED_AT" 2>&1 | tail -30 || true
    red "FEHLER: Backend ist nicht gestartet — STOP. Siehe Log oben."
    exit 1
fi
# Als Migrationslog zählt nur die Ausgabe des Entrypoints bis «=== Starting:».
# ERROR-Zeilen danach schreibt die laufende App; sie sagen nichts über die
# Migration. `|| true`: ein Lauf ohne neue Migration liefert keine Trefferzeile.
MIGRATIONS=$(docker compose logs backend --since "$STARTED_AT" 2>&1 | sed '/=== Starting:/q' | grep -E "Running upgrade|Migrations complete|ERROR" | tail -10 || true)
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

# Laufende Version: /api/health nennt sie unauthentifiziert bewusst nicht mehr
# (Fingerprinting, Security-Report 2026-07-27). Direkt aus dem Container lesen —
# das ist ohnehin die verlässlichere Quelle als der HTTP-Umweg.
# `|| true`, weil das Script unter `set -euo pipefail` läuft — ein fehlschlagender
# exec darf den Deploy nicht in der letzten Zeile abbrechen.
RUNNING_VERSION=$(docker compose exec -T backend python -c "from version import APP_VERSION; print(APP_VERSION)" 2>/dev/null | tr -d '\r' || true)
if [ -n "$RUNNING_VERSION" ]; then
    green "  Laufende Version: v$RUNNING_VERSION"
else
    yellow "  WARNUNG: Version konnte nicht aus dem Backend-Container gelesen werden"
fi
echo

# Worker-Logs auf neue Crons prüfen — die Zeile listet alle registrierten Jobs samt Zeiten
SCHEDULER=$(docker compose logs worker --tail=50 2>&1 | grep -i "Scheduler started" | tail -1 || true)
if [ -n "$SCHEDULER" ]; then
    green "  Worker: $SCHEDULER"
fi
echo

bold "=== Deploy erfolgreich ==="
green "Backup: $BACKUP_FILE"
green "HEAD:   $NEW_HEAD"
echo
yellow "Manuelle Verifikation:"
echo "  - Version oben aus Schritt 6 gegen den Release-Tag prüfen"
echo "  - app.openfolio.cc aufrufen, einloggen, Dashboard prüfen"
echo "  - Release-spezifische One-offs siehe CHANGELOG/Handover"
echo
print_rollback
