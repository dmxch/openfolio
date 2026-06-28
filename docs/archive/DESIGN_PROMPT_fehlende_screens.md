# Claude-Design-Prompt — Fehlende Screens für OpenFolio ergänzen

> Diesen Text in das bestehende Claude-Design-Projekt **„OpenFolio Portfolio-Manager"** geben.
> Ziel: die noch fehlenden Screens, Modals und Zustände **sauber im exakt gleichen Designsystem** ergänzen.

---

## Kontext

OpenFolio ist ein **Desktop-Portfolio-Manager** (Schweiz, CHF-Basis) für systematisches Investieren.
Das Projekt enthält bereits **11 fertige `.dc.html`-Screens** im finalen Look:
`Sidebar`, `Marktklima`, `Branchen`, `Portfolio`, `Performance`, `Watchlist`, `SmartMoney`, `EPS-Scanner`, `Transaktionen`, `OffeneOrders` (+ `support.js`).

Diese Screens decken aber nur einen Teil der echten App ab. Bitte die unten gelisteten **fehlenden Oberflächen ergänzen** — **strikt** im bestehenden Designsystem (Tokens, Layout, Komponenten-Muster siehe unten). Keine neue Designsprache erfinden, nichts „aufhübschen", einfach konsistent weiterbauen.

**Wichtige Rahmenbedingungen:**
- **Desktop-only.** Keine Mobile-/Responsive-Breakpoints, keine Hamburger-Menüs. Feste Breiten wie in den bestehenden Screens.
- **Deutsch (Schweiz):** kein „ß" → immer „ss"; ä/ö/ü korrekt.
- **Neutrale Signal-Sprache:** „Kaufkriterien erfüllt" statt „Kaufsignal", „Verkaufskriterien erreicht" statt „Verkaufen!". Keine imperativen Handlungsanweisungen.
- **Format:** jeder Vollbild-Screen als eigene `.dc.html` mit `<dc-import name="Sidebar" active="…">`, gleichem `<helmet>`-Font-Block und Base-Style wie die bestehenden Dateien.

---

## Designsystem (verbindlich — exakt übernehmen)

### Schrift
- Body: `'IBM Plex Sans', system-ui, sans-serif`
- Zahlen / Labels / Ticker / Codes: `'IBM Plex Mono', monospace`
- Global: `font-variant-numeric: tabular-nums`, `-webkit-font-smoothing: antialiased`
- Laden im `<helmet>` wie bisher (Sans 400;500;600;700, Mono 400;500;600)

### Farben
**Flächen**
- App-Hintergrund `#0a0d12` · Sidebar `#0c0f15`
- Karte/Panel `#11151d` · innere/genestete Karte `#0f141c` · Tabellen-Kopf `#0e131b`
- Sekundär-Fläche (Buttons/Inputs) `#10151d` · Karten-Hover `#131925` · Zeilen-Hover `#141a23`
- Modal-Fläche `#121821` · aktiver Tint (Nav/Filter aktiv) `#15203a`

**Rahmen**
- Header/Sidebar `#1a212c` · Karte `#222a36` · innen/Divider `#1c2331`
- Zeilen-Divider `#161d27` / `#181f2a` · Ticker-Chip-Rand `#232c39`
- Hover-Rand `#2c3645` · aktiver blauer Rand `#2f4470` / `#36425a` · Chip-Blau-Rand `#233458`

**Text**
- Primär `#e9eef5` · sekundär `#cbd4e0` · gedämpft `#9aa6b6` · schwach `#7a8698`
- Label `#626d7d` / `#5f6d7d` · sehr schwach `#4d5868`

**Akzente / Semantik**
- Blau (Akzent) `#5b8def` · Link-Blau `#9bb4e8` · Primär-Button `#1d4ed8` (Rand `#2f5fe0`, Hover `#2f5fe0`)
- Positiv/Grün `#45c08a` · Teal `#29c3b1` · Negativ/Rot `#e8625a` · Amber/Warnung `#e0a64b`
- Krypto-Lila `#b06ee8` · Private-Equity-Lila `#8a7de0`
- Logo-Gradient `linear-gradient(135deg,#5b8def,#29c3b1)`

**Asset-Klassen-Farben (Typ-Badges, je mit ~13–14 % Alpha-Hintergrund)**
Aktien `#5b8def` · ETF `#29c3b1` · Krypto `#b06ee8` · Edelmetall `#e0a64b` · Immobilien `#6b8aa0` · Private Equity `#8a7de0` · Cash `#7a8698` · Vorsorge `#45c08a`

