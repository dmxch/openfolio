# Codebase-Review 2026-06-10

**Methode:** 6 parallele Review-Agents (Fable 5) über Backend-API/Infra, Kern-Finanz-Services,
Analyse/Scoring/Screening, Worker/Models/Migrationen, Frontend, Import/Alerts/Reports.
Jeder Befund wurde im Code-Kontext verifiziert (inkl. `alembic check` gegen die Dev-DB,
AST-Checks, hexdump bei Encoding-Verdacht). Stand: main `fb453e2`.

**Bilanz:** 1 CRITICAL, 10 HIGH, 17 MEDIUM, ~17 LOW. Keine Befunde gegen die heiligen
Berechnungs-Semantiken selbst — die Specs (Modified Dietz, XIRR, MRS EMA-13, Donchian strict >,
Phase-A-Aggregation) sind korrekt umgesetzt. Die Fehler liegen an den Rändern: Pfad-Divergenzen,
stille Fehlerpfade, Cache-Key-Lücken.

---

## CRITICAL

### C1 — Cross-User-Schreibzugriff über Import-Confirm
`backend/services/import_service.py:1010-1081` + `backend/services/recalculate_service.py:79-80,138-139`
`confirm_import` übernimmt ein client-geliefertes `position_id` ohne Ownership-Check in die
Transaction (das user-scoped `all_positions`-Dict wird nur für Nebeneffekte benutzt — fehlt die
ID dort, wird die Txn trotzdem mit der Fremd-UUID angelegt). `recalculate_position` lädt
Transaktionen **nur nach position_id ohne user_id-Filter** → ein authentifizierter User kann mit
einer erratenen/geleakten Position-UUID cost_basis/shares eines anderen Users korrumpieren.
**Fix:** Transaktionen mit `pos_id not in all_positions` in `confirm_import` ablehnen/skippen;
zusätzlich `user_id`-Filter in den Recalc-Queries (Defense in Depth).

## HIGH

### H1 — Breakout-Alerts feuern seit v0.21.4 nie (Silent ImportError)
`backend/services/breakout_alert_service.py:64`
`from services.stock_scorer import download_and_analyze` — die Funktion heisst `_download_and_analyze`
(AST-verifiziert, auch historisch nie public). Der ImportError wird vom per-User-try/except als
Warning verschluckt → **Breakout-E-Mails/Pushes wurden nie zugestellt.** (Schon c27a1c4 fixte
einen anderen "Alerts feuern nie"-Bug in derselben Datei.)
**Fix:** Import korrigieren, Aufruf via `asyncio.to_thread()` (blockiert sonst den Worker-Loop),
Regressionstest der den Import auflöst.

### H2 — GBX-Pence fehlt im gesamten Live-Bewertungspfad
`backend/services/cache_service.py:232` (+ `portfolio_service.py:316-337`, `snapshot_service.py:92-101`)
`_download_yahoo_batch` schreibt rohe Pence-Preise für `.L`-Ticker ungeteilt in `price_cache`/
`positions.current_price`, etikettiert sie aber als GBP → Live-View und Daily-Snapshot bewerten
LSE-Positionen **100× zu hoch**. Die GBX-Erkennung existiert nur im `regenerate_snapshots`-Pfad →
Live und regenerierte Historie divergieren um Faktor 100.
**Fix:** GBX-Detection zentral beim Schreiben in `refresh_cache`/`_download_yahoo_batch`.

### H3 — Dividenden-Pfad: GBp → CHF ohne Umrechnung
`backend/services/dividend_service.py:35-36` + `backend/services/utils.py:39`
`get_fx_rate("GBp","CHF")` findet keinen Eintrag und fällt **still auf 1.0** → Pence-Beträge
werden als CHF ausgewiesen (~100× zu hoch). Betrifft auch den external_v1-Spiegel.
**Fix:** GBp/GBX vor FX-Lookup auf GBP normalisieren und /100.

### H4 — PE-Models fehlen in Base.metadata (Datenverlust-Falle)
`backend/models/__init__.py`
`models.private_equity` wird nicht importiert → `alembic check` meldet die 3 PE-Tabellen als
"removed". Ein `alembic revision --autogenerate` würde **DROP TABLE** generieren; Fresh-Installs
via `seed.py` (create_all + stamp head) haben keine PE-Tabellen → 500 auf allen PE-Endpoints.
**Fix:** Import + `__all__`-Eintrag (Einzeiler) + `alembic check` als CI/Audit-Gate.

