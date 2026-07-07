# OpenFolio External REST API (v1)

Versionierte REST-API für externe Konsumenten (z.B. eine andere
Claude-Code-Instanz, eigene Skripte, Reporting-Tools).

- **Base URL:** `https://<deine-openfolio-instanz>/api/v1/external`
  (Beispiel: `https://app.openfolio.cc/api/v1/external` — die App und damit die
  API laufen unter **app.openfolio.cc**; `openfolio.cc` zeigt die Marketing-Website)
- **Auth:** `X-API-Key: ofk_...` Header
- **Scopes:** `read` (Default, alle Tokens) + optional `write`. Ab **v0.46** ist
  der `write`-Scope volle UI-Paritaet: jede Funktion, die im UI moeglich ist, geht
  auch ueber die API (Positionen, Transaktionen, Immobilien, Private Equity,
  Edelmetalle, Buckets, Dividenden, Watchlist/Tags, Alarme, Pending Orders,
  Stop-Loss, Resistance, ETF-Sektoren, EPS-Schwellen, Screening-Scan,
  Performance-Aktionen, Import, Settings/Onboarding, Report-Vault). **Ausgenommen**
  (bewusst NICHT exponiert): Secret-Writes (SMTP/ntfy/FRED/FMP/Finnhub-Keys,
  API-Token-Erstellung), Auth/Identitaet und Admin-Funktionen.
- **Rate-Limit:** `30/minute` pro API-Key (Backend) + `60/minute` pro IP (nginx, Burst 60)
- **CORS:** nicht aktiv (nicht für Browser-Aufrufe gedacht)
- **PII-Verhalten (v0.38+):** Der Token-Eigentümer darf seine eigenen Daten lesen.
  `bank_name`, `address`, `notes`, `tenant`, `mortgage.bank` werden als Klartext
  ausgeliefert.  **Einzige Ausnahme:** `iban` ist ausschliesslich maskiert
  (letzte 4 Stellen, Pattern `••••...1234`) — identisch zum internen UI über
  `decrypt_and_mask_iban`.  Keine zusätzliche Hürde, sondern Konsistenz.

## Deployment

