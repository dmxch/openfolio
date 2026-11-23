---
id: "api-schluessel-datenquellen"
title: "API-Schlüssel für Datenquellen"
summary: "Optionale Schlüssel für FRED, FMP und Finnhub eintragen und wissen, was ohne sie fehlt."
section: "self-hosting"
order: 40
selfhostOnly: true
---

OpenFolio läuft auch ohne externe API-Schlüssel. Drei optionale Schlüssel erweitern den Funktionsumfang. Alle drei Dienste bieten einen kostenlosen Zugang.

## Welche Schlüssel es gibt

Der **FRED API Key** liefert die US-Makro-Indikatoren: Buffett Indicator, Arbeitslosenquote, Zinsstruktur und Yield Curve. Ausserdem liefert er die CH-10Y-Rendite. Ohne Key zeigt die Marktklima-Ansicht den Hinweis, den Key in den Einstellungen zu hinterlegen.

Der **FMP API Key** liefert Fundamentaldaten wie Income Statement, Cashflow und Bilanz auf den Detailseiten. Das Free-Tier erlaubt 250 Requests pro Tag. Ohne Key zeigt OpenFolio keine Fundamentaldaten.

Der **Finnhub API Key** liefert Earnings-Termine mit Tageszeit. Das Free-Tier erlaubt 60 Requests pro Minute. Ohne Key fällt OpenFolio auf yfinance zurück, dann ohne Tageszeit.

## Schlüssel in der Oberfläche eintragen

Jeder Nutzer trägt seine eigenen Schlüssel ein. OpenFolio speichert sie verschlüsselt in der Datenbank.

**Schritt 1:** Öffne **Einstellungen** und dann den Tab **Integrationen**.

**Schritt 2:** Füge den Schlüssel im Block des Dienstes ein und klicke auf **Speichern**. Der Status wechselt auf «Verbunden».

**Schritt 3:** Klicke auf **Testen**, um den Schlüssel zu prüfen. Mit **Ersetzen** tauschst du ihn aus, mit **Entfernen** löschst du ihn.

Eine Anleitung zu den übrigen Optionen steht unter [Einstellungen konfigurieren](#einstellungen).

## Schlüssel für den ganzen Server in der .env

Die `.env` kennt zusätzlich `FINNHUB_SYSTEM_API_KEY`, `FMP_SYSTEM_API_KEY` und `FRED_SYSTEM_API_KEY`. Globale Jobs ohne zugehörigen Nutzer verwenden diese Werte. Ist ein System-Key leer, nutzen FMP und FRED den Schlüssel des ältesten aktiven Admin-Kontos. Der Finnhub-Key gehört zum EPS-Scanner. Fehlt er, fällt der Job auf yfinance zurück. Starte danach `docker compose up -d`.

> Hinweis: Diese Schlüssel sind mit `ENCRYPTION_KEY` verschlüsselt. Sichere ihn, wie unter [Backup und Wiederherstellung](#backup-wiederherstellen) beschrieben.
