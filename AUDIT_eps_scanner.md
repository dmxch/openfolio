# Audit-Report — EPS-Scanner (Pre-Release) — 2026-06-22

**Verdikt: GO mit Auflagen** — kein Blocker. 2 Major-Findings waren vor Release zu
beheben (beide Trivial-Fix), 2 Minor zusätzlich behoben. **Alle Auflagen erfüllt.**
Berechnungslogik = Spec (`DESIGN_eps_scanner.md`), HEILIGE Regeln intakt,
volle Backend-Suite grün (1230 passed / 3 skipped), Frontend-Build grün.

## Findings & Resolution

| # | Bereich | Severity | Problem | Fix | Status |
|---|---------|----------|---------|-----|--------|
| 1 | Worker/Funktional | Major | `_write_status` schrieb `json.dumps(payload)` mit `missing_tickers[:50]` in `AppSetting.value` (`String(500)`). Im Degraded-Fall (kein System-Key → viele fehlende Ticker) Overflow → `StringDataRightTruncationError` → Job als „failed" geloggt, `/status` dauerhaft „nie gelaufen". | `_serialize_status`-Guard (kürzt das Sample bis ≤500 Zeichen) + `missing_tickers[:15]` + Regressionstest `test_serialize_status_fits_appsetting_column_when_all_missing`. | ✅ behoben |
| 2 | Security (ASVS V7.1.1) | Major | System-Finnhub-Key als Query-Param (`token=`) → bei httpx-Fehlern (401/Timeout) loggt `retry_external` die volle URL inkl. Token auf WARNING-Level. Shared/persistenter Key, sensibler als per-User-Keys. | Header-Auth `X-Finnhub-Token` statt Query-Param. URL enthält kein Secret mehr. | ✅ behoben |
| 3 | UX/A11y (H6) | Minor | Positionale Tabellen-Header (`Q−7`…`Aktuell`) statt Quartalsdaten. | Bewusste, im Code begründete Abweichung (Fiskalquartal-Versatz, OF-7). Spec-konform akzeptiert. | belassen |
| 4 | Performance | Minor | `get_scanner_results` rechnet pro Request alle ~470 Ticker neu (kein Cache). | Tabelle klein (bounded durch Upsert) → für v1 ok. Redis-Cache bei wachsendem Universum. | belassen (v1) |
| 5 | Worker | Minor | Cron ohne `misfire_grace_time` → Tageslauf fällt bei Worker-Downtime um 04:00 aus. | `misfire_grace_time=3600`. | ✅ behoben |
| 6 | UX | Nit | „Streak"-Label suggeriert konsekutive Serie (zählt aber alle pos-YoY-Quartale). | Spec-konform (§Streak). | belassen |
| 7 | UX | Nit | Staleness-Tooltip behauptete pauschal die Financials-Lücke als Ursache. | Wording neutralisiert (junge Aktie/Spinoff/Datenlücke als Alternativen). | ✅ behoben |

## Verifizierte Prüfschwerpunkte (PASS)

- **HEILIGE Regeln (additiv):** Keine Berührung von `portfolio_service`, `recalculate_service`,
  `price_service`, `utils`, `performance_history_service`, `total_return_service`, `scoring_service`.
- **Berechnungskorrektheit (Code = Spec):** YoY-Basis 4 Perioden zurück, alle 5 `yoy_flag`-Fälle,
  Division nur bei `pos_to_pos` mit `abs(basis)`; Outlier-Guard `med>0`-Schutz; Super-Quartal A–D
  inkl. C-Wegfall bei <2 Vorwerten; `record_quarter` (strikt >, Window 8) + `_outlier`/`_turnaround`
  inkl. Koexistenz. 25 Service-Tests + 1 Regressionstest.
- **yfinance/HTTP:** `yf_earnings_dates` nur via `asyncio.to_thread` (Regel 7), Fallback-Semaphore≤3,
  HTTP via httpx (Regel 8).
- **Multi-User:** Thresholds strikt user_id-scoped, EPS-Daten universe-global, kein Cross-User-Leak;
  eigene `async_session` pro Fallback-Branch.
- **Migration 084:** `revises 083` korrekt, up/down symmetrisch, UNIQUE + 2 Indizes; kein neuer
  ApiWriteLog-Action (PATCH läuft über JWT, nicht External-API).
- **API:** JWT auf allen 4 Routen, Query-/Body-Validierung, `sort_by`-Whitelist, Rate-Limit auf PATCH,
  ausschließlich parametrisiertes SQL.
- **Frontend:** Neutrale Signalsprache (Regel 10), Super-Quartal-Disclaimer (OF-1), echte Umlaute,
  ARIA/scope/aria-sort/Fokus-Ringe, keine JSX-in-IIFE-Fragment-Falle.

## Akzeptierte v1-Grenzen (Maintainer-TODO)

- S&P-500-Liste = ~470 Platzhalter-Ticker (Wikipedia in Build-Umgebung blockiert); Refill-Script in
  `sp500_universe.py` dokumentiert → auf exakte 503 ergänzen.
- `name`/`sector` = `ticker`/`None` (kein Company-/GICS-Master im Repo); Sektor-Filter ist v1.1,
  Plumbing liegt und degradiert sauber.
- Super-Quartal-Schwellen (25 % / +5pp) unvalidiert → bewusst mit Disclaimer live (OF-1).
- yfinance-Fallback auf der Dev-Box nicht live testbar (yfinance geblockt) → über Unit-Tests abgedeckt.
