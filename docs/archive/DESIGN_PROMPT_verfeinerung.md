# Claude-Design-Prompt — Runde 2: Verfeinerung bestehender Screens

> In das bestehende Claude-Design-Projekt **„OpenFolio Portfolio-Manager"** geben.
> Ziel: ein paar bestehende Screens **verfeinern**, weil sie die echte App noch zu stark
> vereinfachen. **Kein** neues Designsystem — die etablierten Tokens, Layout-Muster und
> Komponenten **strikt** beibehalten (IBM Plex Sans/Mono, Palette bg `#0a0d12` / card `#11151d`
> / border `#222a36` / Akzent `#5b8def` / grün `#45c08a` / rot `#e8625a` / amber `#e0a64b`
> / teal `#29c3b1`; Cards radius 11px; sticky Per-Page-Header; Filter-Chips; Ticker-Chips;
> Heatmap-Zellen; Modal-Muster aus SmartMoney). **Desktop-only**, Deutsch (Schweiz, kein ß),
> neutrale Signal-Sprache.

Bitte die **bestehenden** `.dc.html`-Dateien aktualisieren (nicht neue Screens anlegen, ausser wo unten anders vermerkt).

---

## 1) Portfolio — alle Anlageklassen abbilden (wichtigster Punkt)

Das aktuelle `Portfolio.dc.html` zeigt EINE vereinheitlichte Tabelle über alle Klassen. Die echte App verwaltet je Klasse **eigene, fachspezifische Felder**, die in einer flachen Tabelle verloren gehen. Bitte Portfolio so überarbeiten, dass **jede Klasse vollständig dargestellt und verwaltbar** ist — im gleichen Look.

Empfohlene Struktur (Reihenfolge top→bottom):
1. **Summary-Tiles** (wie gehabt): Gesamtwert, Tag, Unrealisiert, Realisiert YTD, Cash-Quote.
2. **Aktien & ETFs** — die bestehende Positions-Tabelle (Ticker, Name, Typ, Bucket, Stück, Einstand, Kurs, Wert, Tag, PnL CHF, PnL %) **plus Stop-Loss-Spalte/Indikator** und Zeilen-Aktionen (Bearbeiten/Löschen/Stop-Loss/Buchung) via Hover oder Kebab-`⋯`. Filter-Chips bleiben.
3. Darunter je eine **kompakte Klassen-Sektion** (Karte mit eigener Mini-Tabelle + „+"-Button), weil jede andere Felder hat:
   - **Immobilien:** Objekt, Marktwert, **Hypothek (SARON)**, Eigenkapital, Wertänderung. (Hypothek ist Pflicht — darf nicht fehlen.)
   - **Private Equity / Direktbeteiligungen:** Firma, Commitment/NAV, Anteil %, unrealisiert.
   - **Edelmetalle:** Typ, Menge (oz), Spot, Wert CHF, Anteil.
   - **Krypto:** Coin, Menge, Kurs, Wert CHF, PnL, Anteil.
   - **Liquidität (Cash):** Bank, IBAN, Währung, Saldo, Wert CHF, Anteil — inkl. **„count-as-cash"-ETF** (live bepreist, Badge `ETF · live`).
   - **Vorsorge (Säule 3a):** Konto, Anbieter, Betrag CHF, Anteil + Hinweis „Gebundene Vorsorge, nicht liquide".
   Jede Sektion mit Total-Zeile und Leerzustand.

Ziel: nichts geht verloren — die Aufräum-Optik bleibt, aber die fachliche Tiefe je Klasse ist sichtbar und bearbeitbar.

## 2) Watchlist & StockDetail — 18-Punkte-Checkliste (statt 8)

Die echte Kauf-Checkliste hat **18 Punkte in 6 Kategorien** (je 3): **Price Action · Earnings · Bewertung · Qualität · Wachstum · Sentiment**. Bitte:
- `Watchlist.dc.html`: Score als **„n/18"**, die aufklappbare Checkliste in 6 Kategorien-Gruppen (je 3 Kriterien) statt 8 flacher Punkte.
- `StockDetail.dc.html`: die Score-Karte ebenfalls auf 18 Punkte / 6 Kategorien anheben.

## 3) Smart Money — volle Filter-Sidebar + Pagination

`SmartMoney.dc.html` zeigt nur eine schlanke Chip-Leiste. Real gibt es eine **linke Filter-Sidebar**:
- **Min-Score-Slider** (0–100)
- **Sektor**-Multiselect
- **Sektor-Momentum** (positiv/neutral/negativ)
- **Signal-Typen** (mehrfach): 13F-Zufluss, Insider Form 4, Buyback, Aktivist, Congress-Trade, SIX-Insider, Estimate-Revision
- **Konviktion / „Schwur"** (1× / 2× / 3×)
Plus **Pagination** unter dem Karten-Grid (Seite x/y · n Ticker). Das Detail-Modal bleibt.

## 4) EPS-Scanner — volle Filter-Sidebar + Pagination

`EPS-Scanner.dc.html` zeigt nur Top-Chips. Real gibt es eine **linke Filter-Sidebar**:
- Toggles **Super-Quartal / Rekord-Quartal / Turnaround**
- **Min-Quartale-Slider** (6–40)
- **Sektor**- und **Index**-Multiselect (S&P 500, MidCap 400, SmallCap 600, Watchlist)
- **Suche**
- **Schwellenwert-Einstellungen** (aufklappbares Panel)
Plus **Pagination**. Die Quartals-Heatmap-Tabelle + Staleness-Legende bleiben.

## 5) Bitte ausserdem prüfen / einsortieren

- **Performance:** sicherstellen, dass diese realen Bausteine je einen klaren Platz in den 5 Tabs haben — **Realisierte Gewinne** (Tabelle), **Gebühren/Steuern**, **Trade-Journal**, **Bucket-Korrelationsmatrix**, **Dividenden-Yield-on-Cost**, **Netto-Vermögen** (Bilanz: Aktiven vs. Hypotheken), **Tagesveränderung**.
- **Branchen:** zusätzliche **Flow-Spalten** (Marktkap. + Δ, Turnover %, relatives Volumen, Top-1-Konzentration) und **Drill-down** in die Einzeltitel je Industrie; Filter Period/MCap/„konzentrierte ausblenden".
- **Marktklima:** **kommende Dividenden** als Vorschau-Widget ergänzen.

---

**Bitte beibehalten:** gleiches Designsystem/Tokens, Sidebar-Import (`<dc-import name="Sidebar" active="…">`), Desktop-only, Deutsch (CH), neutrale Signal-Sprache. Nur die genannten Screens anfassen.
