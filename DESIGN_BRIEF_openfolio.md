# OpenFolio — Produkt- & Design-Brief

> Übergabe-Dokument für einen UI/UX-Designer. Beschreibt, was OpenFolio ist, wie es
> aufgebaut ist, was es kann, und wie das aktuelle UI strukturiert ist — als Grundlage
> für einen frischen Design-Entwurf, der danach mit dem Ist-Zustand abgeglichen wird.

---

## 1. Was ist OpenFolio?

**OpenFolio ist ein selbst-gehosteter, Open-Source Portfolio-Manager für systematisches,
regelbasiertes Investieren.** Er richtet sich an ambitionierte Privatanleger, die ihr
gesamtes Vermögen an einem Ort führen, ihre Rendite sauber messen und ihre Investment-
Disziplin mit Daten statt Bauchgefühl untermauern wollen.

Das Produkt ist mehr als ein Depot-Tracker. Es kombiniert vier Welten:

1. **Buchhaltung & Performance** — jede Position, jede Transaktion, jede Dividende; daraus
   exakte, über die Zeit vergleichbare Renditezahlen (XIRR, Modified Dietz, Drawdown,
   Sharpe/Sortino).
2. **Gesamtvermögen** — nicht nur Aktien/ETFs, sondern auch Immobilien (inkl. Hypothek &
   Mieteinnahmen), Private Equity, Edelmetalle, Krypto, Cash und Vorsorge.
3. **Markt- & Signalanalyse** — Marktklima (VIX, COT, Sektor-Rotation), regelbasierte
   Kauf-/Verkaufskriterien, Screening über Smart-Money-Daten (SEC 13F, Insider Form 4),
   EPS-Scanner.
4. **Disziplin-Werkzeuge** — Buckets (Core/Satellite), Stop-Loss-Regeln, Rebalancing-
   Hinweise, Trade-Journal, Alerts über mehrere Kanäle.

### Charakter & Designhaltung
- **Reines Desktop-Tool.** Keine Mobile-Responsiveness — der Designer darf für große
  Bildschirme und dichte Informationsdarstellung optimieren.
- **Dark-Theme First.** Finanz-Cockpit-Ästhetik, ruhig, hoher Kontrast bei Zahlen.
- **Vertrauen in Zahlen ist das Kernversprechen.** Zahlen müssen präzise, eindeutig
  formatiert und über die Zeit vergleichbar wirken (tabellarische Ziffern, klare
  Vorzeichen-/Farb-Codierung grün/rot, CHF als Basiswährung).
- **Neutrale Signalsprache.** Nie imperativ. „Kaufkriterien erfüllt“ statt „Kaufsignal“,
  „Verkaufskriterien erreicht“ statt „Verkaufen!“. Das Tool informiert, es befiehlt nicht.
- **Sprache:** UI durchgehend Deutsch (Schweizer Deutsch — kein „ß“, immer „ss“; ä/ö/ü
  korrekt). Fachbegriffe sind überall per Glossar-Tooltip erklärt.
- **Multi-User.** Selbst-gehostet, mehrere Nutzer pro Instanz, alles user-bezogen.

---

## 2. Tech-Stack (Kontext)

- **Frontend:** React 18, Vite, Tailwind CSS (Dark Theme), Recharts, TradingView-Embed,
  Lucide Icons, React Router v6 (lazy-loaded Pages).
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Redis 7,
  Alembic, APScheduler-Worker für Hintergrundjobs.
- **Datenquellen:** yfinance, CoinGecko, gold.org, FRED, Finnhub, FMP, SEC EDGAR, CFTC,
  TradingView.
- **Auth:** JWT + Refresh-Token-Rotation, TOTP-MFA, Backup-Codes, PII-Verschlüsselung.

---

## 3. Informationsarchitektur & Navigation

Navigation über eine **feste linke Sidebar** (240 px) auf Desktop. Hauptbereiche:

| Route | Label (UI) | Icon | Zweck |
|-------|-----------|------|-------|
| `/` | **Marktklima** | BarChart3 | Einstieg/Dashboard: Markt-Klima, Earnings, Dividenden |
| `/branchen` | **Branchen** | Factory | Sektor-/Industrie-Analyse, Momentum-Heatmaps |
| `/portfolio` | **Portfolio** | Briefcase | Alle Positionen verwalten (alle Assetklassen) |
| `/performance` | **Performance** | LineChart | Rendite-, Risiko- & Allokations-Cockpit |
| `/analysis` | **Watchlist** | Search | Ticker-Recherche + Kauf-Checkliste |
| `/smart-money` | **Smart Money** | Crosshair | Screening (13F, Insider, Estimates) |
| `/eps-scanner` | **EPS-Scanner** | TrendingUp | Gewinn-/Quartals-Screening |
| `/reports` | **Report-Vault** | FileText | PDF-/Export-Verwaltung |
| `/transactions` | **Transaktionen** | ArrowLeftRight | Ledger aller Buchungen |
| `/orders` | **Offene Orders** | ListOrdered | Limit-Orders & Fills |
| `/settings` | **Einstellungen** | Settings | 8 Tabs Konfiguration |
| `/hilfe` | **Hilfe** | HelpCircle | Onboarding & FAQ |
| `/glossar` | **Glossar** | BookOpen | Fachbegriff-Lexikon |
| `/admin` | **Admin** | Shield | Nur Admins: User-Management |

Detailseite ohne Sidebar-Eintrag: **Stock-Detail** (`/stock/:ticker`).
Öffentlich (ausgeloggt): Login, Register, Passwort-Reset, sowie rechtliche Seiten
(Datenschutz, Disclaimer, Nutzungsbedingungen, Impressum).

Globale UX-Bausteine: **Command-Palette (Cmd/Ctrl+K)** für Schnellnavigation,
**Alert-Popover** in der Sidebar (Badge mit Anzahl), **Toast-Notifications**,
**Onboarding-Tour + Checkliste** für neue Nutzer.

---

## 4. Die Seiten im Detail

### Marktklima (Dashboard, `/`)
Einstiegs-Cockpit. Enthält: Markt-Klima-Karte (Einstufung bullish/neutral/bearish aus
VIX, COT-Sentiment, Sektor-Momentum), CoT-Macro-Panel, Schweizer-Makro-Karte (Rohstoffe:
Öl, Gas, Kupfer …), Banner mit anstehenden Earnings, Widget mit offenen (Pending)
Dividenden zum Bestätigen.

### Portfolio (`/portfolio`)
Zentrale Verwaltung. Haupttabelle aller Positionen über **alle Assetklassen**: Aktien,
ETFs, Krypto, Edelmetalle, Immobilien, Private Equity, Cash, Vorsorge. Pro Zeile: Ticker,
Stückzahl, Einstand, aktueller Wert, PnL absolut & %, Bucket-Zuordnung. Aktionen:
Position hinzufügen/bearbeiten/löschen, Stop-Loss setzen (Wizard mit mehreren Methoden),
in anderen Bucket verschieben. Eigene Widgets für die alternativen Assetklassen
(Immobilien mit Hypothek/Hebel/Rendite, Edelmetalle, Krypto, Private Equity mit
Bewertungs-Snapshots). Buckets-Übersicht. **CSV/PDF-Import-Wizard** (Swissquote, IBKR,
Pocket) mit Spalten-Mapping.

### Performance (`/performance`)
Das analytische Herzstück — eine dichte Cockpit-Seite mit vielen Karten:
- **Gesamtrendite-Karte** (Total Return, unrealisiert/realisiert, Dividenden, Gebühren)
- **Performance-Chart** (indexierte Equity-Kurve vs. Benchmark, Perioden 1M–MAX)
- **Risiko-Metriken** (Alpha, Beta, Sharpe, Sortino, Calmar, Volatilität, Max-Drawdown)
- **Rolling-Drawdown / Underwater-Chart**
- **Netto-Vermögen** (Cash vs. investiert)
- **Allokations-Charts** (Pie: Assetklasse / Sektor / Land / Währung)
- **HHI-Konzentration** + Konzentrations-Warnungen
- **Monatsrenditen-Heatmap** (Jahr × Monat)
- **Dividenden-Rendite (Yield on Cost) + Dividenden-Forecast**
- **FIRE-Projektion** (Jahre bis Ziel, Endalter)
- **Trade-Journal** (Rationale + Plan/Ist je Position)
- **Rebalancing-Hinweise** (Portfolio- und Positions-Ebene)
- **Faktor-Exposition** (Value/Growth/Momentum/Quality/LowVol)
- **ETF-Land-Durchblick** (Look-Through durch ETF-Holdings)
- **Pro Bucket:** Vergleichsleiste + Akkordeon mit allen obigen Widgets je Bucket.

