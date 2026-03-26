# Changelog

Alle wichtigen Änderungen an OpenFolio werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.15.6] — 2026-03-26

### Behoben
- Direktbeteiligungen-Widget: Farbige Linie (emerald) an der oberen Kante hinzugefügt — konsistent mit allen anderen Portfolio-Widgets

## [0.15.5] — 2026-03-26

### Hinzugefügt
- Aktien & ETFs: "Dividende erfassen" im Drei-Punkte-Menü (⋮) — öffnet Transaktionsformular mit Typ Dividende vorausgewählt

## [0.15.4] — 2026-03-26

### Behoben
- Private Equity: Unrealisierter Gewinn/Verlust und investiertes Kapital werden jetzt aus der Gesamtrendite-Karte ausgeschlossen (total_return_service.py)
- Private Equity: PE-Positionen fliessen nicht mehr in MWR-Fallback-Berechnung ein
- Private Equity: Komplett aus Snapshot-Berechnungen entfernt (war faelschlicherweise als cost_basis inkludiert, verursachte -89K Phantom-Cashflow in XIRR)
- Private Equity: Aus Portfolio-History-Berechnung entfernt (history_service.py)
- Snapshots regeneriert nach PE-Entfernung (727 Snapshots, sauber)
- XIRR Diagnose-Report erstellt (XIRR_DIAGNOSE.md): 11.36% annualisiert, plausibel, alle 12 PE-Ausschluss-Stellen verifiziert

## [0.15.3] — 2026-03-26

### Behoben
- Private Equity: Wird jetzt korrekt aus allen liquiden Performance-Berechnungen ausgeschlossen (Heute, Gesamtrendite, YTD, Monatsrenditen, XIRR, Snapshots)
- Private Equity: current_price bleibt NULL wenn keine Bewertung hinterlegt ist (kein falscher −90K Verlust mehr)
- Private Equity: In Liquides Vermögen, Daily Change, History und Snapshot-Berechnung gleich behandelt wie Vorsorge/Immobilien

## [0.15.2] — 2026-03-26

### Geändert
- UI Polish: Alle Portfolio-Widgets an das Design des Direktbeteiligungen-Widgets angeglichen — grössere Titel, farbige Icons, ausgefüllte Add-Buttons

## [0.15.1] — 2026-03-26

### Behoben
- Direktbeteiligungen: Drei-Punkte-Menü (⋮) auf jeder Holding-Zeile mit Aktionen "Bewertung hinzufügen", "Dividende hinzufügen", "Bearbeiten", "Löschen"

## [0.15.0] — 2026-03-26

### Hinzugefügt
- Neues Widget: Direktbeteiligungen / Private Equity — nicht-börsenkotierte Unternehmensbeteiligungen mit jährlicher Steuerwert-Bewertung und Dividendenhistorie
- Private Equity: Drei neue Tabellen (Holdings, Valuations, Dividends) mit Fernet-Verschlüsselung für PII
- Private Equity: Vollständige CRUD-API mit 12 Endpoints (Holdings, Bewertungen, Dividenden)
- Private Equity: Position-Sync für Gesamtvermögen-Tracking (analog Edelmetalle)
- Private Equity: Automatische Berechnung von Netto-Steuerwert (Pauschalabzug) und Dividenden-Beträgen (Verrechnungssteuer)
- Private Equity: Detail-Ansicht mit Bewertungshistorie, Dividendenhistorie und Kennzahlen
- Private Equity: Eigene Kategorie "Private Equity" im Sektor-Chart
- Private Equity: Wird NICHT in liquide Performance eingerechnet (wie Vorsorge/Immobilien)

## [0.14.0] — 2026-03-26

### Hinzugefügt
- Neue Alert-Kategorie: "ETF unter 200-DMA (Kaufkriterien)" — benachrichtigt wenn breite Index-ETFs (27-Ticker Whitelist) unter die 200-Tage-Linie fallen
- ETF 200-DMA Alerts prüfen sowohl Portfolio-Positionen als auch Watchlist-Einträge
- E-Mail-Benachrichtigung für ETF 200-DMA Alerts (aktivierbar in Einstellungen, tägliche Deduplizierung)
- Worker-Job für ETF 200-DMA E-Mail-Alerts (täglich 22:35 CET nach US-Marktschluss)
- Positiver Alert-Stil (grün, TrendingUp-Icon) für Kaufkriterien-Alerts

