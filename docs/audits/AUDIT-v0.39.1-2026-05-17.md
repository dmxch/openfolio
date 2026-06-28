# Audit Report — OpenFolio v0.39.1 — 2026-05-17

Scope: Bucket-Feature Phase 1 + Phase 2 (F-13 bis F-17), Import-Rules (F-15/F-18),
Backfill (F-16), Teil-Wechsel (F-17), Drawdown-Bremse, plus alle Bugfixes seit v0.39.1.
Branch: main, Commit 118d045.

## Zusammenfassung

**FAIL** — Security 2 High / QA 2 Medium / Performance 2 Medium / Architektur 1 Low / UX 2 Medium

Test-Suite: 960 passed, 2 skipped, 39 warnings — alle Bucket-Tests gruen.

---

## Findings

| # | Bereich | Severity | Problem | Datei:Zeile | Empfehlung |
|---|---------|----------|---------|-------------|------------|
| 1 | Security | HIGH | Benchmark-Ticker wird ohne Allowlist direkt an yfinance übergeben. `/buckets/{id}/benchmark-comparison` ruft `compare_to_benchmark` → `get_benchmark_monthly_returns(bucket.benchmark)` — der Wert kommt unkontrolliert aus der DB (Benutzer kann beliebigen String via PATCH setzen, max_length=20 ist kein Allowlist). Im performance-Endpoint `/benchmark-returns` existiert eine explizite Allowlist. Das Muster fehlt im Bucket-Pfad. | `backend/api/buckets.py:417`, `backend/services/bucket_performance_service.py:336-339`, `backend/api/performance.py:51-52` | `ALLOWED_BENCHMARKS = frozenset({...})` Prüfung analog `performance.py:51` in `compare_to_benchmark` oder beim PATCH einfügen. |
| 2 | Security | HIGH | Kein Rate-Limiting auf allen Bucket-Mutationspfaden. `POST /buckets`, `POST /buckets/from-template`, `POST /positions/{id}/move-to-bucket`, `POST /positions/{id}/split-to-bucket`, `POST /buckets/backfill-snapshots`, `POST /buckets/migration-rollback` haben keine `@limiter.limit`-Dekoratoren. `analysis.py` und `positions.py` haben 235 Rate-Limit-Dekoratoren; `buckets.py` hat null. | `backend/api/buckets.py:184,232,267,474,517,620` | Mindestens `5/minute` auf Backfill, `10/minute` auf Create/Template/Move/Split, `2/minute` auf Migration-Rollback. |
| 3 | Security | MEDIUM | `risk_rules`-Feld ist untypisiertes `dict | None` ohne Schema-Validierung. Beliebige Keys mit beliebigen Typen können persistiert werden. Ein User kann `{"drawdown_brake_pct": "'; DROP TABLE buckets; --"}` schreiben. Derzeit werden die Werte als float gecasted (`float(rules.get(...))` im Worker), aber ohne try/except kann ein ungültiger Typ den Worker-Job crashen. | `backend/api/buckets.py:113,124`, `backend/services/bucket_drawdown_service.py:98` | Pydantic-Modell `RiskRulesSchema` mit typisierten Feldern definieren; `dict` durch dieses Modell ersetzen. |
| 4 | Security | MEDIUM | `color`-Feld hat `max_length=7` aber keine Hex-Regex-Validierung. User kann `" onload="` (7 Zeichen) senden, das in `style={{ background: b.color }}` landet. React escapt Inline-Styles, aber ein explizites `pattern=r'^#[0-9a-fA-F]{6}$'` wäre korrekt. | `backend/api/buckets.py:108,119`, `frontend/src/pages/settings/BucketsTab.jsx:271` | `Field(None, max_length=7, pattern=r'^#[0-9a-fA-F]{6}$')` |
| 5 | Security | LOW | `note`-Felder in `MovePosition` und `SplitPosition` haben kein `max_length`. User kann beliebig lange Strings in `position_bucket_history.note` schreiben. | `backend/api/buckets.py:135,142` | `note: str | None = Field(None, max_length=500)` |
| 6 | QA | MEDIUM | Kein Test für `bucket_performance_service.py` (get_bucket_summary, get_bucket_history, get_bucket_monthly_returns, compare_to_benchmark, get_bucket_cashflows, get_allocations_by_bucket). Die Datei hat 413 Zeilen Business-Logik ohne eigene Test-Datei. | `backend/services/bucket_performance_service.py` | `backend/tests/test_bucket_performance_service.py` erstellen mit Mock-Snapshots für TWR-Formel, monatliche Compound-Rendite, Benchmark-Vergleich. |
| 7 | QA | MEDIUM | `test_import_bucket_rules.py:135` verwendet das deprecated `datetime.datetime.utcnow()` (Python 3.12 emittiert `DeprecationWarning`, in Python 3.14 wird es entfernt). Wird auch in `pending_dividend_service.py:171,225` getroffen. | `backend/tests/test_import_bucket_rules.py:135`, `backend/services/pending_dividend_service.py:171,225` | `dateutils.utcnow()` statt `datetime.utcnow()` verwenden (Projekt-eigener Wrapper bereits vorhanden). |
| 8 | QA | LOW | PATCH `/buckets/{id}` kann `target_pct`/`target_chf` nicht auf `null` setzen, weil `update_bucket` den Wert nur aktualisiert wenn `!= None`. Ein User der ein Ziel löschen will, muss 0 senden (was validierungstechnisch erlaubt ist). | `backend/services/bucket_service.py:309-314` | Sentinel-Pattern oder explizites `UNSET`-Objekt einführen, analog dem was FastAPI mit `Optional` + `model_fields_set` ermöglicht. |
| 9 | Performance | MEDIUM | N+1-Query in `_record_user_bucket_snapshots`: für jeden der N aktiven Buckets wird separat `SELECT running_peak_chf ... ORDER BY date DESC LIMIT 1` abgesetzt. Bei 15 Buckets = 15 Round-Trips pro User, täglich für alle User. | `backend/services/snapshot_service.py:370-381` | Einmalige Batch-Query: `SELECT bucket_id, MAX(running_peak_chf) ... WHERE date < ? GROUP BY bucket_id` vor der Loop. |
| 10 | Performance | MEDIUM | `get_allocations_by_bucket` ruft `await _calc_position_value_chf(pos, fx_rates)` in einer `for pos in positions`-Schleife. `_calc_position_value_chf` ist eine async-Funktion, aber sie ruft kein I/O aus (pure Berechnung). Das Muster ist trotzdem sequentiell statt `asyncio.gather()`. Bei 200 Positionen summiert sich der Overhead. | `backend/services/bucket_performance_service.py:196-199` | `asyncio.gather(*[_calc_position_value_chf(pos, fx_rates) for pos in positions])` |
| 11 | Performance | LOW | Grafana läuft bei 89.71% des 256 MB Memory-Limits (229.7 MiB). OOM-Kill-Risiko bei Dashboard-Aktualisierungen mit grossen Zeitfenstern. | `docker-compose.monitoring.yml:71-72` | Limit auf 512 MB erhöhen oder Grafana-Dashboard-Query-Range einschränken. |
| 12 | Performance | LOW | `check_bucket_drawdown_brakes` lädt alle aktiven User, dann per User alle aktiven Buckets (N+1 über User), dann für jeden qualifizierenden Bucket `get_max_drawdown`. Im Single-User-Szenario unkritisch; bei wachsender User-Zahl skaliert dies linear. | `backend/services/bucket_drawdown_service.py:63-156` | Buckets für alle User in einer JOIN-Query laden: `SELECT Bucket.*, User.* WHERE kind='user' AND deleted_at IS NULL JOIN User ON active`. |
| 13 | Architektur | MEDIUM | `bucket_performance_service.py:192` importiert `_calc_position_value_chf` aus `snapshot_service.py` (private Funktion, Underscore-Präfix). Das ist eine fragile Kopplung: jede Umbenennung in `snapshot_service` bricht `bucket_performance_service` ohne statische Garantie. | `backend/services/bucket_performance_service.py:192` | `_calc_position_value_chf` in ein gemeinsames `valuation_utils.py` extrahieren oder als öffentliche Funktion aus `snapshot_service` exportieren. |
| 14 | Architektur | LOW | `backfill_bucket_snapshots` approximiert historische Bucket-Werte durch die **aktuelle** Allokation (proportional zu `cost_basis_chf`). Die Limitierung ist korrekt dokumentiert (Kommentar in Service + API-Kommentar), aber das UI-Confirm-Dialog in BucketsTab verwendet technischen Jargon (`bucket_snapshots`, `portfolio_snapshots`, `Non-destructive`) statt User-freundliche Sprache. | `frontend/src/pages/settings/BucketsTab.jsx:87-91` | Confirm-Text auf Deutsch ohne interne Technologie-Begriffe umschreiben. |
| 15 | UX | MEDIUM | `BucketEditModal` (in BucketsTab.jsx) und `BucketTemplateModal` verwenden `role="dialog"` + `aria-modal="true"` aber **keinen `useFocusTrap`-Hook**. Tastatur-Fokus verlässt das Modal beim Tab-Durchlauf. Im Vergleich: `StopLossWizard`, `TransactionCreateModal`, `StopLossModal`, `PositionTypeWizard` verwenden `useFocusTrap` korrekt. | `frontend/src/pages/settings/BucketsTab.jsx:419-421`, `frontend/src/components/BucketTemplateModal.jsx` | `useFocusTrap` importieren und `ref={trapRef}` auf das Modal-`<div>` setzen, analog `StopLossModal`. |
| 16 | UX | MEDIUM | Alle Form-Inputs in `BucketEditModal` (Name, Benchmark, Target, Risk-Rules) haben `<label>`-Texte aber keine `htmlFor`/`id`-Verknüpfung. Screen-Reader können Inputs nicht mit ihren Labels assoziieren (WCAG 2.2 AA 1.3.1, 3.3.2). | `frontend/src/pages/settings/BucketsTab.jsx:434-578` | `id`-Attribute auf Inputs setzen und entsprechende `htmlFor` auf Labels. Da Inputs dynamisch (mehrere BucketEditModal-Instanzen möglich) eindeutige IDs via `useId()` generieren. |
| 17 | UX | LOW | `window.confirm` wird für Bucket-Delete und Backfill-Trigger genutzt. Dies ist Browser-native, bricht das Design-System und ist in Chrome auf localhost manchmal unterdrückt. `BucketChangeConfirmModal` hingegen zeigt einen gestylten Dialog — inkonsistentes Muster. | `frontend/src/pages/settings/BucketsTab.jsx:63,87` | Schlanken `ConfirmDialog`-Component (bereits als `DeleteConfirm.jsx` vorhanden) wiederverwenden. |
| 18 | UX | INFO | `BucketTabBar` persistiert den gewählten Bucket in `localStorage` unter `openfolio.bucketView`. Wenn ein Bucket später gelöscht wird, kann der persistierte `bucketId` auf einen nicht mehr existierenden Bucket zeigen. Der Code fällt elegant auf `aggregated` zurück (kein expliziter Bug), aber der User sieht kurz leeren Bucket-Modus bis der Load fertig ist. | `frontend/src/components/BucketTabBar.jsx:131-143` | Nach dem Bucket-Load validieren ob `bucketView.bucketId` noch in der gültigen Liste ist; falls nicht, auf aggregated wechseln. |