### H5 — Advisory-Lock im Worker leakt über Pool-Connections
`backend/worker.py:62-83,89-111`
`pg_try_advisory_lock` ist connection-gebunden; `refresh_cache` committet zwischendurch, die
Connection geht zurück in den Pool, das `pg_advisory_unlock` im finally landet auf einer anderen
Connection → Lock bleibt hängen (pool_recycle 3600s). Folge-Refreshes skippen **ohne Log** →
bis zu 1h still stale Kurse. Exakt das Silent-Stale-Muster, gegen das der Heartbeat gebaut wurde.
**Fix:** Lock/Unlock auf einer dedizierten, für die Job-Dauer gehaltenen Connection; Log beim Skip.

### H6 — Rate-Limiting hinter nginx: alle Clients teilen einen Key
`backend/api/auth.py:44` + `backend/Dockerfile:32`
slowapi nutzt `request.client.host`, uvicorn läuft ohne `--forwarded-allow-ips` → hinter nginx
ist die Client-IP immer die nginx-Container-IP. Login (10/15min), Forgot-Password (3/h), Register
(5/h) gelten **global**: ein einzelner Client sperrt Login/Reset für alle User (DoS).
**Fix:** `--forwarded-allow-ips` aufs Docker-Subnetz + `key_func` auf `get_client_ip`; zusammen
mit M-XFF fixen (nginx `X-Forwarded-For` überschreiben statt anhängen, sonst spoofbar).

### H7 — Assessment-Cache-Key ignoriert manual_resistance (Cross-User-Leak)
`backend/services/scoring_service.py:39` + `backend/api/analysis.py:261`
`assessment:{ticker}:{sector}` enthält die **per-User** geladene `manual_resistance` nicht →
User B sieht 15 Min das mit User As Resistance berechnete Signal. `PUT /resistance/{ticker}`
invalidiert zudem nur `scorer_data:`, nicht `assessment:` → eigene Änderung wirkt erst nach TTL.
**Fix:** `manual_resistance` in den Key aufnehmen + Invalidierung ergänzen.

### H8 — regenerate_snapshots: Cash fehlt, Deposits zählen trotzdem als Cashflow
`backend/services/snapshot_service.py:574-600,633`
Regenerierte Snapshots bauen Holdings nur aus buy/delivery_in; deposit/withdrawal mutieren keine
Salden (`cash_chf` hartkodiert 0), landen aber in `net_cash_flow_chf` → Modified Dietz/XIRR sehen
Zufluss ohne Wertzuwachs → **fälschlich negative Renditen in Einzahlungsmonaten**, plus Sprung
zum nächsten Daily-Snapshot.
**Fix:** Cash/Pension-Salden im Regen-Pfad mitführen oder deren CFs symmetrisch ausschliessen.
⚠️ Heilige Datei — Umsetzung nur mit Maintainer-Freigabe.

### H9 — Multi-Tab-Refresh-Race → globaler Force-Logout
`frontend/src/hooks/useApi.js:18-48` + `contexts/AuthContext.jsx:44-77` + `backend/api/auth.py:268-288`
Refresh-Token-Rotation mit Reuse-Detection revoked **alle** Sessions; das Refresh-Lock ist aber
nur tab-lokal, das rf-Token geteilt in localStorage. Zwei Tabs (Polling alle 65s / Session-Restore)
→ zweiter Refresh = "Token kompromittiert", User überall ausgeloggt.
**Fix:** Cross-Tab-Lock (Web Locks API) oder serverseitige Grace-Period für frisch rotierte Tokens.

### H10 — Endlos-Fetch-Loop in WatchlistTable
`frontend/src/components/WatchlistTable.jsx:87-91`
`rawData?.items || rawData || []` erzeugt bei null pro Render ein neues Array-Literal; Effect mit
Dep `[data]` feuert endlos → `/api/analysis/tags` wird in Netzwerk-Latenz-Takt gepollt, bei
Watchlist-Fehler unbegrenzt.
**Fix:** `useMemo` oder Dep auf `rawData`.

### H11 — Glossar verstösst gegen Signal-Sprache (Regel 10, Release-Blocker)
`frontend/src/data/glossary.js:319,374`
"bei Breakout handeln", "Wenn nein → verkaufen." — imperative Handels-Anweisungen in der UI.
**Fix:** neutral umformulieren ("erfüllt die Kaufkriterien" / "gilt als Verkaufskriterium").

## MEDIUM

1. **XIRR liefert −99% statt None bei degenerierten Cashflows** (alle am selben Tag, z.B. neuer
   User mit einem Snapshot) — `performance_history_service.py:66-79`: Bisection konvergiert gegen
   lo=−0.99 → "−99%" im Dashboard. Fix: Degenerate-Check → None. ⚠️ Heilige Datei.
