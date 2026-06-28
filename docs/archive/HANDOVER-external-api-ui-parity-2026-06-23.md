# Handover — External API UI-Paritaet (v0.45) Prod-Deploy

**Datum:** 2026-06-23
**Feature:** PR #4 (`feat/external-api-ui-parity`), gemmerged auf `main` (squash `7b16235`)
**Betrifft Prod:** ja — **Migration 085 muss laufen**, sonst HTTP 500 beim ersten externen Write.

---

## Was deployed wird

Die externe REST-API (`/api/v1/external/*`, X-API-Key) hat jetzt volle UI-Schreib-
Paritaet: 88 Write-Routes ueber alle Domaenen (Positionen, Immobilien, Private
Equity, Edelmetalle, Dividenden, Buckets, Performance-Aktionen, Screening-Scan,
ETF-Sektoren, EPS-Schwellen, Resistance, Watchlist-Tags, Settings/Onboarding,
Import) — je hinter Scope `write` mit atomarem `ApiWriteLog`.

**Migration 085** (`085_api_write_log_ui_parity_actions`) weitet ausschliesslich den
CHECK-Constraint `ck_api_write_log_action` um alle neuen Action-Werte. Kein
Datenschema-Change, kein Lock-Risiko (winzige Tabelle), forward-only safe,
Downgrade vorhanden. **Kritisch:** Der `ApiWriteLog` wird atomar mit jeder Mutation
committet — fehlt der Action-Wert im Constraint, rollt der gemeinsame Commit zurueck
→ 500 beim ersten Write.

**Bewusst NICHT exponiert** (Sicherheits-Entscheid): Secret-Writes (SMTP/ntfy/
FRED/FMP/Finnhub-Keys, API-Token-Erstellung), Auth/Identitaet, Admin-Funktionen.

---

## Deploy (auf 10.10.70.10, im Projekt-Root)

Migration 085 laeuft **automatisch** via `backend/entrypoint.sh` (`alembic upgrade
head` beim Containerstart). Das generische Deploy-Skript deckt alles ab:

```bash
./scripts/prod_deploy.sh
```

Ablauf: DB-Backup -> `git pull origin main` (holt `7b16235`) -> Backend-Rebuild
(Migration laeuft via Entrypoint) -> Verifikation `DB-Head == Code-Head` (Abbruch
bei Mismatch) -> Frontend/Worker-Rebuild -> Health-Smoke-Test. Bei jedem Fehler:
Stop + Rollback-Anleitung am Skript-Ende.

> Falls Prod hinter v0.44 (Alembic-Head < 084) liegt, laufen mit `upgrade head`
> auch die dazwischenliegenden Migrationen. Vorher pruefen:
> `docker compose exec -T backend alembic history -r current:head`

---

## v0.45-spezifische Nachpruefung (manuell, nach dem Skript)

Das Skript prueft den Alembic-Head generisch, aber nicht ob der Constraint
tatsaechlich die neuen Actions enthaelt. Diese zwei Checks ergaenzen:

```bash
PG_USER=$(grep '^POSTGRES_USER=' .env | cut -d= -f2)   # prod: openfolio
PG_DB=$(grep '^POSTGRES_DB=' .env | cut -d= -f2)        # prod: openfolio

# (a) Head == 085
docker compose exec -T backend alembic current          # erwartet: 085 (head)

# (b) Constraint enthaelt die neuen Actions (Proof, dass 085 griff)
docker compose exec -T db psql -U "$PG_USER" "$PG_DB" -tAc \
  "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_api_write_log_action';" \
  | grep -q position_create && echo "085 constraint OK" || echo "FEHLT — 085 nicht angewandt!"
```

---

## End-to-End-Smoke-Test eines neuen Write-Endpoints (optional, empfohlen)

Bester Beweis, dass die Whitelist greift: ein Write, der eine **neue** Action
loggt. Braucht ein **write-scoped** API-Token (Settings -> API-Tokens, write
aktiviert) und wegen Cloudflare einen eigenen User-Agent:

```bash
WRITE_KEY=ofk_...   # write-Token
# Throwaway-Position anlegen (loggt action=position_create) ...
RESP=$(curl -s -X POST https://openfolio.cc/api/v1/external/positions \
  -H "X-API-Key: $WRITE_KEY" -H "User-Agent: openfolio-deploy-check/1.0" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"DEPLOYTEST","name":"Deploy Smoke","type":"stock","shares":0,"cost_basis_chf":0}')
echo "$RESP"                       # 201 + JSON mit "id" == Whitelist OK; 500 == 085 fehlt
PID=$(echo "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
# ... und wieder loeschen (loggt position_delete), hinterlaesst keine Daten:
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  "https://openfolio.cc/api/v1/external/positions/by-id/$PID" \
  -H "X-API-Key: $WRITE_KEY" -H "User-Agent: openfolio-deploy-check/1.0"   # erwartet 204
```

201/204 -> Migration + neue Endpoints sind prod-tauglich. 500 -> 085 nicht
angewandt (Schritt (b) pruefen).

---

## Rollback

Nur Migration 085 (trivial reversibel):

```bash
docker compose exec -T backend alembic downgrade -1   # 085 -> 084
```

Voll-Rollback (Code + DB-Restore + `git reset`) steht am Ende von
`scripts/prod_deploy.sh`.

---

## Referenzen

- Doku: `docs/EXTERNAL_API.md` (Sektion „UI-Paritaet — Schreib-Endpoints" + v0.45-Changelog)
- Audit: `AUDIT_ui_parity_v0.45.md` (PASS, Finding #1 behoben)
- Migration: `backend/alembic/versions/085_api_write_log_ui_parity_actions.py`
- Tests: `backend/tests/test_external_ui_parity.py`
