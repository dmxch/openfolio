# Code-Review 2026-07-02: Bugs & Performance (gesamte Codebasis)

> **Status 2026-07-02: ALLE Findings behoben** (gleicher Tag, 10 Fix-Batches
> A-J mit disjunkter Datei-Ownership + Migration 093). Regressionstests in
> `backend/tests/test_review_fixes_[a-h].py`. Details/Behavior-Changes im
> CHANGELOG unter [Unreleased]. Bewusste Abweichungen von der Fix-Richtung:
> M30 nur Mitigation (kein Async-Redis-Umbau, sync-Client wird aus to_thread
> genutzt); LOW-form4-dedup via Vor-Insert-Aggregation statt Constraint;
> IBKR-Reversals werden geskippt+gewarnt statt negativ durchgereicht
> (Confirm-Schema validiert ge=0); LOW-universe filtert is_active UND shares>0.

Vollständige Durchsicht in 5 Bereichen: Kern-Berechnungen, Signale/Screening/Analyse,
API-Layer/Auth, Worker/Models/Imports, Frontend. Jeder Fund wurde im Code verifiziert;
die mit **[selbst verifiziert]** markierten Funde wurden zusätzlich vom Maintainer-Agent
direkt nachgeprüft (Route-Shadowing zusätzlich empirisch im Container).

**Kein IDOR gefunden**: alle Detail-/Update-/Delete-Endpoints (intern + extern, inkl.
Child-Ressourcen) sind sauber user_id-gescoped; `require_scope("write")` auf allen
externen Mutationen.

---

## CRITICAL

### C1. Dividenden-Cache kontaminiert Beträge cross-user [selbst verifiziert]
`backend/services/dividend_service.py:18` — [BUG]
Cache-Key `divs:{ticker}:{since_date}` enthält `shares` nicht, das gecachte Resultat
enthält aber `shares_held`/`total_chf` des ERSTEN Aufrufers. Über das geteilte Redis
(TTL 1h) bekommt jeder weitere Aufrufer die Beträge des ersten:
`refresh_dividend_forecasts` iteriert alle User mit identischem `since = today−365` —
User A (10× VT) füllt den Key, User B (500× VT) erhält As Liste → `forecast_12m_chf`,
`by_month`, `shares_held` um Faktor 50 falsch. Betrifft auch
`/api/positions/.../dividends` nach Käufen (alte Stückzahl 1h lang).
```python
cache_key = f"divs:{ticker}:{since_date.isoformat()}"
...
total_chf = round(shares * float(amount) * fx, 2)
```
Fix-Richtung: nur DPS-Zeitreihe (ticker-scoped) cachen, `shares`-Multiplikation pro
Aufruf ausserhalb des Caches rechnen.

---

## HIGH

### H1. History-Rekonstruktion: Cash/Vorsorge ohne FX [selbst verifiziert]
`backend/services/history_service.py:182,364` — [BUG]
Cash-/Pension-Salden werden als CHF gezählt, obwohl `cost_basis_chf` bei cash/pension
der Saldo in Positionswährung ist (Invariante; Live-Pfad `_compute_market_value` und
Snapshot-Pfad `_calc_portfolio_value_fast` konvertieren beide `saldo × fx`).
USD-Konto 100'000 → `/performance/history` (nicht-liquide Sicht) zeigt +100'000 CHF
statt ~88'000; Kurve weicht dauerhaft von Snapshots/Live ab. Gilt auch für die
Bucket-Drawdown-Rekonstruktion (`bucket_id`-Pfad).
```python
static_positions[pid] = float(pos.cost_basis_chf)   # Z.182, keine FX
value += float(pos.cost_basis_chf)                  # Z.364, keine FX
```