**Buchungs-Typ-Farben**
Kauf `#5b8def` · Verkauf `#e0a64b` · Dividende `#45c08a` · Gebühr `#7a8698` · Einzahlung `#29c3b1` · Steuer `#e8625a`

### Radien
Karten `11px` · Buttons/Inputs/Filter-Chips `8px` · Ticker-Chips `6–7px` · kleine Badges `5–6px` · Modal `14px` · Punkte/Dots `50%`

### Layout-Shell (jeder App-Screen)
- Wrapper `display:flex; min-height:100vh; background:#0a0d12`
- Sidebar `flex:0 0 240px` (sticky, via `<dc-import>`)
- Main `flex:1; min-width:0; display:flex; flex-direction:column`
- **Sticky Header:** `padding:14px 24px; border-bottom:1px solid #1a212c; background:rgba(10,13,18,.86); backdrop-filter:blur(8px); position:sticky; top:0; z-index:30` — enthält: Titel (`h1`, 19px/600, `letter-spacing:-.01em`) + Mono-Untertitel (11.5px, `#5f6d7d`), `flex:1`-Spacer, kontextuelle Aktions-Buttons, Such-Button mit `⌘K`-Chip, Glocken-Icon-Button `◔` mit rotem Zähler-Badge.
- **Content:** `padding:22px 24px 60px; display:flex; flex-direction:column; gap:18px` (manche Seiten 14/16px)

### Bausteine (so wie in den bestehenden Screens)
- **Mono-Mikro-Label:** `IBM Plex Mono; 10.5px; letter-spacing:.06em; text-transform:uppercase; color:#626d7d`
- **Stat-Tile:** Karte → Mikro-Label + grosse Zahl (22–25px/600, Zahlen in Mono) + Delta-Zeile (farbig)
- **Filter-Chip:** `padding:7px 12px; radius:8px; 12.5px/500` — aktiv: bg `#15203a`, Rand `#2f4470`, Text `#cbd4e0`; inaktiv: bg `#10151d`, Rand `#1c2331`, Text `#8893a3`; Zähler in Mono `#626d7d`
- **Ticker-Chip:** `Mono 11–11.5px/600; color:#e9eef5; bg:#161d27; border:1px solid #232c39; radius:6px; padding:4px 7px`
- **Typ-/Status-Badge:** `10.5px/500; radius:5px; padding:3px 7–8px` mit Farbe + getöntem Hintergrund
- **Primär-Button:** `bg:#1d4ed8; border:1px solid #2f5fe0; radius:8px; padding:8px 14px; #fff; 12.5px/600` (oft mit führendem `+`), Hover `#2f5fe0`
- **Sekundär-Button:** `bg:#10151d; border:1px solid #222a36; radius:8px; padding:7–8px 12–13px; #9aa6b6; 12.5px`, Hover-Rand `#2c3645`
- **Icon-Button (36×36):** `bg:#10151d; border:1px solid #222a36; radius:8px; #9aa6b6`; Badge oben-rechts in Rot `#e8625a`
- **Such-Button:** Sekundär-Button + `⌘K`-Kbd-Chip (`bg:#1a212c; border:1px solid #2c3645; radius:4px; padding:1px 5px`)
- **Tabelle:** Karte mit `overflow-x:auto` + Min-Width-Inner; Kopfzeile CSS-Grid, Mono-Uppercase-10px-Labels auf `#0e131b`; Body-Zeilen Grid, Divider `#161d27`, Hover `#141a23`
- **Heatmap-Zelle:** grün/rot rgba nach Betrag skaliert, Zahl zentriert (Mono)
- **Range-Slider:** `accent-color:#5b8def`
- **Modal (Muster aus `SmartMoney`):** Overlay `position:fixed; inset:0; background:rgba(4,7,12,.72); backdrop-filter:blur(3px); z-index:80; zentriert` → Dialog `bg:#121821; border:1px solid #2c3645; radius:14px; box-shadow:0 24px 70px rgba(0,0,0,.6)`; Kopf mit Ticker-Chip/Titel + `✕`-Close-Button; Body als Key-Value-Zeilen / Formular.

---

## Was fehlt — bitte ergänzen