---

## Staerken

**Sicherheitsarchitektur:** Alle Bucket-Endpoints verwenden `Depends(get_current_user)` konsequent. IDOR ist vollständig abgesichert: jede Service-Funktion filtert explizit auf `user_id`. `get_bucket(db, user_id, bucket_id)` wirft `BucketError` wenn das Bucket einem anderen User gehört. Keine Lücken gefunden.

**Transaktionssicherheit:** `create_system_buckets` nutzt PostgreSQL `ON CONFLICT DO NOTHING` auf dem Partial-Index (`deleted_at IS NULL`) — Race-Conditions bei parallelen Registrierungen sind ausgeschlossen. Template-Apply ist atomar (alle Buckets oder keiner). `split_position_to_bucket` prüft Duplikat-Constraint vor dem Split.

**DB-Schema:** UNIQUE-Constraints und CHECK-Constraints korrekt modelliert: `ck_buckets_target_xor` verhindert gleichzeitiges `target_pct` + `target_chf` auf DB-Ebene. Partial-Index `uq_bucket_user_name_active` erlaubt gleiche Namen bei Soft-Delete. Migration 068 (`position_unique_per_bucket`) korrekt für Split-Anforderungen.

**Soft-Delete-Semantik:** Bucket-Delete reassigniert Positionen zu `liquid_default`, schreibt History-Einträge, gibt `deleted_at` ohne Datenverlust. `Migration-Rollback` ist idempotent und setzt `noticed_buckets_migration`-Flag atomar.

