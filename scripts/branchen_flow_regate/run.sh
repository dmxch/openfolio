#!/usr/bin/env bash
# Re-Gate branchen-flow — von cron getriggert (2026-07-06).
# Faehrt den openfolio-Backend-Stack hoch (falls noetig), laeuft das
# direction-signed Re-Gate (3 Arme, Umbau 2026-07-02) read-only und
# legt das Ergebnis als Datei ab.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Repo-Root aus der eigenen Lage ableiten (Skript liegt in <repo>/scripts/branchen_flow_regate/).
REPO="$(cd "$DIR/../.." && pwd)"
if [ ! -f "$REPO/docker-compose.yml" ]; then
  echo "FEHLER: $REPO ist kein openfolio-Repo-Root (docker-compose.yml fehlt)." >&2
  echo "Dieser Ordner muss unter <repo>/scripts/ liegen." >&2
  exit 1
fi
OUT="$DIR/result_$(date +%Y%m%d_%H%M).txt"

{
  echo "=== Re-Gate branchen-flow — $(date '+%Y-%m-%d %H:%M %Z') ==="
  echo
  if ! cd "$REPO"; then
    echo "FEHLER: Repo nicht gefunden ($REPO). Manuell pruefen."
    exit 1
  fi

  # Stack hochfahren (idempotent) und auf Backend-Healthiness warten.
  docker compose up -d backend db >/dev/null 2>&1
  ready=0
  for _ in $(seq 1 18); do
    if docker compose exec -T backend python -c "import db, models.market_industry" >/dev/null 2>&1; then
      ready=1; break
    fi
    sleep 5
  done
  if [ "$ready" -ne 1 ]; then
    echo "FEHLER: Backend-Container nicht erreichbar/ungesund. Re-Gate manuell starten:"
    echo "  cd $REPO && docker compose exec -T backend python - < $DIR/phase0_regate.py"
    exit 1
  fi

  docker compose exec -T backend python - < "$DIR/phase0_regate.py"
  echo
  echo "=== Ende ==="
} > "$OUT" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M %Z')] Re-Gate gelaufen -> $OUT" >> "$DIR/regate.log"