### H2. get_fx_rate: stiller 1.0-Fallback für exotische Währungen
`backend/services/utils.py:39` — [BUG]
Für alle Währungen ausserhalb {USD, EUR, CAD, GBP, JPY} fällt `get_fx_rate` still auf
1.0 zurück (`get_fx_rates_batch`/`get_fallback_fx`/`FX_PAIRS` kennen nur diese 5 Paare).
SEK-/AUD-/HKD-Dividende → `amount × 1.0` als CHF; SEK ~11× zu hoch. Kein Log, kein
Stale-Flag — im Gegensatz zum Positions-Pfad, der wenigstens `{ccy}CHF=X` aus der DB probiert.
```python
from_chf = rates.get(from_currency, fallback_fx.get(f"{from_currency}CHF", 1.0))
```

### H3. Pending-Dividends: keine Pence-Normalisierung (GBp ×100)
`backend/services/pending_dividend_service.py:454,490` — [BUG]
Der H3-Pence-Fix existiert nur in `dividend_service.fetch_dividends` (fast_info.currency
+ ÷100). `expected_gross_chf` rechnet hier `dps × get_fx_rate(pos.currency)` → bei
Pence-quotierten .L-Titeln ~100× zu hohe Pending-Beträge (UI, Digest-Mail, Push);
bei `pos.currency="GBp"` greift zusätzlich der 1.0-Fallback aus H2.

### H4. seed.py seit Migration 064 kaputt [selbst verifiziert]
`backend/seed.py:137` — [BUG]
`Position(**p)` wird ohne `bucket_id` angelegt, `positions.bucket_id` ist NOT NULL
(Migration 064, `models/position.py:72-76`) → `flush()` wirft IntegrityError, kein
Seed-Datensatz wird angelegt. seed.py erzeugt auch keine Default-Buckets.

### H5. Preis-Alert-Emails gehen bei Throttle endgültig verloren [selbst verifiziert]
`backend/services/price_alert_service.py:231-234` — [BUG]
Alerts werden in `check_price_alerts` VOR dem Mailversand als
`is_triggered=True, is_active=False` committet (one-shot, Z.89-108). Der 15-Min-Throttle
in `_send_user_alerts` returnt ohne Queue/Retry → Alert B, der 5 Min nach Alert A
triggert, ist konsumiert, seine Email geht nie raus. Das ungenutzte Feld
`PriceAlert.notification_sent` deutet auf das fehlende Delivery-Tracking.

### H6. Score nicht-deterministisch über Prozesse (Redis-Hit ohne Serien) [selbst verifiziert]
`backend/services/stock_scorer.py:156-161` — [BUG]
`_close_series`/`_volume_series`/… werden bewusst nur ins In-Memory-Objekt mutiert
(Kommentar Z.148-155), Redis enthält das Dict ohne Serien. Bei Redis-Cache-Hit im
jeweils anderen Prozess (Prod: 2 uvicorn-Worker + Worker-Prozess) fallen 5 Kriterien
(id 8, 16, 17, 18, 21) auf `passed=None` und verschwinden aus dem Nenner — derselbe
Ticker kommt mal als 16/18, mal als 13/15 mit anderem `pct`/`rating` zurück, ohne
Datenänderung.

### H7. /macro-indicators: yf_download synchron im Event-Loop [selbst verifiziert]
`backend/api/market.py:211` (via `macro_gate_service.py:114`) — [BUG]
`calculate_macro_gate()` wird sync im async Handler gerufen; bei kaltem Cache läuft
`get_market_climate()` → `compute_moving_averages("^GSPC")` → `yf_download()` auf dem
Event-Loop (Invarianten-Verstoss). Ein yfinance-Hänger/429 blockiert alle Requests des
Workers. Schwester-Endpoints (`market.py:38`, `external_v1.py:3721`) machen es korrekt
via `asyncio.to_thread`.

### H8. Route-Shadowing: GET /buckets/import-rules tot (UI kaputt) [empirisch verifiziert]
`backend/api/buckets.py:664` — [BUG]
Route ist NACH `GET /buckets/{bucket_id}` (Z.329) registriert; Starlette matcht in
Reihenfolge, UUID-Validierung liefert 422 statt Fallthrough (empirisch: 422
`uuid_parsing`, input `"import-rules"`). `ImportRulesSection.jsx:36` ruft genau diesen
Pfad → Import-Regeln-Liste im UI kaputt. POST/DELETE nicht betroffen.

