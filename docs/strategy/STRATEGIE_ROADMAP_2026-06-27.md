# OpenFolio — Strategische Standortbestimmung & Execution-Roadmap

**Session-Report vom 27.06.2026** · **laufend aktualisiert** (dieses Dokument wird bei jedem Arbeits-Inkrement nachgeführt)
**Ziel:** das beste Finanztool der Welt bauen — offene, ambitionierte Standortbestimmung gegen die führenden Tools, plus konkreter, codebasis-geerdeter Umsetzungsplan.

---

## Umsetzungs-Stand (laufend aktualisiert — letzte Aktualisierung 28.06.2026)

Alle Commits auf `main`, gepusht, **prod-deployed & verifiziert** (sofern nicht anders vermerkt).

> **🏷️ Release `v0.49.0` (28.06.2026) — deployt + prod-verifiziert.** Gebündelt: Netto-Vermögen · Trade-Journal (Plan→Ist + Auto-Link) · Dividenden-Forecast · Per-Position-Rebalancing · FIRE-Projektion · External-API-Parität (8 Analyse-Sichten) · Trust-Härtung Import. Audit-Gate grün (1426 Tests), Docker-Build verifiziert, getaggt + gepusht (`81457ff`), Prod `/api/health` meldet `version:0.49.0` (db+redis ok). Damit **3 von 4 strategischen Lücken geschlossen** (① ② ③), ④ CH-Steuer gescopt + bewusst geparkt (Datenreife).

> **🏷️ Release `v0.50.0` (28.06.2026) — UI-Redesign, getaggt + gepusht + prod-verifiziert.** Komplettes verbindliches Design-System (Dark Theme, IBM Plex, Token-System, neues Logo) über ALLE ~24 Screens + Modals + Zustände ausgerollt und als Release getaggt (`a329597`); Design-System dauerhaft verankert (`CLAUDE.md`, `frontend/DESIGN_SYSTEM.md`, `ui/`-Primitives, diff-skopierter Audit-Check). Bündelt zusätzlich den Nach-v0.49-Batch „1·2·3" + einen Changelog-Auslieferungs-Fix (`public/changelog.md` war gitignored + ausserhalb des Docker-Build-Kontexts → Changelog-Seite auf prod war leer). Audit-Gate grün, Docker-Build verifiziert, Prod `/api/health` meldet `version:0.50.0`.

> **🏷️ Release `v0.51.0` (28.06.2026) — Mobile/Responsive, getaggt + gepusht + prod-verifiziert.** App auf `<md` nutzbar gemacht: Bottom-Tab-Navigation + „Mehr"-Seite ersetzen die Sidebar, fünf Kern-Screens (Marktklima/Portfolio/Performance/Watchlist/StockDetail) haben bespoke Mobile-Layouts (dichte Tabellen → Karten); übrige Bereiche responsiv-degradiert via „Mehr". **Rein additiv** — Desktop + alle Berechnungen unverändert. **Kehrt die bisherige Desktop-only-Haltung um** (`frontend/DESIGN_SYSTEM.md` Regel 5 + Memory [[project_desktop_only]] auf responsive umgestellt). Prod `/api/health` meldet `version:0.51.0`, Mobile-Viewport (390px) 0 Konsolen-Fehler, Maintainer-abgenommen.