**Drawdown-Bremse:** Idempotenz via `bucket_alert_log` UNIQUE-Constraint korrekt. `bucket_age_days >= 7`-Gate verhindert False-Positives bei jungen Buckets. HTML-Escape im E-Mail-Template vorhanden. Neutrale Sprache ("Status-Mitteilung, keine Handlungsaufforderung") gemäss CLAUDE.md §10.

**Test-Coverage Bucket-Core:** 7 dedizierte Test-Dateien mit 960 gesamt passing Tests. `test_bucket_service.py` deckt alle CRUD-Pfade, Limit-Check, Split, Migration-Rollback, Risk-Rules-Diff ab. `test_buckets_api.py` deckt HTTP-Layer inkl. 409-Konflikt-Handling und Template-Anwendung. `test_import_bucket_rules.py` deckt Resolver-Logik inkl. Soft-Delete-Bucket-Skip und kombinierte Filter.

**Async-Compliance:** `get_benchmark_monthly_returns` (sync/yfinance) wird korrekt über `asyncio.to_thread` aufgerufen. `get_fx_rates_batch` ebenfalls. Keine direkten yfinance-Calls im async Event-Loop gefunden.

**Docker-Sicherheit:** Redis mit `requirepass` konfiguriert und in Healthcheck korrekt authentifiziert. Keine Hardcoded-Secrets in `docker-compose.yml` — alle via `${VAR:?must be set}` erzwungen. Backend-Container mit `cap_drop: ALL`.