### H9. /dividends/pending: ungecachter yf_download pro Zeile
`backend/api/dividends.py:157` — [PERF]
Pro Nicht-CHF-Zeile ein sequenzieller yfinance-Netzwerk-Download im Request (bis 200
Zeilen), ohne Memoisierung selbst bei identischem (currency, ex_date):
`get_historical_fx_rate` → `_yf_fx_close` → `yf_download` (utils.py:285), kein Cache.
Externer Spiegel `external_v1.py:3502` wird von Cron-Konsumenten gepollt →
Mehrsekunden-Latenz + Burst-429/IP-Ban-Risiko.

### H10. Frontend: "Score neu laden" dauerhaft wirkungslos (stale Closure) [selbst verifiziert]
`frontend/src/components/WatchlistTable.jsx:342` — [BUG]
`refreshScore` löscht `scores[ticker]`, ruft aber nach 100ms die ALTE
`loadScore`-Closure (useCallback mit `[scores, loadingScores]`), deren eingefrorenes
`scores` den Ticker noch enthält → Early-Return. Zeile zeigt „–" bis zum nächsten
vollen Refetch.

### H11. Frontend: Desktop- und Mobile-Baum gleichzeitig gemountet
`frontend/src/pages/StockDetail.jsx:742-809` — [PERF]
Nur CSS-hidden (`hidden md:grid` / `md:hidden`): `TradingViewChart` 2× instanziert
(zwei komplette TV-Embed-iframes auf jedem Gerät), `FundamentalCharts` doppelt →
`/stock/{ticker}/profile` und `/portfolio/summary` je 2×. Gleiches Muster:
`Performance.jsx:302/458` (`/portfolio/history` 2× parallel), `Dashboard.jsx:173`
(3 Makro-Panels fetchen auf Mobile trotz `hidden md:grid`).

### H12. Frontend: keine Request-Deduplizierung beim Mount
`frontend/src/pages/Performance.jsx:60` u.a. — [PERF]
Identische Endpoints 2-4× parallel beim Mount: `/portfolio/summary` (Page +
AllocationDonutCard + TopConcentrationCard + DataContext-Poll), `/portfolio/risk-metrics`
und `/analysis/factor-decomposition` (beide rechenintensiv, OLS) je 2×. Auch
`Portfolio.jsx:48/49`, `StockDetail.jsx:633`/`WatchlistTable.jsx:146` (kompletter
`/analysis/watchlist`-Download parallel zum DataContext-Cache). Der
`useCachedFetch`-Cache im DataContext wird von den Pages systematisch umgangen.

---

## MEDIUM — Korrektheit

### M1. Manuell bepreiste Positionen ohne FX im Live-Summary
`backend/services/portfolio_service.py:323` — [BUG]
`pricing_mode=manual` → `shares × price` als CHF, obwohl der Snapshot-Pfad
(`_calc_position_value_chf`) `× fx` rechnet. Manuelle USD-Position → Portfolio-Seite
~14% zu hoch, Snapshot korrekt → permanente Live/Snapshot-Diskrepanz; verletzt
`value_chf = shares × current_price × fx_rate`.

### M2. Snapshot-Regen verliert Wochenend-Cashflows
`backend/services/snapshot_service.py:823` — [BUG]
Portfolio-Snapshots nur an Wochentagen, `net_cf = cashflows_by_date.get(current_date)`
nur exakt — Sa/So-Cashflows (z.B. Krypto-Kauf am Samstag) werden nirgendwohin
aufgerollt. Daily-Recorder läuft dagegen inkl. Wochenende; `_calc_ytd` und der
Snapshot-CF-Zweig von Dietz/XIRR lesen den Kauf als Marktgewinn.