2. **dividends_gross_chf/tax_chf summieren Originalwährung als CHF** — `total_return_service.py:46-55`:
   `gross_amount`/`tax_amount` sind nicht-CHF, werden ohne `fx_rate_to_chf` aggregiert (net/total korrekt).
   ⚠️ Heilige Datei.
3. **Oversell macht cost_basis_chf negativ** — `recalculate_service.py:61-62` (+ snapshot_service:581):
   `sell_ratio > 1` nicht geklemmt → negative Basis verseucht Folge-Buys/realized_pnl. ⚠️ Heilige Datei.
4. **JPY fehlt im Worker-FX-Set; Snapshot-Pfad defaultet FX still auf 1.0** — `cache_service.py:146,584`
   + `snapshot_service.py:61-282`: JPY-Position würde ~167× zu hoch bewertet.
5. **seed.py: create_all + stamp head überspringt Migration-only-DDL** — Fresh-Installs ohne
   CHECK-Constraints/Composite-Indizes, als "head" markiert. Fix: `alembic upgrade head` statt stamp.
6. **Models↔Migrationen-Drift breiter als bekannt** (via `alembic check`): fehlende/überzählige
   Indizes (api_write_log, pending_orders, transactions, reports, bucket_snapshots) + Nullable-
   Mismatches (reports, screening_*). Fix: Sync-Migration + `alembic check` als Gate.
7. **Fernet-Felder als String(500)** — `models/smtp_config.py`, `models/ntfy_config.py`: lange
   Passwörter/Tokens → StringDataRightTruncation → 500 beim Speichern. Projektregel: Text.
8. **daily_screening_scan: kein rollback() im except** — `worker.py:551-560`: nach DB-Fehler wirft
   das Status-Update PendingRollbackError → Scan hängt ewig auf "running".
9. **Earnings-Datum ohne Vergangenheits-Filter** — `earnings_service.py:50-77` + `stock_scorer.py:383`:
   direkt nach Earnings gilt `days_until < 7` auch negativ → Quality-Cap "Earnings in −2 Tagen"
   genau im Post-Earnings-Breakout-Fenster.
10. **check_breakout_confirmed_today: no_data → passed=False statt None** — `chart_service.py:204`:
    junge Listings werden im Nenner bestraft (gleicher Effekt: `ma200_rising` NaN→False,
    `stock_scorer.py:79`).
11. **yf.Ticker/.info/.calendar direkt statt Wrapper** — `stock_scorer.py:240,267`,
    `earnings_service.py:48`, `dividend_service.py:24`: yfinance-Sessions nicht thread-safe
    (im Projekt selbst dokumentiert). Fix: `yf_ticker_info()`-Wrapper in yf_patch.
12. **Earnings-Refresh Semaphore(5) statt ≤3** — `earnings_service.py:102` / `worker.py:148`:
    überschreitet das dokumentierte Burst-Limit für `.calendar` (IP-Ban-Risiko).
13. **Import-Confirm nicht idempotent** — `api/imports.py:158-192`: Skip basiert allein auf
    client-geliefertem `is_duplicate`; Doppelklick/Retry bucht die Datei doppelt.
14. **Wizard-date_format wird nie angewendet** — `api/imports.py:233` + `import_service.py:508`:
    US-CSVs (MM/DD) werden still als DD/MM geparst, obwohl der User das Format wählt.
15. **parse_num: U+2019-Apostroph nicht gestrippt, "1,234.56" unparsebar, Fehler → silent 0** —
    `import_service.py:531-541`.
16. **Alert-Dedup vor Versand gesetzt** — `breakout_alert_service.py:91,133`,
    `etf_200dma_alert_service.py:118-152`: SMTP-Fehler → Alert 24h unterdrückt, nie zugestellt
    (`rule_alert_service` macht es korrekt: Dedup nur `if sent`).
17. **`/api/import/confirm` mappt ValueError auf 500** statt 422 — `api/imports.py:190-192`
    (Schwester-Endpoints machen es richtig); plus XFF-Spoofing (`nginx.conf:40` + `utils.py:6-8`,
    zusammen mit H6 fixen).

## LOW (Auswahl, vollständig in den Agent-Outputs)

- `asyncio.create_task` ohne Referenz für Snapshot-Regen nach Import (`api/imports.py:187`) —
  ntfy_service dokumentiert+löst denselben Footgun mit `_pending`-Set.
- MRS-Early-Returns cachen nicht (chart_service:31-49) → yf-Hammering bei Coverage-Lücken;
  `cache.set([], ttl=300)` auch dort.
- `cache.clear()` leert In-Memory-Layer nicht wenn Redis da ist (cache.py:152-166, latent).
- Bucket-Backfill: Wealth-Index-Chain falsch verkettet bei Backfill vor existierenden Snapshots
  (`bucket_snapshot_backfill_service.py:129-186`).