### Geändert
- ETF 200-DMA Whitelist aus `scoring_service.py` in gemeinsame Konstante `sector_mapping.py` extrahiert (DRY)

## [0.13.0] — 2026-03-26

### Hinzugefügt
- Portfolio-Sektorchart: ETF-Sektorgewichtungen werden aufgelöst — OEF, CHSPI, EIMI verteilen ihren Marktwert anteilig auf die hinterlegten Sektoren statt als "Multi-Sector" zu klumpen

### Behoben
- TradingView Mini-Widget (Portfolio-Tabelle, Watchlist): Symbol-Mapping für .SW-Ticker (z.B. CHSPI.SW → SIX:CHSPI) — bisher wurde der rohe yfinance-Ticker übergeben
- TradingView-Widgets: Graceful Fallback bei nicht verfügbaren Symbolen (z.B. EIMI.L) — Mini-Widget zeigt "Chart nicht verfügbar", Hauptchart zeigt Fallback mit Link zu TradingView

### Geändert
- TradingView Symbol-Mapping in gemeinsame Utility-Funktion `toTradingViewSymbol()` extrahiert (DRY)

## [0.12.0] — 2026-03-25

### Hinzugefügt
- Immobilien: SARON-Hypotheken mit Marge — dynamische Zinsberechnung (Marge + SARON-Leitzins, Floor auf Marge)
- Immobilien: Effektiver Zinssatz wird im Hypothek-Formular live berechnet und in der Tabelle angezeigt
- Immobilien: Hypothek-Tabelle zeigt bei SARON Subtext "Marge X.XXX%"

## [0.11.0] — 2026-03-25

### Hinzugefügt
- Transaktionen: Ticker-Autocomplete mit Suche (bestehende Positionen + yfinance) ersetzt Positions-Dropdown
- Transaktionen: Positionen werden automatisch erstellt wenn Ticker neu ist (gleicher Flow wie CSV-Import)
- Transaktionen: Erweiterte Währungsauswahl (JPY, SEK, NOK, DKK, AUD, HKD, SGD)
- API: Neuer Endpoint `GET /api/stock/search?q=...` für Ticker-Suche
- Pocket (pocketbitcoin.com) CSV-Import mit Auto-Detection (nur BTC-Käufe, deposit/withdrawal werden übersprungen)
- Watchlist: Resistance-Level (Breakout) manuell setzen über Crosshair-Button im Actions-Bereich

### Geändert
- Watchlist: "Ticker analysieren" öffnet jetzt die volle Detailseite (Chart, Fundamentals, Score) statt nur den Score inline
- Portfolio: Resistance-Level aus dem Positions-Editor entfernt (jetzt nur noch über Watchlist)

## [0.10.0] — 2026-03-25

### Hinzugefügt
- Portfolio: "Position hinzufügen" Button bei Aktien & ETFs und Crypto mit Weiterleitung zu Transaktionen
- Portfolio: Empty States bei leeren Aktien/ETF- und Crypto-Tabellen mit Buttons "Transaktion erfassen" und "CSV importieren"
- Immobilien: Dreipunkte-Menü (⋮) als Mobile-Alternative zum Rechtsklick-Kontextmenü
- Immobilien: "Immobilie löschen" Option im Kontextmenü
- Changelog-Seite unter /changelog mit Versions-Link im Footer

### Behoben
- Immobilien: Netto-Berechnung rechnete Hypothekarkosten doppelt ein (Ausgaben + Zinsen/Amortisation statt nur Ausgaben)

## [0.9.0] — 2026-03-25

### Hinzugefügt
- IBKR Flex Query CSV-Import (Auto-Erkennung, 22 Börsen-Mappings)
- 3-Punkt-Umkehr-Erkennung im Setup-Score (Kriterium #19)
- Versionsnummer im Footer
- Self-Hosting-Dokumentation (Reverse Proxy, CORS, Override)

### Behoben
- JPY-Dividenden wurden nicht in CHF umgerechnet
- Portfolio-Daten nach Import/Erfassung erst nach Hard Refresh sichtbar
- Fresh Install: Fehlende Tabellen bei erstmaliger DB-Erstellung
- Admin-User Race Condition bei mehreren Uvicorn-Workers
- Immobilien-Akkordeon per Default aufgeklappt

### Geändert
- CORS_ORIGINS aus Environment statt hardcoded
- Backend-Port auf localhost für Reverse Proxy
- Score-System: 18 → 19 Kriterien (alle 4 Strategy-Regeln implementiert)