### M3. Double-Fill-Race auf Pending Orders (TOCTOU)
`backend/api/orders.py:415-419` (Twin: `external_v1.py:1859`) — [BUG]
`order.status != "open"`-Check ohne `SELECT ... FOR UPDATE`; kein Unique-Constraint auf
`linked_transaction_id`. Zwei parallele `POST /pending/{id}/fill` (Doppelklick/Retry)
buchen zwei Transaktionen + doppelte Shares.

### M4. Zwei Writer, ein Cache-Key (Summary ohne Enrichment)
`backend/main.py:474-480` vs. `backend/api/portfolio.py:44-74` — [BUG]
`/api/alerts` schreibt die UNangereicherte Summary unter `portfolio_summary:{user.id}`.
Kommt sie nach einer Invalidation zuerst, liefert `/summary` bis 60s Positionen mit
gedefaulteten Feldern (`notes/bank_name/iban=None`, `active_alerts=0`).

### M5. Cross-Worker-Cache-Invalidation kaputt
`backend/services/cache.py:110-124,142-148` — [BUG]
`get()` prüft den prozesslokalen Memory-Cache VOR Redis; `delete()` löscht nur eigenen
Memory + Redis. Bei 2 uvicorn-Workern überlebt die Kopie im anderen Worker bis TTL —
nach einem Write liefert `/summary` mit ~50% Wahrscheinlichkeit bis 60s alte Zahlen.

### M6. Redis-Verbindung: kein Reconnect nach Fehlstart
`backend/services/cache.py:24-31` — [BUG]
Schlägt der erste `ping()` fehl (Worker startet vor Redis), bleibt
`_redis_available=False` für die Prozess-Lebensdauer → permanenter In-Memory-Fallback;
der API-Prozess sieht nie frische Kurse — silent stale bis Container-Restart.

### M7. IBKR-Parser: zweite Dividende pro Tag überschreibt erste
`backend/services/ibkr_parser.py:581-583` — [BUG]
`bucket["dividend"...] = entry` überschreibt statt zu sammeln: "Dividends" + "Payment
In Lieu" am selben Tag → eine Dividende geht still verloren. Zusätzlich flippt
`abs(dividend["_amount"])` (Z.604) IBKR-Reversals zu positiven Dividenden.

### M8. Swissquote: Soll-Zinsen als Ertrag gebucht
`backend/services/swissquote_parser.py:82-83,468` — [BUG]
"Zinsen auf Belastungen" (Aufwand) mappt auf `interest`, `abs(net_account)` macht den
Betrag positiv; `total_return_service` summiert ihn als Einkommen → falsche
Ertrags-/Total-Return-Zahlen für Margin-Nutzer.

### M9. Per-Item-except ohne Rollback → PendingRollbackError-Kaskade
`backend/services/screening/sec_form4_service.py:306-310` — [BUG]
Nach DB-Fehler bleibt die geteilte Session im failed-state, jeder Folge-Ticker wirft
`PendingRollbackError`, still geloggt — Rest des Universums übersprungen. Gleiches
Muster: `etf_holdings_service.py:256-267`, `breakout_alert_service.py:28-32`,
`etf_200dma_alert_service.py:32-36`, `rule_alert_service.py:83-90`.
Korrektes Muster: `dividend_forecast_service.py:167-175`.

### M10. SEC Ticker↔CIK-Maps dauerhaft leer nach erstem Fetch-Fehler
`backend/services/screening/sec_form4_service.py:55-77` (auch `sec_13f_service.py:94-116`,
`activist_tracker.py:107-128`) — [BUG]
Map wird vor dem Fetch auf `{}` gesetzt, Early-Return prüft nur `is not None` — ein
transienter SEC-Fehler beim ersten Laden lässt den langlebigen Worker bis Neustart mit
leerer Map laufen (Form-4-Refresh liefert still 0).

### M11. ETF-Holdings: weggefallene Titel werden nie gelöscht
`backend/services/etf_holdings_service.py:208-222` — [BUG]
Nur UPSERT, kein DELETE für aus dem Index gefallene Holdings → stale Rows mit alten
Gewichten akkumulieren (EIMI ~3000 Positionen), Gewichtssummen > 100%,
Look-Through/Overlap zeigen Exposure zu nicht mehr gehaltenen Titeln.

