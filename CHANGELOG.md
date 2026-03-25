# Changelog

Alle wichtigen Änderungen an OpenFolio werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

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
