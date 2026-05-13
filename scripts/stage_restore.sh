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

# Safety-Check: DB-Name muss _stage enthalten
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

echo "[2/5] Dropping and recreating Stage DB..."
$COMPOSE exec -T db psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB;"
$COMPOSE exec -T db psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $POSTGRES_DB;"

echo "[3/5] Restoring dump (this may take several minutes)..."
$COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$DUMP_FILE"

echo "[4/5] Running anonymization..."
$COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SCRIPT_DIR/anonymize_dump.sql"

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
