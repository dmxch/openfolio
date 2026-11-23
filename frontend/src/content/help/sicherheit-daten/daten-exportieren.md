---
id: "daten-exportieren"
title: "Daten exportieren"
summary: "So lädst du deine Positionen und Transaktionen als CSV-Datei herunter."
section: "sicherheit-daten"
order: 40
---

OpenFolio exportiert deine Daten als CSV-Dateien. Du öffnest sie in Excel oder einem anderen Tabellenprogramm und kannst sie als eigene Sicherung ablegen.

## Export starten

**Schritt 1:** Öffne **Einstellungen** und wähle den Tab **Daten**.

**Schritt 2:** Klicke im Abschnitt **Daten exportieren** auf **Positionen (CSV)** oder auf **Transaktionen (CSV)**.

Der Browser lädt die Datei herunter. Sie heisst `openfolio-positions-JJJJ-MM-TT.csv` beziehungsweise `openfolio-transactions-JJJJ-MM-TT.csv`. Das Datum ist dein lokales Datum. Schlägt der Export fehl, erscheint die Meldung «Export fehlgeschlagen».

## Inhalt der Positionen-Datei

Die Datei enthält alle aktiven Positionen. Die Spalten lauten: Ticker, Name, Typ, Sektor, Waehrung, Stueck, Einstandswert CHF, Aktueller Kurs und Stop-Loss.

## Inhalt der Transaktionen-Datei

Die Datei enthält alle deine Transaktionen, die neuesten zuerst. Die Spalten lauten: Datum, Typ, Ticker, Stueck, Kurs, Waehrung, FX, Gebuehren, Steuern und Total CHF.

## Format

Beide Dateien trennen die Spalten mit einem Semikolon. Öffnest du sie in einem Tabellenprogramm, wähle das Semikolon als Trennzeichen, falls die Spalten nicht automatisch getrennt erscheinen. Pro Minute sind höchstens 5 Exporte möglich.

## Andere Daten

Alarme, Watchlist und Notizen gehören nicht in diese beiden Dateien. Über die [externe API](#api-erste-abfrage) liest du weitere Bereiche deines Portfolios aus.

Den umgekehrten Weg beschreibt [CSV-Import](#csv-import). Das Löschen von Konto und Daten findest du im Tab **Konto & Sicherheit** unter **Konto löschen**. Es ist unwiderruflich, exportiere deshalb vorher.
