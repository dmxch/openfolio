<div align="center">

# OpenFolio

**Daten-souveränes Portfolio-Management fürs systematische, regelbasierte Investieren — self-hosted, in CHF.**

Dein Portfolio, deine Daten, deine Regeln — auf deinem eigenen Server.

[Funktionsumfang](#funktionsumfang) · [Was OpenFolio einzigartig macht](#was-openfolio-einzigartig-macht) · [Sicherheit & Datenschutz](#sicherheit--datenschutz) · [Schnellstart](#schnellstart) · [Tech Stack](#tech-stack)

`Open Source` · `Self-Hosted` · `Multi-User` · `Schweizer Fokus` · `MIT-Lizenz`

</div>

---

## Was ist OpenFolio?

OpenFolio ist ein **selbst-gehosteter, daten-souveräner Portfolio-Manager** für den technisch versierten
Anleger, der sein Vermögen **broker-übergreifend in CHF** führen will — ohne es einem SaaS-Anbieter
anzuvertrauen. Eine Instanz (Docker Compose) bündelt acht Anlageklassen, institutsnahe und
testgepinnte Performance-Mathematik, echtes ETF-Look-Through, 14 Smart-Money-Datenquellen, eine
Handlungsbrücke vom Befund zur dokumentierten Aktion und eine vollständige programmierbare API —
alles auf der eigenen Infrastruktur, multi-user-fähig und mit feldweise verschlüsselten Personendaten.

> **Ehrlich eingeordnet:** OpenFolio ist ein *Werkzeug*, kein Robo-Advisor. Die regelbasierten Signale
> werden **gemessen, nicht versprochen** — ein eingebauter Forward-Return-Backtest zeigt das aktuelle
> Composite-Signal in den bisher getesteten Daten als nicht prädiktiv, weshalb bewusst keine
> Signal-Gewichte ungeprüft live gehen. Wer Datenhoheit, Schweizer Korrektheit und nachvollziehbar
> gerechnete Analytik will, ist hier richtig; wer fertige Kauf-/Verkaufssignale erwartet, nicht.

---

## Was OpenFolio einzigartig macht

| | |
|---|---|
| 🔍 **Echtes UCITS-ETF-Look-Through** | Schaut durch die ETF-Hülle bis auf den Einzeltitel — **Sektor- *und* Länder-Durchsicht** (z.B. EIMI: Taiwan/Korea/China sichtbar statt einer einzigen Zeile). Issuer-nativer Holding-Sektor hebt die Coverage von 0,7 % auf 100 %. Kein anderes OSS-Tool macht das; US-lastige Tools sind ausgerechnet fürs UCITS-Depot blind. |
| 🔒 **Self-hosted & daten-souverän** | Läuft komplett auf deiner Maschine (Docker Compose). Das Portfolio verlässt nie die eigene Infrastruktur — alle Ports sind standardmässig an `localhost` gebunden, sogar die Schriften sind self-hosted (keine Google-Fonts-CDN). |
| 🇨🇭 **Schweizer Buchhaltungs-Korrektheit** | CHF-First, Swissquote-/IBKR-Parser, Quellensteuer-Auflösung pro Dividende, korrekte FX **zum Kaufzeitpunkt**, T-Bill-/Geldmarkt-ETFs als Cash, SARON-Hypotheken, GBX/Pence sauber behandelt (nie aus dem Suffix geraten). Internationale Tracker ignorieren die Schweiz strukturell. |
| 📐 **Test-gepinnte Performance-Mathematik** | XIRR (geldgewichtet) + Modified Dietz als doppelter Standard, OLS-Faktor-Decomposition, korrekter Drawdown auf rekonstruierter Indexreihe. Die Rendite-Definitionen sind durch eine **56-Fälle-Golden-Master-Suite** gegen stillen Definitions-Drift abgesichert — eine Vertrauens-Garantie, die selbst Bezahl-Tools selten bieten. |
| 📊 **Smart-Money aus einer Hand** | 14 institutionelle & alternative Datenquellen (13F-Superinvestoren, CFTC COT, SEC-Insider-Cluster, Congressional, Buyback u.a.) zu einer durchsuchbaren Ansicht verdichtet — mit ehrlichem, backtest-gegatetem Scoring statt Hype. |
| 🤖 **Volle programmierbare API** | Jede Sicht ist auch unter `/api/v1/external` gespiegelt (189 Routen, X-API-Key, read/write-Scopes). So kann ein eigener **LLM-Research-Copilot** das Portfolio lesen *und* pflegen — ohne es einem SaaS-Mittelsmann zu geben. |

### Wie sich OpenFolio einordnet

- **vs. Cloud-SaaS-Tracker** (Parqet, getquin, Sharesight, Snowball): die ignorieren die Schweiz strukturell und halten deine Daten in ihrer Cloud — OpenFolio läuft auf deiner Infrastruktur, in CHF.
- **vs. OSS-Self-Hosted-Peers** (Ghostfolio, Portfolio Performance, Maybe, Wealthfolio): vergleichbare Buchhaltung, aber keiner macht echtes ETF-Look-Through oder bündelt 14 Smart-Money-Quellen + Faktor-Decomposition + Forward-Return-Backtest.
- **vs. CH-Anbieter** (VIAC, finpension, True Wealth, Swissquote): geschlossene Produkt-Silos für die eigenen Vehikel — kein broker-übergreifendes Gesamtbild, keine Research, kein Self-Hosting.
- **vs. Research-/Pro-Tools** (Koyfin, Bloomberg, TradingView, Portfolio Visualizer): tief, aber teuer, cloud-gebunden und nicht auf dein eigenes CHF-Portfolio zugeschnitten.

Die angepeilte Nische ist die Schnittmenge: **regelbasiert + self-hosted + Schweizer Korrektheit + offene API**.

---

## Funktionsumfang

### 💼 Portfolio-Kern & acht Anlageklassen

Alle acht Klassen liegen im **selben Datenmodell** und derselben Allokations-/Netto-Vermögens-Sicht:

- **Aktien & ETFs** — Live-Kurs, Performance, Stop-Loss, MRS, Setup-Score, Δ-Stop
- **Krypto** — CHF-Bewertung inkl. 24 h-Änderung via CoinGecko
- **Edelmetalle** — physisches Inventar pro Barren/Münze (Metall, Hersteller, Gewicht, Feinheit, Seriennummer, Lagerort) mit Spot-Bewertung (Gold.org / Metall-Futures + FX) und Lager-/Versicherungskosten-Ledger
- **Cash & Konti** — Bank, IBAN (verschlüsselt + maskiert), Währung, Saldo in Kontowährung + CHF
- **Vorsorge** — Säule 3a / PK mit Anbieter-Tracking (VIAC / frankly / finpension)
- **Immobilien** — Liegenschaften mit mehreren Hypotheken (Fest / **SARON** mit `max(Marge, Marge + SARON)` / variabel), wiederkehrende Ausgaben, Mieteinnahmen, Restschuld als Verbindlichkeit
- **Private Equity / Direktbeteiligungen** — Bewertung mit Illiquiditäts-Discount (Default 30 %), PE-Dividenden mit Verrechnungssteuer (Default 35 %), verschlüsselte Firmen-/UID-/Register-Felder

**Buckets (Core / Satellite):** benannte Gruppen mit Farbe, Benchmark, Ziel (% *oder* CHF) und Risiko-Regeln;
vier System-Buckets (Liquid / Immobilien / PE / Vorsorge) plus **Strategie-Templates** (Core/Satellite,
FIRE/Spielgeld, Zeithorizont, Risiko-Tiers) in einem Klick. Eine Position darf gleichzeitig in mehreren
Buckets liegen; jeder Bucket-Wechsel wird verlustfrei protokolliert (Realized-Gains bleiben korrekt zugeordnet).

**Stop-Loss-Verwaltung:** vier Methoden (Trailing-%, Higher-Low, MA-basiert, strukturell), Risiko-Tier-Logik
(Active-Risk 15 %/14 Tage Pflicht, Buy-and-Hold 30 %/90 Tage), Trailing-Stop-Guard (kein Absenken ohne Nachkauf).

### 📈 Performance & Risiko-Analytik

Eine eigene **Performance-Seite** mit fünf Sub-Tabs (Übersicht · Rendite · Risiko · Allokation · Cashflow) bündelt:

- **Gesamtrendite** — unrealisiert + realisiert + Dividenden + Ausschüttungen + Zinsen − Gebühren, sauber ohne Doppelzählung; All-Time-% via **XIRR (MWR)**, mit YTD-Breakdown
- **Monatsrenditen-Heatmap** — **Modified Dietz** (cashflow-gewichtet) + annualisierte XIRR-Jahres-Totals + S&P-500-Benchmark-Zeile
- **Equity-Kurve** — indexierte, **cashflow-bereinigte** Tageskurve vs. wählbarem Benchmark (S&P 500 / SMI / Bucket-eigener); Ein-/Auszahlungen täuschen keinen Performance-Sprung vor
- **Risiko-Kennzahlen** — Sharpe / Sortino / Calmar / Volatilität p.a. / Information-Ratio / Rolling-Returns, konfigurierbarer Risk-Free-Rate
- **Max-Drawdown + Drawdown-Bremse** & **Underwater-Chart** (Tiefpunkt passt exakt zur ausgewiesenen Max-DD-Zahl)
- **Faktor-Decomposition (OLS)** — Alpha & Betas gegen 8 Faktoren (Markt, Momentum, Value, Quality, Size, Gold, Krypto, USD/CHF) mit t-Werten und R², NYSE-Session-aligned
- **Portfolio-Konzentration** — HHI + effektive Positionszahl + grösste Position
- **Realisierte Gewinne** pro Verkauf (P&L, Haltedauer, Bucket zum Verkaufszeitpunkt) & **Gebühren-/Steuer-Übersicht**
- **Pro-Bucket-Auswertung** — der volle Widget-Satz je Bucket (TWR vs. Benchmark über das reale Bucket-Fenster, Risiko, Faktoren, Drawdown, Monatsrenditen, HHI …)

> Methodik bewusst getrennt: **XIRR/MWR** für Headline-Renditen, **TWR** als Zähler der Risiko-Ratios,
> **Modified Dietz** für Monatsrenditen — jede in den Docstrings begründet.

### 🔭 Vorausschau, Einkommen & Gesamtbild

- **FIRE-/Kapital-Projektion** — real (inflationsbereinigt), interaktiv: Kapital × (1 + r) + Sparrate → FIRE-Zahl (Ausgaben / Entnahmerate), Coverage-%, Jahre-bis-FIRE. Alle Annahmen sind Live-Regler, serverseitig pro User persistiert. FIRE-Kapital = nur **einkommensfähiges** Finanzkapital (illiquide Werte wie Eigenheim-Equity/PE zählen bewusst nicht mit).
- **Dividenden-Forecast** — projiziertes 12-Monats-Einkommen als Run-Rate **pro aktueller Position** (Trailing-12M-DPS × Stück × FX); bewusst nicht aus dem Ledger (der ist nach vorn kontaminiert). Worker-gecacht, null yfinance pro Request.
- **Dividenden Yield-on-Cost** — rückwärts/realisiert (netto nach Quellensteuer) pro Position und fürs Gesamtdepot.
- **Netto-Vermögen / Vermögensbilanz** — Wertschriften + Cash + Vorsorge + PE + Immobilien (brutto) − Hypothek, aufgeschlüsselt nach Aktiven/Passiven (jede Position genau einmal gezählt).

### 🧭 Handlungsbrücke — vom Befund zur dokumentierten Aktion

- **Rebalancing-Cockpit** — Soll/Ist/Delta je Bucket (CHF + Prozentpunkte), Cash-First-Zusammenfassung; Ist-Allokation deckungsgleich mit dem Allokations-Pie
- **Per-Position-Rebalancing** — konkrete Trim-Kandidaten (grösste Position zuerst) + Klumpenrisiko-Flags (≥ 10 % des liquiden Werts)
- **Trade-Journal** — Plan → Ist → Adhärenz; geplante Trades werden beim Buchen automatisch mit der echten Transaktion verknüpft (±35-Tage-Fenster, deckt asynchrone Fills/CSV-Importe ab)

Durchgängig **neutrale, nicht-imperative Sprache** („Kaufkriterien erfüllt", nie „Kaufen!").

### 🌡️ Markt- & Sektor-Analyse, Signale

- **Marktklima-Ampel** — S&P-500-Trend (50/100/150/200-DMA-Checks) mit harten Sicherheitsregeln (unter 150-DMA nie bullish; VIX-Override), kombiniert mit dem Makro-Status zu einem rot/gelb/grün-Signal
- **Makro-Crash-Indikatoren** — Shiller PE (CAPE), Buffett-Indicator, Arbeitslosen-Trend, Zinsstruktur 10Y-2Y, VIX, High-Yield-Credit-Spread — je mit Schwellen, historischem Schnitt & Quelle
- **Makro-Gate** — 7-Punkte-gewichtetes Kauf-Umfeld; Bestehensschwelle skaliert mit der Datenverfügbarkeit (fair, auch wenn eine Quelle ausfällt)
- **Sektor-Rotation** (11 SPDR-Sektoren, 1T/1W/1M/3M + Holdings-Drilldown mit Portfolio-/Watchlist-Markierung) & **Branchen-Heatmap** (~129 US-Industrien, täglich aufgezeichnet, mit RVOL/Turnover/Konzentration)
- **Zusatz-Indikatoren** — Öl WTI/Brent + Spread, Fed Funds Rate, USD/CHF, **Schweizer Makro-Snapshot** (SNB-Leitzins + nächster Termin, SARON, CH-Inflation, CH-10Y, SMI)

**Setup-Score** — mehrstufige Kauf-Checkliste (~22 Kriterien: Moving Averages, Breakout, Relative Stärke,
Volumen, Trendbestätigung/-wende, Risiken) mit **Tri-State-Logik** (nicht bewertbare Kriterien werden
ausgeschlossen statt als Fail gezählt) und Risk-First-Aggregation (Bonus-Modifier heben ein schwaches Setup nicht künstlich):

- **Donchian-Breakout** (20-Tage-Hoch, strikt `>`, + Volumen ≥ 1,5×) mit **2-Tages-Bestätigung** (Fakeout-Filter)
- **Mansfield Relative Strength** (EMA13 weekly vs. ^GSPC) — als Korrektheits-Invariante gepinnt
- **ETF-200-DMA-Kaufkriterien** (invertierte Logik: bei ~29 breiten Index-ETFs ist *Schwäche* der Trigger)
- **Schwur-/Stage-Kriterien** (Stan-Weinstein-Stil), Death-Cross/Distribution-Day/3-Punkt-Umkehr-Erkennung
- **EPS-/Quartals-Scanner** — Super-Quartal (YoY + Beschleunigung mit Outlier-Guard), Record-Quartal (Trailing-8Q-Hoch), Turnaround, YoY-Streak über das S&P-1500-Universum

### 📊 Smart-Money & alternative Datenquellen

Ein täglicher Composite-Scan zieht **14 unabhängige Quellen** parallel und verdichtet die Treffer pro Ticker;
jede Quelle läuft isoliert (fällt eine aus, bleibt der Scan grün):

| Quelle | Signal |
|---|---|
| SEC EDGAR 13F-HR | Holdings & Q/Q-Konsens von 10 Superinvestoren (Buffett, Burry, Ackman, Tepper …), Master-Feeder-gehärtet |
| SEC 13D/13G | Aktivisten-Stakes mit **Purpose-Tags** (Board-Sitz? Spinoff? Strategic Review?) — regex-basiert, ohne LLM |
| CFTC COT | Commercials- vs. Managed-Money-Positionierung in 5 Märkten, 52-Wochen-Perzentil (eigenes Makro-Panel) |
| OpenInsider / SEC Form 4 | Insider-Cluster-Käufe & Grosskäufe > 500 k |
| Capitol Trades | Congressional-Käufe (90 Tage) |
| Dataroma | Superinvestor-Konsens (Grand Portfolio) |
| SEC 8-K Volltext | Aktienrückkauf-Programme |
| **SIX SER** | **Schweizer Management-Transaktionen (SMI/SMIM)** — höchstgewichtet, von US-Tools nicht abgedeckt |
| FINRA RegSHO / SEC FTD | Short-Trend- & Fails-to-Deliver-Warnsignale (dämpfend) |
| FMP / yfinance | Estimate-Revisions, Unusual Volume |

Jedes Signal trägt im Detail-Modal eine **Frische-Ampel**; Signale ohne verlässliches Datum bekommen
bewusst keins (kein erfundenes Datum). Filter nach Score, Signal-Typ, Sektor + drei Konviktions-Gates
(Trend / Earnings-Veto / **Klumpen** — blendet aus, was du über eigene ETFs schon hoch gewichtest).

> **Ehrlichkeit beim Scoring:** Der Composite-Score ist ein Werkzeug zum *Auffinden* von Smart-Money-Aktivität,
> kein prädiktives Kaufsignal. Ein eingebauter **Forward-Return-Backtest-Harness** + monatliche
> **Per-Signal-Decomposition** messen die Wirksamkeit über die Zeit; Scoring-Gewichte gehen nur mit
> Forward-Return-Evidenz live. *(SEC-Form-4-Cluster und Estimate-Revisions laufen als experimentelle Proben
> mit Kill-Gate und können wieder entfernt werden.)*

### 📥 Import & Transaktionen

- **CSV-Import-Assistent** mit Auto-Erkennung (Encoding, Delimiter, Datumsformat, Spalten-/Typ-Mapping, Broker-Format) — nativ für **Swissquote**, **Interactive Brokers (Flex Query)**, **Pocket** & **Relai** (Bitcoin), plus generischer Fallback
- **Historische FX-Anreicherung** — Fremdwährungs-Transaktionen werden auf den Kurs **zum Transaktionsdatum** gestellt (Cross-Rate über USD bei fehlendem Direktpaar) — korrekt für CH-Performance/-Steuer
- **Duplikat-Erkennung** (order_id / exakt / Teil-Match-Warnung), **Auto-Branchen-/Sektor-Zuweisung**, speicherbare **Import-Profile**, **Bucket-Regeln** (Auto-Zuordnung per Quelle/Ticker-Pattern)
- **15 Buchungsarten** (buy/sell/dividend/fee/tax/tax_refund/delivery/deposit/withdrawal/capital_gain/interest/fx …) über eine zentrale, konsistente Buchungs-Engine; gewichteter Realized-P&L mit Oversell-Guard
- **Dividenden-Automatik** — Worker erkennt Ex-Dates und legt Pending-Dividenden an (Stückzahl read-only aus dem Ledger rekonstruiert), Auto-Matching importierter/manueller Buchungen, **Quellensteuer-Auflösung** (Position-Override → ISIN-Land-Map → User-Default)
- **Pending Orders** (Limit-Order-Verwaltung mit Trigger-Abstand, GTD-Ablauf) & **Fill-Reconciliation** (Order ↔ Transaktion, sehr strenge Match-Kriterien)

### 👁️ Watchlist & Alerts

- Watchlist mit Asset-Typ, Sektor, farbigen **Tags**, manuellem Widerstand, Live-Preisen
- **Preis-Alarme** (über / unter / Tagesveränderung) und **Breakout-Alarme** (Donchian 20d + Volumen)
- **Zweikanalige Benachrichtigung** — E-Mail (per-User-SMTP, verschlüsselte Credentials) **und** ntfy-Push, pro Kategorie steuerbar, dedupliziert, Multi-User-isoliert; Dedup-Key wird erst *nach* erfolgreichem Versand gesetzt (ein SMTP-Ausfall unterdrückt zeitkritische Alerts nicht still)

### ⚙️ Automatisierung (Hintergrund-Worker)

Ein vom API-Prozess getrennter **APScheduler-Worker** fährt ~25 geplante Jobs — schwere yfinance-/Scrape-Last
kann die API-Latenz nie beeinflussen, kein externer Cron nötig.

- **Intraday-Kurs-Refresh** alle 60 s (nur während erweiterter Handelszeiten), **voller Tages-Refresh** 07:00, **tägliche Portfolio-Snapshots** (aus Redis-Kursen, burst-sicher)
- **Alerts**: Breakout 22:30, ETF-200-DMA 22:35, Regel-Digest 22:40, Pending-Dividenden-Digest wöchentlich
- **Smart-Money-Pipeline**: 13F 08:00 → Form 4 08:30 → Estimates 09:00 → Composite-Scan 09:30; COT Sa 09:00; EPS-Scanner 04:00; Branchen-Snapshot 01:30
- **Integritäts-Wächter**: Bucket-Konsistenz, Preis-Staleness („stiller Feed-Tod"), Sektor-Mapping-Drift, ETF-Holdings-Coverage — alle melden, statt still zu verfallen
- **Job-Liveness-/Silent-Stale-Detektor** (stündlich) — erkennt Crons, die einfach aufhören; Health pro Job via `/api/admin/worker-health` (intern + extern) abfragbar

Härtung durchgängig: PostgreSQL-Advisory-Locks gegen Doppelläufe, Datei-Heartbeat für den Docker-Healthcheck,
yfinance-Burst-Schutz (Semaphore ≤ 3 gegen IP-Banns), jeder Job in eigenem try-Block (kein Job killt den Worker).

<details>
<summary><b>Vollständige Cron-Liste (Europe/Zurich)</b></summary>

`daily_refresh` 07:00 · `intraday_refresh` 60 s · `token_cleanup` 03:00 · `screening_cleanup` 04:00 ·
`import_upload_cleanup` stündlich · `cot_weekly_refresh` Sa 09:00 · `sec_13f_refresh` 08:00 ·
`sec_form4_refresh` 08:30 *(Probe)* · `estimate_revisions_refresh` 09:00 *(Probe)* · `daily_screening_scan` 09:30 ·
`eps_scanner_refresh` 04:00 · `industries_refresh` 01:30 · `etf_holdings_refresh` Mo 04:30 ·
`sector_rotation_stale_check` Mo 06:30 · `breakout_alerts` 22:30 · `etf_200dma_alerts` 22:35 ·
`rule_alerts` 22:40 · `bucket_consistency` 03:30 · `bucket_drawdown_brake` 07:30 · `bucket_total_drift` 07:35 ·
`price_staleness_check` 07:40 · `dividend_detection` 09:30 · `dividend_weekly_digest` So 09:00 ·
`per_signal_backtest` 1. d. Monats 02:00 · `job_liveness_check` stündlich · `startup_refresh` (beim Start)

</details>

### 🔌 External API & LLM-Integration

Eine versionierte REST-API unter **`/api/v1/external`** macht die **gesamte App headless steuerbar** —
für uns das eigentliche Alleinstellungsmerkmal für KI-gestütztes Investieren: dein Portfolio wird zum
Werkzeug, das ein **eigener LLM-Agent vollständig bedienen kann (lesen *und* schreiben)** — ohne dass die
Daten je einen SaaS-Anbieter sehen.

- **189 Routen**, exakt dieselbe Service-Logik wie das Web-UI — keine divergierende zweite Codebasis, identische test-gepinnte Rechenregeln
- **X-API-Key-Tokens** (`ofk_…`, 256-Bit, SHA-256-gehasht, Klartext genau einmal sichtbar) mit **read/write-Scopes** (write opt-in, fail-closed); Self-Service-Verwaltung mit optionalem Ablaufdatum
- **Voll-Parität:** jede Analyse-Sicht lesbar, **91 Write-Endpoints** decken alles ab, was ein Mensch im Browser kann — Trades buchen, rebalancen, Alerts setzen, Watchlist/Notizen pflegen, CSV importieren
- **Gebaut für autonome Agenten:** Report-Vault für Markdown-Research-Briefs (idempotent per `source_path`, an die rechtfertigende Transaktion verlinkbar), Note-Provenance für sicheren Zwei-Wege-Sync, strikte Schemas (`extra='forbid'` → kein still verschluckter Tippfehler), tamper-evidentes Write-Audit-Log, per-Request-Ownership-Validierung

> **„AI ohne Datenabgabe":** Weil OpenFolio self-hosted ist, spricht dein LLM-Copilot mit *deiner* Instanz —
> nicht mit einer fremden Cloud. Wir betreiben es selbst so: ein Claude-Agent liest die Live-Instanz über
> genau diese API (Wochen-Checks, Reports in den Vault) und pflegt das Portfolio darüber.

```bash
# Portfolio über die API lesen (read-Scope genügt)
curl -H "X-API-Key: ofk_…" https://<deine-instanz>/api/v1/external/portfolio/summary
```

📖 **Vollständige Referenz — alle Endpoints, Scopes & Beispiele: [`docs/EXTERNAL_API.md`](docs/EXTERNAL_API.md)**

### 🎨 Frontend, UX & Mobile

- **Design-System 2026** — ein verbindliches Dark-Theme, ausschliesslich Token-basiert, per diff-skopiertem Audit-Check erzwungen; **self-hosted IBM Plex** (Sans + Mono, `tabular-nums`) ohne Google-Fonts-CDN
- **Responsiv / Mobile** — unter `md` Bottom-Tab-Navigation + „Mehr"-Seite statt Sidebar, eigene Mobile-Layouts für die Kern-Screens (dichte Tabellen → Karten); rein additiv, Desktop unberührt *(Light-Mode bewusst geparkt)*
- **Command-Palette** (Cmd/Ctrl+K), **Onboarding-Tour** (7-Schritt-Spotlight) + Fortschritts-Checkliste
- **Aktien-Detailseite** — eingebetteter TradingView-Chart (SMA 20/50/150/200, RSI, S/R), Setup-Score, Mansfield-RS, Breakout-Events, ETF-Sektor-Durchsicht, Smart-Money- & EPS-Panels, verknüpfte Transaktionen
- **In-App-Wissen** — Hilfe-Center (53 Artikel in 8 Sektionen, Volltextsuche, Deep-Links), Finanz-Glossar (~180 Begriffe) mit Inline-Tooltips quer durch die App
- **Report-Vault** (Markdown-Browser für extern gepushte Analysen), **aktionsfähige Alerts** (Klick → Lösungsaktion), Toasts, In-App-Changelog
- **Barrierefreiheit** — Focus-Trap, Skip-to-Content, Scroll-Lock, durchgängige ARIA-Rollen, sichtbare Fokus-Ringe
- **Schweizer Hochdeutsch** (durchgehend ss statt scharfem S, echte Umlaute), neutrale Signal-Sprache

---

## Sicherheit & Datenschutz

Sicherheit und Datenhoheit sind keine Zusatzfeatures, sondern die Grundhaltung von OpenFolio.

### Authentifizierung & Sessions
- **JWT** — kurzlebige Access-Tokens (HS256, 15 Min) + Refresh-Tokens (30 Tage, nur SHA-256-gehasht)
- **Refresh-Token-Rotation mit Theft-Detection** — ein wiederverwendetes (bereits widerrufenes) Token löst sofortigen Logout *aller* Geräte aus
- **MFA / TOTP** + 8 Einmal-Backup-Codes (bcrypt-gehasht), **Pflicht für Admins**
- **Session-Management** — Geräte-Übersicht (User-Agent/IP), Einzel- & Logout-all, Zwangs-Widerruf nach Passwortwechsel
- **Strikte Passwort-Policy** (12–128 Zeichen, Komplexität, ~130er-Blocklist; bcrypt 12 Runden) + **Timing-Attack-/User-Enumeration-Schutz** über alle Auth-Pfade

### Verschlüsselung & Daten
- **Feldweise Verschlüsselung at rest** via **Fernet (AES-128-CBC + HMAC-SHA256)** für API-Keys, SMTP-Passwörter, TOTP-Secrets und PII (IBAN, Bank, Notizen, Edelmetall-Seriennummern, PE-Firmen-/UID-Felder) — bei DB-Leak unbrauchbar
- **IBAN-Maskierung** beim Auslesen (nur letzte 4 Stellen) & **transparente Key-Rotation** (Legacy-Fallback + automatische Re-Encryption beim Start)
- **Multi-User-Isolation** — jede Query `user_id`-scoped; per-User-Limits (500 Positionen, 10 000 Transaktionen …)
- **Admin sieht keine Portfolios** — Admin-Funktionen liefern nur Account-Metadaten, jede Aktion im **AdminAuditLog**; Schutzregeln gegen Selbst-Aussperrung / letzten Admin

### Netzwerk, Betrieb & Privacy
- **Self-hosted, own-your-data** — alle Dienste an `127.0.0.1` gebunden; externe Exposition erfordert einen bewussten Reverse-Proxy-Schritt
- **Self-hosted Fonts** (keine Google-CDN-Calls, die Nutzer-IPs leaken — DSGVO-relevant)
- **Rate-Limiting** (slowapi + Redis) über praktisch alle Router, **spoofing-resistent** über die nginx-überschriebene echte Client-IP
- **Security-Header & CSP** (Defense-in-Depth: Backend *und* nginx-Edge; HSTS 1 Jahr, `/api/`-CSP `default-src 'none'`)
- **Gehärtete Container** — `no-new-privileges`, `cap_drop ALL`, CPU-/Memory-Limits, Netzwerk-Segmentierung, Redis passwortgeschützt; **Fail-Fast** bei Platzhalter-Secrets
- **Request-Hardening** — 10-MB-Body-Limit, Korrelations-IDs, CORS-Wildcard-Schutz, keine internen Details in Fehlern; **Swagger standardmässig deaktiviert** (`ENABLE_API_DOCS`)
- **Optionaler self-hosted Observability-Stack** — Prometheus (`/metrics` bewusst PII-frei & ops-only) + Grafana (Anon-Zugriff aus) + Loki + Uptime-Kuma; Metriken verlassen die Instanz nicht

### Vertrauen in die Zahlen
- **Korrektheits-Invarianten** — die Kern-Finanzdefinitionen (`cost_basis_chf` inkl. Gebühren, `perf_pct`, XIRR/MWR, Modified Dietz, MRS, Assetklassen-Ausschluss illiquider Werte) sind durch eine **Golden-Master-Suite (~56 Fälle)** gegen stillen Definitions-Drift gepinnt — du kannst Zahlen über Jahre vergleichen
- **Neutrale, compliance-bewusste UI** — keine imperativen Handlungsanweisungen, keine Anlageberatung

---

## Schnellstart

### Voraussetzungen
- [Docker](https://docs.docker.com/get-docker/) und Docker Compose v2
- Git
- **VM-Betrieb:** virtuelle Maschinen mit CPU-Host-Passthrough (`--cpu host` bei QEMU/KVM), da NumPy SSE4/AVX benötigt

### Installation
```bash
git clone https://github.com/dmxch/openfolio.git
cd openfolio
./init.sh
```
Öffne danach [http://localhost](http://localhost). `init.sh` generiert alle Secrets, legt einen Admin-Account an und startet die Container.

### Manuelle Installation
1. `.env` erstellen (siehe [`.env.example`](.env.example))
2. `docker compose up -d --build`
3. [http://localhost](http://localhost) öffnen

### Monitoring (optional)
```bash
docker compose -f docker-compose.monitoring.yml up -d
```

### Ports
| Service | URL | Beschreibung |
|---|---|---|
| Frontend (nginx) | http://localhost:5173 | Haupt-UI |
| Backend API | http://localhost:8000 | API (Swagger unter `/docs` nur falls `ENABLE_API_DOCS`) |
| Uptime Kuma | http://localhost:3001 | Uptime-Monitoring |
| Grafana | http://localhost:3000 | Dashboards (optional, via Monitoring-Compose) |
| Prometheus Metrics | http://localhost:8000/metrics | Prometheus-Format (ops-only, PII-frei) |

---

## Tech Stack

| Komponente | Technologie |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS (Dark Theme, Token-System), Recharts, Lucide Icons, IBM Plex (self-hosted) |
| Backend | Python 3.12, FastAPI (async, 2 Uvicorn-Worker + uvloop), SQLAlchemy 2.0, asyncpg, Alembic |
| Worker | Separater APScheduler-Prozess (~25 Jobs: Kurse, Snapshots, Alerts, Screening, Backtests, Liveness) |
| Datenbank | PostgreSQL 16 (tuned) |
| Cache | Redis 7 (shared, allkeys-lru) |
| Daten | yfinance, CoinGecko, FRED, FMP, Finnhub, Gold.org, multpl.com, SEC EDGAR, CFTC, FINRA, SIX SER, SNB, TradingView-Scanner |
| Monitoring | Prometheus + Grafana + Loki (optional), Uptime-Kuma |
| Infra | Docker Compose (gehärtet: cap_drop, no-new-privileges, Netz-Segmentierung) |

---

## Konfiguration

| Variable | Beschreibung | Default |
|---|---|---|
| `ADMIN_EMAIL` | E-Mail des Admin-Accounts | — |
| `ADMIN_PASSWORD` | Passwort des Admin-Accounts | — |
| `FMP_API_KEY` | Financial Modeling Prep (optional, US-Fundamentaldaten/Estimates; auch pro User setzbar) | — |
| `FRED_API_KEY` | Federal Reserve (optional, Makro-Indikatoren) | — |
| `FINNHUB_API_KEY` | Finnhub (optional, EPS-/Quartals-Scanner) | — |
| `GRAFANA_USER` / `GRAFANA_PASSWORD` | Grafana-Admin (optional) | admin / openfolio |

Datenbank-, JWT- und Encryption-Secrets generiert `init.sh` automatisch. Neue env-Settings müssen in **beide**
Compose-`environment`-Blöcke (backend **und** worker).

---

## Deployment hinter Reverse Proxy

Für den Betrieb mit eigener Domain hinter Nginx / Caddy / Traefik:

```bash
# .env
CORS_ORIGINS=https://deine-domain.com
FRONTEND_URL=https://deine-domain.com
```

Weitere Anpassungen via Override (wird automatisch geladen, ist gitignored):
```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up -d --build
```

<details>
<summary><b>Nginx-Beispielkonfiguration</b></summary>

```nginx
server {
    listen 443 ssl;
    server_name deine-domain.com;
    ssl_certificate     /etc/letsencrypt/live/deine-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/deine-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
</details>

- **SSL:** Let's Encrypt (Certbot) oder Cloudflare Tunnel.
- **Backend-Port:** standardmässig nur auf `127.0.0.1:8000` — nicht von aussen erreichbar, aber für den lokalen Proxy zugänglich.
- **Echte Client-IP:** das Rate-Limiting liest `X-Forwarded-For` — der Reverse Proxy muss ihn korrekt setzen.

---

## Update / Backup / Restore

```bash
# Update
git pull && docker compose up -d --build

# Backup
docker compose exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup_$(date +%Y%m%d).sql

# Restore
cat backup_20260318.sql | docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

---

## Projektstruktur & Doku

- Beitragsregeln: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- External API: [`docs/EXTERNAL_API.md`](docs/EXTERNAL_API.md)
- Design-System: [`frontend/DESIGN_SYSTEM.md`](frontend/DESIGN_SYSTEM.md)
- Weitere Dokumentation: [`docs/`](docs/) — `design/` (Specs), `audits/` (Reviews), `research/` (Diagnose/Backtests), `strategy/` (Roadmap), `archive/`
- Änderungsverlauf: [`CHANGELOG.md`](CHANGELOG.md) (auch in-app)

## Mitwirken

Pull Requests und Issues sind willkommen — bitte zuerst die [Contributing Guidelines](CONTRIBUTING.md) lesen.

- **Bug melden:** [Issue erstellen](https://github.com/dmxch/openfolio/issues/new?template=bug_report.yml)
- **Feature vorschlagen:** [Issue erstellen](https://github.com/dmxch/openfolio/issues/new?template=feature_request.yml)
- **Fragen:** [GitHub Discussions](https://github.com/dmxch/openfolio/discussions)

Gute erste Beiträge: Tests (Coverage), Accessibility, neue Broker-Import-Profile, weitere ETF-Look-Through-Emittenten (Xtrackers/Vanguard/UBS), Dokumentation.

## Lizenz

[MIT](LICENSE)

---

> **Haftungsausschluss:** OpenFolio ist ein Informations- und Analyse-Werkzeug, **keine Anlageberatung**.
> Alle Signale, Scores und Kennzahlen sind regelbasierte Berechnungen ohne Gewähr. Investitionsentscheide
> und deren Folgen liegen allein beim Nutzer. Keine Steuerberatung.