**Vertrauen in die Zahlen**
- `c5d004b` — CLAUDE.md „heilige Regeln" → testgestützte „Korrektheits-Invarianten" + Golden-Master-Suite (56 Fälle)
- `f5dcb7c` — Forward-Return-Backtest-Harness scharf · `78c005f` — Fetch-Härtung (Coverage 37→85 %)
- `d29eea4` — Bucket-Drift-Alert misst gegen liquides Gesamt (== Pie) statt Aktien-Sleeve
- `2366f0a` — Vorsorge aus liquider invested-Basis ausgeschlossen (Invariante #2)
- Trust-Härtung `import_service.confirm_import` (high-severity, war ungetestet): 8 Tests pinnen Ownership-Skip (Multi-User — fremde/unbekannte position_id wird nie angehängt), Server-Dedup/Idempotenz (+ force_import-Override), `total_chf`-Ableitung aus fx_rate (Invariante #1), Buy→shares/cost_basis, Manual-Balance ohne yfinance_ticker. Begleitend: Dedup-Query backend-agnostisch (uuid statt str → auch auf SQLite testbar). *(v0.49.0, deployt + prod-verifiziert 28.6.)*

**Ops / Security**
- `0d24ff5` — `/metrics` ohne Auth scrapebar + Grafana datasource-uid (Monitoring entblindet)
- `7b517ca` — `daily_refresh` nimmt Tages-Snapshot auch bei Kurs-Timeout auf
- `3800b6a` — Audit-Log-Tab im Admin-Panel
- `aa32ba3` — keine Retries auf 4xx (FMP-402) + ETF-Refresh läuft keyless ohne FMP-Key

**Differenzierer — ETF-Look-Through für UCITS (Lücke #3 geschlossen, iShares)**
- `2548ab9` — iShares-CSV-Adapter (keyless, Exchange→yf-Ticker) · `d18de80` — Issuer-nativer Sektor (EM-Coverage 0.7→100 %) · `8230638` — Länder-Look-Through-View
- Prod-verifiziert: EIMI + CHSPI volle Sektor- + Länder-Durchsicht.

**Handlungsbrücke (Lücke #2, ✅ geschlossen + deployt)**
- `d5aaca8` — Rebalancing-Cockpit MVP: Soll/Ist/Delta je Bucket (target_pct XOR target_chf vs. Ist = Pie-Basis) + Cash-First-Zusammenfassung, Card auf der Performance-Seite, neutrale Sprache. Bucket-Ebene; Trade-Journal + Per-Position-Orders offen.
- Trade-Journal (Adhärenz-Hälfte): gescopt (`docs/design/DESIGN_trade_journal.md`, Ultracode-Workflow), Kill-Gate **gegen Prod gemessen**: pending_orders = NO-GO (nur 11 % der Trades). **Pivot auf Maintainer-Hinweis:** echte Plan-Quelle ist der Report-Vault (`reports` category=`trade`, 86 Trade-Pläne von claude-finance). **Komplett gebaut (3 Iterationen, adversarial geprüft):**
  - *Datenschicht* (Migration 089): `reports.ticker/side/linked_transaction_id` (FK SET NULL), Schreibzeit-Link via External-API POST/PATCH mit Ownership-Validierung, Read-View `/api/analysis/trade-journal` (Plan→Ist→Status).
  - *Schreibpfad* (finance-Repo): Sync-Skript `--ticker/--side/--linked-txn`, `/sell-check` (Sell) + `/trade-plan` (Buy) + globale CLAUDE.md-Regel für ad-hoc Stop-Outs. Vorwärtskompatibel (Prod ignoriert Felder bis Deploy).
  - *Server-seitige Auto-Verknüpfung*: beim Buchen einer Buy/Sell-Txn (direkt/Fill-Reconciliation/CSV-Import) wird der jüngste offene Plan automatisch verlinkt — schliesst die async Buy-Fill-Lücke. Best-effort, exakter `ticker`+`side`-Match, keine Invariante berührt.
  - *Frontend* (`07e5bde`): `TradeJournalCard` auf der Performance-Seite (Handlungsbrücke-Cluster, unter dem Rebalancing-Cockpit) — Plan→Ist-Liste mit Status „umgesetzt/offen", Summary, neutraler Leer-Zustand.
  - 3 adversariale Reviews (je 7–10 Befunde → nur LOW Test-Gaps, alle gefüllt); ~26 neue Tests. Deployt & prod-verifiziert (28.6.: getaggter „Sell-Check AMAT 2026-06-28" trägt ticker/side live). Commits openfolio `27848dd`/`1654364`/`07e5bde`, finance `6c69d8f`/`be8a921`.
- Per-Position-Rebalancing (lean): bricht den Bucket-Überhang auf **Trim-Kandidaten je Position** herunter (grösste zuerst) + **Klumpenrisiko-Flags** (≥10 % des liquiden Werts). BEWUSST keine Positions-Ziele (gibt es nicht) → nur die reduzieren-Seite + Konzentration, read-only, neutrale Sprache. `/api/analysis/position-rebalancing` + `PositionRebalancingCard` (unter dem Rebalancing-Cockpit). Adversarial geprüft (Kern korrekt, nur Nits), 7 Tests. *(v0.49.0, deployt + prod-verifiziert 28.6.)*

**Vorausschau / Income / Gesamtbild (Lücke #1, ✅ geschlossen + deployt)**
- `e96d5b1` — Dividenden Yield-on-Cost (12M, effektiv erhalten): Portfolio + pro Position, rückwärts (kein Forecast), Card auf der Performance-Seite.
- **Dividenden-Forecast (Vorausschau, NEU):** projiziertes 12M-Einkommen als Run-Rate **pro aktueller Position** (Trailing-12M-DPS × shares × FX) — bewusst NICHT aus dem Ledger (Kill-Gate-Probe gegen Prod: Ledger-Run-Rate ist nach vorn kontaminiert, 118 % Coverage durch verkaufte Zahler). **Worker-populiert + Redis-gecacht, null yfinance pro Request** (die Burst-429-Falle wurde live ausgelöst → diktierte die Architektur). `/api/analysis/dividend-forecast` + Card auf der Performance-Seite. Adversarial geprüft (7→1 MED-Befund gefixt: rollback im Multi-User-Loop). *(v0.49.0, deployt + prod-verifiziert 28.6.)*
- **FIRE-/Kapital-Projektion (Vorausschau, NEU — interaktiv):** real (inflationsbereinigt) Projektion `Kapital×(1+r)+Sparrate` → FIRE-Zahl (Ausgaben/SWR), Jahre-bis-FIRE, Deckung + Kurve. **FIRE-Kapital = einkommensfähiges Finanzkapital:** Default `Liquid + Vorsorge`, strenger `Nur Liquid` wählbar; **illiquide (Eigenheim-Equity, Private Equity) zählen bewusst NICHT** (kein Entnahme-Einkommen — Review-Befund, Verzerrung an der Wurzel behoben statt nur bedisclaimert). Annahmen im Card live-änderbar (localStorage, debounced+clamped). `/api/analysis/fire-projection` (+ External-Parität) + `FireProjectionCard`. *(v0.49.0, deployt + prod-verifiziert 28.6.)*
- Vermögensbilanz mit expliziter Hypothek-Zeile: `/api/analysis/net-worth` (Konzept A = Finanzanlagen + Immobilien Brutto − Hypothek). Als Aktiven/Passiven-Aufschlüsselung direkt unter den KPI-Kacheln (kein doppelter Riesen-Betrag — die Netto-Summe == die bestehende Kachel „Gesamtvermögen"; die Karte liefert die Aufschlüsselung + die Hypothek, die die Kachel still im Equity verrechnet). Disclaimer „Brutto-Marktwert, nicht Vermögenssteuerwert". Invariante #2 unberührt. Unit-Tests grün (kein Doppelzählen). *(v0.49.0, deployt + prod-verifiziert 28.6.)*

**Status der 4 strategischen Lücken:** ① Vorausschau — **✅ geschlossen** (Backtest-Beweis + Dividenden-YoC + Netto-Vermögen + Dividenden-Forecast + FIRE-/Kapital-Projektion) · ② Handlungsbrücke — **✅ geschlossen + deployt** (Rebalancing-Cockpit + Per-Position-Trim + Trade-Journal komplett: Daten/Schreibpfad/Auto-Link/Frontend) · ③ Durchsicht — **✅ geschlossen** (iShares; Xtrackers/Vanguard/UBS offen) · ④ CH-Steuer/Vorsorge — **gescopt, Kill-Gate gemessen = NO-GO, geparkt** (`docs/design/DESIGN_ch_tax.md`): MVP wäre CH-Ertragsverzeichnis (Judge 23/25), aber die Daten-Probe zeigt den Einkommens-Ledger zu dünn (Steuerjahr 2025: **0 gebuchte Erträge**; Dividenden 2023:2/2024:6/2025:0/2026:19; alle 4 ETFs thesaurierend/ungebucht). Verfrüht, nicht tot. **Re-Gate: ein vollständig gebuchtes Steuerjahr (2026 → ~Anfang 2027).**

**Bewusst geparkt / verworfen:** Smart-Money-Scoring (anti-prädiktiv, Per-Signal-Decomposition steht bereit) · CH-Steuer (DA-1/eCH-0196/3a) · Tagesbewegungs-Attribution + Counterfactual + Adhärenz-Scoring (Red-Team-Cuts) · OEF/UBS-Look-Through (US-Interstitial bzw. kein keyloser Kanal).

**External-API-Parität (stehende Regel):** ALLE neuen Read-Views sind auch unter `/api/v1/external/analysis/*` (X-API-Key) gespiegelt — net-worth, dividend-yoc, dividend-forecast, rebalancing, position-rebalancing, trade-journal, country-lookthrough, fire-projection, fire-assumptions, signal-backtest-history (Paritätstest intern==extern). API-Doku (`reference_openfolio_api.md`, von Cloud Finance referenziert) immer mitziehen.

**Nach-v0.49-Batch „1·2·3" (28.06.2026, auf `main`, deploy ausstehend):** Drei Vorwärts-Hebel exekutiert, jeder mit Tests + eigenem Commit, jeder API-gespiegelt + Doku gezogen.
- **Feature-Politur** (`c475374`, `dcec96a`): (a) Dividenden-Forecast **on-demand** statt nur 09:30-Worker — `POST .../dividend-forecast/refresh` (write-Scope, gedrosselt via 1h-Cache+Semaphore) + ↻-Button in der Card. (b) **FIRE-Annahmen serverseitig persistiert** (`UserSettings.fire_assumptions` JSON, Migration 090) statt nur localStorage → geräteübergreifend; GET/PUT (+ext), interner PUT klemmt, externes Schema strikt (422), `net_worth`→`with_pension`-Migration.
- **Worker-Job-Liveness + Silent-Stale-Detektor** (`c0d8e0c`): `worker_job_health`-Tabelle (Migration 091) + APScheduler-Listener stempelt nach jedem Lauf last_run/status/runtime/error + aus dem Trigger abgeleitetes `max_age_s` (kein Hardcoding). Stündlicher Meta-Check ERROR-loggt stale/failing Jobs (Alert-Hook fürs Monitoring; kein System-ntfy vorhanden). Admin-Read `GET /api/admin/worker-health` (+ext, admin-gated). Schliesst den letzten §2.2-Betriebshebel + das stehende „Crons brauchen Liveness"-Feedback.
- **Per-Signal-Backtest als Worker-Job + Regime-Persistenz** (`aa29626`): der manuelle `--per-signal`-Harness wird monatlicher Worker-Job (`per_signal_backtest`, 1. um 02:00 CET) → `signal_backtest_results` (Migration 092). Akkumuliert über die Zeit die **Multi-Regime-Historie**, die Invariante #3 für eine fundierte (oder eben gar keine) Gewichts-Entscheidung verlangt. `collect_per_signal_samples` (Reuse der Forward-Return-Pipeline, yfinance-Burst-sicher) + pures `aggregate_per_signal`; Read `GET /api/analysis/signal-backtest-history` (+ext), idempotent pro run_date.

### Nach v0.49.0 — die nächsten Hebel (priorisiert, 28.06.2026)

Die ursprüngliche 4-Lücken-These ist abgearbeitet (3 geschlossen, 1 bewusst geparkt). Die nächste Phase folgt aus den **verifizierten Befunden dieser Session**, nicht aus neuen Wunschlisten:

1. **Daten-Fundament — diagnostiziert 28.6.:** Die ausschüttende Pipeline ist **gesund** (0 offene Pending-Dividenden = keine Confirm-Lücke; 2026 sauber erfasst inkl. OEF). 2025=0 ist eine **einmalige historische Lücke** (Detection-Lookback nur 90d/35d, reicht nie ein Jahr zurück) — kein Defekt, **nichts zu härten.** Es bleiben zwei echte, permanente Lücken: (a) **thesaurierende Fonds** (CHSPI/EIMI/IB01) — CH-steuerbarer Ertrag via ICTax, den Detection prinzipiell nie findet → **eigene Quelle nötig (ICTax/ESTV-Kursliste)**; (b) historisches 2025 (einmaliger Backfill, niedrige Prio). **ICTax-Spike 28.6. (Deep-Research) = GO:** die ESTV-Kursliste ist automatisierbar (jährlicher Bulk-XML, Session+CSRF, kein Login → lokal SQLite per ISIN/Jahr; OSS-Referenz `vroonhof/opensteuerauszug`, MIT). **EIMI + IB01 live verifiziert MIT Pro-Stück-Ertrag in Kursliste 2025** (IE-„ohne-Kurs"-Befürchtung widerlegt). Korrektur: CHSPI ist ausschüttend → echte Thesaurierer = nur EIMI+IB01. **Daten-technisch machbar; das echte Vor-Build-Gate ist jetzt die SIX-Financial-Lizenz** (darf ein multi-user self-hosted Tool die Steuerwerte ziehen/anzeigen? ungeklärt), nicht mehr die Verfügbarkeit. CH-Steuer-Re-Gate ~2027 ohne neue Arbeit auf Kurs.
2. **Aktivierung & Beobachtung der v0.49-Features** — Trade-Journal füllt sich erst mit getaggten claude-finance-Läufen + neuen Buchungen (forward-only by design); Dividend-Forecast beim ersten 09:30-Worker-Lauf. ✅ **Politur erledigt (Batch „1·2·3", 28.6.):** Forecast on-demand-Trigger (`POST .../dividend-forecast/refresh` + ↻-Button) und FIRE-Annahmen serverseitig pro User persistiert (`UserSettings.fire_assumptions`, Migration 090) — beides intern+extern+getestet. Bleibt: real-world beobachten und gezielt iterieren.
3. **Smart-Money Per-Signal-Decomposition — gebaut + gelaufen 28.6. (`a6e144b`):** Harness-`--per-signal`-Modus (present-vs-absent je Signal, eine Fetch). Befund (Dev, 6076 Samples, 1 Regime): **KEIN einzelnes faules Signal — die Anti-Prädiktivität ist breit.** Δ30d: superinvestor −0.029, large_buy −0.029, insider_cluster −0.007 (höchstgewichtet!), buyback ~0; unusual_volume +0.16 = n=12-Rauschen. Die positiv gewichteten Signale sagen in diesem Regime keine Outperformance voraus → Composite nicht durch Komponenten-Cut reparierbar. **Keine Gewichts-Änderung (Invariante #3); Multi-Regime-Validierung nötig.** ✅ **Automatisiert (Batch „1·2·3", 28.6.):** monatlicher Worker-Job `per_signal_backtest` persistiert die Decomposition (`signal_backtest_results`, Migration 092) → akkumuliert die Multi-Regime-Historie über die Zeit; Read `GET /api/analysis/signal-backtest-history`. **Decision bleibt gegatet** bis genügend unterschiedliche Regimes vorliegen.
4. **Verbleibende Differenzierer (gated):** Konfluenz-/Divergenz-Engine (metadata-only) · self-hosted-AI mit Egress-Guard (BYO-Key/Ollama — „AI ohne Datenabgabe") · Gewerbsmässiger-Wertschriftenhändler-Frühwarnung (ESTV KS 36, schützt die CH-Kapitalgewinn-Freiheit) · Vorsorge-/3a-Cockpit.
5. **Frontend/Design-Vollständigkeit — ✅ erledigt (v0.50.0, 28.6.)** + **Mobile nachgezogen (v0.51.0, 28.6.)**: das komplette Redesign (alle ~24 Screens + Modals + Zustände) ist ausgeliefert + prod-verifiziert, das verbindliche Design-System ist verankert; Mobile/Responsive s. Release-Banner oben. Briefs `docs/archive/DESIGN_PROMPT_fehlende_screens.md` / `docs/archive/DESIGN_PROMPT_verfeinerung.md` damit verbraucht.
6. **CH-Steuer #4** — Re-Gate ~Anfang 2027 (vollständig gebuchtes Steuerjahr 2026), greift sobald Hebel 1 wirkt. Alternativ früher: Vermögenssteuer-Wertschriftenverzeichnis (datenunabhängig von Dividenden).
7. **Rest-Betriebshebel:** ✅ **Worker per-Job-Liveness + Failure-Alert erledigt (Batch „1·2·3", 28.6., `c0d8e0c`):** `worker_job_health` + Listener-Heartbeat + stündlicher Silent-Stale-Detektor (ERROR-Log) + Admin-Read `GET /api/admin/worker-health`. Damit sind alle §2.2-Betriebshebel (/metrics, Audit-Log-UI, daily_refresh, Liveness) erledigt. Bleibt: weitere Look-Through-Issuer nur falls gehalten (UBS); Grafana Contact-Point an die ERROR-Logs hängen (Notification-Zustellung, s. Backlog).

---

## Backlog — alle gegateten & aufgeschobenen Arbeiten (Single Source of Truth)

> **Zweck:** Jede geplante, aber (noch) nicht umgesetzte Änderung — egal ob durch Kill-Gate, Datenreife, Lizenz, fehlenden Backtest oder bewusste Priorisierung blockiert — lebt **hier**, damit nichts in Code-Kommentaren oder Einzeldokumenten verloren geht. Quelle steht je Eintrag in Klammern. Erledigtes wandert nach oben in den „Umsetzungs-Stand". Stand 28.06.2026.

> **🔄 Roadmap-Code-Abgleich 28.06.2026 (22-Agenten-Verifikation gegen die echte Codebasis).** Auslöser: die **Risiko-Kennzahlen** waren als „offen" gelistet, obwohl längst prod-live. Der Sweep fand **6 weitere als „offen" gelistete, aber tatsächlich gebaute + deployte** Punkte: die ganze Performance-Seiten-Welle (Risiko-Kennzahlen, Per-Bucket Total-Return/Fees/Alpha-Beta — alle `d4cf8ec`), die **Branchen-Flow-Seite** (live seit April) und der **Schwur-Filter-Toggle** (live seit Mai); Locale-Cleanup ~93 % erledigt; der EPS-**Scanner** ist live (nur der Backtest bleibt offen). Alle unten korrigiert. **Bestätigt korrekt-offen:** Score-Display-Mapping (backtest-gated), FMP→Finnhub, Konfluenz-Engine, ETF-Adapter Xtrackers/Vanguard/UBS, OEF-Default, Trade-Journal-Extras, Symbol-Resolution, real_estate-Golden-Pin, CH-Steuer (geparkt), IBKR-Flex. **Bestätigt erledigt:** Per-Signal-Backtest-Job, Worker-Liveness, FIRE-Persistenz, Forecast-on-demand. **Offene Entscheidung:** Freshness Phase 1 (Kill-Gate überfällig, s. Abschnitt B). **Lehre:** die Roadmap driftet, sobald Features ohne `docs(strategy)`-Nachzug landen — der „Umsetzungs-Stand" muss bei JEDEM Feature-Commit mitgehen ([[feedback_living_strategy_paper]]).

**A. Steuer & CH-Spezifika**
- **CH-Ertragsverzeichnis (MVP)** — ⛔ Kill-Gate gemessen = NO-GO (Steuerjahr 2025: 0 gebuchte Erträge). **Re-Gate: ein vollständig gebuchtes Steuerjahr (2026 → ~Anfang 2027).** (`docs/design/DESIGN_ch_tax.md`)
- **ICTax-Quelle für thesaurierende Fonds (EIMI, IB01)** — Daten-technisch machbar (Bulk-XML, OSS-Referenz `vroonhof/opensteuerauszug`), Deep-Research GO. **Echtes Vor-Build-Gate = SIX-Financial-Lizenz** (darf ein multi-user self-hosted Tool die Steuerwerte ziehen/zeigen? ungeklärt). (`docs/design/DESIGN_ch_tax.md` + ICTax-Spike)
- **Wertschriftenverzeichnis / Jahresend-Steuerwert** — braucht PositionSnapshot oder On-Demand-Replay; Daten-Reife ~40 %. Pivot-Option, datenunabhängig von Dividenden. (`docs/design/DESIGN_ch_tax.md`)
- **DA-1-Prefill + Verrechnungssteuer-Rückforderungs-Status** — Per-Country-Aggregation + Treaty-Lookup; Folge-Welle nach Ertragsverzeichnis. (`docs/design/DESIGN_ch_tax.md`)
- **Gewerbsmässiger-Wertschriftenhändler-Frühwarnung (ESTV KS 36)** — schützt die CH-Kapitalgewinn-Freiheit; eigenständiger Scope. (`docs/design/DESIGN_ch_tax.md`, §4.2)
- **Säule-3a-/Vorsorge-Cockpit** — 0 % Daten heute, eigenes Feature (~20–30 h). (`docs/design/DESIGN_ch_tax.md`, §4.2/4.3)

**B. Screening / Signale / Scoring — alle backtest- oder probe-gated (Invariante #3)**
- **Quant-Probe Kill-Gate 2026-08-15** — `form4_cluster` (deployed) + `estimate_revision` (Probe): braucht ≥3 dokumentierte Trade-Kippungen bis 15.8., sonst Signal raus. (`worker.py`, `models/form4_transaction.py`, [[project_quant_probe_and_a2_gate]])
- **Score-Formel-Swap (Iteration 2.5)** — 96.4 % der Scores ≤30, 0 über Display-67 (linear). 3 Mapping-Kandidaten (log10/percentile/hybrid) **gated bis Forward-Return-Backtest** — jetzt billig via neuem `signal_backtest_results`-Worker. Kein Display-Mapping live ohne Validation. (`docs/research/diagnose_score_verteilung_2026-05-29.md`, `docs/research/backtest_score_mappings_2026-05-31.md`)
- **Multi-Regime-Gewichts-Entscheidung** — der monatliche `per_signal_backtest`-Job akkumuliert ab jetzt Regimes; Decision (Gewichts-Änderung ODER bewusstes Beibehalten) bleibt gegatet bis genügend unterschiedliche Regimes vorliegen. (Batch „1·2·3")
- **Branchen-Flow-Seite (rvol-Fluss-Signal)** — ✅ **ERLEDIGT (Abgleich 28.6.): bereits gebaut + live.** `/branchen`-Seite (`MarketIndustries.jsx`, ~700 Z.), `tradingview_industries_service._compute_rvol_20d`, Migrationen 052–054 (April 2026), extern `GET /market/industries`, alle 5 Flow-Dimensionen + Drill-down. Der „deferred"-Eintrag war von Anfang an stale (Feature älter als die Roadmap). ([[project_branchen_flow_killgate]])
- **Freshness Phase 1 (Signal-Alter-Filter)** — ✅ **ENTSCHIEDEN 28.6. (Maintainer): Phase-0-Badges bewusst BEHALTEN** (reine Anzeige des Signal-Alters, kein Score-Einfluss → harmlos + nützlich); Kill-Gate damit formal geschlossen, KEIN Rückbau. Der Phase-1-*Filter* (max_signal_age) bleibt ungebaut + ungeplant (0 Einfluss-Fälle bis Gate-Ablauf 17.6.). Freshness NIE auto-score-decay. (`freshness_phase1_use_log.md`)
- **Schwur-Filter-Toggle (Iteration 2.6)** — ✅ **ERLEDIGT (Abgleich 28.6.): bereits gebaut + live** (Commit `f194c2d`, 31.5.). 3 Konviktions-Toggles (Trend/SMA150, Earnings-Veto 7d, Klumpen) als reine UI-Filter; Backend `schwur1/2/3_only`-Params (`api/screening.py`), Frontend `SmartMoneyFilters.jsx`, Migration 079, 4 Tests. Stale-Eintrag. (`docs/research/retro_iteration1_2026-05-31.md`)
- **EPS-Scanner: Schwellen-Backtest** — der **Scanner selbst ist gebaut + live** (`/eps-scanner`-Seite, `eps_scanner_service.py`, Migration 084, Worker-Job, intern+extern; Abgleich 28.6.). **Offen bleibt nur die Validierung:** Super-Quartal-Schwellen (25 %/+5pp) live mit Disclaimer, aber nicht forward-return-validiert. Plus offene Design-Fragen: Kriterium-C bei <2 Vorwerten, Restatement-Handling, YoY-Cap, Fiscal-Year-Versatz. (`docs/design/DESIGN_eps_scanner.md` OF-2/3/6/7)
- **FMP→Finnhub estimate_revision-Migration** — 6 US-Ticker FMP-Free 402 (n=6 statt n=33); Finnhub-Probe deckt 6/6. Bau gated/aufgeschoben. (`docs/research/diagnose_universe_audit_2026-05-21.md`, [[project_fmp_finnhub_estimate_gap]])
- **Konfluenz-/Divergenz-Engine** (metadata-only über die Smart-Money-Quellen) — Gewichts-Integration hinter Forward-Return-Power gated. (§4.2)

**C. ETF-Look-Through (Lücke #3, Rest)**
- **Weitere Issuer-Adapter: Xtrackers, Vanguard, UBS** — nur iShares ist gebaut (`etf_holdings_ishares.py`). Andere nur bauen, falls solche ETFs tatsächlich gehalten werden. (Memory [[project_etf_lookthrough_ucits]])
- ✅ **ERLEDIGT (29.6.): OEF-Country-Default.** `ETF_COUNTRY_DEFAULTS` (`constants/etf_holdings_sources.py`) ordnet eindeutig geografisch definierten Indizes ohne verwertbare Holdings-Länderdaten (OEF/SPY/VOO/IVV/SPLG = S&P 100/500 = 100 % USA — kein Raten) ihr Default-Land zu; `get_country_lookthrough` setzt bei `covered_w<=0` den ganzen ETF-Wert aufs Default-Land (sonst fiel OEF still aus der Länder-Sicht). Pro-ETF-`source: holdings|default`, Card markiert „Geo-Default" ehrlich. Tests `test_country_lookthrough_oef_geo_default` + `…_no_default_stays_excluded`. Intern + `external_v1` (Passthrough; byte-genauer Parity-Test deckt es). **Prod-Befund:** OEF war als FMP-Holdings *ohne* Country-Feld unsichtbar (covered 0 %, USA fehlte) → jetzt korrekter USA-Bucket. Rest von Lücke #3 (Xtrackers/Vanguard/UBS) bleibt offen, aber 0 solche ETFs gehalten. (Memory [[project_etf_lookthrough_ucits]])

**D. Performance-Seite & Risiko-Metriken — ✅ ERLEDIGT (v0.51.0, Commit `d4cf8ec` 26.6.; entdeckt im Roadmap-Code-Abgleich 28.6.).** Beide Punkte waren schon gebaut + prod-live, aber nie nachgezogen:
- **Risiko-Kennzahlen** (Sharpe/Sortino/Calmar/Volatilität/Information-Ratio + Rolling Returns) — `risk_metrics_service.py`, Config `RISK_FREE_RATE_PCT`, intern `GET /api/portfolio/risk-metrics` + extern `GET /api/v1/external/performance/risk-metrics`, `RiskMetricsCard` auf der Performance-Seite, `test_risk_metrics_service.py`. Prod-verifiziert (live-Abfrage 28.6.). ✅ **Externer Paritätstest vorhanden** (`test_external_risk_metrics_parity` in `test_external_analysis_parity.py`: intern `/api/portfolio/risk-metrics` == extern `/api/v1/external/performance/risk-metrics` fürs gleiche Fenster) — der „Pfad-Asymmetrie-Rest" war beim Abgleich 29.6. bereits geschlossen.
- **Per-Bucket Total-Return + Fee-Summary + Alpha/Beta** — `GET /buckets/{id}/total-return` + `/buckets/{id}/fee-summary` + `factor-decomposition?bucket_id=` (intern **und** external_v1), `BucketSection`/`FeeSummary`-Frontend, `test_bucket_total_return.py`. Prod-verifiziert.
- ✅ **ERLEDIGT (29.6.): Dividenden-Forecast als Pro-Monat-Balkendiagramm.** Backend erweitert — `dividend_forecast_service.compute_dividend_forecast` bucketet jeden realen Zahltag des Trailing-12M-Fensters auf seinen Kalendermonat (1-12) → neues `by_month[]`-Feld (12 Einträge `{month, chf}`, Summe = `forecast_12m_chf`, **keine geratenen Monate** — Datum kommt aus `fetch_dividends`). Im Worker gerechnet, null yfinance pro Request (Architektur unberührt). Fliesst intern + `external_v1` automatisch mit (Passthrough; byte-genauer Parity-Test deckt es). Forecast-Card zeigt jetzt 12 Monats-Balken („Erwartete Ausschüttung pro Monat · CHF", aktueller Monat hervorgehoben). Test `test_compute_forecast_by_month_distribution` (12 Einträge, korrekte Monate, Summen-Invariante). Damit ist die letzte offene Roadmap-Position der Welle abgeschlossen.

**E. Trade-Journal — Post-MVP-Ausbau** *(MVP gebaut + deployt; diese Teile bewusst draussen)*
- **Gewichtetes Adhärenz-Scoring + Display** — braucht Forward-Return-Validierung. **Partial-Fill-/Near-Miss-Verlinkung** + **Disziplin-Heatmap/Adhärenz-Trend** — brauchen 6m+ Trade-Kadenz. **`from-rebalancing`-Button** (Plan-Capture aus dem Cockpit). (`docs/design/DESIGN_trade_journal.md`)
- **⚠️ Architektur-Klärung (29.6., Maintainer-Frage „wozu Journal neben Offene Orders + Vault?"):** Das Trade-Journal ist **keine eigene Ablage, sondern eine Join-Sicht** (`trade_journal_service.get_trade_journal`): es paart Vault-Trade-Reports (`reports.category='trade'` = das *Warum*, Plan) mit der resultierenden Transaktion (Ist) via `report.linked_transaction_id` und leitet `executed|open` ab — also **eine Linse auf den Vault**, gefiltert auf Trade-Reports + Adhärenz. Damit existieren **zwei parallele Plan→Ist-Spuren auf dieselben Transaktionen**: (A) Offene Orders via `pending_orders.linked_transaction_id`, (B) Journal via `report.linked_transaction_id`. Konzeptioneller Überlapp. **Eigenständiger Mehrwert des Journals = nur die Adhärenz über Zeit** („bin ich meinen eigenen Plänen gefolgt?") — und der **materialisiert sich erst mit dem KI-Report-Layer (Abschnitt J)**: ohne den Plan-Report-Fluss bleibt das Journal dünn. **Konsequenz:** Journal/Adhärenz NICHT isoliert weiterbauen; **zusammen mit J angehen** und dann entscheiden, ob die zwei Plan-Spuren zusammengeführt werden. Der `from-rebalancing`-Button (oben) befüllt **Spur A (Offene Orders), nicht das Journal** → stärkt das Journal nicht, entsprechend deprorisiert. (siehe Abschnitt **J**, [[project_trade_journal_scope]])

**F. Ops / Daten-Qualität / Symbol-Resolution**
- **Grafana Contact-Point** an die Worker-Liveness-ERROR-Logs + `/metrics` hängen (Notification-Zustellung) · **Prometheus multiprocess-mode** (2 uvicorn-Worker → Counter springen). (Memory [[reference_monitoring_stack]])
- **Per-Quelle Symbol-Resolution-Mapping** (Portfolio-Ticker → yfinance/finnhub/TV) — strukturell wichtig; behebt ROG.SW→ROP.SW (kosmetisch, shares=0) + künftige Non-US-Fälle. (`docs/research/SPIKE_SIX_COVERAGE.md`)
- **Daten-Hygiene:** 18 Positionen `shares=0 & active` aufräumen. (Memory [[project_six_coverage_spike]])
- **S&P-1500-Universe-Listenpflege** (~4×/Jahr bei Index-Anpassungen) — Maintainer-Chore, optional GitHub-Action-Reminder. (`backend/services/screening/us_equity_universe.py`)
- **real_estate `shares>0`** — ✅ **ERLEDIGT (28.6.): expliziter Ausschluss-Guard + 3 Pfade vereinheitlicht.** `snapshot_service` hatte 3 divergierende real_estate-Pfade ohne Asset-Typ-Guard (Ausschluss hing allein an `shares=0`, einer bewertete sogar zu cost_basis `:746`); jetzt explizit excluded in allen dreien (`_calc_portfolio_value_fast`, `_calc_position_value_chf`→0.0, `regenerate`-Loop), spiegelt `private_equity` (Invariante #2). Golden-Master-Pins auf Soll 0.0 (`test_real_estate_with_positive_shares_is_excluded` + `…_zero_shares…`). In der Praxis 0 Verhaltensänderung (real_estate = immer `shares=0`); **volle Suite grün (1455 passed)**. (Memory [[project_golden_master_invariants]])
- **Code-Hygiene (Sammel):** Locale-Bypass `toLocaleString` — ✅ **erledigt (28.6.):** letzte Datei `SmartMoneyPanel.jsx` (2 Calls) auf `formatNumber` umgestellt → 0 `toLocaleString` ausserhalb von `format.js` (Schweizer-Locale-konsistent). Vereinzelte Umlaut-Schäden — niedrige Prio. (`docs/audits/REVIEW-codebase-2026-06-10.md`)

**G. Frontend/Design-Vollständigkeit — ✅ ERLEDIGT (v0.50.0, 28.6.).** Alle Screens/Modals/Zustände (StockDetail, Settings-Tabs, Skeleton-/Leer-/Fehlerzustände, Watchlist-18-Punkte-Checkliste, volle Filter-Sidebars …) im neuen Design-System umgesetzt + prod-deployed; Design-System verankert (`CLAUDE.md`, `frontend/DESIGN_SYSTEM.md`, `ui/`-Primitives). Briefs `docs/archive/DESIGN_PROMPT_fehlende_screens.md` / `docs/archive/DESIGN_PROMPT_verfeinerung.md` damit verbraucht. (Einzelne Nice-to-haves wie eine Command-Palette ggf. noch offen.)

**G2. Mobile / Responsive Design — ✅ ERLEDIGT (v0.51.0, 28.6.).** Entscheidung wie empfohlen umgesetzt: **responsive Web** (Tailwind-Breakpoints auf dem bestehenden Design-System — kein PWA/native) mit **read-first-Fokus**, nach Abschluss des Desktop-Redesigns. Geliefert: Sidebar→Bottom-Tab-Nav + „Mehr"-Seite auf `<md`, bespoke Mobile-Layouts (Tabellen→Karten-Stacks) für die 5 Kern-Screens (Marktklima/Portfolio/Performance/Watchlist/StockDetail), dichte Bereiche responsiv-degradiert via „Mehr". Rein additiv (Desktop unberührt); `frontend/DESIGN_SYSTEM.md` Regel 5 + Memory [[project_desktop_only]] auf responsive umgestellt. **Bewusst geparkt:** Light-Mode, native/PWA, volle Mobile-Schreibtiefe für die dichten Screens.

**H. Differenzierer & Moonshots (gated/aspirativ)** — vollständig katalogisiert in §4.2/4.3: konsolidierter Multi-Broker-Steuerauszug · self-hosted daten-souveräne AI (BYO-Key/Ollama + Egress-Guard) · deklarative Regel-Engine · Read-only-MCP-Server · Plugin-/Data-Source-SDK · CHF-FIRE-Vollmodell (AHV/PK/Steuern). IBKR-Flex-Autosync (lean, Pending-Review) als nächster Konnektivitäts-Schritt ([[reference_broker_bank_connectivity]]).

**I. Historische Audit-Reports (abgelöst, nur bei Bedarf gegenprüfen)** — `docs/audits/REVIEW-codebase-2026-06-10.md` (C1/H1–H11/M1–M17) und `docs/audits/AUDIT-v0.39.1-2026-05-17.md` sind **vor v0.49.0** entstanden; die kritischen Befunde (Import-Confirm-Ownership, GBX/GBp, PE-Metadata, Breakout-Zustellung …) sind seither gefixt und durch das stehende `@openfolio-audit`-Gate + den v0.49.0-Audit (1453 Tests grün) abgelöst. Bei Bedarf einzelne Rest-Nits dort nachschlagen — NICHT pauschal als offen behandeln.

**J. KI-Report-Layer (BYO-Key) — Button-getriggerte AI-Reports** *(neu 29.6., für später; Maintainer-Wunsch)* — Die KI-Analysen, die der Maintainer heute extern über die Cloud-Finance-Skills nutzt, nativ in OpenFolio als **Buttons** abbilden. Pro Aktie auf der StockDetail-Seite ein Button **„Trade Plan"** und **„Sell Check"** (erweiterbar um weitere Report-Typen); auf Portfolio-Ebene **„Portfolio Review"**. Mechanik: **BYO-Key** — der Nutzer bindet seinen eigenen AI-Provider-Schlüssel an (Settings, wie die bestehenden FMP/Finnhub-Keys → keine AI-Kosten beim Host, daten-souverän). Je Report-Typ ist nur ein **Prompt-Template hinterlegt** (der Prompt ist das IP), die KI generiert; das Ergebnis wird als **saubere MD-Datei im Report-Vault** abgelegt (Vault-Lifecycle existiert bereits — Prune/Sync fertig). Das ist die **konkrete Ausprägung des „daten-souveräne AI (BYO-Key/Ollama + Egress-Guard)"-Differenzierers** (Abschnitt H) UND der **definierende Mehrwert des Pro-Tiers** (Abschnitt K). **Wiederverwendbar:** Report-Vault, Settings-BYO-Key-Muster, StockDetail-Action-Buttons. **Offene Scoping-Fragen:** Provider-Auswahl (Anthropic/OpenAI vs. Ollama für Self-Host-Datensouveränität); Prompt-Templates eingebaut vs. user-editierbar; **Egress-Guard** (wie viel Portfolio-Kontext darf an eine externe KI gesendet werden — Datensouveränität); Streaming vs. Batch; Rate-Limit/Kosten-Guard; Multi-User-Scoping der Keys + Reports. Bau **nach** der aktuellen Welle. (Memory [[reference_broker_bank_connectivity]]-Nachbar; Vault [[project_report_vault_prune_backlog]])

**K. Kommerzialisierung & Geschäftsmodell (nach Full Release)** *(neu 29.6., Maintainer-Entscheid)* — Nach dem **Full Release** wird OpenFolio **aktiv verkauft**. Geplantes **3-Tier-Modell** (Marketing-Website bereits in Claude Design entworfen — Projekt `OpenFolio Portfolio-Manager`, Ordner `marketing/`: `Home`, `Pricing`, `Walkthrough`, OG/Hero-Assets; Positionierung „Dein gesamtes Vermögen · mehr als ein Depot-Tracker · Schweiz/CHF · kein Anlageberatungs-Ersatz"):
  - **Self-Hosted (Free, OSS):** bleibt **MIT-lizenziert mit vollem Funktionsumfang** — herunterladen, selbst hosten, alles nutzen. Die Grundvariante, **nie kostenpflichtig**.
  - **Hosted (managed):** der Maintainer hostet (günstig, z. B. Hetzner), Nutzer zahlt **monatlich Summe X** (Website-Entwurf: „Hosted Pro" ~CHF 10–12/Mt) — gehostet, Auto-Updates, verschlüsselte Backups, Premium-Datenquellen, E-Mail-Support.
  - **Pro (hosted + AI):** zusätzlich die **AI-Features aus Abschnitt J** integriert — der AI-Report-Layer ist der Pro-Differenzierer.
  - **⚠️ Reconciliation nötig:** Der designte Website-Entwurf nennt die Tiers **Self-Hosted / Hosted Pro / Team** (Team = CHF 31–39/Mt, Family Offices, bis 10 Nutzer, Rollen/SLA) — der **AI-„Pro"-Tier ist dort noch nicht abgebildet**. Vor dem Launch zusammenführen, z. B. Self-Hosted (free) / Hosted (managed) / **Pro (hosted + AI)** / optional Team (Multi-User) als 4. Stufe oder Pro-Add-on.
  - **Vorbedingungen (Bau nach Full Release):** Multi-Tenancy- + Billing-Infra (Subscriptions, TWINT/Kreditkarte), Hosting-Ops, **Lizenz-/ToS-Klärung** (Weiterverkauf von Premium-Datenquellen — vgl. die offene SIX-Financial-Lizenzfrage in Abschnitt A), Egress-/Daten-Governance für die AI-Features (J). Status: **strategisch notiert, Bau nach Full Release**; Website-Assets liegen in Claude Design.

---

## 0. Executive Summary

OpenFolio ist **rückblickend bereits Weltklasse** — Buchhaltung, Performance-Analytik, Smart-Money-Breite und Self-Hosting/Automation liegen tiefer als jedes Open-Source-Pendant und in Einzeldisziplinen auf Koyfin-/Bloomberg-Niveau. Die Lücken sind **systematisch** und genau dort, wo aus einem exzellenten Tracker ein einzigartiges Produkt wird:

1. **Null Vorausschau** — keine Projektion, kein Dividenden-Forecast, kein Beweis, dass die eigenen Signale je funktioniert haben.
2. **Keine Handlungsbrücke** — der Nutzer sieht Drift/Signale, bekommt aber keine Order, kein Rebalancing, kein Adhärenz-Feedback.
3. **Keine echte Durchsicht** — ETF-Look-Through ist US-only, also ausgerechnet fürs UCITS-lastige CH-Depot blind.
4. **Grösster ungedeckter CH-Hebel** — Steuer (DA-1, Verrechnungssteuer, eCH-0196) und Vorsorge (3a/FIRE) fehlen fast komplett, obwohl die Daten bereits im Ledger liegen.

**Der einzigartige, uneinholbare Winkel:** die Schnittmenge, die sonst niemand besetzt —
> **regelbasiertes Investieren + Self-Hosting/Datensouveränität + Schweizer Steuer-/Vorsorge-Tiefe + AI ohne Datenabgabe.**

Internationale Tools (getquin, Parqet, Sharesight, Snowball) ignorieren die Schweiz strukturell und sind SaaS-LLM-gebunden; CH-Anbieter (VIAC, finpension, True Wealth) sind geschlossene Produkt-Silos ohne Research/Signale/Self-Hosting.

**Seither umgesetzt (Stand 28.06.2026 → Release `v0.49.0`):** Diese Standortbestimmung wurde nicht nur geschrieben, sondern grossteils **exekutiert** — 3 der 4 Lücken geschlossen und deployt (Vorausschau, Handlungsbrücke, Durchsicht), die 4. (CH-Steuer) gescopt + datengetrieben geparkt. Den vollständigen, laufenden Stand führt der Abschnitt **„Umsetzungs-Stand"** ganz oben; die forward-gerichteten Prioritäten **„Nach v0.49.0 — die nächsten Hebel"** ebendort. Die untenstehenden Teile A–G sind die **ursprüngliche Diagnose vom 27.06.** (Begründungs-Substrat, bewusst unverändert als Audit-Trail).

---

## 1. Methodik

Die Analysen entstanden über mehrere Multi-Agent-Workflows mit durchgängig **adversarialer Verifikation** — jeder Befund und jeder Soll-Wert wurde von einem unabhängigen Agenten gegengeprüft, bevor er in dieses Dokument einging:

| Workflow | Umfang | Ergebnis |
|---|---|---|
| Interne Lückenanalyse | 7 Such-Lenses → Verifikation jedes Funds | 62 verifiziert offene Punkte (8 Themen) |
| Wettbewerbs-Standortbestimmung | 7 Inventar-Domänen + 6 Web-Recherche-Cluster → 6 Chancen-Lenses → adversariale Prüfung | 48 Chancen (33× „build", 15× „maybe", 0× „skip") |
| Geerdete Execution-Roadmap | 17 Roadmap-Punkte × Code-Erdung × Red-Team × Sequenzierung | First Sprint + 4 Wellen + Phasen-Korrekturen + Risiko-Register |

Leitprinzip: **Verifizierter Wert statt plausibler Behauptungen.** Mehrere „klingt gut"-Punkte wurden im Red-Team als überschätzt, irreführend oder vertrauensschädigend entlarvt und gecuttet (siehe §6).

---

## 2. Teil A — Interne Lückenanalyse (62 verifizierte Punkte)

Verteilung nach Such-Lens: Code-Stubs 9 · Roadmap/Docs 8 · Feature-Vollständigkeit 11 · Frontend 9 · Tests 9 · Ops/Reliability 10 · bekanntes Backlog 6.

### 2.1 Die 8 Themen

1. **Scoring-Validierung & Backtest-Infrastruktur** — alles hing am Forward-Return-Stub (jetzt gelöst, siehe §7.3); davon abhängig: totes oberes Score-Display-Band, EPS-Scoring, Signal-Gewichte.
2. **Smart-Money Signal-Qualität & überfällige Gate-Entscheidungen** — Buyback nur Keyword-Treffer (ohne Programmgrösse), Congressional nur binäres Flag (ohne Datum/Betrag), SIX-Insider Gewicht 3 ohne Backtest.
3. **Test-Abdeckung der Kern-Berechnungen** — MRS, `snapshot_service`-Ausschlüsse, `import_service` waren ungetestet (in dieser Session teilweise geschlossen, siehe §7.2).
4. **Ops — Monitoring & Alerting** — `/metrics` verlangt JWT → Prometheus kann nicht scrapen, beide Grafana-Alerts auf „No Data"; keine Off-Host-Backups.
5. **Ops — Worker-Liveness & Job-Robustheit** — Crons ohne per-Job-Liveness/Failure-Alert; `daily_refresh`-Timeout überspringt still den Tages-Snapshot.
6. **Security & Admin** — Audit-Log-Backend gebaut, aber ohne UI; `get_client_ip` vertraut `X-Forwarded-For` blind.
7. **Datenabdeckung & Domänen-Features** — Konzentration/ETF-Overlap nur US; Private Equity ohne IRR/MOIC; Industry-MRS nur Phase 1.
8. **Frontend/UX-Konsistenz** — inkonsistente native `window.confirm`, technische „HTTP 500"-Meldungen, verwaiste Endpoints.

### 2.2 Höchste interne Hebel (unabhängig von der Wettbewerbsstrategie)

- **`/metrics`-JWT-Wall entfernen** `[S]` — macht das gesamte mitgelieferte Monitoring schlagartig funktionsfähig.
- **Audit-Log-UI** `[S]` — Backend fertig; ein nicht einsehbarer Trail ist für ein self-hosted Multi-User-Tool eine echte Security-Lücke.
- **MRS / `snapshot_service` / `import_service` testen** — Schutz der HEILIGEN Berechnungen (teilweise in dieser Session erledigt).
- **Per-Job-Liveness + Failure-Alerting** für Worker-Crons.
- **`daily_refresh`-Timeout-Bug** — early-return löscht den Tages-Snapshot.

---

## 3. Teil B — Wettbewerbliche Standortbestimmung

### 3.1 Vision

> OpenFolio wird zum **daten-souveränen Betriebssystem fürs systematische Investieren in der Schweiz**: Es schliesst den vollen Kreis von verifizierter Diagnose über *beweisbare* Signale bis zur disziplinierten, dokumentierten Aktion — und löst als einziges Tool den jährlichen CH-Steuer- und Vorsorge-Schmerz broker-übergreifend in CHF.

### 3.2 Ehrliche Positionierung

**Bereits Weltklasse (rückblickend):** Swissquote/IBKR-Parser, Quellensteuer-Auflösung, `count_as_cash`; OLS-Faktor-Decomposition, doppelter Dietz/XIRR-Standard, korrekter Drawdown; 14 Smart-Money-Quellen (13F/COT/SER-Insider); 176-Endpoint-API, 20+ Crons, 3-Kanal-Alerts. → Tiefer als Ghostfolio / Portfolio Performance / Wealthfolio, in Einzeldisziplinen auf Koyfin-/Bloomberg-Niveau.

**Die 4 systematischen Lücken** (siehe Executive Summary): Vorausschau, Handlungsbrücke, echte Durchsicht (UCITS-Look-Through), CH-Steuer/Vorsorge.

### 3.3 Wettbewerbslandschaft (6 Cluster)

| Cluster | Beispiele | Was sie können / wo OpenFolio lernt |
|---|---|---|
| OSS / Self-hosted | Ghostfolio, Portfolio Performance, Maybe, Wealthfolio | Direkte Vorbilder; **kein** OSS-Tool macht echtes ETF-Look-Through — eine offene Flanke, die OpenFolio besetzen kann |
| Retail-Tracker (DACH/EU) | Parqet, getquin, Sharesight, Snowball, Delta | Dividenden-Tracking, schöne Steuerreports, Social — aber **ignorieren die Schweiz strukturell** |
| Research/Analytik | Koyfin, Stock Rover, Simply Wall St, Finchat | Fundamentaldaten-Tiefe, Screener, Visualisierung — Vorbild für OpenFolios Research-Layer |
| Wealth-Aggregation | Kubera, Empower, Monarch | Net Worth, Account-Aggregation, Ruhestandsplanung — Vorbild für das Vermögens-Gesamtbild |
| Pro/Quant | Bloomberg, TradingView, Portfolio Visualizer, Composer | Backtesting, Faktor-Analyse, regelbasierte Strategien — Kernrelevanz für den systematischen Winkel |
| Schweiz-Kontext | VIAC, finpension, True Wealth, Swissquote | Geschlossene Produkt-Silos ohne Research/Signale/Self-Hosting — der Markt, den niemand offen bedient |

---

## 4. Teil C — Strategische Roadmap (Themen & Wetten)

### 4.1 Quick Wins (hoher Wert, kleiner Aufwand)
- Forward-Return-Stub scharf schalten *(✅ in dieser Session erledigt)*
- Deterministischer Signal-/Score-Erklärer (kein LLM, halluzinations-sicher)
- Estimate-Revision-Divergenz-Badge (display-only)
- DA-1 + Verrechnungssteuer-Tracker (US+DE+FR, CHF-messbar)
- Tagesbewegungs-Attribution *(im Red-Team später verworfen — siehe §6)*
- Portfolio-X-Ray Phase 0 (Exposure-Rollup + Overlap-Matrix)
- Netto-Vermögen inkl. Hypothek als Verbindlichkeit

### 4.2 Differenzierer (wo OpenFolio einzigartig führen kann)
- **Konsolidierter Steuerauszug + DA-1-Vorbefüllung über MEHRERE Broker** — kein Tool am Markt konsolidiert IBKR+Swissquote+VIAC.
- **ETF-Look-Through mit UCITS-Coverage** — löst die Lücke, die US-Tools beim CHF-Depot offenlassen.
- **Signal-Forward-Return-Ledger + Preis-Backtest** — macht „regelbasiert" beweisbar.
- **Vorsorge-/3a-Cockpit + CHF-FIRE-Monte-Carlo** (Säulen-/AHV-aware).
- **Signal-zu-Aktion-Loop + Trade-Journal** — der identitätsstiftende „Operating-System"-Wedge.
- **Gewerbsmässiger-Wertschriftenhändler-Frühwarnung** (ESTV KS 36) — schützt den steuerfreien CH-Kapitalgewinn.
- **Self-hosted, daten-souveräne AI** (BYO-Key/Ollama + Egress-Guard) — „AI ohne Datenabgabe".
- **Konfluenz-/Divergenz-Engine** über die 14 Smart-Money-Quellen.

### 4.3 Moonshots (ambitionierte, gegatete Wetten)
- 3a-Staffelauszug-Optimizer mit kantonalen Tarifen
- CHF-FIRE-/Entnahme-Vollmodell (AHV/PK/Steuern/Life-Events)
- Deklarative Regel-Engine als gemeinsames Rückgrat (Alerts/Backtest/Rebalance/Journal)
- Offizieller Read-only-MCP-Server für BYO-LLM-Research-Copilot
- Plugin-/Data-Source-SDK (out-of-process, Score-Write verboten bis Backtest)

---

## 5. Teil D — Geerdete Execution-Roadmap

Die folgende Sequenz ist **gegen den echten Code geerdet und adversarial geprüft** — sie weicht bewusst von der idealisierten Roadmap ab (siehe Phasen-Korrekturen §6).

### 5.1 Erster Sprint (4 Punkte, alle ungeblockt)

| Punkt | Aufwand | Kern |
|---|---|---|
| **Forward-Return-Harness** ✅ | M | Keystone-Unlock; *in dieser Session gebaut* |
| **Dividenden Yield-on-Cost (rückwärts)** | S | Lean-Split aus dem Forecast: YoC = bestätigte Dividende / `cost_basis_chf`, keine 429-Gefahr, kein Raten |
| **Netto-Vermögen: Hypothek-/Immobilien-Zeile** | S | ~90 % da (`PerformanceCard.jsx`); Tag-1-Wert; Snapshot-Tabelle/History abgespalten |
| **Signal-Erklärer Teil 1 „Was fehlt bis STARK"** | M | Gap-Distanz je Kriterium; OHNE Counterfactual (siehe §6); neutrale Sprache |

### 5.2 Wellen (harte Abhängigkeiten)

- **Welle 1 — Vertrauens-Fundament:** kanonische `liquid_investable`-Nenner-Definition (fixt eine Live-Bug, siehe §5.3) · DA-1-Tracker (baut die Steuer-Infra) · UCITS-Look-Through **Spike** (CSV-URLs verifizieren) · Split-Detection mit Golden-Master-Guard.
- **Welle 2 — auf Spike/Infra aufbauend:** UCITS-Look-Through **Bau** · IBKR Flex Autosync (lean, Pending-Review, kein Auto-Confirm) · Konfluenz-Engine (metadata-only) · Trade-Journal (Capture) · Estimate-Badge.
- **Welle 3 — gated:** Portfolio-X-Ray (erst nach UCITS) · Wertschriften-/DA-1-Arbeitsblatt · Konfluenz-Gewichts-Integration (hinter Forward-Return-Power).
- **Welle 4 — später (Datenreife 2027 / Nische):** Dividenden-Forecast · Net-Worth-History-Seite · 3a-Cockpit · PIT-Datalake.

### 5.3 Live-Bug nebenbei gefunden

**Drei widersprüchliche „investierbar"-Nenner** im Code: `alert_service.py:492` (stock+ETF) vs. `bucket_performance_service.py:284` (inkl. pension — **widerspricht Invariante #2**). Der Drift-Alert rechnet auf anderer Basis als die Bucket-Performance. → Vor einem Rebalancing-Cockpit muss eine **kanonische `liquid_investable`-Definition** her (fixt zugleich die Live-Trust-Bug).

---

## 6. Teil E — Was das Red-Team verworfen/zurückgestuft hat

Diese Cuts sind der eigentliche Wert der Erdung — sie verhindern teure Fehlinvestitionen:

| Punkt | Verdikt | Begründung |
|---|---|---|
| Tagesbewegungs-Attribution (Einzeltag) | **CUT** | Für CHF-Anleger irreführend — USD/CHF-FX landet im „idiosynkratischen" Topf und wird als Stock-Picking verkauft; die `factor-decomposition`-Seite macht das schon sauber |
| Counterfactual-Score-Erklärer | **CUT** | Korrektheits-Falle (`Score+1`-Arithmetik widerspricht der echten Engine) + geringe Aktionierbarkeit |
| Adhärenz-Scoring | **CUT** | Selbstreferenziell (immer 100 %), bei n=3–5 bedeutungslos, kollidiert mit der Anti-Imperativ-Doktrin |
| eCH-0196-Naming/Barcode | **CUT** | Echte eSteuerauszüge sind gratis & autoritativ; ein Excel ist kein eCH-0196 = Overclaim + Haftung. Kern bleibt als „Wertschriften-/DA-1-Arbeitsblatt" |
| PIT-Datalake (Step 5) | **CUT** | Scope-Creep; zweiter S&P-1500-Sweep kollidiert mit dem EPS-Scanner. Der wertvolle Kern *ist* der Forward-Return-Harness |
| X-Ray Phase 0 | **→ Welle 3** | FMP ist US-only → für den UCITS-Halter leer, bis Look-Through steht |
| Dividenden-Forecast / 3a-Cockpit / Net-Worth-History | **→ Welle 4** | Raten ohne Datenreife / Nische / kein Day-1-Wert |

---

## 7. Teil F — In dieser Session umgesetzt

> **Hinweis:** Die *vollständige, laufend gepflegte* Liste aller umgesetzten Commits steht oben im Abschnitt **„Umsetzungs-Stand (laufend aktualisiert)"**. Die folgenden Unterabschnitte sind die ausführliche Beschreibung der ersten drei Bausteine.

### 7.1 CLAUDE.md: „heilige Regeln" → „Korrektheits-Invarianten"
Der Block „HEILIGE Regeln (NIEMALS brechen)" wurde durch zwei kalibrierte Abschnitte ersetzt:
- **Korrektheits-Invarianten** (Renditedefinitionen, Assetklassen-Ausschluss, Signal-Definitionen) — Änderung erlaubt, wenn (a) Definition/historische Vergleichbarkeit erhalten bleibt, (b) ein Test den Bruch fängt, (c) bei Bedeutungsänderung Rückfrage. Signal-Parameter explizit als *tunebar mit Forward-Return-Backtest* markiert.
- **Konventionen** (httpx/aiosmtplib/yfinance-Wrapper/neutrale Sprache) — normale Standards.

*Warum:* Angst-Framing behinderte legitime Verbesserungen und vermischte echte Invarianten mit banalen Konventionen. Schutz gehört in Tests, nicht in Prosa-Verbote. (Commit `c5d004b`)

### 7.2 Golden-Master-Test-Suite (56 Fälle)
`backend/tests/test_golden_master_calculations.py` — nagelt die Definitionen mit exakt hergeleiteten Soll-Werten fest, sodass jede stille Definitions-Drift sofort rot wird:

| Invariante | Abdeckung |
|---|---|
| XIRR (MWR) | 365-Basis exakt, Dezimalbruch, Vorzeichen/Merge, Same-Day-Guard, DB-Pfad |
| Modified Dietz | Tages-Gewichtung, Verkettung, Snapshot-CF-Override, Denominator-Fallback, Randgewichte |
| cost_basis | Weighted-Average, Gebühren, Oversell-Guard, fx, delivery_in/out |
| MRS | EMA(13, adjust=False, α=1/7), W-FRI-Resampling, Ratio-Richtung |
| Assetklassen-Ausschluss | PE→0, cash/pension→Saldo, count_as_cash kein Doppelzählen |

**Latenter Befund:** `_calc_position_value_chf` hat keinen expliziten `real_estate`-Guard — Immobilien fallen nur über die `shares=0`-Konvention aus dem liquiden Wert. Der Test pinnt bewusst den Ist-Zustand; ein expliziter Guard ist offen. (Commit `c5d004b`)

### 7.3 Forward-Return-Backtest-Harness scharf geschaltet
`backend/services/screening/backtest_harness.py` (Commit `f5dcb7c`):
- `fetch_forward_return`-Stub (`NotImplementedError`) ersetzt durch reine, testbare `compute_forward_return` (unvollständiges Fenster → `None`, `price_usd`-Entry-Fallback, `exit/entry−1`).
- Gebündelter `fetch_price_histories` (Batches à 50, Semaphore 3, `yf_download` in `to_thread`) statt Per-Ticker-yfinance-Massaker.
- 11 Unit-Tests; CSV mit Sample-Grösse pro Fenster + Survivorship-Caveat.

**Lehre:** Ein fehlender `yf_download`-Import fiel erst im **echten Lauf** auf — die Pure-Function-Unit-Tests fingen ihn nicht. Bei yfinance-Pfaden immer einen echten Lauf machen.

**Reales Ergebnis (Dev, 16'811 Snapshots seit ~3. April; Coverage 85 % = 1205/1420 Ticker nach Retry-Härtung):**

| Score-Bucket | n_30d | Excess 30d | Hit 30d | n_60d | Excess 60d | Hit 60d |
|---|---|---|---|---|---|---|
| 0 (kein/schwaches Signal) | 1466 | **+1.83 %** | 35.5 % | 940 | +1.12 % | 28.7 % |
| 1–2 | 2733 | −2.00 % | 40.3 % | 1392 | −5.83 % | 31.0 % |
| 3–4 | 1048 | −2.06 % | 37.4 % | 523 | −3.52 % | 29.3 % |
| 5–6 | 81 | **−6.12 %** | 34.6 % | 35 | −12.86 % | 22.9 % |
| 7+ | 0 | – | – | – | – | – |

90d-Spalte leer — korrekt (Historie < 90 Tage; validiert die „unvollständiges Fenster → None"-Logik live). Die Fetch-Härtung (Retry/Backoff für fehlende Ticker, 3 Runden mit 5/10/20 s) hob die Coverage von **37 % auf 85 %**; die verbleibenden 215 Ticker sind vermutlich echt nicht verfügbar (delistet/Symbol-Tail).

**Interpretation (ehrlich):** Das aktuelle Composite-Signal ist über dieses Fenster **anti-prädiktiv** — Bucket 0 (kein Signal) schlägt SPY (+1.8 % auf 30d), höhere Buckets verlieren, am stärksten 5–6 (−6.1 % auf 30d, −12.9 % auf 60d). Mit 85 % Coverage und grossen n (1466/2733/1048) ist das **kein Rauschen mehr**, sondern ein ernstzunehmender Befund: die aktuellen Gewichte könnten in diesem Regime falsch oder kontrarisch sein. ABER weiterhin: **ein** Marktregime (Apr–Jun 2026), kein 90d, und Survivorship (die 215 fehlenden = vermutlich delistete = oft die schlechtesten Performer → das echte Bild könnte noch schlechter sein). → **Keine Live-Gewichts-Änderung** (Invariante #3). Nächster analytischer Schritt: **Per-Signal-Decomposition** (welches Einzelsignal treibt das Negative — insider_cluster? buyback? superinvestor?) und Re-Run über mehrere Regimes / längere Historie.

---

## 8. Teil G — Querschnitts-Risiko-Register

| Risiko | Betrifft | Mitigation |
|---|---|---|
| **PIT/Survivorship** | Backtest, Steuer-Jahresend-Rekonstruktion | yfinance droppt delistete Ticker → Verzerrung; Caveat + n + KI im Output, Sichten per 31.12. aus Transaktionen rekonstruieren |
| **yfinance Burst-429** | jeder Universe-Sweep | Semaphore ≤3 zwingend, Retry/Backoff, Daten aus EINEM Worker-Lauf wiederverwenden, keine parallelen Sweeps |
| **Steuer-Haftung / Naming-Overclaim** | DA-1, Steuerauszug, 3a | kein „eCH-0196"-Naming ohne Barcode/ICTax; CH-Resident-Guard; „anrechenbar" ≠ „rückforderbar" |
| **Symbol-Tail (.SW/.L, Pence)** | YoC, Split, Look-Through, Autosync | Währung via `yf_quote_currency`, nie aus Suffix raten; kein Auto-Commit ohne Review |
| **Multi-User-Scoping / Key-Sharing** | `_get_any_user_fmp_key`, Worker, Tokens | pro-User-Key-Attribution; alle Queries user-scoped; rate-limitierte APIs sequenziell |
| **Trust-of-Numbers / Definitions-Drift** | Rebalancing-Nenner, Auto-Confirm, Split→cost_basis | kanonische Nenner-Definition vor Bau; Default Pending-Review; Golden-Master vor Merge |
| **Unvalidierte Gewichte vor Backtest-Gate** | Estimate-Badge, Konfluenz-Gewichte | „(Probe)"-Labels, metadata-only, keine Live-Gewichte ohne Backtest (Invariante #3) |

---

## 9. Empfohlene nächste Schritte

> **Stand 28.06.2026:** Der ursprüngliche Erste Sprint (§5.1) + Welle 1/2-Kern + die internen Top-Hebel (§2.2: /metrics-Wall, Audit-Log-UI, daily_refresh-Bug) sind **erledigt und in v0.49.0 deployt.** Die aktuelle, priorisierte Vorwärts-Roadmap steht oben unter **„Nach v0.49.0 — die nächsten Hebel"**. Kurzfassung der Top-3:

1. **Daten-Fundament** — Ertrags-/Dividenden-Erfassung lückenlos machen (Engpass, der CH-Steuer #4 + den Forecast unblockt; Probe: Steuerjahr 2025 = 0 gebuchte Erträge).
2. **v0.49-Features beobachten & iterieren** — Trade-Journal/Forecast unter realer Nutzung; gezielte Politur (Forecast-Trigger, FIRE-Persistenz).
3. **Smart-Money Per-Signal-Decomposition** — den anti-prädiktiven Composite-Befund auf das treibende Einzelsignal zurückführen, über mehrere Regimes; erst dann Gewichte (Invariante #3).

---

## Anhang — Artefakte dieser Session

**Commits (auf `main`):**
- `c5d004b` — docs(invarianten): heilige Regeln → Korrektheits-Invarianten + Golden-Master
- `f5dcb7c` — feat(screening): Forward-Return-Harness scharf geschaltet

**Geänderte/neue Dateien:**
- `CLAUDE.md` (Reframe)
- `backend/tests/test_golden_master_calculations.py` (neu, 56 Fälle)
- `backend/services/screening/backtest_harness.py` (umgebaut + Fetch-Härtung)
- `backend/tests/test_backtest_forward_return.py` (neu, 11 Fälle)

**Test-Stand (Kickoff 27.06.):** 67/67 grün (56 Golden-Master + 11 Forward-Return). **Stand 28.06. (v0.49.0):** volle Suite **1426 passed / 3 skipped** (Audit-verifiziert). *(Dieser Anhang listet nur die Kickoff-Artefakte; die vollständige Commit-/Feature-Historie steht im „Umsetzungs-Stand" oben.)*

*Erstellt 27.06.2026 als Diagnose-/Strategie-Report, **laufend nachgeführt bis 28.06.2026 (Release v0.49.0)**. Alle Zahlen und Befunde sind codebasis-geerdet und adversarial verifiziert; das Backtest-Ergebnis ist explizit als unterpowert markiert und nicht handlungsleitend.*