### M12. Backtest-Harness-Gewichte driften vom Live-Score
`backend/services/screening/backtest_harness.py:57-66` — [BUG]
`DEFAULT_WEIGHTS` fehlen `six_insider`(+3), `form4_cluster`(+2), `estimate_revision`(+1),
`activist`(+2), 13F-Keys, `sector_bonus` — `reconstruct_score()` sortiert systematisch
in zu tiefe Buckets; die Bucket-Statistik misst nicht den deployten Score.

### M13. Wyckoff-Volumen-Slope nicht cross-ticker vergleichbar
`backend/services/chart_service.py:1169-1173` — [BUG]
Division durch `ln(median_vol)` macht die %/Tag-Metrik vom absoluten Volumen-Niveau
abhängig (~40% Unterschied liquide vs. illiquide bei gleichem relativem Trend); die
festen ±0.5%/d-Schwellen greifen ungleich. Korrekt: `slope * 100` (Slope von
log-Volumen ist bereits relative Änderung/Tag).

### M14. FX-Transaktionen-Import nicht idempotent
`backend/services/import_service.py:1226-1248` — [BUG]
`fx_transactions` werden beim Confirm ohne Duplikat-Check eingefügt (`order_id`
vorhanden, ungenutzt). Zweiter Import derselben CSV → alle FxTransaction-Rows doppelt.

### M15. Sektor-Drilldown pinnt Broken-Scores 24h
`backend/api/market.py:184-195` (Kopie: `external_v1.py:3961-3972`) — [BUG]
`setup_score:{ticker}` wird 24h gecacht ohne den Broken-Fall (`price is None` nach
transientem 429) auszunehmen — `assess_ticker` cached genau diesen Fall bewusst nur
60s; der Wrapper hebelt das aus (Score 2/18 für 24h in `sector_scores:{etf}`).

### M16. PII als Klartext in Redis
`backend/api/portfolio.py:62-74` — [SEC]
Summary wird NACH der PII-Anreicherung gecacht: entschlüsselte `bank_name`/`notes` als
Klartext-JSON in Redis (inkl. RDB/AOF auf Disk) — hebelt die Feld-Verschlüsselung
at-rest für diese Felder aus.

### M17. Macro-Gate: inkonsistente Missing-Data-Semantik
`backend/services/macro_gate_service.py:29-34` — [BUG/LOW-MED]
G5-G7 liefern bei fehlenden Daten `None` (aus Nenner raus), G1/G2/G3 `False` (Fail mit
vollem Gewicht 5 von 9), G4 fail-open (`True`).

### M18. Frontend: DateInput-Parent-Sync ist Dead Code
`frontend/src/components/DateInput.jsx:31-35` — [BUG]
Der Sync-if-Block ist leer (`setText` fehlt): setzt der Parent `value` zurück
(`resetFilters` in Transactions), zeigt das Input weiter das alte Datum, Filter ist
tatsächlich leer — UI und Filterzustand laufen auseinander.

