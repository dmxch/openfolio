# DESIGN — Performance-Seite (neue Lasche)

Status: Scoping (zur Freigabe) · Datum: 2026-06-26 · Autor: Claude (Opus 4.8)

> **✅ AUSGELIEFERT (Stand 28.06.2026, Roadmap-Abgleich):** Dieses Scoping ist umgesetzt — Performance-Seite, Equity-Curve, **Risiko-Kennzahlen (Phase 3)**, Faktor/Alpha-Beta, Per-Bucket Total-Return/Fees sind gebaut + prod-live (Commit `d4cf8ec`, v0.51.0). Die „NEEDS_BUILD"-Markierungen unten sind **historisch** (Scoping-Zeitpunkt), nicht der aktuelle Stand. Einziger Rest: externer Paritätstest für `risk-metrics`. Aktueller Stand: `docs/strategy/STRATEGIE_ROADMAP_2026-06-27.md` (Backlog D).

## 1. Ziel & Kontext

Heute lebt die gesamte Portfolio-Funktionalität auf **einer** Seite (`frontend/src/pages/Portfolio.jsx`,
15 Widgets) mit einem `BucketTabBar`-Switch (Modi „Aggregiert" / „Pro Bucket"), der jeweils nur
**einen** Bucket auf einmal zeigt.

Ziel: Eine **neue Lasche „Performance"** (`/performance`), die alle Performance-/Analyse-Widgets
aufnimmt und die Buckets (Total, Core, Satellite, Hard Money, Crypto) **gleichzeitig nebeneinander**
zeigt — statt sie durchzuschalten. Die **Portfolio-Seite wird zur reinen Positionsverwaltung**
(Switch entfällt).

Entscheidungen des Maintainers (26.6.):
- Allokations-Charts + Diversifikation (HHI) → **wandern auf die Performance-Seite**.
- Bucket-Tiefe → **volle Widgets pro Bucket** (jeder Bucket bekommt den kompletten Satz).
- Zusatz-Metriken → **alle vier**: Alpha & Beta / Faktor-Exposure, Risiko-Kennzahlen,
  Equity-Curve vs Benchmark, Rolling Returns + Drawdown-Chart.
- **API-Anforderung: Alles Neue muss auch über die externe API (`backend/api/external_v1.py`)
  erreichbar sein** — nicht nur über die interne UI-API.

## 2. Was umzieht, was bleibt

| Bleibt auf **Portfolio** (Positionsverwaltung, CRUD) | Zieht auf **Performance** (Analyse) |
|---|---|
| PortfolioTable (Aktien/ETFs) | PerformanceCard / TotalReturnCard |
| CashTable (Banken + count_as_cash-ETFs) | MonthlyHeatmap (Monatsrenditen) |
| PensionTable (Vorsorge) | TopMovers (Top-Gewinner/Verlierer) |
| ImmobilienWidget | RealizedGainsTable |
| PrivateEquityWidget | FeeSummary |
| PreciousMetalsWidget | AllocationCharts (Asset-Typ/Sektor/Währung) |
| CryptoWidget | HhiCard (Diversifikation) |
| | **NEU:** PerformanceChart (Equity-Curve, reaktiviert) |
| | **NEU:** Faktor-Exposure / Alpha-Beta-Karte |
| | **NEU:** Risiko-Kennzahlen-Karte |
| | **NEU:** Rolling-Returns + Underwater-Drawdown-Chart |

**Switch-Entfernung:** `BucketTabBar` raus aus Portfolio.jsx; `bucketView`-State + `passesBucketFilter`
entfallen dort. Portfolio zeigt immer alle Positionen. Damit die Bucket-Zuordnung sichtbar bleibt:
**Bucket-Badge-Spalte** in `PortfolioTable`. Bucket-*Zuweisung* bleibt unverändert (EditPositionModal /
BucketsModal) — nur der *Ansichts-Filter* verschwindet.

## 3. Daten-Readiness (verifiziert)

Quelle: 2 Explorations-Workflows über Frontend, Backend, Routing, Git-History (26.6.).