### Watchlist (`/analysis`)
Ticker-Suche mit Autocomplete; Watchlist-Tabelle mit einer **18-Punkte-Kauf-Checkliste**
pro Titel; Notizen & Tags.

### Stock-Detail (`/stock/:ticker`)
Tiefenanalyse eines Titels: TradingView-Chart (Timeframes, Indikatoren), Fundamental-
Charts (KGV, KCV, Wachstumshistorie), Sektor-/ETF-Lookup, Smart-Money-Panel, EPS-Scanner-
Panel, Scoring-Karte (Signal-Komponenten), eigene Position (falls gehalten).

### Smart Money (`/smart-money`)
Screening-Grid mit filterbaren Kandidaten aus Smart-Money-Daten (SEC 13F Superinvestoren,
Insider Form 4, Estimate-Revisionen). Filter: Mindest-Score, Sektor, Momentum, Signal-Typ.
Pagination, Detail-Modal je Titel.

### EPS-Scanner (`/eps-scanner`)
Quartals-Gewinn-Screening über breiten US-Index. Tabelle mit Quartalszellen (YoY-Badges,
Daten-Alter-Tags). Filter: Super-Quartal, Rekord-Quartal, Turnaround, Min-Quartale,
Sektor, Index. Sortierung, Pagination, Detail-Modal.

### Branchen (`/branchen`)
Sektor-/Industrie-Dashboard: Performance-Tabelle, Momentum-Heatmaps, VIX-Levels,
Relative-Strength-Charts (TradingView-Snapshot).

### Transaktionen (`/transactions`)
Vollständiges Ledger: Käufe, Verkäufe, Dividenden, Zinsen, Gebühren, Steuern, Ein-/
Auszahlungen, FX. Filter (Typ, Ticker, Datum, Suche), Add/Edit/Delete, Batch-Import,
Bestätigungs-Modal für Dividenden.

### Offene Orders (`/orders`)
Limit-Kauf-/Verkauf-Orders, Fill-Status, Fill-Simulator/Bestätigung, Benachrichtigungen.

### Report-Vault (`/reports`)
PDF-Upload/Download, Meta-Verwaltung, Tagging — für Audit/Backups/Exports.

### Einstellungen (`/settings`) — 8 Tabs
Konto & Sicherheit (MFA, Passwort) · Portfolio (Basiswährung, Länderfilter) · Buckets
(Templates/Namen) · Alerts (Stop-Loss, Sektor, Limits) · Integrationen (API-Keys) ·
Anzeige (Zahlen-/Datumsformat, Theme) · Daten (Neuberechnung, Export) · API-Tokens.

### Weitere
Hilfe (FAQ + Glossar-Links), Glossar (Lexikon), Admin (User-Management, System-Status,
Recalculation, Cache-Insights), Changelog, Auth-/Legal-Seiten.

---

## 5. Datendomäne (was dargestellt wird)

Kern-Entitäten, die das UI sichtbar macht:

- **Position** — Ticker, Name, Typ (stock/etf/crypto/commodity/cash/pension/real_estate/
  private_equity), Sektor, Währung, Stückzahl, Einstand (cost_basis_chf), aktueller Kurs,
  Bucket, Stil (defensive/compounder/core/opportunistic/cash), Stop-Loss (Preis + Methode),
  nächster Earnings-Termin, „zählt als Cash“-Flag.
- **Transaction** — Typ (buy/sell/dividend/fee/tax/deposit/withdrawal/interest/fx/…),
  Datum, Stück, Preis, Währung, FX-Rate, Gebühren, Steuern, realisierter PnL.