### M19. Frontend: Timezone-Off-by-one in Datumsanzeige
`frontend/src/lib/format.js:109-113` — [BUG]
`new Date("YYYY-MM-DD")` parst UTC-Mitternacht, formatiert lokal → westlich von UTC
zeigt alles den Vortag. Spiegelbildlich `toISOString().split('T')[0]`:
`DateInput.jsx:215` („Heute"-Button vor ~01:00 CET = gestern), `PerformanceChart.jsx:51/123`,
`RollingDrawdownCard.jsx:119`.

## MEDIUM — Performance

### M20. concentration_service: 5× get_portfolio_summary pro Request
`backend/services/concentration_service.py:47,71,161,244,249` — [PERF]
Ein `get_concentration_for_ticker`-Request ruft die ungecachte `get_portfolio_summary()`
fünfmal (ETF-Map, Direkt-Position, Liquid-Total, Sektor-Aggregation, ETF-Map erneut) —
je mehrere DB-Queries + Preis-/FX-Resolution über alle Positionen.

### M21. stock_scorer lädt ^GSPC pro Ticker neu
`backend/services/stock_scorer.py:45-46` — [PERF]
`yf_download(f"{ticker} ^GSPC", period="2y")` cached nur per Ticker — Sektor-Drilldown
(~25-30 Holdings, seriell) lädt die identische Benchmark-Historie 30× → doppeltes
Transfervolumen, höhere 429-Exposure.

### M22. Snapshot-Regen: get_close ist O(Serie) pro Lookup
`backend/services/snapshot_service.py:576-588` — [PERF]
`col.loc[:ts].dropna()` (Slice+Kopie) × (Positionen+FX) × Kalendertage ≈ 10⁷
Zeilenoperationen pro Regen (läuft bei jeder rückdatierten Txn). `history_service`
löst dasselbe mit O(1)-Dict + Forward-Fill (Z.305-319).

### M23. History-Download-Fenster hängt an erster Transaktion
`backend/services/history_service.py:259-268` — [PERF]
`dl_start = min(earliest_txn, start_date) − 5d`: 1-Monats-Chart bei 10 Jahren Historie
lädt ~2500 Handelstage × alle Ticker+FX — nötig wären ~2 Wochen Warm-up vor `start_date`.
Nach jedem 15-min-Cache-Ablauf erneut.

### M24. Täglicher Bucket-Snapshot lädt komplette Historie
`backend/services/snapshot_service.py:430-442` — [PERF]
`date < snapshot_date` ohne LIMIT/DISTINCT ON als ORM-Objekte, nur um pro Bucket die
jüngste Row zu picken (Kommentar behauptet „DISTINCT ON"). 3 Buckets × 2 Jahre ≈ 2200
Rows pro User pro Tag statt 3.

### M25. Realized Gains: Full-Table-GROUP-BY über alle User
`backend/services/total_return_service.py:296-302` — [PERF]
First-Buy-Query weder user- noch positions-gefiltert → Full-Scan über Transaktionen
ALLER User bei jedem Aufruf der Realized-Gains-Seite.

### M26. get_fx_rate: immer 5 Sync-DB-Queries; teils auf dem Event-Loop
`backend/services/utils.py:38` — [PERF]
`get_fallback_fx()` läuft bedingungslos (5 Sync-Sessions pro Aufruf), auch bei
Redis-Hit. In `pending_dividend_service.py:454` direkt auf dem Event-Loop (nicht
to_thread), inkl. potenziellem sync yf_download bei Redis-Miss.

### M27. get_portfolio_summary: N+1 Sync-Preis-Lookups im async Pfad
`backend/services/price_service.py:31-46` + `portfolio_service.py:172` — [PERF]
Pro Position sync `get_stock_price`; bei Redis-Miss 1-2 synchrone DB-Sessions pro
Position auf dem Event-Loop. `get_cached_prices_batch_sync` existiert, wird nicht genutzt.

### M28. Report-Listen laden alle Bodies, paginieren in Python
`backend/api/reports.py:91-109` (identisch `external_v1.py:2249-2267`) — [PERF]
Alle User-Reports als volle Entities inkl. Markdown-`body` (Limit 5000/User), Filter/
Sort/Pagination in Python. Fix: Spalten-Select ohne `body` + SQL LIMIT/OFFSET.

### M29. Prometheus-Label-Kardinalität explodiert
`backend/middleware/metrics.py:42-54` — [PERF]
`_normalize_path` kollabiert nur UUIDs und `stock/stocks`-Segmente; Ticker-/Slug-Pfade
(`/analysis/score/AAPL`, `/market/fx/USD`, `/etf-sectors/{ticker}`, …) erzeugen je
Ticker×Methode×Status eigene Serien (Counter + Histogram×10 Buckets).

### M30. Cache nutzt synchronen Redis-Client in async Handlern
`backend/services/cache.py:24-43,119-139` — [PERF]
Blockierende Netz-I/O auf dem Event-Loop; bei Redis-Stall blockiert jeder Cache-Op den
Loop bis `socket_timeout=1`s für alle Requests seriell; `get_or_compute` hält dabei
einen `asyncio.Lock`.

### M31. Import-Duplikat-Check: 1-3 Queries pro Zeile, kein order_id-Index
`backend/services/import_service.py:759-765` + `models/transaction.py:60` — [PERF]
Pro Import-Zeile sequenzielle EXISTS-Queries in Preview UND Confirm; 2000-Zeilen-Import
→ bis ~6000 Roundtrips. Batch-Vorab-Query bzw. Index `(user_id, order_id)` fehlt.

### M32. Frontend: unbegrenzter paralleler Score-Burst
`frontend/src/components/PortfolioTable.jsx:209` (auch `WatchlistTable.jsx:304`) — [PERF]
`Promise.all(tickers.map(...))` feuert N gleichzeitige `/api/analysis/score/{ticker}` —
bei Cache-Miss landet das auf yfinance und unterläuft clientseitig das dokumentierte
Burst-Limit (Semaphore ≤ 3, 429-IP-Ban).

### M33. Frontend: Tabellen-Sort bei jedem Render
`frontend/src/components/PortfolioTable.jsx:302` — [PERF]
`[...filteredPositions].sort(...)` ungememoized — läuft bei jedem Tastendruck im
Inline-Notizen-Textarea und jedem Popover-Toggle; ganze Tabelle re-rendert.

---

## LOW (Auswahl, vollständig)

- `backend/services/total_return_service.py:48-63` — [BUG] `gross_amount IS NULL`-Rows
  fallen aus der Gross-SUM, bleiben aber in net → gross < net möglich (unmöglicher Zustand).
- `backend/services/snapshot_trigger.py:29` — [BUG] Fire-and-forget `create_task` ohne
  Referenz + kein Per-User-Lock: konkurrierende Regens kollidieren am
  `uq_bucket_snapshot` (pg_insert ohne on_conflict) und brechen ab.
- `backend/services/performance_service.py:98-104` — [BUG] Daily-Change nutzt
  `fx_cache.get(pos.currency)` statt der resolved Quote-Währung der Cache-Row
  (Standing Rule: „.L sagt NICHTS über Währung") → falsche FX-Gewichtung oder Skip.
- `backend/worker.py:812,1093` — [BUG] `create_task` ohne starke Referenz
  (Heartbeat/startup_refresh) — GC-Footgun; Repo hat das korrekte `_pending`-Set-Muster
  in `ntfy_service.py:69-72`.
- `backend/services/api_token_service.py:176` — [BUG] dito `_touch_last_used` →
  `last_used_at` sporadisch nicht aktualisiert.
- `backend/services/screening/sec_13f_service.py:562-697` — [BUG] kein per-Fund
  try/except: ein Fehler bricht den ganzen 13F-Lauf ab.
- `backend/services/import_service.py:1319-1326` — [PERF] `_auto_assign_industries` im
  awaited Confirm-Request: `sleep(0.5)` + rohes `yf.Ticker(t).info` pro neuer Position
  (50 Positionen ≈ 1-2 Min Response; einziger Pfad am yf_patch-Wrapper vorbei).
- `backend/api/transactions.py:263-265` / `orders.py:359-362` — [PERF] rohes
  `yf.Ticker(ticker).info` (429-anfällig, kein Wrapper/Semaphore) im Request-Pfad.
- `backend/models/position.py:72-76` — [BUG] `ondelete="SET NULL"` widerspricht
  `nullable=False` → Hard-Delete eines Buckets = NotNullViolation.
- `backend/services/screening/sec_form4_service.py:280-289` — [BUG] Dedup-Key kollabiert
  gleichtägige Teilausführungen desselben Insiders → `total_value` unterschätzt.
- `backend/services/cache_service.py:644-660` — [PERF] Kurs-Refresh: 1 UPDATE pro
  Ticker (Universum inkl. Watchlist) statt gebatchtem `UPDATE ... FROM (VALUES ...)`;
  kein Index auf positions.ticker/yfinance_ticker.
- `backend/services/screening/universe.py:68-70` — [BUG] `resolve_equity_universe`
  filtert nicht auf `is_active` (Docstring verspricht es) → ~18 geschlossene Positionen
  laufen in jedem SEC-Refresh mit.
- `backend/services/stock_scorer.py:504,638-641` — [BUG] `"weight": 2` (Kriterium 8)
  wird nirgends verwendet — Aggregation zählt alles mit 1.
- `backend/services/chart_service.py:101-116,666-671` — [PERF] kein Negative-Caching in
  `get_breakout_events`/`get_support_resistance_levels` (get_mrs_history hat es).
- `backend/services/stock_scorer.py:114-124` (auch `chart_service.py:125-137,214-235`) —
  [BUG] Positional-Indexing über getrennt `dropna()`-te Serien (close vs. high/volume)
  → bei NaN-Lücken Misalignment, falsches Breakout-Datum/Volumen-Confirm.
- `backend/services/macro_gate_service.py:29-34` — siehe M17.
- `backend/api/analysis.py:474-480` — [BUG] PATCH watchlist gibt Fernet-Ciphertext
  statt Klartext-Notiz zurück.
- `backend/api/auth.py:608-616` — [SEC] forgot-password: SMTP inline awaited →
  Timing-basierte Account-Enumeration (gedämpft durch Rate-Limit).
- `backend/api/auth.py:273-292` — [BUG] Refresh-Rotation ohne Grace-Window: zwei Tabs
  lösen benign die Theft-Heuristik aus → alle Sessions revoked.
- `backend/api/external_v1.py:1945-1950` — [PERF] screening/latest ohne Pagination
  (~1500 Rows inkl. signals-JSON). Nebenbefund: `GET /performance/fee-summary` doppelt
  registriert (Z.445 + 3678, zweiter Handler toter Code).
- `frontend/src/pages/StockDetail.jsx:276-292` — [BUG] Panels resetten beim
  Ticker-Wechsel nur `error`, nicht die Daten → Daten des vorherigen Tickers sichtbar.
- `frontend/src/contexts/DataContext.jsx:95-112` — [PERF] Context-value ohne useMemo →
  alle Consumer re-rendern; Refresh-Interval wird nach jedem Fetch neu erstellt.
- `frontend/src/components/Toast.jsx:14` — [BUG] `Date.now()` als Toast-ID → Kollision
  bei schnellen Folge-Toasts (doppelter React-Key, beide schliessen).
- `frontend/src/components/GlossarTooltip.jsx:3` — [PERF] glossary.js (72KB) hängt am
  eager geladenen Dashboard im Initial-Chunk.
- `frontend/src/components/FireProjectionCard.jsx:68-77` — [PERF] redundanter
  PUT nach Server-Seed bei jedem Mount (Write-on-Read).

---

## Ohne Befund geprüft

Backend: yf_patch.py, cot_service, unusual_volume, sector_rotation,
factor_decomposition (Download gebündelt, NYSE-Alignment ok), Swing-Low-Leiter in
chart_service (Gap-up-Guard vorhanden), MRS-/Donchian-Definitionen entsprechen den
Invarianten, Advisory-Locks, Multi-User-Scoping der Worker-Jobs,
pending_dividend-Session-Handling (Semaphore 3), SMTP via aiosmtplib / HTTP via httpx
durchgängig, Import-Flow ruft Recalculate + Snapshot-Regen, kein IDOR in allen 27
Routern + external API.

Frontend: useApi (Abort + 401-Refresh-Queue), AuthContext (Token-Rotation),
Cleanup-Hooks, SmartMoney/EpsScanner, localStorage-Zugriffe (try/catch überall),
Recharts korrekt lazy-isoliert.