Die External API teilt sich Domain und nginx-Reverse-Proxy mit dem Frontend.
Wenn deine OpenFolio-Instanz bereits öffentlich erreichbar ist (via
Cloudflare Tunnel, nginx/Caddy mit Let's Encrypt, Traefik o.ä.), ist
`/api/v1/external/*` **automatisch mit freigegeben** — keine zusätzliche
Konfiguration nötig. `frontend/nginx.conf` proxyt `location /api/` an den
Backend-Container weiter.

**Nur lokal**: Bei einem reinen Localhost-Setup ohne Public Ingress läuft
die API unter `http://localhost:8000/api/v1/external` auf demselben Host wie
OpenFolio. Für LAN-Zugriff einen SSH-Tunnel verwenden:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<openfolio-host>
```

**Sicherheits-Hinweis**: Der `X-API-Key` Header wird im Klartext gesendet.
Niemals über unverschlüsseltes HTTP im Internet freigeben — immer TLS
(HTTPS) verwenden.

## Token-Management

Tokens werden in der OpenFolio-UI verwaltet (Einstellungen -> API-Tokens) oder
über die JWT-geschützten Endpoints unter `/api/settings/api-tokens`.

In den Beispielen steht `$OPENFOLIO_HOST` als Platzhalter — setze ihn auf
deine Instanz, z.B. `export OPENFOLIO_HOST=https://app.openfolio.cc` oder
`export OPENFOLIO_HOST=http://localhost:8000` für lokale Entwicklung.

### Token erstellen

```bash
# Read-only Token (Default — bestehender Vertrag)
curl -X POST $OPENFOLIO_HOST/api/settings/api-tokens \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Claude Code Laptop","expires_in_days":90}'

# Token mit Schreib-Scope (Watchlist-Notizen + Preis-Alarme)
curl -X POST $OPENFOLIO_HOST/api/settings/api-tokens \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Claude Code Writer","expires_in_days":90,"write_access":true}'
```

Response (Klartext-Token wird **nur einmal** zurückgegeben):

```json
{
  "id": "5f3b...",
  "name": "Claude Code Laptop",
  "prefix": "ofk_a1b2c3d4",
  "scopes": ["read"],
  "token": "ofk_a1b2c3d4e5f6...full-256-bit-token",
  "created_at": "2026-04-08T12:00:00",
  "expires_at": "2026-07-07T12:00:00"
}
```

Bewahre den Token sicher auf — er wird nicht erneut angezeigt.

`scopes` enthält bei Read-Only-Tokens `["read"]`, bei Schreib-Tokens
`["read", "write"]`. Der Scope wird bei der Erstellung festgelegt und kann
später nicht geändert werden — wenn andere Rechte gebraucht werden, alten
Token widerrufen und neuen erstellen.

### Tokens auflisten

```bash
curl $OPENFOLIO_HOST/api/settings/api-tokens \
  -H "Authorization: Bearer <jwt>"
```

### Token widerrufen

```bash
curl -X DELETE $OPENFOLIO_HOST/api/settings/api-tokens/<token-id> \
  -H "Authorization: Bearer <jwt>"
```

## Authentifizierung

Alle externen Endpoints (ausser `/health`) erwarten den Header:

```
X-API-Key: ofk_<token>
```

Bei fehlendem, ungültigem, abgelaufenem oder widerrufenem Token wird ein
generischer **401 Unauthorized** zurückgegeben.

X-API-Key-Tokens sind von der globalen MFA-Erzwingungs-Policy (ab v0.54.0)
ausgenommen und funktionieren unabhängig vom eingestellten `mfa_policy` weiter.

### Scopes

| Scope | Was er erlaubt |
|---|---|
| `read` | Alle GET-Endpoints. Notizen sind ab v0.38 immer sichtbar (auch read-only Tokens), inklusive der `notes_last_api_*`-Marker für Provenienz. |
| `write` | Zusätzlich `PATCH /watchlist/{ticker}/notes` (Notizen setzen/anhängen), vollständiges CRUD auf `/alerts` (Preis-Alarme erstellen, aktualisieren, löschen), vollständiges CRUD + `/fill` auf `/pending-orders`, volles CRUD auf `/transactions` (Buchen via `POST`, Ändern via `PUT`, Löschen via `DELETE`) und Schreib-Zugriff auf den Report-Vault (`POST`/`PATCH`/`DELETE /reports` + `POST /reports/prune`). Tokens mit `write` sehen `notes` auch im GET-Response, damit Append-Workflows die Vor-Notiz lesen können. |

Mutationen ohne den `write`-Scope antworten mit **403 Forbidden** und der
Meldung *"Dieser Token hat keine Schreib-Berechtigung (fehlender Scope: write)"*.

`GET /alerts` ist **nicht** scope-gated — auch Read-Only-Tokens dürfen ihre
eigenen Alarme listen, damit ein Skript vor dem Schreiben prüfen kann, ob
ein Alarm bereits existiert.

## Endpoints

| Method | Pfad | Beschreibung |
|---|---|---|
| GET | `/health` | Liveness-Probe (keine Auth) |
| GET | `/portfolio/summary` | Totale, Allokationen, Positionsliste |
| GET | `/portfolio/upcoming-earnings?days=N&include_etfs=bool` | Nächste Earnings-Termine der Portfolio-Positionen (Finnhub, 12h gecacht) |
| GET | `/positions` | Liste aller aktiven Positionen (inkl. bank_name + maskierte iban) |
| GET | `/positions/{ticker}` | Einzelposition nach Ticker |
| GET | `/positions/by-id/{position_id}` | Einzelposition nach UUID — für den Stop-Loss-PATCH-Workflow |
| GET | `/positions/by-id/{position_id}/history` | Transaktionshistorie der Position |
| GET | `/positions/by-id/{position_id}/dividends` | Dividendenhistorie aus yfinance |
| GET | `/positions/without-type` | Aktive Positionen ohne core/satellite-Klassifikation |
| GET | `/transactions?type=&ticker=&date_from=&date_to=&search=&page=&per_page=` | Transaktionen (paginiert), gleiche Filter wie UI |
| POST | `/transactions` | **Scope `write`** — Transaktion direkt buchen (volle Paritaet zum UI). Caller-seitiger Dedup-Check erwartet. Eine passende offene Pending-Order (gleicher Ticker/Seite, exakt gleiche Stueckzahl, ±35d) wird dabei automatisch auf `filled` gesetzt + verlinkt — kein separates `/fill` noetig |
| PUT | `/transactions/{txn_id}` | **Scope `write`** — Transaktion aendern (Position/Ticker/Typ nicht aenderbar) |
| DELETE | `/transactions/{txn_id}` | **Scope `write`** — Transaktion loeschen (Positions-Wirkung wird rueckgaengig gemacht) |
| GET | `/dividends/pending?status=pending&limit=50` | Pending-Dividenden mit historischer FX am Ex-Date |
| GET | `/dividends/count` | Counter für pending Dividenden (Sidebar-Badge) |
| GET | `/private-equity` | Aktive PE-Beteiligungen + Summary |
| GET | `/private-equity/{holding_id}` | Detail einer Beteiligung inkl. Valuations + Dividends |
| GET | `/portfolio/positions-without-stoploss` | Aktive Positionen (shares > 0) ohne gesetzten Stop-Loss |
| GET | `/portfolio/stop-loss-status` | Stop-Loss-Status aller Tradables (price/method/distance/confirmed) |
| PATCH | `/positions/by-id/{position_id}/stop-loss` | **Scope `write`** — Stop-Loss setzen. `confirmed_at_broker` Default = `false`. |
| POST | `/portfolio/stop-loss/batch` | **Scope `write`** — Batch-Setting (Cap: 100 Items pro Request) |
| GET | `/performance/history?period=1m\|3m\|ytd\|1y\|all&benchmark=^GSPC&raw=false&liquid=false&bucket_id=` | History (tägliches `portfolio_indexed`). `raw=true` → ungedownsamplete Tageskurve (keine 5-Tage-Ausdünnung), verankert an echter Inception (erste Transaktion statt 2000-Default), kein synthetisches Pre-Inception. `liquid=true` → nur Rendite-Risikobuch (Cash + Vorsorge raus; stock/etf/crypto/commodity inkl. Gold+BTC), damit konstanter Ballast Faktor-Betas/Vol nicht dämpft. `bucket_id` (v0.48) skopiert die Kurve auf die Positionen eines Buckets (gleiche `portfolio_indexed`-Methodik). PE + Immobilien immer ausgeschlossen |
| GET | `/performance/monthly-returns?bucket_id=` | Modified-Dietz Monatsrenditen, Jahres-Total = XIRR/MWR. `bucket_id` (v0.53) skopiert auf einen Bucket (identisch zu `/buckets/{id}/monthly-returns`, TWR aus Bucket-Snapshots); vorher wurde der Param still ignoriert und das Gesamtportfolio geliefert |
| GET | `/performance/total-return` | XIRR-basierte Total Return |
| GET | `/performance/drawdown?period=ytd\|1m\|...` | Max-Drawdown + Brake-Flag (≥6%) |
| GET | `/performance/realized-gains` | Realisierte Gewinne |
| GET | `/performance/daily-change` | Tagesveränderung |
| GET | `/performance/benchmark-returns?ticker=^GSPC` | Monatliche Benchmark-Returns (GSPC/IXIC/STOXX50/SSMI) |
| GET | `/performance/fee-summary` | Gebühren- und Steuer-Aggregat |
| GET | `/performance/risk-metrics?period=1y\|2y\|3y\|5y\|all&benchmark=^GSPC&bucket_id=` | **v0.48** — Risiko-Kennzahlen (Sharpe/Sortino/Calmar/Volatilität/Information-Ratio + Rolling-Returns + Max-Drawdown) aus der cash-flow-bereinigten Index-Reihe. `risk_free_rate_pct` aus `RISK_FREE_RATE_PCT`. Default `5y`. `bucket_id` skopiert auf einen Bucket. Bei zu wenig Historie: 422. |
| GET | `/performance/allocation/core-satellite?view=liquid` | Core/Satellite-Allocation |
| GET | `/analysis/score/{ticker}` | Setup-Score + Concentration-Block + Liquid-Portfolio-Wert |
| GET | `/analysis/heartbeat/{ticker}` | ATR-Compression Heartbeat + Wyckoff-Volumen-Sub-Layer |
| GET | `/analysis/breakouts/{ticker}?period=1y` | Donchian-20d Breakout-Events |
| GET | `/analysis/mrs/{ticker}?period=1y` | Mansfield Relative Strength History. Bei leerem `data` enthält die Antwort `warnings[]` (Preisserie fehlt oder Wochen-Historie < 14) statt eines stillen `[]` |
| GET | `/analysis/levels/{ticker}` | Support / Resistance Levels |
| GET | `/analysis/reversal/{ticker}` | 3-Punkt-Reversal-Signal |
| GET | `/analysis/correlation-matrix?period=30d\|90d\|180d\|1y&bucket_id=` | Korrelations-Matrix + HHI-Konzentration (24h gecacht). `bucket_id` (v0.39) filtert auf Positionen eines Buckets. |
| GET | `/analysis/factor-decomposition?period=1y\|2y\|3y\|5y\|all&bucket_id=` | Serverseitige OLS-Faktor-Decomposition der liquiden Portfolio-Returns gegen SPY/MTUM/VLUE/QUAL/IWM/GLD/BTC-USD/USDCHF — Betas, t-Stats, R², n_obs. NYSE-Session-aligned, 1h gecacht. Default `all`. `bucket_id` (v0.48) regressiert nur die liquiden Positionen eines Buckets. |
| GET | `/macro/ch` | Schweizer Makro-Snapshot (SNB, SARON, FX, CPI, 10Y, SMI-vs-SP500), 6h gecacht |
| GET | `/market/sectors` | Sektor-Rotation der 11 SPDR-ETFs mit 1D/1W/1M/3M Performance und Trend |
| GET | `/market/sectors/{etf}/holdings` | SPDR-Sektor-ETF Holdings + Setup-Scores |
| GET | `/market/sectors/{etf}/scores` | Setup-Scores aller Holdings (24h Cache) |
| GET | `/market/industries?period=ytd&top=15` | Branchen-Rotation der ~129 US-Industries (24h Cache) |
| GET | `/market/industries/{slug}/members?limit=50` | Einzelaktien einer Branche, nach MCap (Drill-down, 24h Cache) |
| GET | `/market/climate` | Markt-Klima inkl. Macro-Gate, Tech-Checks, VIX/SARON |
| GET | `/market/vix` | VIX-Snapshot |
| GET | `/market/macro-indicators` | 5 Makro-Crash-Indikatoren mit Ampel-Status + Gate |
| GET | `/market/fx/{from}?to=CHF` | FX-Spot-Rate (Default Ziel: CHF) |
| GET | `/market/precious-metals` | Gold/Silber-Spot + Gold-Silver-Ratio |
| GET | `/market/real-estate` | Immobilien-Markt-Benchmark (Schweizer Indizes) |
| GET | `/market/crypto-metrics` | Krypto-Metriken (BTC-Dominance, F&G, Halving, DXY, BTC-ATH-Distanz) |
| GET | `/stock/search?q=...` | Ticker-Suche: zuerst eigene Positionen, dann yfinance |
| GET | `/stock/{ticker}/profile` | Company-Profil (Sector/Industry/MCap/Margins) |
| GET | `/etf-sectors/{ticker}` | User-spezifische Sektor-Gewichtungen für Multi-Sektor-ETFs |
| GET | `/watchlist` | Watchlist mit Preisen, Tags, Alert-Counts. **`notes` + `notes_last_api_*` Marker werden immer ausgeliefert** (Provenienz für Sync) |
| GET | `/watchlist/tags` | Eigene Watchlist-Tags |
| POST | `/watchlist` | **Scope `write`** — Ticker zur Watchlist hinzufügen (max. 200 aktive pro User) |
| DELETE | `/watchlist/{ticker}` | **Scope `write`** — Ticker entfernen. Cascade-Verhalten wie im UI |
| PATCH | `/watchlist/{ticker}/notes` | **Scope `write`** — Notiz setzen oder mit Trenner `\n\n---\n` anhängen (max. 10 000 Zeichen) |
| GET | `/alerts?ticker=&active=&triggered=` | Eigene Preis-Alarme listen |
| GET | `/alerts/triggered` | Kürzlich ausgelöste Alarme der letzten 7 Tage |
| POST | `/alerts` | **Scope `write`** — Neuen Preis-Alarm anlegen (max. 100 aktive pro User) |
| PATCH | `/alerts/{alert_id}` | **Scope `write`** — Alarm aktualisieren |
| DELETE | `/alerts/{alert_id}` | **Scope `write`** — Alarm löschen |
| GET | `/pending-orders?status=open\|closed\|all` | Manuell gepflegte Limit-Orders. **`notes` + Marker werden immer ausgeliefert** |
| POST | `/pending-orders` | **Scope `write`** — Neue Pending Order anlegen (max. 100 pro User) |
| PATCH | `/pending-orders/{order_id}` | **Scope `write`** — Order aktualisieren. Bei `status='filled'` nur `notes` editierbar |
| DELETE | `/pending-orders/{order_id}` | **Scope `write`** — Order entfernen (auch gefillte) |
| POST | `/pending-orders/{order_id}/fill` | **Scope `write`** — Atomar: Transaktion anlegen + Status `filled`. Hinweis: nicht noetig, wenn die Ausfuehrung ohnehin als Transaktion gebucht/importiert wird — die Order wird dann automatisch gefuellt (Fill-Reconciliation). `/fill` nur nutzen, wenn die Order die Transaktion *erst erzeugen* soll, sonst droht eine Duplikat-Buchung |
| GET | `/screening/latest?min_score=1` | Letzte Screening-Ergebnisse + `pipeline_health` |
| GET | `/screening/results?min_score=1&signal_type=&sector_momentum=&page=&per_page=` | Paginiertes Screening mit Filtern |
| GET | `/screening/ticker/{ticker}` | Screening-Resultat eines einzelnen Tickers |
| GET | `/screening/scan/{scan_id}/progress` | Scan-Fortschritt (Polling nach `POST /screening/scan`) |
| GET | `/screening/macro/cot` | CFTC COT Macro-Positionierung |
| GET | `/precious-metals` | Edelmetall-Bestände, gruppiert nach Metall-Typ |
| GET | `/precious-metals/sold` | Verkaufte Bestände |
| GET | `/precious-metals/expenses?metal_type=` | Edelmetall-Ausgaben |
| GET | `/precious-metals/expenses/summary` | Annualisierte Aggregate pro Kategorie |
| GET | `/immobilien` | Alle Immobilien inkl. Hypotheken (Klartext: address/notes/bank) |
| GET | `/immobilien/{property_id}` | Detailansicht einer einzelnen Immobilie |
| GET | `/immobilien/{property_id}/hypotheken` | Hypotheken einer Immobilie |
| GET | `/vorsorge` | Alle Vorsorge-Konten (Säule 3a, inkl. bank_name + maskierte iban) |
| GET | `/vorsorge/{position_id}` | Detailansicht eines Vorsorge-Kontos |
| GET | `/settings` | User-Settings (base_currency, broker, Stop-Loss-Defaults). API-Keys als `has_*`-Boolean |
| GET | `/settings/alert-preferences` | Pro-Kategorie Alert-Präferenzen |
| GET | `/settings/onboarding/status` | Onboarding-Tour-Status |
| GET | `/taxonomy/sectors` | Sektor/Industrie-Hierarchie |
| GET | `/buckets?include_deleted=false` | **v0.39** — Liste aller Buckets des Users (User + System) inkl. `risk_rules`, `benchmark`, `color`, `target_pct`/`target_chf`. |
| GET | `/buckets/allocations` | **v0.39** — Live-Allokation pro Bucket (value_chf, pct). PE/Real-Estate excluded analog interner UI. |
| GET | `/buckets/{bucket_id}/summary` | **v0.39** — Marktwert + Cost-Basis + Unrealized PnL eines Buckets inkl. `running_peak_chf`. |
| GET | `/buckets/{bucket_id}/history?period=ytd\|1m\|3m\|6m\|1y\|all` | **v0.39** — Snapshot-Zeitreihe (date, total_value_chf, net_cash_flow_chf, running_peak_chf). |
| GET | `/buckets/{bucket_id}/drawdown?period=ytd\|1m\|...` | **v0.39** — Peak-to-Trough-Drawdown pro Bucket. `drawdown_brake_active=true` wenn die in `bucket.risk_rules.drawdown_brake_pct` konfigurierte Schwelle erreicht ist. |
| GET | `/buckets/{bucket_id}/benchmark-comparison?period=ytd\|...` | **v0.39** — Bucket-Return vs. konfiguriertem Benchmark (Compound der Monatsrenditen) inkl. Delta. |
| GET | `/buckets/{bucket_id}/monthly-returns` | **v0.39** — Monatsrenditen + Jahres-Totale eines Buckets (vereinfachtes cashflow-bereinigtes Wealth-Index-Verfahren). |
| GET | `/buckets/{bucket_id}/total-return` | **v0.48** — Bucket-skopierter Total-Return-Breakdown (Schema analog `/performance/total-return`). `total_return_pct` ist Geld-auf-Geld (`is_money_weighted=false`); die zeitgewichtete Rendite liefert `/benchmark-comparison` + `/monthly-returns`. |
| GET | `/buckets/{bucket_id}/fee-summary` | **v0.48** — Monatlicher Gebühren-/Steuer-Breakdown eines Buckets (Schema analog `/performance/fee-summary`). |
| GET | `/eps-scanner/results?super_quarter_only=&record_quarter_only=&turnaround_only=&min_quarters=&sector=&index=&search=&sort_by=&sort_asc=&page=&per_page=` | **v0.44** — EPS-Scanner-Ergebnistabelle (S&P 1500 + Portfolio/Watchlist). Paginiert, alle Filter kombinierbar. `index`-Filter: sp500/sp400/sp600. |
| GET | `/eps-scanner/thresholds` | **v0.44** — Aktive Filter-Schwellen des Token-Eigentümers (Super-Quartal-YoY-Grenze, Beschleunigungs-Margin, Ausreisser-Faktor). |
| GET | `/eps-scanner/status` | **v0.44** — Daten-Freshness des EPS-Scanners (letzter Worker-Lauf, Universe-Grösse). |
| GET | `/reports?category=&tag=&q=&source=&date_from=&date_to=&archived=&page=&per_page=` | Report-Vault: Markdown-Briefe des Users, Metadaten **ohne** `body`, gefiltert + paginiert. Liefert je Eintrag `id` + `archived_at`. Standardmäßig nur **aktive** Reports; `archived=true` zeigt ausschliesslich das Archiv. |
| GET | `/reports/{report_id}` | Voller Report inkl. Markdown-`body` (auch für archivierte). |
| POST | `/reports` | **Scope `write`** — Brief hochladen. Idempotenter Upsert über `source_path` (gleicher Hash → `unchanged`, neuer Body → `updated`); user-editierte `tags` bleiben erhalten; ein zuvor archivierter/geprunter Report wird beim Re-Upload reaktiviert. Limit 5000 Reports/User. |
| PATCH | `/reports/{report_id}` | **Scope `write`** — Report partiell ändern (`title`/`category`/`report_date`/`body`/`tags`). Nur übergebene Felder; `tags: []` leert die Tags; Body-Änderung berechnet `content_hash` neu. |
| POST | `/reports/{report_id}/archive` | **Scope `write`** — Report ins Archiv verschieben (reversibler Soft-Delete, kein Datenverlust). Verschwindet aus der Default-Liste, sichtbar unter `?archived=true`. Idempotent. |
| POST | `/reports/{report_id}/unarchive` | **Scope `write`** — Report aus dem Archiv zurück in die aktive Ansicht holen. |
| DELETE | `/reports/{report_id}` | **Scope `write`** — Einzelnen Report **endgültig** löschen (204, kein Undo). Für reversibles Entfernen `archive` nutzen. |
| POST | `/reports/prune` | **Scope `write`** — Reconciliation: **archiviert** Vault-Waisen einer `source` (deren `source_path` nicht in `source_paths` steht); Re-Upload reaktiviert. Antwort `{archived, kept}`. Leere Liste = bewusster No-op. |

### UI-Paritaet — Schreib-Endpoints (v0.46)

Alle folgenden Endpoints erfordern Scope `write` und hinterlassen einen `ApiWriteLog`-Eintrag. Sie spiegeln 1:1 das interne UI.

| Method | Pfad | Beschreibung |
|---|---|---|
| POST | `/positions` | Position anlegen (Bucket-Auto-Zuordnung, PII-Verschluesselung, Sektor-Ableitung wie UI) |
| PUT | `/positions/by-id/{position_id}` | Position aendern |
| DELETE | `/positions/by-id/{position_id}` | Position loeschen (Snapshot-Regen) |
| POST | `/positions/recalculate` | Cost-Basis aller Positionen neu rechnen |
| POST | `/positions/by-id/{position_id}/recalculate` | Einzelne Position neu rechnen |
| POST | `/immobilien` | Immobilie anlegen |
| PUT | `/immobilien/{property_id}` | Immobilie aendern |
| DELETE | `/immobilien/{property_id}` | Immobilie loeschen |
| POST | `/immobilien/{property_id}/hypotheken` | Hypothek anlegen |
| PUT | `/immobilien/hypotheken/{mortgage_id}` | Hypothek aendern |
| DELETE | `/immobilien/hypotheken/{mortgage_id}` | Hypothek loeschen |
| POST | `/immobilien/{property_id}/ausgaben` | Ausgabe anlegen |
| PUT | `/immobilien/ausgaben/{expense_id}` | Ausgabe aendern |
| DELETE | `/immobilien/ausgaben/{expense_id}` | Ausgabe loeschen |
| POST | `/immobilien/{property_id}/einnahmen` | Einnahme anlegen |
| PUT | `/immobilien/einnahmen/{income_id}` | Einnahme aendern |
| DELETE | `/immobilien/einnahmen/{income_id}` | Einnahme loeschen |
| POST | `/private-equity` | PE-Beteiligung anlegen |
| PUT | `/private-equity/{holding_id}` | PE-Beteiligung aendern |
| DELETE | `/private-equity/{holding_id}` | PE-Beteiligung loeschen |
| POST | `/private-equity/{holding_id}/valuations` | Bewertung anlegen |
| PUT | `/private-equity/{holding_id}/valuations/{valuation_id}` | Bewertung aendern |
| DELETE | `/private-equity/{holding_id}/valuations/{valuation_id}` | Bewertung loeschen |
| POST | `/private-equity/{holding_id}/dividends` | PE-Dividende anlegen |
| PUT | `/private-equity/{holding_id}/dividends/{dividend_id}` | PE-Dividende aendern |
| DELETE | `/private-equity/{holding_id}/dividends/{dividend_id}` | PE-Dividende loeschen |
| POST | `/precious-metals` | Edelmetall-Bestand anlegen |
| PUT | `/precious-metals/{item_id}` | Edelmetall-Bestand aendern |
| DELETE | `/precious-metals/{item_id}` | Edelmetall-Bestand loeschen |
| POST | `/precious-metals/expenses` | Edelmetall-Ausgabe anlegen |
| PUT | `/precious-metals/expenses/{expense_id}` | Edelmetall-Ausgabe aendern |
| DELETE | `/precious-metals/expenses/{expense_id}` | Edelmetall-Ausgabe loeschen |
| POST | `/dividends/{pending_id}/confirm` | Pending-Dividende bestaetigen (bucht Dividenden-Transaktion) |
| POST | `/dividends/{pending_id}/dismiss` | Pending-Dividende verwerfen |
| POST | `/buckets` | Bucket anlegen |
| PATCH | `/buckets/{bucket_id}` | Bucket aendern |
| DELETE | `/buckets/{bucket_id}` | Bucket loeschen (Positionen → Liquid-Default) |
| POST | `/buckets/from-template` | Bucket-Set aus Vorlage anlegen |
| POST | `/buckets/migration-rollback` | Bucket-Migration zurueckrollen |
| POST | `/buckets/import-rules` | Import-Bucket-Mapping-Regel anlegen |
| DELETE | `/buckets/import-rules/{rule_id}` | Import-Regel loeschen |
| POST | `/buckets/backfill-snapshots` | Bucket-Snapshots rueckwirkend backfillen |
| POST | `/buckets/onboarding-dismiss` | Bucket-Migrations-Modal schliessen |
| POST | `/positions/by-id/{position_id}/split-to-bucket` | Position teilweise in anderen Bucket splitten |
| POST | `/positions/by-id/{position_id}/move-to-bucket` | Position in anderen Bucket verschieben |
| POST | `/performance/recalculate` | Cost-Basis-Recalc + Snapshot-Regen |
| POST | `/performance/fix-total-chf` | total_chf aus FX-Rate korrigieren |
| POST | `/performance/regenerate-snapshots` | Alle Portfolio-Snapshots neu bauen |
| POST | `/performance/earnings/refresh` | Earnings-Termine aktualisieren |
| POST | `/screening/scan` | Screening-Scan starten (1/Tag; Fortschritt via `/screening/scan/{id}/progress`) |
| PUT | `/etf-sectors/{ticker}` | ETF-Sektorgewichte setzen (Summe = 100%) |
| DELETE | `/etf-sectors/{ticker}` | ETF-Sektorgewichte loeschen |
| PATCH | `/eps-scanner/thresholds` | EPS-Scanner-Filterschwellen setzen |
| PUT | `/analysis/resistance/{ticker}` | Manuelles Resistance-Level setzen (Positionen + Watchlist) |
| POST | `/watchlist/{item_id}/tags` | Tag an Watchlist-Eintrag haengen (find-or-create, max. 5) |
| DELETE | `/watchlist/{item_id}/tags/{tag_id}` | Tag von Watchlist-Eintrag entfernen |
| PATCH | `/settings` | User-Einstellungen aendern (KEINE Secrets — API-Keys/SMTP/ntfy bleiben gesperrt) |
| PUT | `/settings/alert-preferences` | Alert-Praeferenz pro Kategorie setzen |
| POST | `/settings/onboarding/tour-complete` | Onboarding-Tour abschliessen |
| POST | `/settings/onboarding/hide-checklist` | Onboarding-Checkliste ausblenden |
| POST | `/settings/onboarding/step-complete` | Onboarding-Schritt erledigen |
| POST | `/import/parse` | CSV hochladen + parsen (multipart, Vorschau) |
| POST | `/import/analyze` | CSV-Struktur analysieren (multipart) |
| POST | `/import/parse-with-mapping` | Hochgeladene CSV mit explizitem Mapping parsen |
| POST | `/import/confirm` | Geparste Transaktionen bestaetigen + bulk-inserten (Recalc + Snapshot-Regen) |
| GET | `/import/profiles` | Import-Profile auflisten |
| POST | `/import/profiles` | Import-Profil anlegen |
| DELETE | `/import/profiles/{profile_id}` | Import-Profil loeschen |

> **Hinweis:** Immobilien (HEILIGE Regel 4) und Vorsorge (HEILIGE Regel 5)
> haben bewusst eigene Namespaces. Sie sind **nicht** Teil der liquiden
> Portfolio-Performance unter `/portfolio/*` und `/performance/*` und werden
> dort niemals eingerechnet. Aggregierte Werte (`total_value_chf`, `equity`,
> `current_mortgage`) gelten ausschliesslich innerhalb dieser Namespaces.
>
> **Buckets:** Lesen seit v0.39, **Schreiben seit v0.46** — Bucket-CRUD,
> Templates, Migration-Rollback, Backfill, Import-Rules sowie `move-to-bucket`/
> `split-to-bucket` sind jetzt mit Scope `write` ueber die External-API erreichbar
> (siehe Tabelle oben). Jede Position im `/positions`-Response enthält die Felder
> `bucket_id` (UUID oder `null`) und `risk_rules` (Position-Level-Override,
> meistens `null`).
>
> **Cash-Klassifikation (v0.47):** `POST /positions` und
> `PUT /positions/by-id/{id}` akzeptieren das optionale Feld
> `count_as_cash` (boolean, Default `false`). Ist es `true`, bleibt die Position
> eine regulaer bepreiste Wertschrift — Marktwert = `shares × Kurs × FX`,
> Performance/PnL unveraendert —, wird aber in der Anlageklassen-Allokation
> (`by_type` → `cash`), der Cash-Quote sowie den Portfolio- und Bucket-Snapshots
> (`cash_chf`) als **Cash** gezaehlt und aus der Core/Satellite-Aufteilung
> ausgenommen. Gedacht fuer Geldmarkt-/T-Bill-ETFs. Das Feld wird in jeder
> Position des `/positions`- und `/portfolio/summary`-Response zurueckgegeben.

### EPS-Scanner (v0.44)

Der EPS-Scanner wertet Reported EPS (Quartalsgewinne) für das S&P-Composite-1500-
Universe (S&P 500 + 400 MidCap + 600 SmallCap) sowie deine eigenen Portfolio-
Positionen und Watchlist-Einträge aus. Primärquelle
ist Finnhub (`FINNHUB_SYSTEM_API_KEY`); ohne Key wird auf yfinance zurückgefallen
(geringere Abdeckung). Alle drei Endpoints sind Scope `read` (kein `write` nötig).

#### `GET /eps-scanner/results`

Paginierte Ergebnistabelle mit allen verfügbaren Filtern.

**Query-Parameter:**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `super_quarter_only` | bool | `false` | Nur Ticker mit Super-Quartal-Kriterium (YoY ≥ Schwelle + Beschleunigung + positive Basis) |
| `record_quarter_only` | bool | `false` | Nur Ticker, deren jüngstes Quartal ein neues 8-Q-EPS-Hoch ist |
| `turnaround_only` | bool | `false` | Nur Ticker mit Verlust-zu-Gewinn-Übergang im 8-Q-Fenster |
| `min_quarters` | int (2–8) | `6` | Mindestanzahl gültiger Quartale im Datensatz |
| `sector` | string (wiederholbar) | — | GICS-Sektor-Filter (z.B. `sector=Technology&sector=Health+Care`) |
| `index` | string (wiederholbar) | — | Index-Filter: `sp500`, `sp400` (MidCap), `sp600` (SmallCap), z.B. `index=sp400&index=sp600` für nur Mid+Small Cap |
| `search` | string (max. 50) | — | Freitext-Suche nach Ticker oder Firmenname (server-seitig) |
| `sort_by` | string | `yoy_growth` | Sortierfeld: `ticker`, `yoy_growth`, `streak_count`, `latest_eps` |
| `sort_asc` | bool | `false` | Aufsteigend sortieren |
| `page` | int ≥ 1 | `1` | Seite |
| `per_page` | int (1–200) | `50` | Einträge pro Seite |

Mehrere Filter sind **kombinierbar (UND)**. `super_quarter_only=true` und
`record_quarter_only=true` gleichzeitig liefert also nur Ticker, die beides
erfüllen.

```bash
curl -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/eps-scanner/results?super_quarter_only=true&per_page=20"
```

200 Response:

```json
{
  "results": [
    {
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "sector": "Information Technology",
      "index": "sp500",
      "latest_eps": 0.89,
      "yoy_growth": 168.7,
      "streak_count": 5,
      "super_quarter": true,
      "record_quarter": true,
      "turnaround": false,
      "quarters": [
        {"period": "2024Q4", "eps": 0.89, "yoy_growth": 168.7, "super_quarter": true, "record_quarter": true, "turnaround": false},
        {"period": "2024Q3", "eps": 0.68, "yoy_growth": 103.0, "super_quarter": true, "record_quarter": false, "turnaround": false}
      ]
    }
  ],
  "total": 87,
  "page": 1,
  "per_page": 20,
  "thresholds": {
    "super_quarter_yoy_pct": 25.0,
    "acceleration_margin_pp": 5.0,
    "outlier_multiplier": 10.0
  },
  "data_refreshed_at": "2026-06-23T04:12:34"
}
```

> **Hinweis zu den Schwellen:** `super_quarter_yoy_pct` und
> `acceleration_margin_pp` sind Arbeits-Defaults, noch nicht durch einen
> Forward-Return-Backtest validiert. Die Filterung zeigt Gewinn-Momentum
> — keine Kauf-Empfehlung.

#### `GET /eps-scanner/thresholds`

Aktive Filter-Schwellen des Token-Eigentümers (User-Settings oder Service-Defaults,
falls noch keine individuellen Schwellen gesetzt wurden).

```bash
curl -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/eps-scanner/thresholds"
```

200 Response:

```json
{
  "super_quarter_yoy_pct": 25.0,
  "acceleration_margin_pp": 5.0,
  "outlier_multiplier": 10.0
}
```

| Feld | Beschreibung |
|---|---|
| `super_quarter_yoy_pct` | Mindest-YoY-Wachstum (%) für das Super-Quartal-Kriterium |
| `acceleration_margin_pp` | Mindest-Beschleunigung in Prozentpunkten gegenüber dem Vorquartal |
| `outlier_multiplier` | Ausreisser-Filter: Quartale mit EPS > Faktor × Median werden ausgeblendet |

#### `GET /eps-scanner/status`

Daten-Freshness des EPS-Scanners (universe-global, nicht user-spezifisch).

```bash
curl -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/eps-scanner/status"
```

200 Response:

```json
{
  "last_run_at": "2026-06-23T04:12:34",
  "universe_size": 503,
  "tickers_with_data": 498,
  "source": "finnhub"
}
```

`source` ist `"finnhub"` wenn `FINNHUB_SYSTEM_API_KEY` gesetzt ist, sonst
`"yfinance"`. Der Worker-Job läuft täglich um 04:00 CET. Nach dem ersten Deploy
oder nach dem Setzen des Keys: `last_run_at` ist `null`, bis der erste Cron
abgeschlossen ist.

### Screening-Signale (Signal-Keys im `signals`-Objekt)

| Signal-Key | Quelle | Gewicht | Beschreibung |
|---|---|---|---|
| `insider_cluster` | OpenInsider (Form-4) | +3 | Mehrere Insider kaufen gleichzeitig |
| `superinvestor` | Dataroma | +2 | Superinvestor-Portfolio oder Realtime-Kauf |
| `superinvestor_13f_consensus` | SEC EDGAR 13F-HR | +3 | >=3 getrackte Fonds mit gleicher Q/Q-Aktion |
| `superinvestor_13f_single` | SEC EDGAR 13F-HR | +1 | 1-2 Fonds mit Q/Q-Aktion (informativ) |
| `six_insider` | SIX SER | +3 | Schweizer Management-Transaktion (Pflichtmeldung) |
| `activist` | SEC EDGAR 13D/13G | +2 | Aktivist-Position >5%, ggf. mit `letter_excerpt` und `purpose_tags` |
| `buyback` | SEC EDGAR | +2 | Aktienrückkauf-Ankündigung |
| `large_buy` | OpenInsider (Form-4) | +1 | Grosser Einzelkauf eines Insiders |
| `congressional` | Capitol Trades | +1 | Kongressmitglied-Kauf |
| `unusual_volume` | yfinance | 0 | Volumen >3x Durchschnitt (informativ) |
| `short_trend` | FINRA | -1 | Short-Ratio stark gestiegen |
| `ftd` | SEC | -1 | Hohe Fails-to-Deliver |
| `credit_stress` | -- | -- | Nicht implementiert (TRACE API erfordert Auth) |

## Beispiel-Responses

### `GET /watchlist`

Ab v0.38 werden `notes` (entschlüsselt) und die Marker-Felder
`notes_last_api_write_at` / `notes_last_api_token_name` **immer** ausgeliefert
— auch für read-only Tokens.  Schreiben verlangt weiterhin Scope `write`.

```json
{
  "items": [
    {
      "id": "a1b2c3...",
      "ticker": "CRWD",
      "name": "CrowdStrike Holdings",
      "sector": "Technology",
      "notes": "Pre-Earnings: RSI überkauft, abwarten.\n\n---\nQ4 Beat, +8% AH",
      "notes_last_api_write_at": "2026-05-08T10:30:00",
      "notes_last_api_token_name": "Claude Code Writer",
      "manual_resistance": 425.00,
      "created_at": "2026-03-15T10:00:00",
      "price": 382.50,
      "currency": "USD",
      "change_pct": 1.85,
      "tags": [
        {"id": "t1...", "name": "Breakout-Kandidat", "color": "#22c55e"}
      ],
      "active_alerts": 2
    }
  ],
  "active_alerts_count": 2
}
```

`notes_last_api_write_at` ist der Zeitstempel des letzten API-Schreibvorgangs;
`notes_last_api_token_name` ist ein Snapshot des Token-Namens (kein Foreign
Key — bleibt nach Widerruf erhalten). Beide Felder werden auf `null`
zurückgesetzt, sobald die Notiz manuell über die OpenFolio-UI gespeichert
wird (signalisiert "manuell geprüft"). Der `/watchlist`-Skill braucht diese
Marker, um manuell-vs-via-API unterscheiden zu können — deshalb sind sie
auch für read-only Tokens sichtbar.

### `POST /watchlist`

Erfordert Scope `write`. Fügt einen neuen Ticker zur Watchlist hinzu.
Limit pro User: 200 aktive Einträge. Doppelte Ticker werden mit 409
abgelehnt.

```bash
curl -X POST "$OPENFOLIO_HOST/api/v1/external/watchlist" \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{"ticker":"NVDA","name":"Nvidia","sector":"Technology"}'
```

Body-Felder:

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `ticker` | string (max. 30) | ja | Wird auf Uppercase normalisiert |
| `name` | string (max. 200) | ja | Anzeige-Name |
| `sector` | string (max. 100) | nein | Frei-Text-Sektor |

201 Response:

```json
{
  "id": "a199c950-7e4f-4f76-8972-e3d6d2c6e8b9",
  "ticker": "NVDA",
  "name": "Nvidia",
  "sector": "Technology",
  "created_at": "2026-05-08T16:15:46"
}
```

| Status | Wann |
|---|---|
| `201` | Eintrag angelegt |
| `400` | Watchlist-Limit (200) erreicht |
| `403` | Token hat keinen `write`-Scope |
| `409` | Ticker ist bereits in der Watchlist |
| `422` | Pydantic-Validierung (z.B. `ticker` leer) |

### `DELETE /watchlist/{ticker}`

Erfordert Scope `write`. Entfernt den Ticker aus der Watchlist.

```bash
curl -X DELETE -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/watchlist/NVDA"
```

204 No Content bei Erfolg, 404 wenn der Ticker nicht in der Watchlist
des Users ist (oder einem anderen User gehört).

> **Cascade-Hinweis (identisch zum UI):** Preis-Alarme auf demselben Ticker
> werden nur dann mit-gelöscht, wenn der User keine aktive Position auf
> dem Ticker hält. Stop-Loss-Alarme auf Portfolio-Tickers überleben das
> Entfernen aus der Watchlist.

### `PATCH /watchlist/{ticker}/notes`

Erfordert Scope `write`. Body:

```json
{
  "content": "RSI überkauft, abwarten",
  "mode": "replace"
}
```

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `content` | string (max. 10 000 Zeichen) | — | Notiz-Text. Leerstring + `mode=replace` löscht die Notiz. |
| `mode` | `"replace"` \| `"append"` | `"replace"` | Bei `append` wird der Trenner `"\n\n---\n"` zwischen Vor-Notiz und neuem Inhalt eingefügt. Limit 10 000 gilt nach dem Anhängen. |

Beispiel (Append-Workflow):

```bash
curl -X PATCH "$OPENFOLIO_HOST/api/v1/external/watchlist/AAPL/notes" \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{"content":"Q4 Beat, +8% AH","mode":"append"}'
```

200 Response:

```json
{
  "ticker": "AAPL",
  "mode": "append",
  "char_count": 47,
  "notes_last_api_write_at": "2026-05-08T10:30:00"
}
```

| Status | Wann |
|---|---|
| `200` | Notiz gesetzt / angehängt |
| `403` | Token hat keinen `write`-Scope |
| `404` | Ticker ist nicht in der Watchlist des Users |
| `422` | `content` allein > 10 000 Zeichen (Pydantic) **oder** kombinierter Append-Text > 10 000 Zeichen (server-side, bestehende Notiz bleibt unverändert) |

> **Audit-Log:** Jeder Schreibvorgang wird in `api_write_log` mit
> `action`, `ticker`, `char_count_before`, `char_count_after`, `token_id`
> protokolliert. Der **Inhalt** der Notiz wird **nie** geloggt.

### `GET /alerts`

Listet eigene Preis-Alarme. **Kein Scope-Gate** — auch Read-Only-Tokens
dürfen ihre Alarme sehen.

Query-Parameter (alle optional): `ticker`, `active` (bool), `triggered` (bool).

```bash
curl -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/alerts?ticker=AAPL&active=true&triggered=false"
```

200 Response:

```json
[
  {
    "id": "9d5b...",
    "ticker": "AAPL",
    "alert_type": "price_above",
    "target_value": 250.0,
    "currency": null,
    "is_active": true,
    "is_triggered": false,
    "triggered_at": null,
    "trigger_price": null,
    "notify_in_app": true,
    "notify_email": false,
    "note": "Resistance break",
    "created_at": "2026-05-08T10:00:00",
    "expires_at": null
  }
]
```

### `POST /alerts`

Erfordert Scope `write`. Legt einen neuen Preis-Alarm an. Der Ticker muss
entweder in der **Watchlist** oder als **aktive Position** im Portfolio
existieren — verhindert, dass ein leakender Token beliebige Tickers spammt.
Max. 100 aktive Alarme pro User.

```bash
curl -X POST "$OPENFOLIO_HOST/api/v1/external/alerts" \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","alert_type":"price_above","target_value":250.0,"note":"Breakout über 250"}'
```

Body-Felder:

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `ticker` | string | ja | Wird auf Uppercase normalisiert |
| `alert_type` | `price_above` \| `price_below` \| `pct_change_day` | ja | |
| `target_value` | float > 0 | ja | Schwellwert oder Tagesveränderung in % |
| `currency` | string (max. 3) | nein | z.B. `USD`, `CHF` |
| `notify_in_app` | bool | nein (Default `true`) | |
| `notify_email` | bool | nein (Default `false`) | Pro User-Throttling 1 Mail / 15 min |
| `note` | string (max. 200) | nein | |
| `expires_at` | ISO-8601 datetime | nein | Alarm wird nach diesem Zeitpunkt nicht mehr getriggert |

201 Response: gleiches Schema wie ein Element aus `GET /alerts`.

| Status | Wann |
|---|---|
| `201` | Alarm angelegt |
| `400` | Ticker weder in Watchlist noch im Portfolio aktiv **oder** 100-Alert-Limit erreicht **oder** ungültiger `alert_type` |
| `403` | Token hat keinen `write`-Scope |
| `422` | Pydantic-Validierung (z.B. `target_value <= 0`) |

### `PATCH /alerts/{alert_id}`

Erfordert Scope `write`. Aktualisiert Felder eines bestehenden Alarms. Alle
Body-Felder sind optional; weggelassene bleiben unverändert.

```bash
curl -X PATCH "$OPENFOLIO_HOST/api/v1/external/alerts/9d5b..." \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{"target_value":260.0,"note":"Adjusted threshold"}'
```

Editierbare Felder: `target_value`, `note`, `notify_in_app`, `notify_email`,
`expires_at`. **Nicht** änderbar: `is_triggered`, `is_active`, `ticker`,
`alert_type`. Bereits ausgelöste Alarme können nicht editiert werden — der
Endpoint antwortet mit `400 "Alarm wurde bereits ausgeloest"`.

### `DELETE /alerts/{alert_id}`

Erfordert Scope `write`. 204 No Content bei Erfolg, 404 wenn der Alarm nicht
existiert oder einem anderen User gehört.

```bash
curl -X DELETE -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/alerts/9d5b..."
```

> **Cascade-Hinweis:** Wenn ein Watchlist-Eintrag aus der UI gelöscht wird,
> werden zugehörige Alarme nur dann mitgelöscht, wenn der User keine aktive
> Position auf demselben Ticker hält. Stop-Loss-Alarme auf Portfolio-Tickers
> überleben das Entfernen aus der Watchlist.

### `GET /pending-orders`

Listet manuell gepflegte Limit-Orders, die der User beim Broker platziert
hat aber die noch nicht ausgeführt sind (`open`), schon ausgeführt
(`filled`), storniert (`cancelled`) oder effektiv abgelaufen (`expired`,
nur GTD-Orders).

**Query-Parameter:**

| Parameter | Default | Werte | Beschreibung |
|---|---|---|---|
| `status` | `open` | `open` / `closed` / `all` | `closed` umfasst `filled`, `cancelled` und effektiv-`expired` (GTD mit abgelaufenem `expiry_date`) |

**Wichtig — Computed `effective_status`:** Die DB speichert nur den Roh-
Status (`open|filled|cancelled`). GTD-Orders mit Datum in der Vergangenheit
werden vom Service-Layer beim Read als `expired` ausgewiesen, ohne dass die
DB-Spalte geändert wird. Das Filter-Verhalten oben respektiert das.

```bash
curl -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/pending-orders?status=open"
```

200 Response:

```json
{
  "items": [
    {
      "id": "f01a...",
      "ticker": "AAPL",
      "side": "buy",
      "shares": 10.0,
      "limit_price": 150.0,
      "stop_price": null,
      "currency": "USD",
      "expiry_type": "gtc",
      "expiry_date": null,
      "broker": "IBKR",
      "bucket_id_target": "b08d1569-991d-4dc6-b5ac-b82ba8f99f9c",
      "status": "open",
      "effective_status": "open",
      "linked_transaction_id": null,
      "notes": "Setup nach Pullback-Korrektur",
      "current_price": 152.30,
      "quote_currency": "USD",
      "distance_pct": 0.0151,
      "created_at": "2026-05-08T16:15:46+00:00",
      "updated_at": "2026-05-08T16:15:46+00:00"
    }
  ],
  "counts": {"open": 1, "filled": 0, "cancelled": 0, "expired": 0}
}
```

**`bucket_id_target` (v0.40.1+):** Vorab-Wahl des Buckets für eine
*neue* Position, falls die Order später per `/fill` einen unbekannten
Ticker auto-anlegt. `null` = Fallback auf den `liquid_default`-Bucket
des Users. Wird der Ticker zum Fill-Zeitpunkt schon als Position
existiert, ist das Feld irrelevant — die Position behält ihren Bucket.

**Distance-Semantik:** `distance_pct` ist signed:

- **Positiv** = Order noch nicht erreicht (Spot muss sich noch bewegen).
- **Negativ** = Spot hat den Trigger bereits durchbrochen — entweder ist
  die Order gefillt und die Pending-Liste ist im Drift, oder dein Broker
  hat sie nicht ausgeführt.
- **`null`** = kein Quote oder Currency-Mismatch (`order.currency` ≠
  `quote_currency`). Es wird **bewusst kein FX-Convert** gemacht, weil das
  bei `.L`-Tickern (GBX vs. GBP) zu falschen Alarmen führt.

Formel — `BUY: (current - limit) / current`, `SELL: (limit - current) / current`.

`counts` ist **immer ungefiltert** über alle Records des Users (auch wenn
`?status=open` aktiv ist), damit ein UI-Frontend Tab-Badges konsistent
zeigen kann.

Ab v0.38 werden `notes` und die Marker-Felder `notes_last_api_write_at` /
`notes_last_api_token_name` **immer** ausgeliefert — auch für read-only
Tokens.  Provenienz braucht der Konsument für Sync (manuell vs. via API).

### `POST /pending-orders`

Erfordert Scope `write`. Limit pro User: 100. Tickers werden auf Uppercase
normalisiert. GTD-Orders **müssen** ein `expiry_date` haben; nicht-GTD
Orders dürfen keins haben (Pydantic 422).

```bash
curl -X POST "$OPENFOLIO_HOST/api/v1/external/pending-orders" \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "MSFT",
    "side": "buy",
    "shares": 5,
    "limit_price": 380.0,
    "currency": "USD",
    "expiry_type": "gtc",
    "broker": "IBKR",
    "notes": "Re-entry nach Pullback"
  }'
```

| Feld | Typ | Pflicht | Default | Beschreibung |
|---|---|---|---|---|
| `ticker` | string (max. 30) | ja | — | Wird auf Uppercase normalisiert |
| `side` | `"buy"` \| `"sell"` | ja | — | |
| `shares` | float > 0 | ja | — | Fractional erlaubt |
| `limit_price` | float > 0 | ja | — | |
| `stop_price` | float > 0 | nein | `null` | Für Stop-Limit-Orders |
| `currency` | string (max. 10) | nein | `"USD"` | Wird auf Uppercase normalisiert |
| `expiry_type` | `"gtc"` \| `"day"` \| `"gtd"` | nein | `"gtc"` | |
| `expiry_date` | ISO-Date `YYYY-MM-DD` | nur bei GTD | `null` | Pflicht bei GTD, sonst nicht erlaubt |
| `broker` | string (max. 50) | nein | `null` | Frei-Text (z.B. `IBKR`, `Swissquote`, `Pocket`) |
| `notes` | string (max. 2000) | nein | `null` | |
| `bucket_id_target` | UUID | nein | `null` | **v0.40.1+** Ziel-Bucket, falls die Order beim `/fill` eine *neue* Position auto-anlegt. Muss dem aufrufenden User gehören. `null` ⇒ Fallback `liquid_default`. |

201 Response: serialisierte Order (selbes Format wie ein Item aus `GET`,
ohne `current_price` / `distance_pct`).

| Status | Wann |
|---|---|
| `201` | Order angelegt |
| `400` | Limit (100) erreicht **oder** `bucket_id_target` gehört nicht dem User / existiert nicht |
| `403` | Token hat keinen `write`-Scope |
| `422` | Pydantic-Validierung (z.B. GTD ohne `expiry_date`) |

### `PATCH /pending-orders/{order_id}`

Erfordert Scope `write`. Alle Felder optional.

**Schreibschutz für gefillte Orders:** Wenn `status='filled'` (DB-Wert),
darf nur `notes` aktualisiert werden — alle anderen Felder im Body geben
400 mit Begründung *"Gefillte Order ist historisch — nur 'notes' editierbar"*.
Damit kann eine bereits verbuchte Transaktion nicht mehr indirekt mutiert
werden.

`status='filled'` ist im Schema **gar nicht erst erlaubt** (Literal nur
`"open"` / `"cancelled"`). Der Übergang nach `filled` läuft ausschliesslich
über den `/fill`-Endpoint.

```bash
curl -X PATCH "$OPENFOLIO_HOST/api/v1/external/pending-orders/f01a..." \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{"limit_price": 148.5, "notes": "Limit nach Earnings angepasst"}'
```

PATCH akzeptiert dieselben Felder wie POST plus `status`. Insbesondere
`bucket_id_target` kann nachträglich geändert werden, solange die Order
noch nicht gefillt ist. Ungültiger / fremder Bucket ⇒ 400.

| Status | Wann |
|---|---|
| `200` | Order aktualisiert |
| `400` | Order ist gefillt und Body enthält andere Felder als `notes`, **oder** `bucket_id_target` ist ungültig |
| `403` | Token hat keinen `write`-Scope |
| `404` | Order existiert nicht (oder gehört anderem User) |
| `422` | GTD-Validation (Endresultat) verletzt |

### `DELETE /pending-orders/{order_id}`

Erfordert Scope `write`. Auch für `filled`-Orders erlaubt (User darf
Karteileiche aufräumen). Dank `ON DELETE SET NULL` auf
`linked_transaction_id` bleibt die zugehörige Transaktion in
`/transactions` unberührt.

```bash
curl -X DELETE -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/pending-orders/f01a..."
```

204 No Content bei Erfolg, 404 sonst.

### `POST /pending-orders/{order_id}/fill`

Erfordert Scope `write`. **Atomar:** legt eine `Transaction` an, mappt sie
auf die Position des Tickers (oder erzeugt sie minimal mit yfinance-
Best-Effort), setzt den Status der Pending Order auf `filled` und
`linked_transaction_id` auf die neu erzeugte Transaktion. Bei einem Fehler
in einem der Schritte wird die ganze Operation zurückgerollt — die Pending
Order bleibt unverändert.

> **Disziplin-Hinweis:** Wenn der Trade bereits via CSV-Import in den
> Transaktionen gelandet ist, **nicht** `/fill` aufrufen — sonst entstehen
> Duplikate. Stattdessen die Pending Order via PATCH `status="cancelled"`
> schliessen.

```bash
curl -X POST "$OPENFOLIO_HOST/api/v1/external/pending-orders/f01a.../fill" \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "price_per_share": 149.85,
    "fill_date": "2026-05-09",
    "fees_chf": 5.0,
    "fx_rate_to_chf": 0.88,
    "notes": "Tier-1 Fill"
  }'
```

Body-Felder:

| Feld | Typ | Pflicht | Default | Beschreibung |
|---|---|---|---|---|
| `price_per_share` | float > 0 | ja | — | Tatsächlicher Fill-Preis (kann vom Limit abweichen) |
| `fill_date` | ISO-Date | ja | — | Ausführungsdatum |
| `fees_chf` | float ≥ 0 | nein | `0` | |
| `taxes_chf` | float ≥ 0 | nein | `0` | |
| `fx_rate_to_chf` | float > 0 | nein | `1.0` | `1 currency = X CHF` |
| `currency` | string (max. 10) | nein | `order.currency` | **v0.40.1+** Override der Currency für die erzeugte Transaktion. Falls eine neue Position auto-angelegt wird, bekommt sie diese Currency. `null`/weggelassen ⇒ `order.currency`. |
| `notes` | string (max. 2000) | nein | `null` | Wird an die `Transaction.notes` weitergegeben (verschlüsselt gespeichert) |

**Bucket-Auto-Resolve bei `/fill`:** Wenn der Order-Ticker keine
existierende Position trifft, wird eine neue angelegt. Bucket-Reihenfolge:
1. `order.bucket_id_target` (gesetzt beim POST oder PATCH oben)
2. Andernfalls der `liquid_default`-Bucket des Users (Fallback)

Existiert die Position bereits, gilt deren Bucket — `bucket_id_target`
wird ignoriert.

200 Response:

```json
{
  "order": {"id": "f01a...", "status": "filled", "linked_transaction_id": "9e7c...", "...": "..."},
  "transaction_id": "9e7c..."
}
```

### `POST /transactions`

Erfordert Scope `write`. Bucht eine Transaktion **direkt** — volle Paritaet
zum internen UI-Endpoint (`/api/transactions`). Teilt dessen Kernlogik:
Position-Auto-Anlage (bei unbekanntem Ticker, yfinance-Best-Effort),
Snapshot-Regen, Cache-Invalidierung und Dividend-Auto-Match laufen identisch.

Entweder `position_id` **oder** `ticker` angeben. Bei unbekanntem `ticker`
wird die Position automatisch angelegt (wie im UI). Jeder Aufruf hinterlässt
einen `ApiWriteLog`-Eintrag (`action="transaction_create"`).

> **Disziplin-Hinweis:** Es gibt **keinen** server-seitigen Duplikat-Schutz
> (bewusst — UI-Paritaet). Der Caller muss vor dem Buchen prüfen, dass die
> Transaktion nicht schon existiert, z.B. via
> `GET /transactions?ticker=…&date_from=…&date_to=…`. Recurring-DCA-Käufe
> tauchen ohnehin per IBKR-Import auf — doppelt buchen vermeiden.

```bash
curl -X POST "$OPENFOLIO_HOST/api/v1/external/transactions" \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "RKLB",
    "type": "sell",
    "date": "2026-06-01",
    "shares": 8,
    "price_per_share": 125.23,
    "currency": "USD",
    "fx_rate_to_chf": 0.88,
    "fees_chf": 0.02,
    "total_chf": 881.62
  }'
```

Body-Felder (Whitelist-Mirror des internen Schemas; unbekannte Felder ⇒ 422):

| Feld | Typ | Pflicht | Default | Beschreibung |
|---|---|---|---|---|
| `type` | enum | ja | — | `buy`/`sell`/`dividend`/`fee`/`tax`/`tax_refund`/`delivery_in`/`delivery_out`/`deposit`/`withdrawal`/`capital_gain`/`interest`/`fx_credit`/`fx_debit`/`fee_correction` |
| `date` | ISO-Date `YYYY-MM-DD` | ja | — | Transaktionsdatum |
| `position_id` | UUID | nein¹ | `null` | Bestehende Position direkt referenzieren |
| `ticker` | string (max. 60) | nein¹ | `null` | Alternativ zu `position_id`; unbekannt ⇒ Auto-Anlage |
| `asset_type` | string (max. 30) | nein | `"stock"` | Nur relevant bei Auto-Anlage (`stock`/`etf`/`crypto`/…) |
| `bucket_id` | UUID | nein | `liquid_default` | Ziel-Bucket bei Auto-Anlage; muss dem User gehören |
| `shares` | float ≥ 0 | nein | `0` | |
| `price_per_share` | float ≥ 0 | nein | `0` | |
| `currency` | string (genau 3) | nein | `"CHF"` | |
| `fx_rate_to_chf` | float > 0 | nein | `1.0` | `1 currency = X CHF` |
| `fees_chf` | float ≥ 0 | nein | `0` | |
| `taxes_chf` | float ≥ 0 | nein | `0` | |
| `total_chf` | float ≥ 0 | nein | `0` | Brutto-CHF-Wert der Transaktion |
| `notes` | string (max. 2000) | nein | `null` | Verschlüsselt gespeichert |
| `stop_loss_price` | float ≥ 0 | nein | `null` | Nur bei `buy`; muss unter `price_per_share` liegen |
| `stop_loss_method` | string (max. 50) | nein | `null` | |
| `stop_loss_confirmed_at_broker` | bool | nein | `null` | |

¹ Genau eines von `position_id` / `ticker` ist Pflicht — fehlen beide ⇒ 422.

201 Response: die gebuchte Transaktion inkl. `ticker`, `position_name` und
`created_position` (bool — ob eine neue Position angelegt wurde).

| Status | Wann |
|---|---|
| `201` | Transaktion gebucht |
| `400` | Positions-/Transaktions-Limit erreicht **oder** `bucket_id` ungültig |
| `403` | Token hat keinen `write`-Scope |
| `404` | `position_id` existiert nicht (oder gehört anderem User) |
| `422` | Validierung: weder `position_id` noch `ticker`, ungültiger `type`, unbekanntes Feld, Stop-Loss ≥ Kaufkurs |

### `PUT /transactions/{txn_id}`

Erfordert Scope `write`. Ändert eine bestehende Transaktion — alle Body-Felder
optional, nur gesetzte werden angewendet (`exclude_unset`). **Position, Ticker
und Typ sind nicht änderbar** (identisch zum UI); für eine Umbuchung die
Transaktion löschen und neu anlegen. Bei `buy`/`sell` werden `shares` und
`total_chf` der Position konsistent nachgeführt.

```bash
curl -X PUT "$OPENFOLIO_HOST/api/v1/external/transactions/9e7c..." \
  -H "X-API-Key: ofk_..." \
  -H "Content-Type: application/json" \
  -d '{"price_per_share": 125.23, "fees_chf": 0.02, "notes": "Fill korrigiert"}'
```

Änderbare Felder: `date`, `shares`, `price_per_share`, `currency`,
`fx_rate_to_chf`, `fees_chf`, `taxes_chf`, `total_chf`, `notes`. Unbekannte
Felder ⇒ 422 (`extra="forbid"`).

| Status | Wann |
|---|---|
| `200` | Transaktion aktualisiert (Response = aktualisierte Transaktion) |
| `403` | Token hat keinen `write`-Scope |
| `404` | Transaktion existiert nicht (oder gehört anderem User) |
| `422` | Unbekanntes/nicht-änderbares Feld (z.B. `ticker`, `type`) |

### `DELETE /transactions/{txn_id}`

Erfordert Scope `write`. Löscht die Transaktion **und macht ihre
Positions-Wirkung rückgängig** (`reverse_transaction_on_position`): Shares und
Cost-Basis werden zurückgerechnet, Snapshots regeneriert. Bei Dividenden wird
eine zuvor gematchte Pending-Dividende wieder auf `pending` gesetzt.

```bash
curl -X DELETE -H "X-API-Key: ofk_..." \
  "$OPENFOLIO_HOST/api/v1/external/transactions/9e7c..."
```

204 No Content bei Erfolg, 404 sonst. Der zugehörige `ApiWriteLog`
(`action="transaction_delete"`) wird **atomar** mit dem Delete geschrieben —
schlägt er fehl, bleibt die Transaktion erhalten (kein halb-gelöschter Zustand).

| Status | Wann |
|---|---|
| `200` | Atomar Order + Transaktion angelegt |
| `400` | Position-Limit erreicht |
| `403` | Token hat keinen `write`-Scope |
| `404` | Order existiert nicht |
| `409` | Order ist nicht offen (bereits `filled`/`cancelled` oder effektiv `expired`) |

**Audit-Log:** `pending_order_create`, `pending_order_update`,
`pending_order_cancel`, `pending_order_fill` werden in `api_write_log`
mit Token-ID, User-ID, Ticker und Order-ID protokolliert.

### `GET /portfolio/summary`

```json
{
  "total_invested_chf": 125430.50,
  "total_market_value_chf": 138210.75,
  "total_pnl_chf": 12780.25,
  "total_pnl_pct": 10.19,
  "total_fees_chf": 245.30,
  "positions": [
    {
      "id": "abc-123",
      "ticker": "MSFT",
      "name": "Microsoft Corp",
      "type": "stock",
      "sector": "Technology",
      "currency": "USD",
      "shares": 25,
      "cost_basis_chf": 8200.00,
      "market_value_chf": 9850.00,
      "current_price": 412.50,
      "pnl_chf": 1650.00,
      "pnl_pct": 20.12,
      "local_return_pct": 14.30,
      "fx_return_pct": 5.09,
      "fx_cross_pct": 0.73,
      "weight_pct": 7.13,
      "position_type": "core",
      "style": "compounder",
      "mansfield_rs": 0.45,
      "ma_status": "GESUND",
      "buy_date": "2023-08-15",
      "is_etf": false,
      "count_as_cash": false,
      "stop_loss_price": 380.00,
      "stop_loss_method": "manual",
      "stop_loss_confirmed_at_broker": true,
      "active_alerts": 2,
      "change_pct_24h": 1.42,
      "notes": "Long-term hold — Cloud-Cashcow",
      "bank_name": "UBS Switzerland AG",
      "iban": "••••••••••••••••2957"
    }
  ],
  "allocations": {
    "by_type": [],
    "by_sector": [],
    "by_currency": []
  },
  "fx_rates": {"USD": 0.8821, "EUR": 0.9412}
}
```

**FX-vs-Lokal-Renditezerlegung** (`local_return_pct`, `fx_return_pct`, `fx_cross_pct`):
Zerlegt die CHF-Rendite einer Fremdwährungsposition additiv in Kursbewegung
(lokal) und Währungsbewegung (FX), berechnet auf der **Ex-Gebühren**-Kostenbasis.
Es gilt `(1 + local/100) · (1 + fx/100) − 1 ≈ market_value_chf /
cost_basis_chf_at_fx − 1`; `fx_cross_pct` ist der Kreuzterm
`local · fx`. Die Felder sind `null`, wenn keine Zerlegung möglich ist (CHF-native
Position ohne FX-Effekt liefert `fx_return_pct = 0`; Crypto/Edelmetalle mit
CHF-Preis, manuelle/transaktionslose Positionen bleiben `null`). Sie ändern die
bestehenden `cost_basis_chf`/`pnl_pct`-Definitionen nicht (rein additiv).

### `GET /immobilien`

```json
{
  "total_value_chf": 1350000.00,
  "total_mortgage_chf": 795200.00,
  "total_equity_chf": 554800.00,
  "properties": [
    {
      "id": "f1e2d3...",
      "name": "Testhaus Zürich",
      "property_type": "efh",
      "purchase_date": "2020-06-01",
      "purchase_price": 1200000.00,
      "estimated_value": 1350000.00,
      "canton": "ZH",
      "current_mortgage": 795200.00,
      "equity": 554800.00,
      "equity_pct": 41.1,
      "ltv": 58.9,
      "ltv_status": "green",
      "annual_interest": 9600.00,
      "annual_amortization": 2400.00,
      "annual_expenses": 4800.00,
      "annual_income": 0.00,
      "total_annual_cost": 16800.00,
      "net_annual": -4800.00,
      "next_maturity": "2025-06-01",
      "days_until_maturity": 419,
      "unrealized_gain": 150000.00,
      "unrealized_gain_pct": 12.5,
      "mortgages": [
        {
          "id": "a1b2c3...",
          "property_id": "f1e2d3...",
          "name": "Tranche A",
          "type": "saron",
          "amount": 800000.00,
          "current_amount": 795200.00,
          "interest_rate": 1.2,
          "margin_rate": 0.85,
          "effective_rate": 1.05,
          "start_date": "2020-06-01",
          "end_date": "2025-06-01",
          "monthly_payment": 800.00,
          "monthly_total": 1000.00,
          "annual_payment": 9600.00,
          "amortization_monthly": 200.00,
          "amortization_annual": 2400.00,
          "is_active": true,
          "days_until_maturity": 419
        }
      ],
      "expenses": [],
      "income": []
    }
  ]
}
```

`effective_rate` ist bei SARON-Hypotheken dynamisch: `max(margin_rate,
margin_rate + saron_rate)`. Ab v0.38 werden `address`, `notes`,
`mortgage.bank` und `income.tenant` als Klartext mit ausgeliefert (PII gehört
dem Token-Eigentümer).

### `GET /vorsorge`

```json
{
  "total_value_chf": 25000.00,
  "accounts": [
    {
      "id": "v1w2x3...",
      "ticker": "VORSORGE-VIAC",
      "name": "VIAC 3a Konto",
      "type": "pension",
      "currency": "CHF",
      "cost_basis_chf": 25000.00,
      "market_value_chf": 25000.00,
      "buy_date": null,
      "is_active": true,
      "bank_name": "VIAC AG",
      "iban": "••••••••••••••••2957",
      "notes": "3a-Konto seit 2018"
    }
  ]
}
```

Vorsorge-Konten werden manuell gepflegt — `cost_basis_chf` entspricht stets
`market_value_chf`. Ab v0.38 werden `bank_name` (Klartext), `iban`
(maskiert via `decrypt_and_mask_iban`) und `notes` (Klartext) ausgeliefert.

### `GET /portfolio/upcoming-earnings`

Liefert für jede aktive Stock/ETF-Position des Users den nächsten
Earnings-Termin im konfigurierbaren Fenster. Primärquelle ist
[Finnhub](https://finnhub.io) (strukturiert, `bmo`/`amc`/`dmh`, EPS- und
Revenue-Schätzungen, `is_confirmed`). Fällt Finnhub aus oder ist kein
`FINNHUB_API_KEY` gesetzt, wird auf yfinance zurückgefallen — dann ist
`earnings_time` immer `"unknown"` und `eps_estimate`/`revenue_estimate_usd`
sind `null`.

**Query-Parameter:**

- `days` (int, 1..60, default 7) — Lookahead-Fenster.
- `include_etfs` (bool, default true) — wenn false, werden ETFs ignoriert.

**Cache:** 12h pro `(user, days, include_etfs)`-Kombi (Response-Cache) plus
24h pro Ticker (Rich-Earnings-Cache).

```bash
curl $OPENFOLIO_HOST/api/v1/external/portfolio/upcoming-earnings?days=7 \
  -H "X-API-Key: $TOKEN"
```

```json
{
  "as_of": "2026-04-09T07:32:25+00:00",
  "lookahead_days": 7,
  "earnings": [
    {
      "ticker": "JNJ",
      "name": "JOHNSON & JOHNSON ORD",
      "type": "stock",
      "earnings_date": "2026-04-14",
      "days_until": 5,
      "earnings_time": "bmo",
      "earnings_time_label": "Before Market Open",
      "eps_estimate": 2.6999,
      "revenue_estimate_usd": 23862652556,
      "is_confirmed": true,
      "source": "finnhub"
    },
    {
      "ticker": "PEP",
      "name": "PEPSICO ORD",
      "type": "stock",
      "earnings_date": "2026-04-16",
      "days_until": 7,
      "earnings_time": "bmo",
      "earnings_time_label": "Before Market Open",
      "eps_estimate": 1.5661,
      "revenue_estimate_usd": 19120339461,
      "is_confirmed": true,
      "source": "finnhub"
    }
  ],
  "no_earnings_in_window": ["LHX", "OEF", "RSG", "WM"],
  "warnings": [
    "finnhub_no_coverage:CHSPI.SW",
    "finnhub_no_coverage:EIMI.L",
    "finnhub_no_coverage:NOVN.SW"
  ]
}
```

**Feld-Erklärung:**

- `earnings_time` — Raw-Wert von Finnhub: `bmo` (Before Market Open),
  `amc` (After Market Close), `dmh` (During Market Hours) oder `unknown`.
- `earnings_time_label` — Vorformatiertes Label für die UI.
- `days_until` — Tage bis zum Termin (0 = heute).
- `is_confirmed` — `true`, wenn Finnhub den Termin als bestätigt meldet.
  yfinance-Fallback-Einträge haben immer `false`.
- `source` — `"finnhub"` oder `"yfinance"` (Fallback).
- `no_earnings_in_window` — Tickers, die geprüft wurden und definitiv
  keinen Termin im angefragten Fenster haben. Positive Bestätigung, keine
  Lücke.
- `warnings` — Tickers, bei denen der Abruf nicht eindeutig geprüft
  werden konnte. Mögliche Prefixe:
    - `finnhub_no_coverage:<ticker>` — Finnhub's Plan (Free-Tier) deckt
      den Markt nicht ab (z.B. SIX-, LSE- oder andere Nicht-US-Listings).
      yfinance-Fallback hat ebenfalls kein Ergebnis geliefert. Die
      Information "Earnings im Fenster ja/nein" ist für diesen Ticker
      unbekannt — NICHT als "kein Termin" interpretieren.
    - `earnings_fetch_failed:<ticker>` — transienter Fehler (Netzwerk,
      Timeout, unerwartetes Exception). Kann beim nächsten Call nach
      Cache-Ablauf automatisch weg sein.

**Semantik-Regel:** Wenn ein Ticker weder in `earnings[]` noch in
`warnings[]` erscheint, ist er **definitiv** termin-frei im angefragten
Fenster. Stille Lücken gibt es nicht.

### `GET /analysis/score/{ticker}`

Setup-Score eines Tickers (Position oder Watchlist-Eintrag, sonst Live-
Berechnung). Antwort enthält zusätzlich den `concentration`-Block und
`liquid_portfolio_chf` — hier nur die Score-Kernfelder:

```json
{
  "ticker": "OEF",
  "score": 13,
  "max_score": 15,
  "pct": 90,
  "rating": "STARK",
  "setup_quality": "STARK",
  "criteria": [
    {"id": 1, "group": "Trend", "name": "Preis > MA200", "passed": true, "detail": "..."},
    {"id": 21, "group": "Volumen", "name": "Volume-Confirmation (Slope vs Vol-Ratio)",
     "passed": null, "score_modifier": 1, "detail": "..."}
  ]
}
```

**Semantik `score` / `max_score` / `pct` / `rating`:**

- `score` / `max_score` — bestandene vs. **bewertbare** Binär-Kriterien.
  `max_score` ist **pro Ticker variabel**: Kriterien ohne Datengrundlage
  (`passed: null`, z.B. fehlende Earnings- oder Industry-Daten) fallen aus
  dem Nenner, statt als "nicht bestanden" zu zählen. Reine Modifier-Items
  (`score_modifier` gesetzt, `passed: null`) zählen ebenfalls nie in
  `score`/`max_score`. `13/15` und `13/18` sind also verschiedene Setups.
- `pct` (0–100) — **nicht** einfach `score/max_score`. Basis ist
  `score/max_score × 100`, darauf wirken die Modifier-Items (positive wie
  negative, ±3 Prozentpunkte je Modifier-Punkt, geclampt auf 0–100).
  Beispiel OEF: 13/15 = 87 % Basis, +1 Modifier → `pct: 90`. `pct` ist der
  Anzeige-Score — Konsumenten sollen dieses Feld nutzen statt selbst aus
  `score/max_score` zu rechnen.
- `rating` (`STARK` ≥ 70 / `MODERAT` ≥ 45 / `SCHWACH`) — hängt **nicht**
  an `pct`, sondern an einer internen Quality-Variante, bei der nur
  **negative** Modifier wirken (mit 8 Prozentpunkten je Punkt, Risk-First).
  Ein Setup mit Distribution-Verdacht kann daher kosmetisch hohes `pct`
  haben und trotzdem auf `MODERAT` fallen. `rating` und `pct` können also
  scheinbar inkonsistent sein — das ist gewollt.
- Diagnose-Felder: `base_pct` (Basis ohne Modifier), `quality_pct`
  (Rating-Grundlage), `pct_legacy` (Migrations-Vergleichswert, temporär).

### `GET /analysis/correlation-matrix`

Paarweise Pearson-Korrelation der täglichen simple returns aller aktiven
Positionen plus HHI-basierte Konzentrations-Metriken. Reine pandas-Berechnung
auf yfinance-Daten, 24h Redis-Cache pro (User, Period, Flag-Combo).

**Query-Parameter:**

| Parameter | Default | Werte | Beschreibung |
|---|---|---|---|
| `period` | `90d` | `30d` / `90d` / `180d` / `1y` | Lookback-Fenster |
| `include_cash` | `false` | bool | Cash-Positionen in Matrix aufnehmen |
| `include_pension` | `false` | bool | Vorsorge (Säule 3a) in Matrix aufnehmen |
| `include_commodity` | `true` | bool | Rohstoffe (inkl. Gold `GC=F`) |
| `include_crypto` | `true` | bool | Krypto (BTC-USD etc.) |
| `bucket_id` | – | UUID | **v0.39** — Optional. Filtert die Matrix auf Positionen eines Buckets (Konzentrationsanalyse pro Bucket). |

Immobilien (HEILIGE Regel 4) und Private Equity (HEILIGE Regel 6) sind
**immer** ausgeschlossen — auch aus der HHI-Berechnung. Tickers mit weniger
als 20 gemeinsamen Handelstagen fallen aus der Matrix und erscheinen in
`warnings[]`.

```json
{
  "as_of": "2026-04-08T12:00:00",
  "period": "90d",
  "observations": 62,
  "filters": {
    "include_cash": false,
    "include_pension": false,
    "include_commodity": true,
    "include_crypto": true
  },
  "tickers": [
    {"yf_ticker": "MSFT", "ticker": "MSFT", "name": "Microsoft", "type": "stock", "sector": "Technology", "weight_pct": 7.13},
    {"yf_ticker": "RSG", "ticker": "RSG", "name": "Republic Services", "type": "stock", "sector": "Industrials", "weight_pct": 4.21}
  ],
  "matrix": [
    [1.0, 0.42],
    [0.42, 1.0]
  ],
  "high_correlations": [
    {
      "ticker_a": "RSG",
      "ticker_b": "WM",
      "correlation": 0.87,
      "interpretation": "gleicher Sektor (Industrials) — stark positiv korreliert"
    }
  ],
  "concentration": {
    "hhi": 0.0842,
    "effective_n": 11.88,
    "max_weight_ticker": "MSFT",
    "max_weight_pct": 7.13,
    "classification": "low"
  },
  "warnings": []
}
```

Klassifikation HHI (CFA-Konvention): `< 0.10` low, `0.10-0.18` moderate,
`> 0.18` high.

### `GET /analysis/factor-decomposition`

Serverseitige OLS-Faktor-Decomposition der **liquiden** Portfolio-Tagesrenditen
(`raw=true, liquid=true` — ohne Cash/Vorsorge, ohne PE/Immobilien) gegen ein
fixes Faktor-Menu. Ersetzt den clientseitigen Zusammenbau aus 8 Einzel-Kursreihen
plus eigener OLS. 1h Redis-Cache pro (User, Fenster).

**Faktor-Menu (fix):** `SPY` Markt · `MTUM` Momentum · `VLUE` Value · `QUAL`
Quality · `IWM` Size · `GLD` Gold · `BTC-USD` Krypto · `USDCHF=X` FX (CHF-Sicht,
eigener Faktor — die Regression attribuiert die Währungs-Exposure auf das
USDCHF-Beta, die Equity-Faktoren bleiben in ihrer Notierungswährung).

**Alignment:** Alle Serien werden auf den NYSE-Handelskalender (SPY) alignt;
Wochenend-Bewegungen werden per Level-Forward-Fill in die nächste Session
**kompoundiert**. Damit behalten Portfolio- und BTC/FX-Returns das Wochenende —
das BTC-Beta wird nicht unterschätzt und die Stichprobe nicht halbiert.

**Query-Parameter:**

| Parameter | Default | Werte | Beschreibung |
|---|---|---|---|
| `period` | `all` | `1y` / `2y` / `3y` / `5y` / `all` | Lookback-Fenster. `all` verankert via `raw=true` an der echten Inception (keine synthetische Pre-Inception-Historie). |

```json
{
  "alpha": { "daily": -9.4e-05, "annualized_pct": -2.33, "std_err": 0.000138, "t_stat": -0.68 },
  "factors": {
    "SPY":    { "beta": 0.2771, "std_err": 0.0673, "t_stat": 4.12 },
    "MTUM":   { "beta": 0.0251, "std_err": 0.0238, "t_stat": 1.06 },
    "VLUE":   { "beta": -0.0141, "std_err": 0.0270, "t_stat": -0.52 },
    "QUAL":   { "beta": -0.1279, "std_err": 0.0626, "t_stat": -2.04 },
    "IWM":    { "beta": 0.0119, "std_err": 0.0216, "t_stat": 0.55 },
    "GLD":    { "beta": 0.0066, "std_err": 0.0111, "t_stat": 0.59 },
    "BTCUSD": { "beta": 0.0298, "std_err": 0.0050, "t_stat": 5.97 },
    "USDCHF": { "beta": 0.3606, "std_err": 0.0275, "t_stat": 13.13 }
  },
  "r_squared": 0.3774,
  "adj_r_squared": 0.3707,
  "n_obs": 746,
  "window": { "start": "2023-06-15", "end": "2026-06-05" },
  "missing_factors": [],
  "method": "OLS, taegliche Returns, NYSE-Session-aligned (Wochenende vorwaerts kompoundiert); liquid=True, raw=true"
}
```

**Fehler:** `422` bei < 30 überlappenden Handelstagen (`n_obs` im Detail);
`503` wenn die Faktor-Kursdaten gerade nicht abrufbar sind. Reine Lese-Operation,
berührt keine Performance-Berechnung.

### `GET /macro/ch`

CH-Makro-Kontext in einem Call: SNB-Leitzins (inkl. nächstem geplanten
Meeting), SARON mit 30d-Delta, CHF/EUR + CHF/USD aus Schweizer Sicht
(positives Delta = CHF stärker), CH-Inflation (Headline + Core),
CH-10Y-Rendite und 30d-Performance SMI vs S&P 500. Datenquellen: SNB
Data Portal (Policy Rate + SARON), Eurostat HICP (CPI Headline + Core,
kein API-Key nötig), FRED (10Y-Rendite), yfinance (FX + Indizes).
6h Redis-Cache, partial-failure-tolerant.

**Verhalten bei Teilausfällen:** Jede nicht erreichbare Quelle landet als
maschinenlesbarer String in `warnings[]` (z.B. `fx_unavailable`,
`ch_cpi_unavailable`, `fred_no_api_key`, `snb_policy_rate_fallback_used`);
der Endpoint liefert trotzdem `200` mit dem, was verfügbar ist. Nur wenn
der Orchestrator selbst wirft, kommt ein `503` mit
`detail: "ch_macro_unavailable"`.

```json
{
  "as_of": "2026-04-09T07:06:06",
  "snb": {
    "policy_rate_pct": 0.0,
    "policy_rate_changed_on": "2025-06-20",
    "next_meeting": "2026-06-19"
  },
  "saron": {
    "current_pct": -0.04,
    "as_of": "2026-04-02",
    "delta_30d_bps": 2.0,
    "trend": "stable"
  },
  "fx": {
    "chf_eur": {"rate": 1.08361, "as_of": "2026-04-09", "delta_30d_pct": -2.082, "trend": "chf_weaker"},
    "chf_usd": {"rate": 1.26417, "as_of": "2026-04-09", "delta_30d_pct": -1.662, "trend": "chf_weaker"}
  },
  "ch_inflation": {
    "cpi_yoy_pct": 0.2,
    "cpi_as_of": "2025-12",
    "core_cpi_yoy_pct": 0.6
  },
  "ch_rates": {
    "eidg_10y_yield_pct": 0.25,
    "delta_30d_bps": -2.0,
    "trend": "stable"
  },
  "smi_vs_sp500_30d": {
    "smi_return_pct": -2.331,
    "sp500_return_pct": -1.827,
    "relative_pct": -0.504
  },
  "warnings": []
}
```

FX-Rates sind in der Konvention `1 CHF = X Fremdwährung` (umgedreht
gegenüber Yahoo Finance). `delta_30d_bps` sind Basispunkte (1 bp = 0.01%).
CPI-Daten kommen von Eurostat HICP (CH als EFTA-Land, monatliche YoY-Rate,
COICOP `CP00` für Headline und `TOT_X_NRG_FOOD` für Core). `cpi_as_of` ist
im Format `YYYY-MM` und hinkt typisch 1-2 Monate hinter dem aktuellen
Datum her (Eurostat publiziert ~4 Wochen nach Monatsende). Ohne
konfigurierten FRED-API-Key ist `ch_rates` leer + `fred_no_api_key` warning;
`ch_inflation` funktioniert ohne API-Key.

### `GET /market/sectors`

Sektor-Rotation der 11 SPDR-Sektor-ETFs. Daten werden vom Worker alle 60s
via yfinance aktualisiert. Trend wird aus 1W/1M/3M-Performance abgeleitet
(`up` = Mehrheit positiv, `down` = Mehrheit negativ, `neutral` = gemischt).

```json
[
  {
    "etf": "XLK",
    "sector": "Technology",
    "perf_1d": 0.27,
    "perf_1w": 4.47,
    "perf_1m": 1.29,
    "perf_3m": -3.10,
    "trend": "neutral"
  },
  {
    "etf": "XLE",
    "sector": "Energy",
    "perf_1d": -1.24,
    "perf_1w": -3.24,
    "perf_1m": 1.27,
    "perf_3m": 24.52,
    "trend": "up"
  }
]
```

### `GET /market/industries`

Branchen-Rotation auf ~129 US-Industries-Ebene (TradingView-Scanner).
Taeglicher DB-Snapshot um 01:30 CET. 24h Cache. Keine User-spezifischen
Daten. Namen sind englisch (z.B. "Integrated Oil", "Semiconductors").

**Query-Parameter:**
- `period` (default `ytd`) — Sortier-/Metric-Spalte: `1w`, `1m`, `3m`, `6m`, `ytd`, `1y`, `5y`, `10y`.
- `top=N` — nur die N besten nach `period` (desc).
- `bottom=N` — nur die N schlechtesten nach `period` (asc).
- `order` (default `desc`) — `desc` oder `asc`. Bei `bottom` ignoriert.

**Beispiel:**

```bash
curl -sS "$OPENFOLIO_HOST/api/v1/external/market/industries?period=ytd&top=5" \
  -H "X-API-Key: $TOKEN"
```

```json
{
  "scraped_at": "2026-04-23T14:24:06+00:00",
  "period": "ytd",
  "count": 5,
  "rows": [
    {
      "slug": "computer-peripherals",
      "name": "Computer Peripherals",
      "change_pct": 0.17,
      "perf_1w": 10.96,
      "perf_1m": 34.56,
      "perf_3m": 52.67,
      "perf_6m": 165.46,
      "perf_ytd": 115.65,
      "perf_1y": 950.09,
      "perf_5y": 1234.5,
      "perf_10y": 2480.8,
      "market_cap": 125000000000.0,
      "volume": 15000000.0,
      "value_traded": 980000000.0,
      "turnover_ratio": 0.00784,
      "rvol": 1.42,
      "top1_ticker": "STX",
      "top1_weight": 0.58,
      "effective_n": 3.1
    }
  ]
}
```

`perf_*`-Felder sind in Prozent (nicht als Faktor). `null`-Werte (z.B. bei
sehr jungen Branchen ohne 10Y-Historie) werden immer als letzte Eintraege
sortiert, unabhaengig von `order`.

**Flow- und Konzentrations-Felder** (aus dem taeglichen Stock-Level-Scan der
Branche aggregiert, koennen `null` sein):

| Feld | Bedeutung |
|------|-----------|
| `volume` | Aggregiertes Handelsvolumen der Branche (Stueck, nicht Dollar). |
| `value_traded` | Aggregiertes Dollar-Volumen des Tages (Summe ueber die Konstituenten). |
| `turnover_ratio` | `value_traded / market_cap`. Anteil der MCap, der an einem Tag umgesetzt wird — der eigentliche Fluss-Indikator. 0.001–0.02 normal, >0.03 ungewoehnlich. |
| `rvol` | Relatives Volumen: heutiges `value_traded` / 20-Tage-Schnitt. `null` bis 20 Snapshot-Tage Historie vorliegen. Nicht markt-normalisiert (marktweite Volumen-Spikes heben alle Branchen). |
| `top1_ticker` | Ticker des groessten Mitglieds der Branche nach MCap. |
| `top1_weight` | MCap-Anteil dieses Top-1-Tickers an der Branche (0..1). |
| `effective_n` | Effektive Mitgliederzahl `1/HHI` — von ~1 (ein Wert dominiert) bis N (gleichverteilt). |

`turnover_ratio` und `rvol` sind die echten Fluss-Signale; `market_cap × perf`
ist hingegen eine Bewertungsaenderung, **kein** Kapitalzufluss. Eine Branche
gilt als konzentriert (eher Einzelwert- als Branchen-Signal), wenn
`top1_weight > 0.5` oder `effective_n < 5`.

### `GET /market/industries/{slug}/members`

Einzelaktien einer Branche (Drill-down), nach Marktkapitalisierung absteigend.
Live von der TradingView-Scanner-API, nach Branche gefiltert — daher etwas
frischer als der taegliche Aggregat-Snapshot. 24h Cache. Keine
User-spezifischen Daten.

Der `slug` ist der `slug` einer Zeile aus `GET /market/industries` (z.B.
`integrated-oil`). Unbekannte Slugs liefern `404` (`industry_not_found`); faellt
der Scanner aus, kommt `502` (`industry_members_unavailable`).

**Query-Parameter:**
- `limit` (default `50`, 1–200) — maximale Anzahl Aktien (Top N nach MCap).

**Beispiel:**

```bash
curl -sS "$OPENFOLIO_HOST/api/v1/external/market/industries/integrated-oil/members?limit=5" \
  -H "X-API-Key: $TOKEN"
```

```json
{
  "slug": "integrated-oil",
  "name": "Integrated Oil",
  "count": 5,
  "members": [
    {
      "ticker": "XOM",
      "name": "Exxon Mobil Corporation",
      "exchange": "NYSE",
      "change_pct": -0.24,
      "perf_1w": 1.2,
      "perf_1m": 3.4,
      "perf_3m": 8.9,
      "perf_6m": 15.1,
      "perf_ytd": 29.0,
      "perf_1y": 12.7,
      "market_cap": 642135222801.0
    }
  ]
}
```

`perf_*`-Felder sind in Prozent. `exchange` (z.B. `NYSE`, `NASDAQ`, `OTC`)
erlaubt das Deep-Linking auf TradingView. Die Liste kann auslaendische
OTC-Doppellistings desselben Unternehmens enthalten (TradingView ordnet sie
der US-Branche zu).

### `GET /screening/latest`

```json
{
  "scan_id": "uuid",
  "scanned_at": "2026-04-10T08:30:00",
  "total": 42,
  "results": [
    {
      "ticker": "GOOG",
      "name": "Alphabet Inc.",
      "sector": "Communication Services",
      "score": 7,
      "signals": {
        "superinvestor_13f_consensus": {
          "action": "new_position",
          "consensus_count": 4,
          "funds": [
            {"fund": "Scion Asset Management", "action": "new_position", "filing_date": "2026-02-14"},
            {"fund": "Pershing Square Capital", "action": "new_position", "filing_date": "2026-02-17"},
            {"fund": "Third Point LLC", "action": "new_position", "filing_date": "2026-02-17"},
            {"fund": "Appaloosa LP", "action": "new_position", "filing_date": "2026-02-17"}
          ],
          "quarter": "2025-Q4",
          "quarter_ready_date": "2026-03-16",
          "score_applied": 3
        },
        "insider_cluster": {
          "insider_count": 3,
          "total_value": 2500000,
          "trade_date": "2026-04-05"
        },
        "buyback": {
          "filing_date": "2026-03-15"
        }
      },
      "price_usd": 178.50
    },
    {
      "ticker": "NESN.SW",
      "name": "Nestle S.A.",
      "sector": "Consumer Staples",
      "score": 3,
      "signals": {
        "six_insider": {
          "transaction_count": 2,
          "total_amount_chf": 1150000,
          "latest_date": "2026-04-02",
          "obligor_functions": ["VR-Mitglied", "CEO"]
        }
      },
      "price_usd": null
    }
  ]
}
```

### `GET /screening/macro/cot`

CFTC COT Macro-Positionierung — isolierte Daten ohne Einfluss auf den
Equity-Screening-Score.

```json
{
  "instruments": [
    {
      "code": "GC",
      "name": "Gold (COMEX)",
      "report_date": "2026-03-31",
      "commercial_net": -201640,
      "commercial_net_pct_52w": 90.3,
      "mm_net": 92814,
      "mm_net_pct_52w": 1.7,
      "open_interest": 361409,
      "is_extreme_commercial": true,
      "is_extreme_mm": true,
      "history_weeks": 52
    }
  ],
  "updated_at": "2026-04-10T06:39:52"
}
```

### `GET /buckets`

```json
{
  "buckets": [
    {
      "id": "5267a110-9e9e-40e1-b000-028fedcd5117",
      "name": "Alle Positionen",
      "kind": "system",
      "system_role": "liquid_default",
      "color": "#64748b",
      "benchmark": null,
      "target_pct": null,
      "target_chf": null,
      "description": null,
      "sort_order": 0,
      "risk_rules": null,
      "deleted_at": null
    },
    {
      "id": "8a3f...",
      "name": "Core",
      "kind": "user",
      "system_role": null,
      "color": "#3b82f6",
      "benchmark": "URTH",
      "target_pct": 70.0,
      "risk_rules": {
        "drawdown_brake_pct": 6.0,
        "drawdown_brake_active": true,
        "stop_loss_method_default": null
      },
      "deleted_at": null
    }
  ],
  "count": 6
}
```

### `GET /buckets/{id}/summary`

```json
{
  "bucket_id": "8a3f...",
  "name": "Core",
  "color": "#3b82f6",
  "benchmark": "URTH",
  "total_value_chf": 124500.00,
  "cost_basis_chf": 110000.00,
  "unrealized_pnl_chf": 14500.00,
  "unrealized_pnl_pct": 13.18,
  "position_count": 8,
  "running_peak_chf": 128300.00,
  "snapshot_date": "2026-05-17"
}
```

### `GET /buckets/{id}/drawdown?period=ytd`

```json
{
  "period": "ytd",
  "snapshots_count": 137,
  "max_drawdown_pct": -8.42,
  "peak_date": "2026-03-14",
  "trough_date": "2026-04-22",
  "current_value_chf": 124500.00,
  "running_peak_value_chf": 128300.00,
  "current_vs_peak_pct": -2.96,
  "drawdown_brake_active": false,
  "drawdown_brake_threshold_pct": 6.0,
  "bucket_id": "8a3f..."
}
```

### `GET /buckets/{id}/benchmark-comparison?period=ytd`

```json
{
  "bucket_id": "8a3f...",
  "period": "ytd",
  "bucket_return_pct": 5.23,
  "benchmark_ticker": "URTH",
  "benchmark_name": "MSCI World",
  "benchmark_return_pct": 7.81,
  "delta_pct": -2.58
}
```

### `GET /buckets/allocations`

```json
{
  "items": [
    {"bucket_id": "...", "name": "Core", "color": "#3b82f6", "kind": "user", "system_role": null, "value_chf": 124500.00, "pct": 62.5},
    {"bucket_id": "...", "name": "Satellite", "color": "#f59e0b", "kind": "user", "system_role": null, "value_chf": 55800.00, "pct": 28.0},
    {"bucket_id": "...", "name": "Alle Positionen", "color": "#64748b", "kind": "system", "system_role": "liquid_default", "value_chf": 18900.00, "pct": 9.5}
  ]
}
```

### Position-Response mit Bucket-Feldern (seit v0.39)

```json
{
  "id": "...",
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "type": "stock",
  "bucket_id": "8a3f...",
  "risk_rules": null,
  "shares": 25.0,
  "cost_basis_chf": 5000.0,
  "market_value_chf": 6250.0,
  "pnl_pct": 25.0
}
```

`risk_rules: null` ist der Normalfall — die Position erbt die Rules ihres
Buckets. Nur wenn der User beim Bucket-Wechsel explizit "Aktuelle Rules
beibehalten" gewählt hat, enthält `risk_rules` die eingefrorenen Werte
(`{drawdown_brake_pct, max_position_pct, alert_loss_pct, ...}`).

### Report-Vault — Lesen / Ändern / Archivieren / Löschen

Markdown-Briefe (Daily/Weekly/Trade/…), die der Claude-Finance-Workspace via
`POST /reports` hochlädt. Lesen ist read-Scope, alle Mutationen brauchen
`write`. Jeder Eintrag trägt `archived_at` (NULL = aktiv).

```bash
# Liste (nur aktive), Metadaten ohne Body — liefert die id
curl "$OPENFOLIO_HOST/api/v1/external/reports?category=daily_brief&per_page=20" \
  -H "X-API-Key: $KEY"
# Nur das Archiv
curl "$OPENFOLIO_HOST/api/v1/external/reports?archived=true" -H "X-API-Key: $KEY"
```

```json
{
  "total": 1,
  "page": 1,
  "per_page": 20,
  "results": [
    {
      "id": "5f3a…",
      "category": "daily_brief",
      "title": "Daily Brief 2026-05-29",
      "report_date": "2026-05-29",
      "tags": ["macro"],
      "source": "claude-finance",
      "source_path": "Output/briefs/2026-05-29_daily.md",
      "created_at": "2026-05-29T05:30:00",
      "updated_at": "2026-05-29T05:30:00",
      "archived_at": null
    }
  ]
}
```

```bash
# Voller Report inkl. body
curl "$OPENFOLIO_HOST/api/v1/external/reports/5f3a…" -H "X-API-Key: $KEY"

# Partiell ändern — nur übergebene Felder; tags:[] leert, Body-Edit recomputed Hash
curl -X PATCH "$OPENFOLIO_HOST/api/v1/external/reports/5f3a…" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"title":"Daily Brief 2026-05-29 (Korrektur)","tags":["macro","fx"]}'

# Archivieren (reversibel) / wiederherstellen
curl -X POST "$OPENFOLIO_HOST/api/v1/external/reports/5f3a…/archive"   -H "X-API-Key: $KEY"
curl -X POST "$OPENFOLIO_HOST/api/v1/external/reports/5f3a…/unarchive" -H "X-API-Key: $KEY"

# Endgültig löschen (kein Undo)
curl -X DELETE "$OPENFOLIO_HOST/api/v1/external/reports/5f3a…" -H "X-API-Key: $KEY"
```

`PATCH`/`archive`/`unarchive` antworten mit `{"status": "...", <Metadaten>}`,
`DELETE` mit `204`. Statuscodes: `403` ohne write-Scope, `404` für fremde/
unbekannte `report_id`, `422` bei >20 Tags.

| Operation | Reversibel? | Effekt |
|---|---|---|
| `POST /reports/{id}/archive` | ✅ via `unarchive` oder Re-Upload | Aus Default-Liste raus, nur unter `?archived=true` |
| `POST /reports/prune` | ✅ via Re-Upload derselben `source_path` | Archiviert Sync-Waisen, Antwort `{archived, kept}` |
| `DELETE /reports/{id}` | ❌ endgültig | Zeile entfernt |

> **Resurrection:** Ein `POST /reports` mit bekanntem `source_path` reaktiviert
> einen archivierten/geprunten Report automatisch (`archived_at → NULL`) —
> taucht eine umbenannte/gelöschte Quelldatei wieder auf, kommt ihr Report
> ohne Dublette zurück.

## Stop-Loss-Workflow

Stop-Loss-Werte können seit v0.38 vollständig über die externe API gesetzt
werden — vorher musste der User sie manuell in der UI eintragen.

### Status lesen

```bash
# Welche Positionen haben noch keinen Stop?
# Items enthalten u.a. ticker, type, shares, current_price, market_value_chf, bucket_id.
curl -H "X-API-Key: $TOKEN" \
  $OPENFOLIO_HOST/api/v1/external/portfolio/positions-without-stoploss

# Status aller Tradables (price/method/distance/confirmed)
curl -H "X-API-Key: $TOKEN" \
  $OPENFOLIO_HOST/api/v1/external/portfolio/stop-loss-status
```

### Einzeln setzen

`PATCH /positions/by-id/{position_id}/stop-loss` benötigt Scope `write`.
**Wichtig:** `confirmed_at_broker` ist Default `false` — wenn das Feld nicht
gesendet wird, markiert die API den Stop NICHT als beim Broker bestätigt.

```bash
curl -X PATCH \
  -H "X-API-Key: $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"stop_loss_price": 95.50, "method": "manual"}' \
  $OPENFOLIO_HOST/api/v1/external/positions/by-id/<UUID>/stop-loss
```

### Batch (mehrere Positionen)

`POST /portfolio/stop-loss/batch` — **Hard-Cap: 100 Items pro Request**.
Schützt vor versehentlichen Skript-Loops.  Batches mit > 100 Items werden
mit HTTP 422 abgelehnt.

```bash
curl -X POST \
  -H "X-API-Key: $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"ticker": "AAPL", "stop_loss_price": 180.0, "method": "manual"},
      {"ticker": "MSFT", "stop_loss_price": 350.0, "method": "atr",
       "confirmed_at_broker": true}
    ]
  }' \
  $OPENFOLIO_HOST/api/v1/external/portfolio/stop-loss/batch
```

## Sicherheits-Hinweise

- **PII-Felder** (bank_name, address, notes, mortgage.bank, tenant) werden ab
  v0.38 als Klartext ausgeliefert — sie gehören dem Token-Eigentümer.
- **IBAN ist immer maskiert** (letzte 4 Stellen, Pattern `••••...1234`),
  identisch zum internen UI-Verhalten.  Klartext-IBANs verlassen das System
  über die externe API niemals.
- Tokens haben 256 Bit Entropie und werden serverseitig nur als sha256-Hash gespeichert.
- Tokens sind standardmässig **read-only**. Der `write`-Scope muss explizit
  beim Erstellen aktiviert werden — bestehende Tokens vor diesem Feature-Release
  haben automatisch `["read"]` und können keine Mutationen ausführen.
- **Schreib-Aktionen werden auditiert**: Jede Notes/Alert-Mutation erzeugt
  einen Eintrag in `api_write_log` mit Token-ID, User-ID, Ticker, Action und
  (für Notes) `char_count_before`/`_after`. Der **Inhalt** der Notiz wird
  niemals geloggt — die Tabelle ist DSGVO-freundlich.
- Notizen werden serverseitig mit dem `ENCRYPTION_KEY` aus der OpenFolio-
  Konfiguration verschlüsselt (Fernet/AES-128-CBC).
- Bei Verdacht auf Kompromittierung: Token sofort widerrufen via UI oder
  `DELETE /api/settings/api-tokens/{id}`. Widerrufene Schreib-Tokens können
  keine weiteren Mutationen mehr durchführen, der Audit-Log-Eintrag bleibt
  bestehen (Token-ID via `ON DELETE SET NULL` entkoppelt).
- Rate-Limit `30/minute` gilt sowohl für GETs als auch für Mutationen.
  Externe Konsumenten sollten cachen.

## Versionierung

Die API ist unter `/api/v1/external/*` gemounted. Breaking Changes erfolgen nur
unter einem neuen Versions-Prefix (`/api/v2/...`); v1 bleibt stabil.

### v0.46 — Volle UI-Schreib-Paritaet

- **Jede UI-Funktion ist jetzt auch ueber die API erreichbar** (Scope `write`).
  Neu hinzugekommen: Positionen-CRUD + Recalc, Immobilien (Objekte/Hypotheken/
  Ausgaben/Einnahmen), Private Equity (Holdings/Bewertungen/Dividenden),
  Edelmetalle (Items/Ausgaben), Pending-Dividenden confirm/dismiss, Buckets
  (CRUD, Templates, Migration-Rollback, Import-Rules, Backfill, Split/Move),
  Performance-Aktionen (Recalc, Fix-Total-CHF, Snapshot-Regen, Earnings-Refresh),
  Screening-Scan, ETF-Sektorgewichte, EPS-Schwellen, Resistance, Watchlist-Tags,
  Settings + Onboarding und der komplette Import-Flow (parse/analyze/mapping/
  confirm/profiles). Vollstaendige Liste: Abschnitt „UI-Paritaet — Schreib-
  Endpoints" oben.
- **Geteilte Kernlogik** mit den internen Endpoints ueber `_core`-Funktionen
  (`create_position_core`, `create_holding_core`, `confirm_pending_dividend_core`
  usw.) bzw. denselben Service-Layer — kein zweiter Code-Pfad, identisches
  Verhalten (Verschluesselung, Snapshot-Regen, Cache-Invalidierung, Auto-Anlagen).
- **Audit-Log atomar** mit jeder Mutation committet; Migration 085 erweitert die
  `ck_api_write_log_action`-Whitelist um alle neuen Aktionen (sonst Prod-500 +
  Rollback).
- **Bewusst NICHT exponiert** (Sicherheits-Entscheidung): Secret-Writes
  (SMTP/ntfy/FRED/FMP/Finnhub-Keys, API-Token-Erstellung), Auth/Identitaet
  (Login/MFA/Passwort/Sessions/Account-Delete) und Admin-Funktionen
  (User-Management, Invite-Codes). Diese bleiben JWT/UI- bzw. admin-only.

### v0.42 — Transaktionen voll schreibbar (CRUD)

- **`GET /analysis/mrs/{ticker}`: `warnings[]` bei leerem `data`** — ein leeres
  Resultat ist jetzt von fehlender Coverage unterscheidbar (Details im
  Server-Log); leere Resultate werden zudem nur noch 5 min gecached, damit ein
  Preis-Historie-Backfill sofort wirkt.
- **`GET /portfolio/positions-without-stoploss`: `market_value_chf` + `type`**
  ergänzt (kein Join gegen `/portfolio/summary` mehr nötig).
- **Stop-Loss-Writes defaulten `method` auf `manual`** statt `null`.
- **`POST` / `PUT` / `DELETE /transactions[/{id}]` (Scope `write`)** — volle
  CRUD-Paritaet zum UI. Bisher war der einzige Schreibpfad Pending-Order →
  `/fill`; DCA-Käufe ohne vorherige Order liessen sich extern gar nicht buchen,
  und Löschen/Ändern ging nur im UI. Alle drei teilen die Kernlogik der internen
  Endpoints (`create_/update_/delete_transaction_core`): Position-Auto-Anlage,
  Positions-Reversal beim Delete, Snapshot-Regen, Cache-Invalidierung,
  Dividend-Match.
- **Whitelist-Mirror-Schemas** (`ExternalTransactionCreate/Update`) auf
  `extra="forbid"`: ein vertippter oder nicht-änderbarer Feldname (z.B.
  `fee_chf`, oder `ticker` beim Update) gibt 422 statt still zu schlucken.
- **Audit-Log atomar mit der Mutation** committet (`transaction_create/update/
  delete`): schlägt der Log-Insert fehl (z.B. CHECK-Constraint), rollt die
  Mutation mit zurück — kein Orphan, ein Caller-Retry bleibt duplikatfrei.
  *(Fix gegenüber der ersten `POST`-Version, die den Log in einem zweiten Commit
  schrieb und bei fehlendem Whitelist-Wert einen 500 nach erfolgter Buchung
  warf.)*
- **Kein server-seitiger Dedup** (bewusst — UI-Paritaet): Caller prüft vor dem
  Buchen via `GET /transactions` gegen Duplikate.

### v0.40 — Report-Vault Voll-CRUD + Archiv

- **Report-Vault per `report_id` extern voll bedienbar** (vorher nur Upload +
  Bulk-Prune über Token; Einzel-Lesen/Ändern/Löschen war JWT/UI-only):
  - `GET /reports` (Liste, Filter inkl. `archived`) + `GET /reports/{id}`
    (Detail mit Body) — read-Scope.
  - `PATCH /reports/{id}` — partielles Ändern (`title`/`category`/`report_date`/
    `body`/`tags`), `tags:[]` leert, Body-Edit recomputed `content_hash`.
  - `DELETE /reports/{id}` — endgültiges Löschen (204, kein Undo).
- **Archiv als reversibler Soft-Delete** neben dem harten DELETE:
  - Neues Feld `archived_at` (NULL = aktiv) auf jedem Report (Migration `078`).
  - `POST /reports/{id}/archive` + `/unarchive`; `GET /reports?archived=true`
    ist die separate Archiv-Ansicht. Default-Liste (extern + interne UI) blendet
    Archiviertes aus.
- **`POST /reports/prune` archiviert** Sync-Waisen jetzt statt sie zu löschen
  (Antwort `{archived, kept}` statt `{deleted, kept}`); ein Re-Upload derselben
  `source_path` reaktiviert den Report automatisch.

### v0.39 — Bucket-Feature (Read-Only)

- **Position-Response erweitert** um `bucket_id: string|null` (UUID des Buckets)
  und `risk_rules: object|null` (Position-Level-Override falls gesetzt; sonst
  greifen Bucket-Rules). Beide Felder sind in der Whitelist
  `EXTERNAL_POSITION_FIELDS` und werden automatisch ausgeliefert.
- **9 neue Read-Only Bucket-Endpoints** unter `/buckets/...`:
  - `GET /buckets` — Liste aller Buckets (User + System) mit risk_rules,
    benchmark, target_pct/chf, deleted_at.
  - `GET /buckets/allocations` — Live-Allokation pro Bucket.
  - `GET /buckets/{id}/summary` — Marktwert + PnL.
  - `GET /buckets/{id}/history?period=` — Snapshot-Zeitreihe mit
    running_peak_chf.
  - `GET /buckets/{id}/drawdown?period=` — Peak-to-Trough + Bremse-Flag.
  - `GET /buckets/{id}/benchmark-comparison?period=` — Bucket vs Benchmark.
  - `GET /buckets/{id}/monthly-returns` — Monatsrenditen + Jahres-Totale.
- **Correlation-Matrix mit Bucket-Filter**:
  `GET /analysis/correlation-matrix?bucket_id=<UUID>` filtert die Matrix
  und HHI auf Positionen des Buckets.
- **Write-Endpoints bleiben JWT-only**: Bucket-CRUD, Templates, Move/Split,
  Migration-Rollback, Backfill, Import-Mapping-Regeln sind nicht via
  X-API-Key erreichbar. Drittparteien können analysieren, aber nicht
  selbständig umstrukturieren. Falls Schreib-Workflows benötigt werden:
  separater Audit-Cycle wie für Stop-Loss in v0.38.

### v0.38 — UI-Parität

- **Stop-Loss vollständig schreibbar** via `PATCH /positions/by-id/{id}/stop-loss`
  und `POST /portfolio/stop-loss/batch` (Cap 100). `confirmed_at_broker` Default
  ist `false`, ein API-Aufruf ohne dieses Feld setzt KEINE Broker-Bestätigung.
- **PII-Sichtbarkeit erweitert**: `bank_name`, `address`, `notes`, `tenant`,
  `mortgage.bank` als Klartext.  IBAN bleibt maskiert.
- **Marker-Felder konsistent**: `notes_last_api_write_at` und
  `notes_last_api_token_name` werden bei `/watchlist` und `/pending-orders`
  immer ausgeliefert (auch für read-only Tokens) — der Konsument braucht die
  Provenienz für Sync.
- **Neue Read-Endpoints**: `/transactions`, `/dividends/{pending,count}`,
  `/private-equity[/...]`, `/positions/{by-id|without-type|history|dividends}`,
  `/performance/{benchmark-returns|fee-summary|allocation/core-satellite}`,
  `/market/{climate|vix|macro-indicators|fx|precious-metals|real-estate|crypto-metrics|sectors/{etf}/holdings|scores}`,
  `/stock/{search|profile}`, `/etf-sectors/{ticker}`,
  `/screening/{results|ticker|scan/progress}`, `/precious-metals[/...]`,
  `/alerts/triggered`, `/watchlist/tags`, `/settings[/alert-preferences|onboarding/status]`,
  `/taxonomy/sectors`.