**UX-Konsistenz:** `BucketChangeConfirmModal` und `BucketsOnboardingModal` verwenden `useEscClose`, `role="dialog"`, `aria-modal`, `aria-labelledby`. Bucket-Tab-Bar persistiert View-State in localStorage für UX-Kontinuität. Benchmark-Vergleich direkt in `BucketRow` mit YTD-Delta sichtbar.

**Architektur (12-Factor):** Bucket-Services respektieren die "Heilige Regel": `portfolio_service`, `recalculate_service`, `performance_history_service` wurden nicht modifiziert. Bucket-Snapshots sind additiv. `bucket_performance_service` wrapped nur, modifiziert nichts.

---

## Kritische Empfehlungen vor Release

1. **[HIGH — Security]** Benchmark-Ticker-Allowlist in `compare_to_benchmark` einfügen. Ein einzeiliger frozenset-Check wie in `performance.py:51` genügt.

2. **[HIGH — Security]** Rate-Limiting auf alle POST/PATCH/DELETE-Endpoints in `buckets.py` hinzufügen. Backfill (`5/minute`) und Migration-Rollback (`2/minute`) besonders kritisch da sie teure DB-Operationen auslösen.

3. **[MEDIUM — Security]** `risk_rules` durch typisiertes Pydantic-Modell ersetzen. Schutz gegen Type-Confusion-Crashes im Worker-Pfad.

4. **[MEDIUM — UX]** `useFocusTrap` in `BucketEditModal` einfügen. WCAG 2.2 AA 2.1.2 (No Keyboard Trap) Anforderung.

5. **[MEDIUM — QA]** `test_bucket_performance_service.py` erstellen mit mindestens: TWR-Berechnung (2 Snapshots), monatliche Returns (compound), Benchmark-Vergleich (mocked `to_thread`).
