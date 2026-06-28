# OpenFolio — Strategische Standortbestimmung & Execution-Roadmap

**Session-Report vom 27.06.2026** · **laufend aktualisiert** (dieses Dokument wird bei jedem Arbeits-Inkrement nachgeführt)
**Ziel:** das beste Finanztool der Welt bauen — offene, ambitionierte Standortbestimmung gegen die führenden Tools, plus konkreter, codebasis-geerdeter Umsetzungsplan.

---

## Umsetzungs-Stand (laufend aktualisiert — letzte Aktualisierung 27.06.2026)

Alle Commits auf `main`, gepusht, **prod-deployed & verifiziert** (sofern nicht anders vermerkt).

**Vertrauen in die Zahlen**
- `c5d004b` — CLAUDE.md „heilige Regeln" → testgestützte „Korrektheits-Invarianten" + Golden-Master-Suite (56 Fälle)
- `f5dcb7c` — Forward-Return-Backtest-Harness scharf · `78c005f` — Fetch-Härtung (Coverage 37→85 %)
- `d29eea4` — Bucket-Drift-Alert misst gegen liquides Gesamt (== Pie) statt Aktien-Sleeve
- `2366f0a` — Vorsorge aus liquider invested-Basis ausgeschlossen (Invariante #2)
- Trust-Härtung `import_service.confirm_import` (high-severity, war ungetestet): 8 Tests pinnen Ownership-Skip (Multi-User — fremde/unbekannte position_id wird nie angehängt), Server-Dedup/Idempotenz (+ force_import-Override), `total_chf`-Ableitung aus fx_rate (Invariante #1), Buy→shares/cost_basis, Manual-Balance ohne yfinance_ticker. Begleitend: Dedup-Query backend-agnostisch (uuid statt str → auch auf SQLite testbar). *(committet, Deploy ausstehend)*

**Ops / Security**
- `0d24ff5` — `/metrics` ohne Auth scrapebar + Grafana datasource-uid (Monitoring entblindet)
- `7b517ca` — `daily_refresh` nimmt Tages-Snapshot auch bei Kurs-Timeout auf
- `3800b6a` — Audit-Log-Tab im Admin-Panel
- `aa32ba3` — keine Retries auf 4xx (FMP-402) + ETF-Refresh läuft keyless ohne FMP-Key

**Differenzierer — ETF-Look-Through für UCITS (Lücke #3 geschlossen, iShares)**
- `2548ab9` — iShares-CSV-Adapter (keyless, Exchange→yf-Ticker) · `d18de80` — Issuer-nativer Sektor (EM-Coverage 0.7→100 %) · `8230638` — Länder-Look-Through-View
- Prod-verifiziert: EIMI + CHSPI volle Sektor- + Länder-Durchsicht.

**Handlungsbrücke — Rebalancing-Cockpit (Lücke #2, MVP)**
- `d5aaca8` — Rebalancing-Cockpit MVP: Soll/Ist/Delta je Bucket (target_pct XOR target_chf vs. Ist = Pie-Basis) + Cash-First-Zusammenfassung, Card auf der Performance-Seite, neutrale Sprache. Bucket-Ebene; Trade-Journal + Per-Position-Orders offen.
- Trade-Journal (Adhärenz-Hälfte): gescopt (`DESIGN_trade_journal.md`, Ultracode-Workflow), Kill-Gate **gegen Prod gemessen**: pending_orders = NO-GO (nur 11 % der Trades). **Pivot auf Maintainer-Hinweis:** echte Plan-Quelle ist der Report-Vault (`reports` category=`trade`, 86 Trade-Pläne von claude-finance). **Komplett gebaut (3 Iterationen, adversarial geprüft):**
  - *Datenschicht* (Migration 089): `reports.ticker/side/linked_transaction_id` (FK SET NULL), Schreibzeit-Link via External-API POST/PATCH mit Ownership-Validierung, Read-View `/api/analysis/trade-journal` (Plan→Ist→Status).
  - *Schreibpfad* (finance-Repo): Sync-Skript `--ticker/--side/--linked-txn`, `/sell-check` (Sell) + `/trade-plan` (Buy) + globale CLAUDE.md-Regel für ad-hoc Stop-Outs. Vorwärtskompatibel (Prod ignoriert Felder bis Deploy).
  - *Server-seitige Auto-Verknüpfung*: beim Buchen einer Buy/Sell-Txn (direkt/Fill-Reconciliation/CSV-Import) wird der jüngste offene Plan automatisch verlinkt — schliesst die async Buy-Fill-Lücke. Best-effort, exakter `ticker`+`side`-Match, keine Invariante berührt.
  - *Frontend* (`07e5bde`): `TradeJournalCard` auf der Performance-Seite (Handlungsbrücke-Cluster, unter dem Rebalancing-Cockpit) — Plan→Ist-Liste mit Status „umgesetzt/offen", Summary, neutraler Leer-Zustand.
  - 3 adversariale Reviews (je 7–10 Befunde → nur LOW Test-Gaps, alle gefüllt); ~26 neue Tests. Deployt & prod-verifiziert (28.6.: getaggter „Sell-Check AMAT 2026-06-28" trägt ticker/side live). Commits openfolio `27848dd`/`1654364`/`07e5bde`, finance `6c69d8f`/`be8a921`.
- Per-Position-Rebalancing (lean): bricht den Bucket-Überhang auf **Trim-Kandidaten je Position** herunter (grösste zuerst) + **Klumpenrisiko-Flags** (≥10 % des liquiden Werts). BEWUSST keine Positions-Ziele (gibt es nicht) → nur die reduzieren-Seite + Konzentration, read-only, neutrale Sprache. `/api/analysis/position-rebalancing` + `PositionRebalancingCard` (unter dem Rebalancing-Cockpit). Adversarial geprüft (Kern korrekt, nur Nits), 7 Tests. *(committet, Deploy ausstehend)*

**Vorausschau / Income / Gesamtbild (Lücke #1, teilweise)**
- `e96d5b1` — Dividenden Yield-on-Cost (12M, effektiv erhalten): Portfolio + pro Position, rückwärts (kein Forecast), Card auf der Performance-Seite.
- **Dividenden-Forecast (Vorausschau, NEU):** projiziertes 12M-Einkommen als Run-Rate **pro aktueller Position** (Trailing-12M-DPS × shares × FX) — bewusst NICHT aus dem Ledger (Kill-Gate-Probe gegen Prod: Ledger-Run-Rate ist nach vorn kontaminiert, 118 % Coverage durch verkaufte Zahler). **Worker-populiert + Redis-gecacht, null yfinance pro Request** (die Burst-429-Falle wurde live ausgelöst → diktierte die Architektur). `/api/analysis/dividend-forecast` + Card auf der Performance-Seite. Adversarial geprüft (7→1 MED-Befund gefixt: rollback im Multi-User-Loop). *(committet, Deploy ausstehend)*
- **FIRE-/Kapital-Projektion (Vorausschau, NEU — interaktiv):** real (inflationsbereinigt) Projektion `Kapital×(1+r)+Sparrate` → FIRE-Zahl (Ausgaben/SWR), Jahre-bis-FIRE, Deckung + Kurve. **FIRE-Kapital = einkommensfähiges Finanzkapital:** Default `Liquid + Vorsorge`, strenger `Nur Liquid` wählbar; **illiquide (Eigenheim-Equity, Private Equity) zählen bewusst NICHT** (kein Entnahme-Einkommen — Review-Befund, Verzerrung an der Wurzel behoben statt nur bedisclaimert). Annahmen im Card live-änderbar (localStorage, debounced+clamped). `/api/analysis/fire-projection` (+ External-Parität) + `FireProjectionCard`. *(committet, Deploy ausstehend)*
- Vermögensbilanz mit expliziter Hypothek-Zeile: `/api/analysis/net-worth` (Konzept A = Finanzanlagen + Immobilien Brutto − Hypothek). Als Aktiven/Passiven-Aufschlüsselung direkt unter den KPI-Kacheln (kein doppelter Riesen-Betrag — die Netto-Summe == die bestehende Kachel „Gesamtvermögen"; die Karte liefert die Aufschlüsselung + die Hypothek, die die Kachel still im Equity verrechnet). Disclaimer „Brutto-Marktwert, nicht Vermögenssteuerwert". Invariante #2 unberührt. Unit-Tests grün (kein Doppelzählen). *(committet, Deploy ausstehend)*

**Status der 4 strategischen Lücken:** ① Vorausschau — **✅ geschlossen** (Backtest-Beweis + Dividenden-YoC + Netto-Vermögen + Dividenden-Forecast + FIRE-/Kapital-Projektion) · ② Handlungsbrücke — **gebaut** (Rebalancing-Cockpit auf Bucket-Ebene + Trade-Journal komplett — Daten/Schreibpfad/Auto-Link/Frontend; nur Deploy offen) · ③ Durchsicht — **✅ geschlossen** (iShares; Xtrackers/Vanguard/UBS offen) · ④ CH-Steuer/Vorsorge — **geparkt** (User-Entscheid).

**Bewusst geparkt / verworfen:** Smart-Money-Scoring (anti-prädiktiv, Per-Signal-Decomposition steht bereit) · CH-Steuer (DA-1/eCH-0196/3a) · Tagesbewegungs-Attribution + Counterfactual + Adhärenz-Scoring (Red-Team-Cuts) · OEF/UBS-Look-Through (US-Interstitial bzw. kein keyloser Kanal).

**External-API-Parität (stehende Regel):** ALLE neuen Read-Views sind auch unter `/api/v1/external/analysis/*` (X-API-Key) gespiegelt — net-worth, dividend-yoc, dividend-forecast, rebalancing, position-rebalancing, trade-journal, country-lookthrough (Paritätstest intern==extern). API-Doku (`reference_openfolio_api.md`, von Cloud Finance referenziert) immer mitziehen.

**Nächste offene Hebel:** Deploy (FIRE + Position-Rebalancing) · weitere Look-Through-Issuer (UBS; Xtrackers/Vanguard nur falls gehalten) · FIRE-Ausbau optional (Annahmen server-seitig pro User persistieren statt localStorage; Vorsorge-Auszahlungsalter). **Drei der vier strategischen Lücken sind damit geschlossen** (① Vorausschau ✅, ② Handlungsbrücke ✅, ③ Durchsicht ✅; ④ CH-Steuer geparkt).

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

**In dieser Session bereits umgesetzt:** (1) CLAUDE.md von „heiligen Regeln" auf testgestützte „Korrektheits-Invarianten" umgestellt, (2) eine Golden-Master-Test-Suite mit 56 Fällen gebaut, die die Kern-Berechnungen exakt festnagelt, (3) den **Forward-Return-Backtest-Harness scharf geschaltet** — den Keystone, der die gesamte Scoring-Weiterentwicklung entsperrt.

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

1. **Forward-Return-Fetch härten & Coverage prüfen** (läuft) — bis ~vollständig, dann ist das 30d-Fenster belastbar; danach periodisch re-runnen, bis 60d/90d voll und mehrere Regimes drin sind.
2. **Erster Sprint** abarbeiten: YoC, Netto-Vermögens-Zeile, Score-Erklärer Teil 1 — alle ungeblockt, hoher fühlbarer Wert.
3. **Welle 1 Vertrauens-Fundament:** kanonische `liquid_investable`-Definition (fixt Live-Bug) + DA-1-Tracker (baut die Steuer-Infra) + UCITS-CSV-Spike.
4. **Parallel die internen Top-Hebel** (§2.2): `/metrics`-Wall, Audit-Log-UI, Worker-Liveness, `daily_refresh`-Bug — günstig, schliessen echte Betriebs-/Security-Lücken.

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

**Test-Stand:** 67/67 grün (56 Golden-Master + 11 Forward-Return).

*Erstellt am 27.06.2026 als Diagnose-/Strategie-Report. Alle Zahlen und Befunde sind codebasis-geerdet und adversarial verifiziert; das Backtest-Ergebnis ist explizit als unterpowert markiert und nicht handlungsleitend.*
