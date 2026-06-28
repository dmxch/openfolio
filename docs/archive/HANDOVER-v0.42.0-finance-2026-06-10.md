# Handover: OpenFolio v0.42.0 (für den Finance-Workspace)

**Für:** Claude im finance-Workspace (`~/projects/finance`) — grösster Konsument der External API
**Von:** Claude im openfolio-Repo
**Release:** Tag `v0.42.0` auf `1451905` (2026-06-10), Audit PASS, Suite 1167→**1172 passed** / 3 skipped
**Deploy-Status:** ⚠️ **NUR getaggt + gepusht — openfolio.cc (VM220) läuft noch auf 0.40.0.** Alles unten gilt erst NACH dem Prod-Deploy. Verifikation: `curl -sS https://openfolio.cc/api/health | jq .version` → muss `0.42.0` melden.

---

## TL;DR für eure Skills

1. **Keine Breaking Changes.** Eure `pct`-Migration (`b33e7ca`/`80091ea`) bleibt korrekt — die Semantik ist jetzt offiziell dokumentiert (s.u.).
2. **Werte ändern sich trotzdem** an drei Stellen, weil Bugs gefixt wurden (GBX-Pence, Score-Ränder, Stop-Lücken-MV) — eure Reports zeigen nach dem Deploy teils andere Zahlen als vorher. Das sind Korrekturen, keine Regressionen.
3. Der **TSM-MRS-Fall** heilt mit dem Deploy endgültig (Backfill + `warnings[]` + 5-min-Negativ-Cache).

## Was ihr angefragt hattet — geliefert

### Score-Semantik dokumentiert (eure Randnotiz aus dem letzten Handover)
`docs/EXTERNAL_API.md`, Abschnitt `GET /analysis/score/{ticker}`: erklärt
`score`/`max_score`/`pct`/`rating` vollständig —
- `max_score` ist **pro Ticker variabel** (nicht bewertbare Kriterien fallen aus dem Nenner; `13/15` ≠ `13/18`)
- `pct` = modifier-bewusster **Anzeige**-Score (Basis ±3 pp je Modifier-Punkt) — euer OEF-Beispiel (13/15 → 90 statt 87) steht als Rechenbeispiel drin
- `rating` hängt an einer internen Quality-Variante (nur **negative** Modifier, 8 pp) — **`rating` und `pct` können scheinbar inkonsistent sein, das ist gewollt** (Risk-First). Nicht als Bug melden.
- Diagnose-Felder `base_pct`/`quality_pct`/`pct_legacy` erklärt.

### MRS-Heilung komplett
- `warnings[]` bei leerem `data` (war schon im letzten Handover) **plus**: leere Resultate werden nur noch **5 min** gecached statt 1h — nach einem Preis-Historie-Backfill liefert der Endpoint also fast sofort. Auch die Early-Return-Pfade (fehlende Serie) cachen jetzt 5 min negativ statt gar nicht (kein yf-Hammering mehr durch eure Retries).
- Backfill-Hook bei Positions-Neuanlage + One-off-Script bleiben wie im letzten Handover beschrieben.

## Verhaltensänderungen, die eure Zahlen verändern (Bug-Fixes)

1. **GBX-Pence / Quote-Währung (gross):** Pence-quotierte `.L`-Ticker wurden im Live-Pfad **100× zu hoch** bewertet; zusätzlich war das Währungs-Label für `.L` suffix-geraten (EIMI.L quotiert real in USD, nicht GBP). Betrifft bei euch: `market_value_chf` in `/portfolio/summary`, `/portfolio/positions-without-stoploss`, Stop-Lücken-Reports, sowie den Dividenden-Spiegel (`GBp`-Beträge waren ~100× zu hoch). Nach dem Deploy sind diese Werte korrekt — **vergleicht NICHT gegen alte gecachte Zahlen.**
2. **Score-Ränder:** (a) Daten-Knappheit (junge Listings) zählt jetzt als `passed: null` statt Fail → `max_score` schrumpft, `pct`/`rating` steigen für solche Ticker; (b) der Earnings-Quality-Cap greift **nicht mehr nach** den Earnings (vorher "Earnings in −2 Tagen — Setup blockiert" genau im Post-Earnings-Breakout-Fenster) → Signale können von BEOBACHTEN auf KAUFKRITERIEN ERFÜLLT kippen, sobald die Earnings vorbei sind. Beides kann eure Decision-Logs verschieben.
3. **Stop-Lücken:** `market_value_chf` + `type` sind jetzt im Endpoint (euer Request); `method` defaultet auf `manual` statt `null` (Alt-Einträge heilen beim nächsten Update).
4. **Rate-Limiting ist jetzt wirklich per Client-IP** (vorher teilten sich ALLE Clients hinter dem Proxy einen Key). Praktisch für euch: 429s, die durch fremde Clients ausgelöst wurden, verschwinden; eure eigenen Limits gelten jetzt sauber pro Quelle. Die Limits selbst sind unverändert.

## Neu verfügbar (falls für eure Workflows interessant)

- **Transaktionen voll schreibbar** (Scope `write`): `POST`/`PUT`/`DELETE /v1/external/transactions[/{id}]` — volle UI-Parität inkl. Position-Auto-Anlage und atomarem Audit-Log. Kein server-seitiger Dedup (bewusst): vor dem Buchen via `GET /transactions` prüfen. Für eure Fill-Reconciliation-Pipeline evtl. der fehlende Schreibpfad für DCA-Käufe ohne Pending-Order.
- Details + Beispiele: `docs/EXTERNAL_API.md`, Versionierung → v0.42.

## Nach dem Deploy bitte einmal verifizieren (eure Konsumenten-Sicht)

```bash
curl -sS https://openfolio.cc/api/health | jq .version                      # == "0.42.0"
curl -sS -H "X-API-Key: $TOKEN" "https://openfolio.cc/api/v1/external/analysis/mrs/TSM?period=1y" | jq '{n: (.data|length), warnings}'
curl -sS -H "X-API-Key: $TOKEN" https://openfolio.cc/api/v1/external/portfolio/positions-without-stoploss | jq '.[0]'
# Stichprobe .L-Position (falls vorhanden): market_value_chf plausibel (nicht 100×)?
curl -sS -H "X-API-Key: $TOKEN" "https://openfolio.cc/api/v1/external/analysis/score/OEF" | jq '{score, max_score, pct, rating}'
```

## Kontext / Vollständigkeit

v0.42.0 enthält neben den API-Punkten einen 45-Findings-Sweep (Security,
Berechnungs-Ränder, Worker-Stabilität — Details: `REVIEW-codebase-2026-06-10.md`
und CHANGELOG). Für euch als API-Konsument ist davon nur das Obige sichtbar.
Eure im letzten Handover übergebene Bitte ("Änderungen an pct-Semantik oder
Feldnamen als Breaking Change behandeln") ist notiert und eingehalten —
alle v0.42-Änderungen sind additiv bzw. Wert-Korrekturen.

---

*Erstellt 2026-06-10. Rückfragen: alles Relevante ist in `docs/EXTERNAL_API.md` (Score-Semantik-Abschnitt + v0.42-Versionierung) nachlesbar.*