- **Bucket** — Segment/Kategorie (z. B. Core/Satellite); System-Buckets für Immobilien,
  Private Equity, Vorsorge; Farbe, Benchmark, Zielgewicht (% oder CHF), Risk-Rules
  (max-Gewicht, Drawdown-Bremse, Positions-Max).
- **PortfolioSnapshot / BucketSnapshot** — tägliche NAV-Zeitreihe (Wert, Cash, Netto-Cashflow).
- **Watchlist-Item, PriceAlert, PendingDividend, PendingOrder.**
- **Alternative Assets:** Property (+ Mortgage, Income, Expense), PrivateEquityHolding
  (+ Valuation, Dividend), PreciousMetalItem (+ Expense).
- **Screening/Quant:** ScreeningScan/Result, EstimateRevision, EpsQuarterly,
  Form4Transaction.
- **Makro/Markt:** MacroIndicatorCache (VIX/DXY/MOVE), MacroCotSnapshot, MarketIndustry,
  TickerIndustry, EtfHolding.

> Design-Relevanz: CHF ist Basiswährung; Werte sind oft mehrwährungsfähig; Renditen sind
> über die Zeit vergleichbar zu halten (konsistente Formatierung, Vorzeichen, Farbe).

---

## 6. Funktionsumfang (kompakt, nach Domäne)

- **Performance & Rendite:** Total-Return-Breakdown, Monats-/Jahresrenditen, indexierte
  Equity-Kurve vs. Benchmark, realisierte/unrealisierte Gewinne, Gebührenquote.
- **Risiko:** Sharpe/Sortino/Calmar (+ rolling), Volatilität, Information Ratio,
  Max-Drawdown & Dauer, Stop-Loss-Tracking, Bucket-Drawdown-Bremsen & Drift, Stale-Price-
  Erkennung.
- **Konzentration & Overlap:** HHI, ETF-Look-Through (Sektor/Land), Korrelationsmatrix
  (30/90/180/360 Tage), versteckte Doppel-Exponierung über ETFs.
- **Signale & Scoring:** Stock-Scorer (MRS, Relative Strength, Reversal, Breakout),
  Makro-Gate als Filter, ETF-200-Tage-Linien-Alerts, Donchian-Breakouts.
- **Makro:** US-Indikatoren (VIX, DXY, MOVE, 10Y), FRED, CFTC COT (wöchentlich),
  Sektor-Rotation, Schweizer Makro.
- **Screening/Quant:** Composite-Screening (13F + Form 4 + Estimate-Revisionen +
  regelbasiert), EPS-Scanner über breiten Index.
- **Dividenden:** automatische Ex-Date-Erkennung, Forecast (brutto CHF mit FX am Ex-Date),
  Quellensteuer-Behandlung, Wochen-Digest.
- **Import:** CSV/PDF-Parser für Swissquote, IBKR, Pocket; Spalten-Mapping; Auto-Bucket-
  Regeln; Profile.
- **Alternative Assets:** Immobilien (Hypothek/Miete/Kosten), Private Equity (Bewertung,
  Dividenden), Edelmetalle, FIRE-Projektion über das Gesamtvermögen.
- **Alerts (mehrkanalig):** Email (SMTP), Push (ntfy), In-App. Preis-, Regel-, Breakout-,
  200-DMA-, Bucket-Risiko-, Dividenden-Alerts.
- **Sicherheit:** JWT + Refresh-Rotation, TOTP-MFA, Backup-Codes, X-API-Key (scoped),
  Audit-Logs, PII-Verschlüsselung.
- **Externe API:** versionierte `/api/v1/external` mit X-API-Key — volle Schreib-Parität
  zur UI.

> Hintergrund-Worker hält Kurse (60 s), Snapshots, Makro, Earnings, Dividenden-Erkennung,
> Screening-Jobs etc. aktuell — das UI zeigt also weitgehend frische, gecachte Daten.

---

## 7. Aktuelles Design-System (Ist-Zustand zum Abgleich)

