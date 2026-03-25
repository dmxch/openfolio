# Changelog

Alle wichtigen Änderungen an OpenFolio werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

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
