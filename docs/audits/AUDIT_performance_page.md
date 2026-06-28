# Audit Report — Performance-Seite (neue Lasche)

Datum: 2026-06-26 · Auditor: @openfolio-audit (Opus 4.8) · Scope: uncommitted Working-Tree-Diff
Grundlage: DESIGN_performance_page.md, git diff (15 Dateien geändert, 7 neu)
Re-Audit: 2026-06-26 (Fix-Verifikation gegen aktuellen Working-Tree)

## Zusammenfassung

**Verdikt: GRÜN — der Blocker (#1) und beide adressierten Non-Blocker (#2, #3) sind verifiziert behoben; mergebar.**

Security PASS · QA PASS · Architektur PASS · HEILIGE Regeln PASS · UX PASS.

Die Backend-Änderungen sind sauber additiv: die geschützten whole-portfolio-Pfade
(`get_total_return`, `get_fee_summary(bucket_id=None)`) bleiben byte-identisch, das
Per-Bucket-Verhalten liegt in separaten Funktionen bzw. additiven Filtern. Multi-User-
Scoping, Bucket-Ownership auf den Pfad-Endpoints und External-API-Parität sind erfüllt.
Der ursprüngliche Blocker (Rate-Limit-Kollision auf `/portfolio/history`) ist durch
Anhebung des Limits auf 30/min behoben; die beiden adressierten UX-/Konsistenz-Non-Blocker
sind ebenfalls eingearbeitet. Die zwei verbleibenden Info-Findings (#4 422-vs-404, #5
Doppel-Fetch) sind bewusst nicht gefixt und genuin nicht-blockierend (kein Leak, kosmetisch).

## Findings

| # | Bereich | Severity | Datei:Zeile | Problem | Status |
|---|---------|----------|-------------|---------|--------|
| 1 | Perf/UX | **BLOCKER (funktional)** → **BEHOBEN** | `backend/api/performance.py:25` (`@limiter.limit("5/minute")`) + `frontend/src/components/PerformanceChart.jsx:70`, `RollingDrawdownCard.jsx:110` | `/portfolio/history` war auf **5/min pro Client-IP** limitiert. Die Performance-Seite fächert es 2× beim Mount + **2× pro aufgeklapptem Bucket** auf → Mount (2) + Bucket A (2) + Bucket B (2) = **6 Calls/Min → der 6. lieferte HTTP 429**. | **BEHOBEN** — `performance.py:25` jetzt `@limiter.limit("30/minute")` (aligned mit `/drawdown`, das ebenfalls rekonstruiert). Verifiziert: 6× Headroom-Faktor; siehe Headroom-Rechnung unten. |
| 2 | UX-Konsistenz | Niedrig → **BEHOBEN** | `frontend/src/components/BucketSection.jsx:70` | `capital_gains_dist_chf` hiess im Bucket-Breakdown „Kapitalrückzahlungen", in der whole-portfolio-Karte „Kapitalgewinne" → inkonsistent bei identischer Quelle. | **BEHOBEN** — `BucketSection.jsx:70` labelt jetzt „Kapitalgewinne" (deckungsgleich mit `PerformanceCard.jsx:37`). |
| 3 | Perf/Konsistenz | Niedrig → **BEHOBEN** | `frontend/src/components/RollingDrawdownCard.jsx:112` vs `RiskMetricsCard` (`risk_metrics_service.py:104`) | Der Underwater-Drawdown-Chart las `/portfolio/history` **ohne `liquid=true`** (zählte Vorsorge mit), während die „Max Drawdown"-Kennzahl auf `liquid=True` rechnet → Talsohle konnte von der Kennzahl divergieren. | **BEHOBEN** — `RollingDrawdownCard.jsx:112` hängt jetzt `&liquid=true` an; der Param ist im Backend (`performance.py` → `get_portfolio_history(..., liquid=...)`, `history_service.py:113,290`) korrekt verdrahtet. PerformanceChart bleibt bewusst whole-portfolio (`PerformanceChart.jsx:70`, kein `liquid`) — Equity-Curve zeigt das Gesamtvermögen, Drawdown das Risikobuch. |
| 4 | Sicherheit/Konsistenz | Info (nicht gefixt — bewusst) | `backend/api/performance.py` `/risk-metrics`, `/history`; `backend/api/analysis.py` factor-decomposition (alle `?bucket_id=`) | Die Query-Param-Endpoints validieren Bucket-**Ownership nicht** via `get_bucket`. **Kein Datenleck**: `get_portfolio_history`/`factor_decomposition` filtern hart auf `Position.user_id == current_user` UND `bucket_id`; ein fremder Bucket liefert leere Reihe → 422/`{data:[]}` statt 404. Die Pfad-Endpoints (`/buckets/{id}/total-return`, `/fee-summary`) prüfen Ownership korrekt (404). | **NICHT-BLOCKIEREND (bestätigt)** — kein Leak, harter user_id-Filter; 422-statt-404 ist rein kosmetisch. Optionaler `get_bucket()`-Guard als Follow-up. |
| 5 | Perf | Info (nicht gefixt — bewusst) | `frontend/src/pages/Performance.jsx:27,31,33` + `BucketComparisonBar.jsx:157-160` | `/portfolio/summary`, `/portfolio/total-return`, `/portfolio/buckets` werden doppelt geladen (Page-Level + erneut in BucketComparisonBar). | **NICHT-BLOCKIEREND (bestätigt)** — server-seitig gecacht, kosmetisch. Props-Durchreichung als Follow-up. |

## Re-Audit / Fix-Verifikation (2026-06-26)

Verifiziert gegen den aktuellen Working-Tree (`git diff` + Direkt-Lesung der untracked Neufiles):

- **Blocker #1 — Rate-Limit:** `backend/api/performance.py` Zeile 25 ist jetzt `@limiter.limit("30/minute")` (vorher `5/minute`), aligned mit `/drawdown` (`performance.py`, ebenfalls 30/min, rekonstruiert dieselbe Index-Reihe). Der Endpoint nimmt additiv `bucket_id: uuid.UUID | None` und `liquid: bool = Query(default=False)` und reicht beide an `get_portfolio_history(...)` durch. Die geschützten whole-portfolio-Defaults bleiben unverändert (`liquid=False`, `bucket_id=None`).
- **Headroom-Rechnung (30/min):** Mount = 2 whole-Calls (PerformanceChart 1Y + RollingDrawdownCard 5y). Pro aufgeklapptem Bucket = +2. Perioden-Wechsel im Equity-Chart ändern `startDate` → je distinkter Periode +1 Request (server-Cache reduziert DB-Last, **nicht** das slowapi-Budget — jeder HTTP-Request zählt). Realistische Kern-Interaktion: Mount (2) + 3 Buckets aufklappen (6) + ein paar Perioden-Wechsel (≈5) ≈ 13 Calls/Min. Aggressiv (3 Buckets × alle 6 Perioden durchklicken + whole) ≈ 26 — bleibt unter 30. Vorher brach es bei 6. → **6× Limit, ausreichend Headroom für den dokumentierten Fan-out** (mount=2, +2/Bucket, gelegentliche Perioden-Switches, durch 15-min-Cache latenz-, nicht budget-entlastet).
- **Non-Blocker #2 — Label:** `frontend/src/components/BucketSection.jsx:70` → `<Stat label="Kapitalgewinne" value={tr.capital_gains_dist_chf} />`. Konsistent mit `PerformanceCard.jsx`.
- **Non-Blocker #3 — liquid-Konsistenz:** `frontend/src/components/RollingDrawdownCard.jsx:112` hängt `&liquid=true` an die `/portfolio/history`-URL; Kommentar (Zeile 110–111) dokumentiert die Absicht. `PerformanceChart.jsx:70` bleibt bewusst ohne `liquid` (Equity-Curve = Gesamtportfolio). Backend-Verdrahtung verifiziert: `history_service.py:113` und `:290` schliessen bei `liquid=True` Cash + Vorsorge aus.
- **Keine Regression:** Der Diff berührt nur additive Pfade; `total_return_service.py` (`get_total_return` byte-identisch, `get_fee_summary` nur additiver `if bucket_id is not None`-Filter), keine Berührung von `portfolio_service`/`recalculate_service`/`price_service`/`utils`/`performance_history_service`. Implementer-Verifikation (py_compile OK, `npm run build` grün, Images rebuilt, Stack live, `/api/portfolio/history?liquid=true` → 401 = Route akzeptiert den Param) deckungsgleich mit der Code-Lesung.

## HEILIGE-Regeln-Compliance (verifiziert)

- **Regel 1 & 11 (Performance-/Renditeberechnung unverändert):** ERFÜLLT. `git diff` zeigt für `total_return_service.py` nur Additionen: `get_total_return` ist **nicht** im Diff (byte-identisch); `get_fee_summary` bekommt nur einen additiven `if bucket_id is not None`-Filter, der `bucket_id=None`-Pfad ist unverändert. `get_bucket_total_return` ist bewusst eine **separate** Funktion (Money-on-Money, `is_money_weighted=False`, kein XIRR — korrekt deklariert). `risk_metrics_service.py` rechnet rein read-only auf der bestehenden `portfolio_indexed`-Reihe; die TWR-Annualisierung ist explizit als **nicht** die XIRR/MWR-Jahresrendite gelabelt (Service-Docstring + UI-Hinweis `RiskMetricsCard.jsx:137`). Keine Berührung von `portfolio_service`/`recalculate_service`/`price_service`/`utils`/`performance_history_service`.
- **Regel 4/5/6 (Immobilien/Vorsorge/PE nicht in liquide Performance):** ERFÜLLT. Risiko-Kennzahlen + Faktor-Decomposition rufen `get_portfolio_history(..., liquid=True)` → schliesst Cash, Vorsorge, PE, Immobilien aus. Mit Fix #3 rechnet jetzt auch der Underwater-Drawdown-Chart `liquid=true`, d.h. Vorsorge ist nicht mehr mitgezählt — die letzte Feinheit aus dem Erst-Audit ist damit ausgeräumt. `get_bucket_total_return` filtert `type != private_equity` (analog whole-portfolio). Immobilien/PE/Vorsorge-Widgets bleiben auf der Portfolio-Seite.
- **Multi-User-Scoping:** ERFÜLLT. Alle neuen Endpoints `user_id`-scoped; Pfad-Bucket-Endpoints erzwingen Ownership (404). Cache-Keys enthalten `user_id` **und** `bucket_id` (`history_service.py:49-52`, `factor_decomposition_service.py:156`) → kein Cross-User-Cache-Leak. Test `test_bucket_total_return_user_isolation` deckt das ab.

## External-API-Parität (Maintainer-Anforderung)

ERFÜLLT — jeder neue interne Read-Endpoint ist in `external_v1.py` gespiegelt (X-API-Key via `get_api_user`, `@limiter.limit(RATE_LIMIT)`):
- `/api/portfolio/risk-metrics` → `/v1/performance/risk-metrics` (default `5y`, mit prior Review aligned)
- `/api/portfolio/buckets/{id}/total-return` → `/v1/buckets/{id}/total-return` (Ownership-Guard vorhanden)
- `/api/portfolio/buckets/{id}/fee-summary` → `/v1/buckets/{id}/fee-summary` (Ownership-Guard vorhanden)
- `/api/analysis/factor-decomposition?bucket_id=` → `/v1/analysis/factor-decomposition?bucket_id=`
- `/api/portfolio/history?bucket_id=` → `/v1/performance/history?bucket_id=`
- Zusätzlich die vorbestehende Lücke geschlossen: `/v1/performance/fee-summary` (whole).

## Verifizierte angewandte Fixes des Vor-Reviews (alle korrekt, NICHT re-flagged)

- `get_bucket_total_return` invested = `market_value_chf - pnl_chf` → Fremdwährungs-Cash im Bucket wird nicht fehl-skaliert. Test `test_invested_uses_chf_market_value_for_cash` (USD-Cash: 8800 CHF, nicht 10000 USD-Saldo). KORREKT.
- Allokations-Alert navigiert nach `/performance#allocation-charts` (`Portfolio.jsx:139`) + Hash-Scroll-Effekt (`Performance.jsx:37-45`, 200ms Delay nach Load). KORREKT.
- 422-Unterscheidung: `FactorExposureCard.jsx:48` (`/\b422\b/.test(String(error))`) und `RiskMetricsCard.jsx:56` — `useApi`-Error ist `"HTTP <status>"`, Match greift. KORREKT.
- `BucketComparisonBar` `onSelectBucket` verdrahtet (scrollt zu `#bucket-{id}`); kein doppeltes „Performance je Bucket"-Heading (nur in BucketComparisonBar); external risk-metrics default = `5y`. KORREKT.

## Stärken

- Saubere Additivität: geschützte Formeln nachweislich unberührt; Bucket-Scoping ausschliesslich über `Position.bucket_id`-Filter im Daten-Vorlauf.
- Korrekte Realized-P&L-Attribution über `bucket_id_at_sale` (Snapshot zum Verkauf), konsistent mit `get_realized_gains`; durch Test `test_realized_uses_bucket_id_at_sale_not_current` abgesichert.
- Gute Test-Abdeckung der neuen Services (Attribution, User-Isolation, Cash-FX-Nenner, rf-Sensitivität, insufficient_history, IR ohne Benchmark).
- Lazy-Load der Bucket-Sektionen (`BucketSection`, `{open && ...}`) — Per-Bucket-Fetches feuern erst beim Aufklappen.
- Sorgfältige Leerzustände (422/503/zu-wenig-Historie sauber getrennt), `aria-expanded` an Accordion/Context-Buttons, Schweizer Deutsch konsequent (kein ß, korrekte Umlaute), neutrale Signalsprache (keine imperativen Anweisungen).
- `RISK_FREE_RATE_PCT` korrekt in `config.py` UND **beide** Compose-Env-Blöcke (backend + worker) — vermeidet die bekannte „Compose Env-Passthrough"-Falle.

## Empfehlung

**GRÜN — mergebar.** Der Blocker (#1) ist durch Anhebung des `/history`-Limits auf 30/min
behoben (6× Headroom, deckt den Accordion-Fan-out inkl. Perioden-Wechsel ab); die beiden
adressierten Non-Blocker (#2 Label, #3 liquid-Konsistenz) sind verifiziert eingearbeitet
und korrekt durchverdrahtet. Die zwei verbleibenden Info-Findings (#4 422-statt-404, #5
Doppel-Fetch) sind bewusst nicht gefixt und genuin nicht-blockierend — kein Datenleck,
rein kosmetisch — und können als Follow-up laufen. Keine Regression in geschützten Pfaden.