### Farbpalette (Dark Theme, Tailwind-Tokens)
| Token | Hex | Verwendung |
|-------|-----|-----------|
| body | `#070a10` | Haupt-Hintergrund (sehr dunkel) |
| card | `#0f1520` | Karten-/Box-Hintergrund |
| card-alt | `#161f2e` | Hover/alternierende Karte |
| border | `#1c2638` | Rahmen |
| text-primary | `#f1f5f9` | Haupttext |
| text-secondary | `#94a3b8` | Labels/Hilfstext |
| text-muted | `#7a8ba3` | Zeitstempel/abgeschwächt |
| primary | `#3b82f6` | Aktionen, Links, Highlights (Blau) |
| success | `#10b981` | Gewinne / positiv (Grün) |
| danger | `#ef4444` | Verluste / negativ (Rot) |
| warning | `#f59e0b` | Warnungen (Gelb) |
| etf | `#14b8a6` / `#2dd4bf` | ETF-Hervorhebung (Türkis) |

### Typografie
- System-Font-Stack (`-apple-system, Segoe UI, Roboto, sans-serif`).
- Überschriften `text-lg/xl font-bold`; Karten-Titel `text-sm font-medium text-secondary`;
  Body `text-sm`; kleine Labels `text-xs text-muted`.
- **Zahlen `tabular-nums`** für saubere Spalten-Ausrichtung.

### Layout & Form
- Sidebar 240 px fest; Hauptinhalt mit Offset.
- Karten: `rounded-lg`, `border border-border`, Padding `p-4/5/6`, Hover `bg-card-alt`.
- Aktive Nav: linker Akzentbalken in primary.
- Schmale 6-px-Scrollbars im Body-Ton.

### Bausteine & Bibliotheken
- **Charts:** Recharts (Line/Bar/Pie/Area) + TradingView-Embed für Kurscharts.
- **Icons:** lucide-react.
- **Chart-Farben:** primary `#3b82f6`, success `#10b981`, danger `#ef4444`,
  benchmark `#6b7280`, grid `#1e293b`.

### Wiederkehrende UI-Patterns
Karten-Grid · Stat-Tiles (Label oben, Wert unten) · Badges (`bg-primary/10 text-primary`) ·
Tab-Bars (Unterstrich, aktiv = primary) · Modals (Overlay `bg-black/50`, zentriert,
Focus-Trap + ESC-Close + Scroll-Lock) · Toasts (Slide-in) · Skeleton-Loader
(`animate-pulse`) · Glossar-Tooltips inline · Such-Autocomplete · Heatmaps (Farbgradient
rot–gelb–grün) · Akkordeons.

### Komponenten-Inventar (Größenordnung)
~26 Pages, ~93 Komponenten. Schwerpunkte: Performance-/Risiko-Karten (~12), Position-/
Portfolio-Management (~8), Screening/Filtering (~12), alternative Assets (4), Buckets (5),
Modals (6+), Layout/Utility (Sidebar, Command-Palette, Toasts, Onboarding).

---

## 8. Hinweise für den Design-Entwurf

- **Zielgerät:** ausschließlich Desktop, große, informationsdichte Ansichten erwünscht.
- **Stimmung:** ruhiges, vertrauenswürdiges Finanz-Cockpit; Dark-Theme; Zahlen im Fokus.
- **Hierarchie:** Performance- und Portfolio-Seiten sind extrem karten-/widget-reich —
  ein gutes Ordnungs-, Gruppierungs- und Verdichtungs-Konzept ist der größte Hebel.
- **Konsistenz der Zahlen:** Vorzeichen, Farbe (grün/rot), CHF-Basis, tabellarische
  Ziffern; Vergleichbarkeit über Zeit nicht durch Formatierung verwischen.
- **Sprache & Ton:** Schweizer Deutsch, neutrale (nicht-imperative) Signalsprache,
  Fachbegriffe per Tooltip erklärbar.
- **Erklärbarkeit:** komplexe Kennzahlen (XIRR, Drawdown, HHI, Faktor-Exposition)
  brauchen niedrigschwellige Erklärungen/Tooltips direkt am Wert.
- **Wiederverwendung:** Bucket-Ansichten spiegeln die Gesamt-Widgets — ein skalierbares
  Karten-/Akkordeon-System lohnt sich.
- **Frei zur Neuinterpretation:** Die obige Palette/Token sind der Ist-Zustand zum
  Abgleich — der Entwurf darf bewusst davon abweichen; danach wird verglichen.
