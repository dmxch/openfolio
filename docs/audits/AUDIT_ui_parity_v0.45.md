# Audit Report — v0.45 "UI-Paritaet" External Write API — 2026-06-23

Scope: uncommitted working-tree diff only (external_v1.py +1701, external_v1_schemas.py +385,
positions/private_equity/precious_metals/dividends `_core`-Refactors, Migration 085, neue Tests).
Frameworks: OWASP Top 10 (A01 Broken Access Control, A04 Insecure Design), ASVS v4.0.3 L2, STRIDE
(Tampering/Info-Disclosure/Repudiation), Multi-User-HEILIGE-Regel.

## Zusammenfassung

**PASS** — Security 0 kritisch / 0 hoch, QA ok, Architektur sauber. 2 Low + 1 Info.

Die 7 abgefragten Risikobereiche wurden alle verifiziert und sind **korrekt umgesetzt**:

1. Auth/Scope: alle 88 schreibenden Endpoints haben `require_scope(request, "write")` **und**
   `Depends(get_api_user)` — automatisiert geprueft, 0 Treffer ohne beides.
2. IDOR/user_id: jeder pfad-id-basierte Endpoint erzwingt Ownership (direkt via
   `... .user_id != user.id → 404` oder via Service/`_core`, das `user.id` filtert). Kein Fund.
3. PII: alle Write-Responses laufen durch `filter_*`-Whitelists; `filter_settings` strippt
   `fred/fmp/finnhub_api_key` UND alle `*_api_key_masked`-Felder. Kein Klartext-/Ciphertext-Leak.
4. Audit-Atomizitaet: ApiWriteLog wird in jeder Mutation **in derselben Transaktion** wie die
   Mutation committet. Kein Two-Commit-Orphan auf einem Mutations-Pfad.
5. Migration: alle 76 in `external_v1.py` verwendeten `action`-Strings sind in Migration 085
   whitelisted (skript-verifiziert). Kein fehlender Wert → kein Prod-500-Risiko.
6. Scope-Exclusions: keine Secret-Writes (API-Keys/SMTP/ntfy), keine Token-/Auth-/Admin-Endpoints.
   `SettingsUpdate` hat keine Key-Felder; Key-Endpoints (`FredApiKeyUpdate` etc.) sind NICHT gespiegelt.
7. `_core`-Refactors: Ownership, Encryption, sync-Calls (`sync_position`/`sync_metal_position`),
   Commit-Reihenfolge und Return-Werte verhaltensidentisch zum Original. Kein Drift.

## Findings

| # | Bereich | Severity | Problem | Empfehlung |
|---|---------|----------|---------|------------|
| 1 | QA / Repudiation | Low | `import_parse`/`import_analyze`/`import_parse-with-mapping` (external_v1.py:5214, 5244, 5291) machen `db.add(log)` + `await db.commit()` **vor** dem `parse_csv`/`analyze_csv_structure`-Aufruf. Da Parse read-only ist, persistiert der Audit-Log auch dann, wenn der Parse danach mit 422 scheitert. Kein Orphan-**Mutation** (es gibt keine), aber der Log suggeriert eine erfolgreiche Aktion, die fehlschlug. | Akzeptabel als "Versuchs-Log". Optional: Log erst nach erfolgreichem Parse committen, oder Doku-Hinweis dass `import_parse` ein Attempt-Marker ist. |
| 2 | Architektur / DoS | Low | `POST /screening/scan` (external_v1.py:4563) legt einen **global, nicht user-gescopten** `ScreeningScan` an (`models/screening.py:15` hat kein `user_id`). Ein Write-Token startet damit einen system-weiten Scan; der zurueckgegebene `scan_id` ist nicht user-isoliert (spiegelt aber 1:1 das interne Verhalten). | Kein IDOR auf User-Daten. Resourcen-Abuse durch das **harte `1/day`-Limit** ausreichend mitigiert. Belassen; ggf. dokumentieren dass Scans global sind. |
| 3 | QA / Test-Abdeckung | Info | Test-DB baut via `create_all`, nicht Alembic → der `ck_api_write_log_action`-CHECK-Constraint ist in Tests **unsichtbar** (bekanntes Pattern, MEMORY). Ein in Code verwendeter, aber in Migration 085 fehlender `action` wuerde erst in Prod als 500 + Rollback auffallen. | Für v0.45 **nicht** kritisch: alle 76 Action-Strings sind skript-verifiziert in 085 vorhanden. Hinweis bleibt für künftige neue Actions. |

## Verifizierte Stärken

- **`_core`-Extraktion sauber**: Die internen Routen sind nun duenne Wrapper
  (`return await create_position_core(db, user, data)`); `audit_log` wird als Keyword-only-Param
  durchgereicht und in derselben Transaktion via `db.add(audit_log)` **vor** dem committenden
  Aufruf persistiert. Encryption (`encrypt_field` auf serial/storage/notes/bank/iban),
  `sync_metal_position`/`sync_position`-Aufrufe und `trigger_snapshot_regen` bleiben erhalten.
- **Property-Endpoints ohne `_core`** rufen `property_service`-Funktionen, die self-committen, und
  haengen den Log **davor** in die Session — atomar. `update/delete_mortgage|expense|income` nehmen
  `uuid.UUID(int=0)` als (dokumentiert ungenutzten) `property_id` entgegen; die Ownership wird ueber
  die aus dem Entity aufgeloeste `property_id` + `_verify_property_owner` erzwungen → **kein IDOR**.
- **Settings-Doppelriegel**: `settings_to_dict` exponiert ohnehin nur `*_masked` + `has_*`; der
  `filter_settings` entfernt zusaetzlich beide Schluessel-Varianten. Test `test_settings_never_exposes_secrets`.
- **PII-Vertrag (v0.38) konsistent**: Owner-PII (bank_name/IBAN-maskiert/notes/serial/storage,
  PE company_name/uid/register) wird wie im UI ausgeliefert, aber IBAN ist immer ueber
  `decrypt_and_mask_iban` maskiert; Metal-`serial_number`/`storage_location` werden **dekryptiert**
  (kein Ciphertext-Leak), nie roh.
- **AsyncSession-Hygiene**: `import/confirm` regeneriert Snapshots in einer **eigenen**
  `async_session()` (Background-Task) — entspricht der MEMORY-Regel "keine AsyncSession across
  asyncio.gather/tasks teilen".
- **Schema-Entkopplung**: alle `External*`-Write-Schemas sind `_StrictWrite` (extra=forbid),
  bewusst von internen Schemas entkoppelt → interne Felderweiterungen leaken nicht automatisch.
- **`fill_pending_order_external`**: `_do_fill` committet bewusst NICHT selbst
  (caller-commit), der Fill-Log geht in denselben Commit — atomar verifiziert.
- **`migration_rollback`/`backfill_bucket_snapshots`** nutzen `flush()` (kein self-commit) →
  Log + Mutation im selben `db.commit()` des Endpoints.

## Methodik

- Migration-Cross-Check skript-basiert (alle `action="..."` + `_mk_re_log(...,"...")` gegen 085-Whitelist): 0 fehlend.
- Scope-Check skript-basiert ueber alle 88 `@router.(post|put|patch|delete)`-Bloecke: 0 ohne `require_scope`+`get_api_user`.
- Alle 4 `_core`-Refactors zeilenweise gegen das Original verglichen (Ownership/Encryption/Commit/Return).
- Service-Ownership stichprobenartig im Quellcode verifiziert (`property_service`, `dividends`-core,
  `settings_service` self-commit).
