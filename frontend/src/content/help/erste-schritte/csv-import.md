---
id: "csv-import"
title: "CSV-Import"
summary: "Importiere Transaktionen direkt aus deinem Broker-Export (Swissquote, IBKR, Pocket, Relai)."
section: "erste-schritte"
order: 40
---

OpenFolio unterstützt den direkten Import von Transaktionen aus den CSV-Dateien mehrerer Broker: **Swissquote**, **Interactive Brokers (IBKR)**, **Pocket** (Schweizer Bitcoin-Börse) und **Relai** (Krypto). Das Format wird automatisch erkannt — das spart dir die manuelle Eingabe und stellt sicher, dass alle Daten korrekt übernommen werden.

## CSV-Datei vorbereiten

Exportiere deine Transaktionshistorie aus deinem Broker als CSV-Datei und lade sie unverändert hoch — OpenFolio erkennt das Format automatisch. Die technischen Details unterscheiden sich je nach Broker: Swissquote nutzt Latin-1-Encoding mit Semikolon, Interactive Brokers UTF-8 mit Komma, Pocket und Relai UTF-8 mit Semikolon. Du musst nichts daran ändern.

## Import-Vorschau

Nach dem Upload siehst du eine **Vorschau** aller erkannten Transaktionen. Hier kannst du prüfen, ob Ticker, Stückzahl und Preise korrekt erkannt wurden. Erst wenn du die Vorschau bestätigst, werden die Daten in dein Portfolio übernommen.

## Was wird importiert?

Der Import erkennt automatisch Käufe, Verkäufe und Dividenden. **Teilausführungen** mit derselben Order-ID werden intelligent zu einer Transaktion zusammengefasst (gewichteter Durchschnittspreis, summierte Gebühren) — Dividenden und Gebühren werden dabei nicht aggregiert. Börsengehandelte **Anleihen-ETFs** werden regulär importiert und anhand des Fondsnamens der Assetklasse Anleihen zugeordnet. Übersprungen werden bei Swissquote und IBKR nur **Direktanleihen** — einzelne Obligationen, die in Prozent vom Nominal notieren und separate Stückzinsen abrechnen. Dieses Datenmodell unterstützt OpenFolio aktuell nicht; solche Transaktionen erscheinen in der Vorschau als übersprungen (Pocket und Relai sind reine Kryptobörsen ohne Anleihen). Der Import erkennt zudem **Duplikate** anhand der Broker-Order-ID und blendet bereits vorhandene Transaktionen aus.

> Hinweis: Schweizer Aktien erhalten automatisch das Suffix **.SW**, irische und luxemburgische ETFs das Suffix **.L**. Die Zuordnung erfolgt über die ISIN bzw. den Börsenplatz. Fehlende historische Wechselkurse für Fremdwährungs-Transaktionen lädt OpenFolio automatisch nach (Broker-Forex-Paare oder yfinance, mit USD als Cross-Rate-Fallback).

## Nach dem Import

Nach einem erfolgreichen Import werden alle Positionen automatisch neu berechnet. Die aktuellen Kurse werden abgerufen und die Performance-Daten aktualisiert. Du findest die importierten Transaktionen unter [Transaktionen](#transaktionen).
