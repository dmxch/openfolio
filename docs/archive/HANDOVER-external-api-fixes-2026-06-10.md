# Handover: External-API-Fixes 2026-06-10 (aus dem Finance-Workspace)

**Für:** Claude im openfolio-Repo
**Von:** Claude im finance-Workspace (`~/projects/finance`) — dem grössten Konsumenten der External API
**Commit:** `7078e30` (`feat(external-api): Stop-Lücken-MV + MRS-Warnings + Preis-Historie-Backfill`)
**Tests:** volle Suite grün — **1167 passed, 3 skipped** (`docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm backend-test`)
**Deploy-Status:** ⚠️ **NUR committed + gepusht — NICHT auf VM220 deployed.** Lokale Dev-Instanz läuft noch auf dem alten Image.

---

## Kontext: Warum diese Änderungen

Im finance-Workspace lief am 2026-06-10 ein voller Workspace-Audit (siehe dort `Output/2026-06-10_workspace_audit.md`). Dabei fielen in der Live-Nutzung der External API mehrere Reibungspunkte auf. Vier davon stellten sich als echte Backend-Gaps heraus, zwei als Falsch-Befunde auf Konsumenten-Seite. Alle vier Gaps sind gefixt, die Falsch-Befunde sind client-seitig korrigiert (finance-Repo `80091ea`).

## Was geändert wurde (4 Fixes)

### 1. `GET /portfolio/positions-without-stoploss` — `market_value_chf` + `type` ergänzt
**Datei:** `backend/services/stoploss_service.py` (`get_positions_without_stoploss`)
**Problem:** Endpoint lieferte nur id/ticker/name/shares/current_price/currency/bucket_id. Konsumenten (Stop-Lücken-Reports im `/portfolio-review`-Skill) brauchen den CHF-Marktwert pro Lücke und mussten gegen `/portfolio/summary` joinen.
**Fix:** `market_value_chf` = shares × current_price × fx (via `get_fx_rates_batch`, CHF→1.0, fehlender Kurs→null) + `type` (Enum-Value). Additiv, kein Breaking Change.

### 2. Stop-Loss-Writes: `method` defaultet auf `'manual'`
**Datei:** `backend/services/stoploss_service.py` (`update_stop_loss` + `batch_update_stop_loss`)
**Problem:** Stops, die ohne Methoden-Angabe gesetzt wurden (UI-Pfad), standen im `stop-loss-status` als `method: null` (live gesehen bei CAT/EQIX). Konsumenten lesen das Feld für die Trail-Logik.
**Fix:** `method or "manual"` bzw. `item.get("method") or "manual"` beim Setzen. Beim **Entfernen** eines Stops bleibt `method = None` (korrekt). Alt-Einträge heilen beim nächsten Update — keine Migration nötig.