### A) Fehlende ganze App-Screens (eigene `.dc.html`, mit Sidebar)
1. **StockDetail** — Einzeltitel-Detailseite. Header: Zurück-Pfeil + Logo + Ticker-Chip + Name + aktueller Kurs + Tagesveränderung + YTD. Inhalt: „Meine Position"-Panel (Stück, Wert, Einstand, PnL CHF/%, Allokations-%) inkl. Konzentrations-Banner falls >10 %; grosser (TradingView-)Kurschart; **Score-Karte = 18-Punkte-Kauf-Checkliste** in 6 Kategorien (s. Diskrepanz unten); Fundamental-Kennzahlen + Mini-Charts (P/E, PEG, Div.-Rendite, ROE, Debt/Equity); **MRS-Panel** (Mansfield Relative Strength); **Breakout-Events** (52-W-Hochs/Tiefs, „in Prüfung"-Badge bis Tag-2-Bestätigung); **Levels-Panel** (Support/Resistance); **ETF-Sektor-Panel** (falls Multi-Sektor-ETF); **EPS-Panel** + **Smart-Money-Panel**; verknüpfte Transaktionen; Disclaimer-Banner.
2. **Report-Vault** (Sidebar-Key `reports`, aktuell auf `#`) — **Zwei-Spalten-Layout**: links Liste (~400px) mit Volltext-Suche, Kategorie- + Tag-Filter, je Eintrag Kategorie-Badge/Datum/Titel/Tags, Gesamtzähler, Leerzustand; rechts Viewer mit Kategorie/Datum/Quelle, Titel, **Inline-Tag-Editor**, Export-(MD)- + Löschen-Button und **gerendertem Markdown-Body** (Überschriften, Listen, Tabellen, Code, Zitate — dark-theme).
3. **Einstellungen** (Sidebar-Footer „Einstellungen", neuer aktiver Key `settings`) — Seite mit linker Unter-Navigation (vertikale Tabs) und Formular-Bereich rechts. Tabs:
   - **Konto** — E-Mail, Passwort ändern, MFA/TOTP einrichten (mit QR-Code)
   - **Alerts** — Regeln: Allokations-Drift, Konzentration, Dividende (Schwellen, an/aus)
   - **API-Tokens** — Token erzeugen / rotieren / widerrufen (Liste)
   - **Buckets** — Bucket-CRUD, Zielgewichte, Template wählen
   - **Daten** — Import/Export, Cache leeren, Neuberechnung anstossen
   - **Anzeige** — Zahlenformat (CH/DE/EN), Datumsformat, Theme
   - **Integrationen** — TradingView, Interactive Brokers, Pocket (Verbindungs-Status)
   - **Portfolio** — Dividenden-Einstellungen, Rebalancing-Regeln
4. **Hilfe** (Footer „Hilfe & Glossar", Key `hilfe`) — FAQ/Hilfe-Layout (Suchfeld + aufklappbare Abschnitte).
5. **Glossar** (Key `glossar`) — Finanz-Begriffsliste (alphabetisch, mit Suche/Filter, Begriff + Definition).
6. **Admin** (Key `admin`, nur Admin) — Nutzerverwaltung (Tabelle), Cache-Status & -Purge, Invite-Codes, Token-Rotation.
7. **Changelog** — Versionshistorie (gerendertes Markdown, Versions-Abschnitte).
8. **Rechtliches** — Datenschutz, Disclaimer, Nutzungsbedingungen, Impressum (ruhiges Lese-Layout; darf ohne Sidebar sein).
9. **404 / Nicht gefunden** — schlichte Fehlerseite mit Zurück-Link.

### B) Auth-Screens (eigenes zentriertes Layout OHNE Sidebar)
Eigene Auth-Shell: zentrierte Karte (`#11151d`/Rand `#222a36`/radius 11px), Logo oben (Gradient-Quadrat „O" + „OpenFolio"), Eingabefelder im Sekundär-Flächen-Stil, Primär-Button.
- **Login** (E-Mail + Passwort, danach optional MFA/TOTP-Code-Schritt)
- **Registrieren** (mit optionalem Invite-Code, Passwort-Stärke-Anzeige)
- **Passwort vergessen**
- **Passwort zurücksetzen** (Token-Flow)
- **Passwort ändern (erzwungen)** (Erststart / nach MFA-Setup)

### C) Modals, Wizards & Overlays (nur das SmartMoney-Modal existiert — Muster wiederverwenden)
- **Position hinzufügen / bearbeiten** — mit **klassenspezifischen Feldern**: Aktien/ETF (Ticker, Stück, Einstand, Bucket), Krypto, Edelmetall (oz/Spot), **Immobilien** (Wert + Hypothek/Saron), **Private Equity** (Commitment/NAV), **Cash-/Vorsorge-Saldo** (manueller Betrag, Währung). Wichtig: das Portfolio-Mockup zeigt alle Klassen als Tabellenzeilen — das Erfassen je Klasse braucht dieses Modal.
- **Löschen bestätigen** — generischer Bestätigungsdialog (Titel, Warntext, Abbrechen/Löschen-Rot).
- **Buchung erfassen / bearbeiten** — Datum, Typ (Kauf/Verkauf/Dividende/Gebühr/Einzahlung/Steuer), Titel, Stück, Kurs, Betrag, Bucket.
- **Dividende bestätigen** — erkannte Dividende prüfen/buchen.
- **Stop-Loss einrichten** — als **mehrstufiger Wizard** (Methode/Schwelle/Bestätigung).
- **Bucket-Wechsel bestätigen**, **Bucket-Template wählen**, **Bucket-Onboarding**.
- **Order anlegen / bearbeiten** (Limit/Stop, Seite, Menge, Limit) und **Order als ausgeführt markieren** (Fill).
- **Import-Wizard** — mehrstufig: Quelle wählen (Swissquote / Interactive Brokers / Pocket) → Datei-Upload → Spalten-Mapping & Vorschau → Bestätigung → Resultat. (Auslöser: „↑ Batch-Import" in Transaktionen.)
- **EPS-Detail** — Detail-Popup je Titel (kann dem SmartMoney-Modal folgen).
- **Command-Palette (⌘K)** — das Such-Overlay selbst: Eingabefeld + gruppierte Resultate/Aktionen (Seiten springen, Ticker öffnen, Aktionen), Tastatur-Hervorhebung. Bisher nur der Auslöse-Button.
- **Ticker-Suche / Autocomplete-Dropdown** — für „+ Ticker" (Watchlist), „+ Position", globale Suche.
- **Kontextmenü** (Rechtsklick auf Tabellenzeilen).

### D) Globale Zustände (für ALLE Listen/Tabellen/Karten — bisher nur der „volle" Zustand)
- **Ladezustand:** Skeleton-Platzhalter (keine Spinner) für Tabellen, Karten-Grids, Stat-Tiles, Charts.
- **Leerzustand:** je eigener Empty-State für *keine Positionen / keine Watchlist / keine Orders / keine Transaktionen / keine Smart-Money-Signale / keine Reports* — mit Icon, kurzem Text und Primär-Aktion („+ …").
- **Fehlerzustand:** fehlgeschlagener Abruf mit „Erneut versuchen" (auch pro Karte als Teil-Fehler).
- **Offline-Banner** (Verbindung verloren).

### E) Benachrichtigungen & Alerts
- **Glocken-Popover/-Panel:** Das `◔`-Glockenicon mit Badge „3" ist in jedem Header — das **geöffnete Alert-Panel fehlt**. Liste der Alerts mit Typ-Icon, Text, Zeit, Aktion. Alert-Typen: Allokations-Drift, Konzentration, Stop-Loss getroffen, Dividende fällig, 200-DMA, Earnings.
- **Toasts** (Erfolg/Fehler/Info) — Position, Stil, Auto-Dismiss.
- **Inline-Banner:** Konzentrations-Warnung, kommende Earnings, Disclaimer-Hinweis, Dividenden-Hinweis.
- **Sidebar-Zähler-Badges:** kleine Badges an Nav-Items (Portfolio = Alert-Anzahl, Transaktionen = Dividenden-Anzahl).

### F) Tooltips & Glossar-Integration
- **Tooltip-Popover:** Die `?`-Icons und die `data-term`-Hover-Trigger (Performance) sind angelegt, aber das eigentliche **Tooltip-Popover** (Begriff + kurze Definition + „Mehr im Glossar →") ist noch nicht gestaltet. Bitte konsistent ergänzen.

### G) Tabellen-Interaktionen & Detailtiefe (in bestehenden Screens angedeutet)
- **Zeilen-Aktionen:** Bearbeiten / Löschen / Stop-Loss je Zeile (Hover-Aktionen oder Kebab-`⋯`-Menü) — Portfolio, Transaktionen, Offene Orders, Watchlist.
- **Sortierbare Spaltenköpfe** mit Sortier-Indikator (nur Branchen hat Sort-Buttons; Portfolio/Transaktionen/EPS/Watchlist sollten sortierbar sein).
- **Pagination** (lange Listen, v.a. Smart Money).
- **Benchmark-Dropdown:** Performance-Header zeigt „MSCI World ▾" — das offene Dropdown fehlt.
- Zeilen-Klick auf Portfolio → führt zu **StockDetail**.

### H) Bereiche INNERHALB bereits designter Seiten
- **Portfolio:** Cash-Konten und Vorsorge (Säule 3a) sind eigene Inline-Tabellen mit eigenem „+ Konto"/Saldo-Erfassen und Zeilen-Kontextmenü (im Mockup nur als Tabellenzeilen) → Bearbeiten-Flow je Klasse designen; „count-as-cash"-ETF-Badge (`ETF · live`); Stop-Loss-Spalte/Indikator; kleine Allokations-/Bucket-Übersicht oder Netto-Vermögens-Aufschlüsselung; Top-Mover; Onboarding-Checkliste.
- **Performance:** prüfen, ob diese bestehenden Bausteine einen Platz in den 5 Tabs haben und sie einsortieren — **Realisierte Gewinne** (Tabelle), **Gebühren/Steuern**-Übersicht, **Trade-Journal**, **Bucket-Korrelationsmatrix**, **Dividenden-Yield-on-Cost**, **Tagesveränderung**, **Netto-Vermögen** (Bilanz: Aktiven vs. Hypotheken).
- **Marktklima:** **kommende Dividenden** (Vorschau-Widget); Einstieg in **Onboarding-Checkliste**.
- **Branchen:** Period-Selector (1W/1M/3M/6M/YTD/1J), Schnellfilter Top-15/Bottom-15, MCap-Filter, „Konzentrierte ausblenden"-Toggle; zusätzliche **Flow-Spalten** (Marktkap. + Δ, Turnover %, relatives Volumen, Top-1-Konzentration); **Drill-down** in die Einzeltitel je Industrie.
- **EPS-Scanner:** **linke Filter-Sidebar** (Super-Quartal / Rekord-Quartal / Turnaround-Toggles, Min-Quartale-Slider, Sektor- + Index-Multiselect, Suche) + **Schwellenwert-Einstellungen** (aufklappbar) + **Pagination**; Staleness-Legende existiert.
- **Smart Money:** **linke Filter-Sidebar** (Min-Score-Slider, Sektor-Multiselect, Sektor-Momentum, Signal-Typen — 13F, Insider, Buyback, Aktivist, Congress, SIX-Insider, Estimate-Revision —, Schwur/Konviktion 1×/2×/3×) + **Pagination** (das Mockup zeigt nur 4 Top-Chips — die echte Filterung ist deutlich reicher).
- **Transaktionen:** 5er-**Summary-Stat-Karten** (Anzahl, Käufe, Verkäufe, Dividenden, Gebühren); erweiterte Filter (Ticker, Datum-von/-bis, Reset); zusätzliche Spalten (Währung, FX-Kurs, Gebühren, Notizen); **Pagination**; realisierte Gewinne / Verknüpfung zu Orders; Zeilen-Bearbeiten/Löschen; mehr Buchungstypen (zusätzlich Kapitalgewinn, Zins, FX, Steuer-Rückerstattung).

### Diskrepanzen / Korrekturen am bestehenden Mockup
- **Watchlist-Checkliste:** Das Mockup nennt „8-Punkte-Kauf-Checkliste" mit 8 Kriterien — die echte App nutzt eine **18-Punkte-Checkliste in 6 Kategorien** (Price Action, Earnings, Bewertung, Qualität, Wachstum, Sentiment, je 3). Bitte Watchlist **und** StockDetail-Score auf die 18-Punkte-Struktur anheben (Score als „n/18", Kategorien-Gruppierung). Falls bewusst auf 8 reduziert werden soll: bitte als Entscheid kennzeichnen.
- **Smart Money & EPS-Scanner:** Mockups zeigen eine schlanke Chip-Leiste; real existiert eine **Filter-Sidebar + Pagination** (s. H). Bitte die reichere Filterung gestalten (oder bewusst vereinfachen).

### I) Onboarding
- **Onboarding-Tour** (mehrstufige Spotlight-/Coachmark-Schritte) und **Onboarding-Checkliste** (Setup-Fortschritt) im neuen Look.

---

## Liefer-Konventionen
- **Vollbild-Screens** → je eigene `.dc.html` mit `<dc-import name="Sidebar" active="…">`, gleicher helmet-/Base-Style.
- **Sidebar ergänzen:** aktive Keys/Verlinkungen für `reports`, `settings`, `hilfe`, `glossar`, `admin` (Footer-Items + Report-Vault echt verlinken statt `#`).
- **Modals / Overlays / Zustände** → bevorzugt je Thema eigene Komponenten-Dateien (z.B. `Modals.dc.html`, `Zustaende.dc.html`, `Auth.dc.html`, `Alerts.dc.html`) mit State-Toggles zum Durchschalten der Varianten — alternativ als Varianten in der jeweiligen Seite.
- **Auth & Rechtliches** ohne Sidebar (eigenes Layout).
- **Designsystem 1:1** beibehalten (Tokens oben). **Desktop-only, kein Mobile.** Deutsch (Schweiz, kein ß), neutrale Signal-Sprache.
