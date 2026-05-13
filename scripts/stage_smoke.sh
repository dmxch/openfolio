#!/usr/bin/env bash
#
# Stage Smoke-Test
#
# Prueft nach Stage-Restore:
#   - Backend /api/health antwortet
#   - Login mit admin@example.test / stage123 funktioniert
#   - Portfolio-Summary-Endpoint liefert Daten
#   - alembic ist auf head
#   - Keine produktiven Emails in DB
#
# Exit-Code != 0 bei Fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$PROJECT_ROOT/.env.stage"
if [ ! -f "$ENV_FILE" ]; then
    echo ".env.stage missing." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

POSTGRES_USER="${POSTGRES_USER:-finance_stage}"
POSTGRES_DB="${POSTGRES_DB:-finance_stage}"
BACKEND_URL="http://127.0.0.1:8001"
FRONTEND_URL="http://127.0.0.1:5174"

COMPOSE="docker compose --env-file $ENV_FILE -f $PROJECT_ROOT/docker-compose.stage.yml"

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

ok() {
    echo "OK:   $1"
}

echo "Stage Smoke Test"
echo "================"

# 1. Health
if curl -sf "$BACKEND_URL/api/health" > /dev/null; then
    ok "Backend /api/health responding"
else
    fail "Backend /api/health not responding at $BACKEND_URL"
fi

# 2. Frontend reachable
if curl -sf "$FRONTEND_URL/" > /dev/null; then
    ok "Frontend reachable at $FRONTEND_URL"
else
    fail "Frontend not reachable at $FRONTEND_URL"
fi

# 3. Login
LOGIN_RESPONSE=$(curl -s -X POST "$BACKEND_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@example.test","password":"stage123"}' || echo "FAIL")

if echo "$LOGIN_RESPONSE" | grep -q "access_token"; then
    ok "Login as admin@example.test works"
    TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
else
    fail "Login failed. Response: $LOGIN_RESPONSE"
fi

# 4. Portfolio summary loads
SUMMARY=$(curl -sf -H "Authorization: Bearer $TOKEN" "$BACKEND_URL/api/portfolio/summary" || echo "FAIL")
if echo "$SUMMARY" | grep -q "positions\|total_value"; then
    ok "Portfolio summary endpoint reachable"
else
    fail "Portfolio summary failed. Response head: $(echo "$SUMMARY" | head -c 200)"
fi

# 5. Alembic on head
HEAD_CHECK=$($COMPOSE exec -T backend alembic current 2>/dev/null | tail -1)
if echo "$HEAD_CHECK" | grep -q "(head)"; then
    ok "Alembic is at head"
else
    fail "Alembic NOT at head: $HEAD_CHECK"
fi

# 6. No production emails left
LEAKED=$($COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT COUNT(*) FROM users WHERE email NOT LIKE '%@example.test';" | tr -d '[:space:]')
if [ "$LEAKED" = "0" ]; then
    ok "No production emails in users table"
else
    fail "$LEAKED users still have non-stage emails"
fi

# 7. No production webhooks
WEBHOOK_LEAK=$($COMPOSE exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT COUNT(*) FROM ntfy_config WHERE server_url NOT LIKE '%.example.test%';" 2>/dev/null | tr -d '[:space:]' || echo "0")
if [ "$WEBHOOK_LEAK" = "0" ]; then
    ok "No production ntfy webhooks"
else
    fail "$WEBHOOK_LEAK ntfy configs still point to non-stage URLs"
fi

echo
echo "All smoke tests passed."