### 3. `GET /v1/external/analysis/mrs/{ticker}` — `warnings[]` bei leerem `data`
**Dateien:** `backend/api/external_v1.py` (Endpoint) + `backend/services/chart_service.py` (`get_mrs_history`)
**Problem:** Endpoint lieferte reproduzierbar `{"ticker":"TSM","data":[]}` — für Konsumenten nicht unterscheidbar von „keine Coverage", und im Log stand **nichts** (die frühen `return []`-Pfade loggten nicht).
**Fix:**
- `get_mrs_history` loggt jetzt WARNING mit präzisem Grund: welche Close-Serie fehlt (stock/bench, „yf + DB fallback exhausted") oder Wochen-Overlap < 14 (mit Count).
- Der External-Endpoint hängt bei leerem `data` ein `warnings[]`-Array an (generischer Text, Detail im Log). Additiv.

### 4. Preis-Historie-Backfill (der eigentliche Root-Cause-Fix)
**Dateien:** `backend/services/cache_service.py` (`backfill_price_history` + Hook in `_seed_safe`) + **neu** `backend/scripts/backfill_price_history.py`

**Root-Cause-Analyse des TSM-Falls (wichtig fürs Verständnis):**
1. Production-Web-Prozess: `yf_download("TSM", "2y")` schlug fehl (transient/Rate-Limit im langlaufenden Prozess — in einem frischen Python-Prozess im selben Container funktionierte derselbe Call einwandfrei, 501 rows).
2. Fallback `get_close_series_from_db("TSM", "2y")` → **leer bzw. zu kurz**, weil `price_cache` pro Ticker erst ab Anlage-Datum der Position akkumuliert (der 60s-Worker upsertet nur den Tages-Close). TSM wurde 2026-04-10 gekauft → ~8 Wochen Historie < 14-Wochen-Minimum für MRS.
3. In der lokalen Dev-DB verifiziert: von den Portfolio-Tickern hatten nur OEF/^GSPC/^VIX & Co. nennenswerte Historie; `seed_historical_prices` seedet **nur** `^GSPC`/`^VIX`.

**Fix:**
- Neue Funktion `backfill_price_history(db, ticker, period="2y")`: yf-Download → idempotenter Bulk-Upsert (`on_conflict_do_nothing`) nach `price_cache`. Wirft nie, loggt Erfolg/Fehlschlag.
- **Hook:** `_seed_safe` (Background-Task bei Positions-Anlage) ruft den Backfill nach dem Live-Kurs-Seed auf — nur für Yahoo-fähige Typen (nicht `_NON_YAHOO_TYPES`, nicht gold_org, nicht coingecko).
- **One-off-Script** für Bestandspositionen: `python -m scripts.backfill_price_history` (iteriert alle aktiven Yahoo-fähigen Positionen, dedupe, 1.5s Sleep zwischen Downloads). Idempotent, gefahrlos mehrfach ausführbar.

---

## Was bewusst NICHT geändert wurde (Falsch-Befunde, client-seitig korrigiert)

1. **„`/watchlist` liefert keine Preise"** — falsch. Die Felder heissen `price` / `change_pct` / `currency`; der Konsument las `current_price` / `change_pct_day` (existieren nicht → jq ergab null). Skills im finance-Repo korrigiert. **Kein Backend-Handlungsbedarf.**
2. **„Score-Endpoint braucht serverseitiges `score_pct`"** — obsolet. `assess_ticker` liefert bereits `pct` (0–100, modifier-bewusst — weicht von score/max ab: OEF 13/15 → pct 90) plus `rating`. Die finance-Skills nutzen jetzt primär das Server-`pct`. **Kein Backend-Build nötig.** *(Randnotiz: die variable `max_score`-Mechanik pro Ticker war konsumentenseitig nie nachvollzogen worden — falls es dazu eine Doku-Lücke in `EXTERNAL_API.md` gibt, wäre ein Absatz zu `score`/`max_score`/`pct`/`rating`-Semantik sinnvoll.)*

## Doku-Änderungen

- `CHANGELOG.md`: 3 Einträge unter „Hinzugefügt", 1 unter „Geändert" (Unreleased).
- `docs/EXTERNAL_API.md`: MRS-Zeile (warnings-Hinweis) + positions-without-stoploss-Beispiel (Feldliste).

---

## ⚠️ Offene Schritte (Production, VM220 — von der Dev-Maschine nicht erreichbar)

```bash
# Auf 10.10.70.10, im Projekt-Root:
./scripts/prod_deploy.sh                      # Backup → git pull → rebuild → Smoke

# Danach EINMALIG (füllt price_cache mit 2y-Historie für Bestandspositionen):
docker compose exec backend python -m scripts.backfill_price_history
```

**Verifikation nach Deploy:**
```bash
# MRS-TSM sollte Daten liefern (oder warnings[] mit Grund):
curl -sS -H "X-API-Key: $TOKEN" https://openfolio.cc/api/v1/external/analysis/mrs/TSM?period=1y | jq '{n: (.data|length), warnings}'
# Stop-Lücken mit MV:
curl -sS -H "X-API-Key: $TOKEN" https://openfolio.cc/api/v1/external/portfolio/positions-without-stoploss | jq '.[0]'
```

## Anregungen für später (nicht umgesetzt, kein Druck)

- **MRS-Cache-Hygiene:** `get_mrs_history` cached auch erfolgreich berechnete *leere* Resultate 1h (Zeile `cache.set` im Success-Pfad). Harmlos, aber ein leeres Resultat zu cachen verzögert die Heilung nach einem Backfill um bis zu 1h.
- **yfinance-Resilienz im Web-Prozess:** der TSM-Fall zeigt, dass `yf_download` im langlaufenden Prozess fehlschlagen kann, während frische Prozesse funktionieren (Cookie/Crumb-State?). Falls das häufiger auftritt: Retry-once oder periodischer Session-Reset im `yf_patch`-Wrapper.
- **`seed_historical_prices`** (Worker-Boot) könnte auf aktive Positionen ausgeweitet werden statt nur ^GSPC/^VIX — der neue Backfill-Hook deckt Neuanlagen ab, aber ein Boot-Check wäre Belt-and-Suspenders.

---

*Erstellt 2026-06-10 ~04:45 CEST. Konsumenten-Kontext: der finance-Workspace hat parallel alle Skills auf das Server-`pct`-Feld migriert (Commits `b33e7ca` + `80091ea` in `dmxch/finance`) — künftige Änderungen an `pct`-Semantik oder Feldnamen in `/analysis/score`, `/watchlist`, `/portfolio/stop-loss-status`, `/analysis/mrs` bitte als Breaking Change behandeln und im CHANGELOG flaggen.*
