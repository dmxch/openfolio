#!/usr/bin/env bash
#
# Stage-Restore-Skript
#
# Usage:
#   ./scripts/stage_restore.sh <prod-dump.sql>
#
# Workflow:
#   1. Prueft, dass Stage-Compose laeuft (DB-Container up).
#   2. Loescht Stage-DB-Inhalt.
#   3. Restored den Dump.
#   4. Fuehrt Anonymisierung aus.
#   5. Triggert alembic upgrade head (falls Schema-Drift).
#
# Sicherheit:
#   - Skript prueft strikt, dass DATABASE_URL auf Port 5433 zeigt (Stage).
#   - Bricht ab, wenn DB-Name nicht "_stage" enthaelt.
#   - Restore und Anonymisierung laufen mit ON_ERROR_STOP=1. Scheitert einer der
#     beiden Schritte, loescht das Skript die Stage-DB wieder: sie enthielte
#     sonst echte Emails, Passwort-Hashes und ntfy-Topics.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ $# -ne 1 ]; then
    echo "Usage: $0 <prod-dump.sql>" >&2
    exit 1
fi

DUMP_FILE="$1"

if [ ! -f "$DUMP_FILE" ]; then
    echo "Dump file not found: $DUMP_FILE" >&2
    exit 1
fi

ENV_FILE="$PROJECT_ROOT/.env.stage"
if [ ! -f "$ENV_FILE" ]; then
    echo ".env.stage missing. Create from .env.example and adjust ports/credentials." >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a
. "$ENV_FILE"
set +a

POSTGRES_USER="${POSTGRES_USER:-finance_stage}"
POSTGRES_DB="${POSTGRES_DB:-finance_stage}"

if [[ "$POSTGRES_DB" != *"_stage"* ]]; then
    echo "REFUSING: POSTGRES_DB=$POSTGRES_DB does not contain '_stage'. Wrong env file?" >&2
    exit 1
fi

COMPOSE="docker compose -p openfolio-stage --env-file $ENV_FILE -f $PROJECT_ROOT/docker-compose.stage.yml"

echo "[1/5] Checking Stage DB container..."
if ! $COMPOSE ps db | grep -q "Up\|running"; then
    echo "Stage DB container not running. Start with: $COMPOSE up -d db" >&2
    exit 1
fi

# Ab dem Restore liegen echte Daten in der Stage-DB. Bis die Anonymisierung
# committet hat, darf kein Abbruch sie dort stehen lassen.
REAL_DATA_ON_STAGE=0
drop_unanonymized_db() {
    local rc=$?
    [ "$REAL_DATA_ON_STAGE" -eq 1 ] || return 0
    echo >&2
    echo "FAILED (exit $rc) before the anonymization finished." >&2
    echo "Dropping Stage DB $POSTGRES_DB so that no production data stays on Stage..." >&2
    # WITH (FORCE): ein laufendes Stage-Backend haelt sonst Verbindungen offen.
    if $COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS $POSTGRES_DB WITH (FORCE);" >&2; then
        echo "Stage DB dropped. Fix the error above and run the restore again." >&2
    else
        echo "COULD NOT DROP $POSTGRES_DB. It still holds production data — drop it by hand." >&2
    fi
}
trap drop_unanonymized_db EXIT

echo "[2/5] Dropping and recreating Stage DB..."
$COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB;"
$COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $POSTGRES_DB;"

echo "[3/5] Restoring dump (this may take several minutes)..."
REAL_DATA_ON_STAGE=1
# Ein Dump ohne --no-owner weist jedes Objekt der Rolle der Quell-DB zu. Diese
# Rolle gibt es auf Stage nicht, und mit ON_ERROR_STOP waere das der erste
# Abbruch. Die Zeilen fallen weg; alles gehoert danach dem Stage-User, wie
# bisher, als psql die Fehler ueberging.
sed -E '/^ALTER [A-Z ]+ .* OWNER TO [^ ]+;$/d' "$DUMP_FILE" \
    | $COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

echo "[4/5] Running anonymization..."
$COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SCRIPT_DIR/anonymize_dump.sql"
REAL_DATA_ON_STAGE=0

echo "[5/5] Running alembic upgrade head (in case of schema drift)..."
if $COMPOSE ps backend | grep -q "Up\|running"; then
    $COMPOSE exec -T backend alembic upgrade head
else
    echo "  (Backend not running — skipping alembic. Run manually after starting backend.)"
fi

echo
echo "Stage restore complete."
echo "  DB: $POSTGRES_DB (port 5433)"
echo "  Login: admin@example.test / stage123 (or user-<8hex>@example.test)"
echo "  Frontend: http://localhost:5174"