### 3.1 Whole-Portfolio
| Feature | Endpoint | Status |
|---|---|---|
| Total-Return-Breakdown | `GET /api/portfolio/total-return` | READY |
| Monatsrenditen | `GET /api/portfolio/monthly-returns` | READY |
| Top-Mover | client-seitig aus `summary.positions` | READY |
| Realisierte Gewinne | `GET /api/portfolio/realized-gains` | READY |
| Gebühren | `GET /api/portfolio/fee-summary` | READY |
| Allokation | `GET /api/portfolio/summary` (`allocations`) | READY |
| HHI / Diversifikation | `GET /api/portfolio/correlation-matrix` | READY |
| Drawdown | `GET /api/portfolio/drawdown` | READY |
| **Equity-Curve** | `GET /api/portfolio/history` | **READY** (Chart-Komponente nur reaktivieren) |
| **Alpha/Beta/Faktoren** | `GET /api/analysis/factor-decomposition` | **READY** |
| **Risiko-Kennzahlen** | — | **NEEDS_BUILD** |
| **Rolling Returns** | abgeleitet aus `/history` | **NEEDS_BUILD** (leichtgewichtig) |

> **PerformanceChart-Hinweis:** Der Disable-Kommentar (`Portfolio.jsx:10`, „performance calculation
> needs rework") stammt aus dem Initial-Commit `f7af54e` und ist veraltet. `history_service` ist seither
> produktiv gehärtet (Pence-Fix `6c461b2`, CHF-Konsistenz `c26d2fe`, beide 19.6.) und Single-Source-of-Truth
> für Drawdown + Faktor-Decomposition. Reaktivierung ist sicher.

### 3.2 Pro-Bucket (für „volle Widgets pro Bucket")
| Feature | Quelle | Status |
|---|---|---|
| Summary-Karte | `GET /buckets/{id}/summary` | READY |
| Monatsrenditen | `GET /buckets/{id}/monthly-returns` | READY |
| Drawdown / Underwater | `GET /buckets/{id}/drawdown` | READY |
| Benchmark-Vergleich (eigener Benchmark) | `GET /buckets/{id}/benchmark-comparison` | READY |
| Equity-Curve | `GET /buckets/{id}/history` (Index-to-100 client) | READY |
| Realisierte Gewinne | `GET /api/portfolio/realized-gains?bucket_id=` | READY |
| Top-Mover | client-seitig (Positionen tragen `bucket_id`) | READY |
| HHI / Diversifikation | `GET /api/portfolio/correlation-matrix?bucket_id=` | READY |
| Cashflows | `GET /buckets/{id}/cashflows` | READY |
| **Total-Return-Breakdown** | — | **NEEDS_BUILD** |
| **Fee-Summary** | — | **NEEDS_BUILD** |
| **Alpha/Beta** | `factor_decomposition(bucket_id=…)` durchreichen | NEEDS_BUILD (trivial) |
| **Risiko-Kennzahlen** | aus `get_portfolio_history(bucket_id=…)` | NEEDS_BUILD |

> **Schlüssel-Befund:** `history_service.get_portfolio_history()` akzeptiert bereits
> `bucket_id` (Signatur Z. 32, filtert `Position.bucket_id`, Z. 61–62). Dadurch sind per-Bucket
> Equity-Curve, Alpha/Beta und Risiko-Kennzahlen aus *derselben* Reihe ableitbar wie whole-portfolio.

## 4. Seiten-Aufbau (Layout `/performance`)

```
┌─ Performance ─────────────────────────────────────────────┐
│ [Header: Icon + „Performance"]                             │
│                                                            │
│ A. Total-Karte (whole-portfolio)                           │
│    PerformanceCard / TotalReturnCard (MWR, YTD, Breakdown) │
│                                                            │
│ B. Equity-Curve  (Portfolio vs Benchmark, indexiert=100)   │
│    + Periodenwahl (1M/3M/6M/YTD/1Y/MAX) + Benchmark-Dropdown│
│                                                            │
│ C. Risiko & Faktoren (whole-portfolio)                     │
│    ├ Faktor-Exposure/Alpha-Beta-Karte (R², Betas, Alpha)   │
│    └ Risiko-Kennzahlen (Sharpe/Sortino/Calmar/Vol/IR)      │
│       + Rolling-Returns + Underwater-Drawdown              │
│                                                            │
│ D. Allokation (3 Pies) + HHI                               │
│                                                            │
│ E. Monatsrenditen-Heatmap (+ S&P-500-Zeile)                │
│                                                            │
│ F. Top-Gewinner / Top-Verlierer                            │
│                                                            │
│ G. Realisierte Gewinne · Gebühren/Steuern                  │
│                                                            │
│ ─── Pro Bucket (Total · Core · Satellite · Hard Money · Crypto)│
│ H. Bucket-Sektionen: je Bucket der volle Widget-Satz       │
│    (Summary, Equity-Curve, Monatsrenditen, Drawdown,       │
│     Benchmark-Δ, Top-Mover, Realisiert, Fees, Risiko, α/β) │
└────────────────────────────────────────────────────────────┘
```

**Pro-Bucket-Darstellung (H):** Akkordeon/Tab je User-Bucket. Oben eine kompakte Vergleichsleiste
(Total + jeder Bucket: Wert, YTD-TWR, All-Time, Δ vs Benchmark, Drawdown) + Balkenchart
„Rendite je Bucket vs Benchmark". Aufklappen zeigt den vollen Widget-Satz des Buckets.
Buckets werden dynamisch aus `GET /api/portfolio/buckets` geladen (generisch, nicht hartkodiert).

## 5. Neue Backend-Endpoints (Spec) — **intern UND external_v1**

> Harte Regel (Maintainer 26.6.): **jeder** neue Read-Endpoint bekommt eine gespiegelte Route in
> `backend/api/external_v1.py` (X-API-Key-Auth, Custom-UA). Im Zuge dessen: bestehende
> Performance-Endpoints, die extern noch fehlen, ebenfalls ergänzen (Audit-Task 5.4).

### 5.1 Per-Bucket Total-Return
- Intern: `GET /api/portfolio/buckets/{id}/total-return`
- Extern: `GET /v1/portfolio/buckets/{id}/total-return`
- Service: `total_return_service.get_total_return(user_id, bucket_id=…)` — 6 Transaction-Queries
  + Unrealized um `.join(Position).where(Position.bucket_id==bucket_id)` ergänzen. **Formeln (Z. 99–106)
  unverändert** → HEILIGE Regel 1 & 11 gewahrt. Mechanisch.

### 5.2 Per-Bucket Fee-Summary
- Intern: `GET /api/portfolio/buckets/{id}/fee-summary`
- Extern: `GET /v1/portfolio/buckets/{id}/fee-summary`
- Service: `get_fee_summary(user_id, bucket_id=…)` — ein `.where(Position.bucket_id==bucket_id)` an die
  Position-Subquery (Z. 331–334). Einzeiler.

### 5.3 Risiko-Kennzahlen (whole + bucket)
- Intern: `GET /api/portfolio/risk-metrics?start=&end=&benchmark=` und
  `GET /api/portfolio/buckets/{id}/risk-metrics`
- Extern: gespiegelt unter `/v1/...`
- Neuer Service `risk_metrics_service.py`: liest `get_portfolio_history(..., bucket_id, downsample=False,
  liquid=True)`, leitet Tagesrenditen aus `portfolio_indexed` ab und berechnet:
  - Volatilität (annualisiert) = `std(daily) × √252`
  - Sharpe = `(ann_return − rf) / vol`
  - Sortino = `(ann_return − rf) / downside_vol`
  - Calmar = `ann_return / |max_drawdown|` (Drawdown aus `drawdown_service`)
  - Information Ratio = `(port_ann − bench_ann) / tracking_error`
  - Rolling Returns (30/90/252T)
- **Additiv, keine bestehende Formel berührt.** Risk-free-Rate als Config `RISK_FREE_RATE_PCT`
  (Default konservativ; später optional an SARON/FRED koppeln). → muss in **beide** Compose-Env-Blöcke
  (backend + worker), vgl. Memory „Compose Env-Passthrough".

### 5.4 Alpha/Beta per Bucket
- Intern: `factor_decomposition(bucket_id=…)` durchreichen → `GET /api/analysis/factor-decomposition?bucket_id=`
- Extern: vorhandene/zu ergänzende `/v1/analysis/factor-decomposition?bucket_id=`
- Service-Änderung: Parameter `bucket_id` annehmen, an `get_portfolio_history(...)` weitergeben;
  Cache-Key enthält `bucket_id` bereits. Zwei Zeilen.

### 5.5 External-API-Audit (eigener Task)
Vor Abschluss: prüfen, welche Performance-Endpoints in `external_v1.py` bereits existieren
(`/performance/history` ist da) und alle fehlenden Read-Routen ergänzen:
total-return, monthly-returns, realized-gains, fee-summary, drawdown, correlation/HHI,
factor-decomposition, risk-metrics, sowie sämtliche `/buckets/{id}/*`-Pendants.

## 6. Phasen-Plan & Akzeptanzkriterien

> Jede Phase ist eigenständig auslieferbar und audit-gated (CLAUDE.md: kein Merge ohne grünen
> `@openfolio-audit`). UI-Texte Deutsch (Schweizer Deutsch, kein ß, ä/ö/ü korrekt).

### Phase 1 — Seite + Umzug + Equity-Curve (kein neues Backend)
- `/performance`-Route + Sidebar-Eintrag; Layout-/Auth-Wrapper greifen automatisch.
- 7 Performance-Widgets von Portfolio → Performance verschoben.
- `BucketTabBar`-Switch aus Portfolio entfernt; Bucket-Badge-Spalte in `PortfolioTable`.
- `PerformanceChart` reaktiviert (whole-portfolio Equity-Curve vs Benchmark).
- **Akzeptanz:** Portfolio zeigt nur Positionsverwaltung; Performance zeigt alle Analyse-Widgets;
  Equity-Curve lädt; `npm run build` grün; `docker compose up --build` grün.

### Phase 2 — Volle Widgets pro Bucket
- Bucket-Sektionen (Total + je User-Bucket), Reuse der 9 READY-Quellen.
- **Neu:** `/buckets/{id}/total-return` + `/buckets/{id}/fee-summary` (intern **und** external_v1).
- **Akzeptanz:** je Bucket vollständiger Widget-Satz inkl. Total-Return-Breakdown & Fees;
  externe API liefert dieselben Werte; pytest für die 2 neuen Services/Routen
  (inkl. Migration-Check falls neue `ApiWriteLog`-actions — vgl. Memory „Test-DB ohne CHECK-Constraints").

### Phase 3 — Zusatz-Metriken
- `risk_metrics_service` + `/risk-metrics`-Endpoints (whole + bucket, intern + external_v1).
- Faktor-Exposure/Alpha-Beta-Karte (whole + bucket).
- Rolling-Returns + Underwater-Drawdown-Chart.
- `RISK_FREE_RATE_PCT` in beide Compose-Env-Blöcke.
- External-API-Audit (5.5) abschließen.
- **Akzeptanz:** alle Kennzahlen sichtbar + plausibilisiert; jede neue Metrik per externer API abrufbar;
  keine Änderung an Modified-Dietz/XIRR/Total-Return-Formeln (Diff-Review gegen HEILIGE Regeln 1 & 11).

## 7. HEILIGE-Regeln-Compliance
- Regel 1 & 11 (Performance-/Renditeberechnung): **nur additive** Metriken; bestehende Formeln
  (`portfolio_service`, `recalculate_service`, `price_service`, `utils`, `performance_history_service`,
  `total_return_service`) werden **nicht** in der Rechenlogik geändert — Bucket-Scoping nur via
  `Position.bucket_id`-Join im Daten-Vorlauf.
- Regel 4/5/6 (Immobilien/Vorsorge/PE nicht in liquide Performance): unverändert — diese Widgets
  bleiben auf der Portfolio-Seite, Performance nutzt liquide Reihen (`liquid=True`).
- Multi-User: alle neuen Endpoints `user_id`-scoped (Memory „Multi-User").

## 8. Offene Design-Entscheidungen (für Build)
1. **Risiko-Reihe pro Bucket:** `get_portfolio_history(bucket_id)` (Ledger-rekonstruiert, konsistent mit
   Alpha/Beta + whole-portfolio) — *nicht* die BucketSnapshot-`wealth_index`-Reihe (die Monatsrenditen/
   Drawdown speisen). Eine Quelle pro „Risiko-Block", klar gelabelt. **Empfehlung: Ledger-Reihe.**
2. **Risk-free-Rate-Default:** konservative Konstante via Config; SARON/FRED-Kopplung später (Phase 3+).
3. **Pro-Bucket-UI:** Akkordeon (platzsparend) vs Tabs. **Empfehlung: Akkordeon** mit Vergleichsleiste oben.
4. **Performance-Daten-Last:** viele Pro-Bucket-Calls → `skip`-Sequencing wie heute (H-7-Pattern),
   lazy beim Aufklappen einer Bucket-Sektion laden.

## 9. Risiken
- **Daten-Last** bei „volle Widgets pro Bucket" × N Buckets → Lazy-Load + Caching (vorhandene TTLs nutzen).
- **PerformanceChart** seit Launch ungenutzt → in echter Umgebung gegen Prod-Daten verifizieren (verify-Skill).
- **External-API-Drift:** neue Endpoints müssen synchron intern+extern bleiben (Memory
  „Externe APIs deprecaten silent" — count=N/Health-Check-Disziplin sinngemäss bei Eigen-API: Tests).
