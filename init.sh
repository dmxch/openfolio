#!/usr/bin/env bash
set -euo pipefail

# --- Colors (with fallback) ---
if [ -t 1 ] && command -v tput &>/dev/null && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[0;33m'
  BLUE='\033[0;34m'
  BOLD='\033[1m'
  DIM='\033[2m'
  NC='\033[0m'
else
  RED='' GREEN='' YELLOW='' BLUE='' BOLD='' DIM='' NC=''
fi

info()  { echo -e "${BLUE}ℹ${NC} $1"; }
ok()    { echo -e "${GREEN}✔${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
err()   { echo -e "${RED}✖${NC} $1" >&2; }
fatal() { err "$1"; exit 1; }

# --- Banner ---
echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  OpenFolio — Setup                   ║${NC}"
echo -e "${BOLD}║  Portfolio & Marktanalyse             ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

# --- Navigate to script directory (supports both clone and curl usage) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" 2>/dev/null || echo ".")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
  cd "$SCRIPT_DIR"
elif [ -f "./docker-compose.yml" ]; then
  cd "."
else
  # Likely run via curl — check if we need to clone
  if [ -d "openfolio" ]; then
    cd openfolio
  else
    info "Repository wird geklont..."
    git clone https://github.com/dmxch/openfolio.git
    cd openfolio
  fi
fi

info "Arbeitsverzeichnis: $(pwd)"
echo ""

# --- Prerequisites ---
echo -e "${BOLD}Voraussetzungen prüfen...${NC}"

command -v docker &>/dev/null || fatal "Docker ist nicht installiert. → https://docs.docker.com/get-docker/"
ok "Docker installiert"

if docker compose version &>/dev/null; then
  ok "Docker Compose v2 verfügbar"
else
  fatal "Docker Compose v2 nicht gefunden. Bitte Docker Desktop aktualisieren oder das Compose-Plugin installieren."
fi

if docker info &>/dev/null 2>&1; then
  ok "Docker Daemon läuft"
else
  fatal "Docker Daemon läuft nicht. Bitte Docker starten und erneut ausführen."
fi

command -v openssl &>/dev/null || fatal "openssl ist nicht installiert (wird für Schlüsselgenerierung benötigt)."

# Port checks
check_port() {
  local port=$1
  if command -v ss &>/dev/null; then
    ss -tlnp 2>/dev/null | grep -q ":${port} " && return 1
  elif command -v lsof &>/dev/null; then
    lsof -iTCP:"${port}" -sTCP:LISTEN &>/dev/null && return 1
  elif command -v netstat &>/dev/null; then
    netstat -tln 2>/dev/null | grep -q ":${port} " && return 1
  fi
  return 0
}

FRONTEND_PORT_DEFAULT=5173
BACKEND_PORT_DEFAULT=8000

# Belegte Ports werden erst bei der Abfrage geprueft (ask_port) — dort stehen die
# tatsaechlich gewaehlten Werte fest. Eine Warnung auf die Defaults waere irrefuehrend,
# sobald jemand eigene Ports vergibt.

# Name des DB-Volumes — in docker-compose.yml fest vergeben.
PGDATA_VOLUME="finance-dashboard_pgdata"

volume_exists() {
  docker volume inspect "$PGDATA_VOLUME" &>/dev/null
}

# Fragt einen Port ab und laesst nur brauchbare Werte durch:
#   - Zahl im gueltigen Bereich
#   - nicht derselbe wie der bereits vergebene Port ($3): zwei Container koennen sich
#     einen Host-Port nicht teilen, der zweite scheitert mit "port is already allocated"
#   - belegte Ports nur nach ausdruecklicher Bestaetigung — eine bereits laufende
#     OpenFolio-Instanz haelt ihre eigenen Ports, das ist ein legitimer Fall und darf
#     hier niemanden aussperren
ask_port() {
  local label="$1" default="$2" taken="${3:-}" input port answer
  while true; do
    echo -en "  Port für ${label} [${default}]: " >&2
    read -r input
    port="${input:-$default}"

    if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
      err "Ungültig: '${port}'. Erlaubt sind ganze Zahlen von 1 bis 65535."
      continue
    fi
    if [ -n "$taken" ] && [ "$port" = "$taken" ]; then
      err "Port ${port} ist bereits für den anderen Dienst vergeben — jeder braucht einen eigenen."
      continue
    fi
    if ! check_port "$port"; then
      warn "Port ${port} ist auf diesem Host belegt." >&2
      echo -en "  ${DIM}Ist das eine bereits laufende OpenFolio-Instanz, kannst du fortfahren.${NC} Trotzdem verwenden? [j/N] " >&2
      read -r answer
      [[ "$answer" =~ ^[jJyY]$ ]] || continue
    fi

    echo "$port"
    return 0
  done
}

echo ""

# --- Check for existing .env ---
if [ -f .env ]; then
  echo -en "${YELLOW}⚠${NC} Bestehende .env gefunden. Überschreiben? [j/N] "
  read -r overwrite
  if [[ ! "$overwrite" =~ ^[jJyY]$ ]]; then
    info "Bestehende Konfiguration wird beibehalten."
    echo ""
    # Skip to docker compose
    SKIP_ENV=true
  else
    SKIP_ENV=false
  fi
else
  SKIP_ENV=false
fi

if [ "$SKIP_ENV" = false ]; then
  # --- Bestehende Secrets retten, BEVOR neue gewuerfelt werden ---
  # Das DB-Volume ueberlebt jedes `docker compose down` und traegt weiterhin das
  # Passwort, mit dem es angelegt wurde. Ein frisch gewuerfeltes POSTGRES_PASSWORD
  # sperrt das Backend dauerhaft aus seiner eigenen Datenbank aus — sichtbar nur als
  # Endlos-Neustart und "container ... is unhealthy", ohne Hinweis auf die Ursache.
  # Fuer den ENCRYPTION_KEY gilt dasselbe, nur schlimmer: mit einem neuen Key sind
  # alle verschluesselten Werte in der bestehenden DB (API-Keys, Notizen) still
  # unlesbar, ohne dass irgendetwas abstuerzt.
  OLD_POSTGRES_PASSWORD=""
  OLD_ENCRYPTION_KEY=""
  if [ -f .env ]; then
    OLD_POSTGRES_PASSWORD=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2- || true)
    OLD_ENCRYPTION_KEY=$(grep '^ENCRYPTION_KEY=' .env | cut -d= -f2- || true)
  fi

  # --- Generate secrets ---
  echo -e "${BOLD}Secrets generieren...${NC}"
  JWT_SECRET=$(openssl rand -base64 48)
  ENCRYPTION_KEY=$(openssl rand -base64 32)
  POSTGRES_PASSWORD=$(openssl rand -base64 24)
  REDIS_PASSWORD=$(openssl rand -hex 32)
  GRAFANA_PASSWORD=$(openssl rand -base64 16)

  if volume_exists; then
    if [ -n "$OLD_POSTGRES_PASSWORD" ]; then
      POSTGRES_PASSWORD="$OLD_POSTGRES_PASSWORD"
      if [ -n "$OLD_ENCRYPTION_KEY" ]; then
        ENCRYPTION_KEY="$OLD_ENCRYPTION_KEY"
      fi
      warn "Bestehende Datenbank erkannt — DB-Passwort und Encryption-Key aus der alten .env übernommen."
    else
      echo ""
      err "Es existiert bereits ein Datenbank-Volume (${PGDATA_VOLUME}), aber keine .env"
      err "mit dem zugehörigen Passwort. Ohne dieses Passwort kommt das Backend nicht mehr"
      err "an die Datenbank — es würde endlos neu starten und Docker meldete nur \"is unhealthy\"."
      echo ""
      echo "    1) Volume löschen und frisch aufsetzen  ⚠ alle gespeicherten Daten gehen verloren"
      echo "    2) Abbrechen (z. B. um eine Sicherung der alten .env zurückzuspielen)"
      echo ""
      echo -en "  Auswahl [1/2]: "
      read -r volume_choice
      if [ "$volume_choice" = "1" ]; then
        echo -en "  Zum Bestätigen ${BOLD}LOESCHEN${NC} tippen: "
        read -r volume_confirm
        [ "$volume_confirm" = "LOESCHEN" ] || fatal "Abgebrochen — nichts verändert."
        docker compose down &>/dev/null || true
        docker volume rm "$PGDATA_VOLUME" &>/dev/null \
          || fatal "Volume liess sich nicht entfernen. Zuerst 'docker compose down' ausführen."
        ok "Volume entfernt — die Datenbank wird frisch aufgesetzt."
      else
        fatal "Abgebrochen — nichts verändert."
      fi
    fi
  fi

  ok "Kryptographische Schlüssel generiert"
  echo ""

  # --- Admin account ---
  echo -e "${BOLD}Admin-Account erstellen:${NC}"

  # Email
  while true; do
    echo -n "  E-Mail: "
    read -r ADMIN_EMAIL
    if [[ "$ADMIN_EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
      break
    fi
    err "Ungültiges E-Mail-Format. Bitte erneut eingeben."
  done

  # Password
  while true; do
    echo -n "  Passwort: "
    read -rs ADMIN_PASSWORD
    echo ""

    if [ ${#ADMIN_PASSWORD} -lt 12 ]; then
      err "Passwort muss mindestens 12 Zeichen lang sein."
      continue
    fi

    if ! echo "$ADMIN_PASSWORD" | grep -qP '[A-Z]'; then
      err "Passwort muss mindestens einen Grossbuchstaben enthalten."
      continue
    fi
    if ! echo "$ADMIN_PASSWORD" | grep -qP '[a-z]'; then
      err "Passwort muss mindestens einen Kleinbuchstaben enthalten."
      continue
    fi
    if ! echo "$ADMIN_PASSWORD" | grep -qP '[0-9]'; then
      err "Passwort muss mindestens eine Zahl enthalten."
      continue
    fi
    if ! echo "$ADMIN_PASSWORD" | grep -qP '[^A-Za-z0-9]'; then
      err "Passwort muss mindestens ein Sonderzeichen enthalten."
      continue
    fi

    echo -n "  Passwort bestätigen: "
    read -rs ADMIN_PASSWORD_CONFIRM
    echo ""

    if [ "$ADMIN_PASSWORD" = "$ADMIN_PASSWORD_CONFIRM" ]; then
      break
    fi
    err "Passwörter stimmen nicht überein. Bitte erneut eingeben."
  done

  ok "Admin-Account konfiguriert"
  echo ""

  # --- Ports ---
  echo -e "${BOLD}Ports:${NC}"
  echo -e "  ${DIM}Die Oberfläche rufst du später über den ersten Port auf. Der API-Port wird nur${NC}"
  echo -e "  ${DIM}für Direktzugriffe gebraucht — die Oberfläche spricht intern mit dem Backend.${NC}"
  FRONTEND_PORT="$(ask_port "die Web-Oberfläche" "$FRONTEND_PORT_DEFAULT")"
  BACKEND_PORT="$(ask_port "die API" "$BACKEND_PORT_DEFAULT" "$FRONTEND_PORT")"
  echo ""

  # --- Write .env ---
  info ".env wird erstellt..."
  cat > .env <<ENVFILE
# OpenFolio Konfiguration — generiert von init.sh
# Erstellt: $(date +%Y-%m-%d)

# Datenbank
POSTGRES_USER=openfolio
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=openfolio

# Sicherheit (NICHT teilen oder committen!)
JWT_SECRET=${JWT_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
REDIS_PASSWORD=${REDIS_PASSWORD}

# Monitoring (optional, für docker-compose.monitoring.yml)
GRAFANA_PASSWORD=${GRAFANA_PASSWORD}

# Initialer Admin (wird beim ersten Start verwendet)
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}

# Ports
FRONTEND_PORT=${FRONTEND_PORT}
BACKEND_PORT=${BACKEND_PORT}
ENVFILE

  ok ".env erstellt"

  # Ensure .env is in .gitignore
  if [ -f .gitignore ]; then
    if ! grep -qx '.env' .gitignore; then
      echo '.env' >> .gitignore
      ok ".env zu .gitignore hinzugefügt"
    fi
  fi

  echo ""
fi

# --- Start Docker Compose ---
echo -e "${BOLD}Starte OpenFolio...${NC}"

docker compose build --quiet 2>&1 | while read -r line; do echo -e "  ${DIM}${line}${NC}"; done
ok "Images gebaut"

docker compose up -d 2>&1 | while read -r line; do echo -e "  ${DIM}${line}${NC}"; done
ok "Container gestartet"

# --- Wait for health ---
# Die tatsaechlichen Ports kommen aus der .env — auch im SKIP_ENV-Fall (bestehende
# Konfiguration behalten) ist sie die einzige verlaessliche Quelle.
if [ -f .env ]; then
  BACKEND_PORT_ACTUAL=$(grep '^BACKEND_PORT=' .env 2>/dev/null | cut -d= -f2 || echo "$BACKEND_PORT_DEFAULT")
  BACKEND_PORT_ACTUAL="${BACKEND_PORT_ACTUAL:-$BACKEND_PORT_DEFAULT}"
  FRONTEND_PORT_ACTUAL=$(grep '^FRONTEND_PORT=' .env 2>/dev/null | cut -d= -f2 || echo "$FRONTEND_PORT_DEFAULT")
  FRONTEND_PORT_ACTUAL="${FRONTEND_PORT_ACTUAL:-$FRONTEND_PORT_DEFAULT}"
else
  BACKEND_PORT_ACTUAL="$BACKEND_PORT_DEFAULT"
  FRONTEND_PORT_ACTUAL="$FRONTEND_PORT_DEFAULT"
fi

echo -n "  Warte auf Backend"
TRIES=0
MAX_TRIES=30
while [ $TRIES -lt $MAX_TRIES ]; do
  if curl -sf "http://localhost:${BACKEND_PORT_ACTUAL}/api/health" &>/dev/null; then
    break
  fi
  echo -n "."
  sleep 2
  TRIES=$((TRIES + 1))
done
echo ""

if [ $TRIES -ge $MAX_TRIES ]; then
  warn "Backend antwortet nicht nach 60 Sekunden."
  warn "Prüfe die Logs mit: docker compose logs backend"
else
  ok "Backend ist bereit"
fi

# Read email from .env for display
DISPLAY_EMAIL=""
if [ -f .env ]; then
  DISPLAY_EMAIL=$(grep '^ADMIN_EMAIL=' .env 2>/dev/null | cut -d= -f2 || echo "")
fi

# --- Done ---
echo ""
echo -e "${GREEN}✅ OpenFolio läuft!${NC}"
echo ""
echo -e "  ${BOLD}Öffne im Browser:${NC} http://localhost:${FRONTEND_PORT_ACTUAL}"
if [ -n "$DISPLAY_EMAIL" ]; then
  echo -e "  ${BOLD}Anmelden mit:${NC}     ${DISPLAY_EMAIL}"
fi
echo ""
echo -e "  ${YELLOW}⚠ Sicherheit:${NC}     ADMIN_PASSWORD aus .env entfernen — Account wurde erstellt"
echo ""
echo -e "  ${DIM}Nützliche Befehle:${NC}"
echo -e "    Stoppen:     ${BOLD}docker compose down${NC}"
echo -e "    Logs:        ${BOLD}docker compose logs -f${NC}"
echo -e "    Update:      ${BOLD}git pull && docker compose up -d --build${NC}"
echo -e "    Neu starten: ${BOLD}docker compose restart${NC}"
echo ""
echo -e "  Dokumentation: https://github.com/dmxch/openfolio"
echo ""