- Score variiert je nach Worker-Cache-Lokalität (Redis-Hit ohne pandas-Serien → Kriterien fallen
  aus dem Nenner; `data_degraded`-Flag wäre ehrlich).
- Screening-SMA-Phase: ungedrosselte yf-Einzeldownloads für nicht-gebatchte Ticker
  (`screening_service.py:455-458`).
- ntfy_config timestamptz↔naive-DateTime-Mismatch; prometheus_client ohne Multiprocess-Mode bei
  2 Workern; widersprüchliche X-XSS-Protection-Header nginx vs Backend; `/change-email` ohne
  Format-Validierung; `uuid.UUID(profile_id)` unhandled; Klartext-Passwort im MFA-React-State +
  irreführender "not localStorage"-Kommentar; hängende Promise-Queue bei fehlgeschlagenem Refresh;
  Transactions/PendingOrders maskieren API-Fehler als leere Liste; StockDetail verschluckt non-OK;
  A11y: 2 Modals ohne FocusTrap, StopLossWizard ohne EscClose; aria-label mit rohem "KAUFSIGNAL";
  price_alert: HTML-Injection (fehlendes html.escape) + One-Shot konsumiert vor Send; Roh-CSV-Uploads
  (PII) ohne periodischen Cleanup; swissquote fx_source toter Branch ("swissquote_forex");
  classify_tickers_bulk sync im Worker-Event-Loop; `_check_user_breakout_alerts` würde nach
  H1-Fix den Worker-Loop blocken (to_thread fehlt); Router-Riesen (screening 173 Z., alerts 136 Z.
  in main.py) gegen die 5-Zeilen-Regel.
- **Umlaut-Schäden (Sammel-Finding):** Backend `api/buckets.py:138,560,602,659`, `dividends.py:116`,
  `screening.py:189`, `external_v1.py:2183,2517,2799,2918`; Frontend `ImportRulesSection.jsx:137,230`,
  `settings/BucketsTab.jsx:255-264,419`, `BucketTemplateModal.jsx:144`, `SmartMoneyFilters.jsx:112,120`,
  `ImportWizard.jsx:521`, `BucketChangeConfirmModal.jsx:161`.
- **Locale-Bypass (Sammel-Finding):** ~15 Dateien rufen `toLocaleString('de-CH')` direkt auf statt
  format.js (MarketIndustries, SmartMoney, StockDetail, Portfolio, PendingOrders, CotMacroPanel,
  ConfirmDividendModal, StockScoreCard, PerformanceCard, BucketCorrelationCard, CacheStatus,
  BucketsTab) — User-Setting `number_format` wird ignoriert.

---

## Stärken (von allen Agents unabhängig bestätigt)

- Lückenlose Auth auf allen 27 Routern, konsequentes user_id-Scoping inkl. Service-Layer,
  100% Rate-Limit-Abdeckung auf Writes, External-API mit Scope-Checks + atomarem ApiWriteLog.
- Heilige Berechnungs-Semantiken korrekt implementiert; yfinance-Disziplin im Kern (yf_download +
  to_thread + Event-Loop-Guards); Snapshots/price_cache idempotent via on_conflict.
- Worker: Session-pro-Job, max_instances, CASCADE-FKs vollständig, CHECK-Whitelist aktuell deckend.
- Frontend: AbortController in useApi, Modal-Trio (dialog/ESC/FocusTrap) fast flächendeckend,
  sauberes Logout-Unmounting (kein Cross-User-Datenleck).
- Import-Pipeline hält Parse→Preview→Confirm strikt ein; SMTP überall aiosmtplib + SSRF-Validierung.

## Empfohlene Fix-Reihenfolge

1. **Sofort (Sicherheit/Datenintegrität):** C1, H1, H2+H3 (GBX gemeinsam), H4, H7
2. **Bald (stille Ausfälle):** H5, H6 (+XFF), H8 (mit Freigabe), M8, M16
3. **Frontend-Paket:** H9, H10, H11 (Release-Blocker!), Fehler-Maskierung
4. **Berechnungs-Ränder (mit Freigabe, da heilige Dateien):** M1, M2, M3, M4
5. **Hygiene-Paket:** M5-M7 (Migrations-Drift + `alembic check` als Audit-Gate), M9-M15, M17
6. **Sammel-Findings:** Umlaute, Locale-Bypass, LOWs

⚠️ Bei H8, M1, M2, M3 sind heilige Dateien betroffen (CLAUDE.md Regel 1/11) — Bugs, keine
Semantik-Änderungen, aber Umsetzung nur mit expliziter Freigabe.
