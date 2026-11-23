---
id: "import-fehler"
title: "Häufige Importfehler"
summary: "Fehlermeldungen und Warnungen des CSV-Imports mit Ursache und Abhilfe, dazu die Erkennung von Duplikaten."
section: "import"
order: 50
---

Fehler beim Hochladen erscheinen in einem roten Feld im Import-Assistenten. Warnungen zu einzelnen Zeilen stehen in der Vorschau unter «Warnungen».

## Fehler beim Hochladen

**«Nur CSV-Dateien erlaubt»**, **«Datei ist leer»**: Lade eine CSV-Datei mit Inhalt hoch.

**«Datei zu gross (max. 10 MB)»** und **«Datei enthält mehr als 20000 Zeilen. Bitte in mehrere Dateien aufteilen.»**: Teile die Datei auf.

**«Keine importierbaren Transaktionen gefunden (… übersprungen)»**: Die Interactive-Brokers-Datei enthält nur Zeilen, die der Import auslässt, zum Beispiel Forex oder Optionen. Exportiere die Trades für Aktien und ETFs.

**«Upload nicht gefunden. Bitte CSV erneut hochladen.»**: OpenFolio entfernt Uploads, die älter als 30 Minuten sind. Lade die Datei erneut hoch.

## Warnungen in der Vorschau

**«Zeile N: Unbekannter Typ 'X' — übersprungen»**: Der Import kennt diese Transaktionsart nicht. Erfasse die Zeile von Hand.

**«Zeile N: Ungültiges Datum 'X'»** und **«Zeile N: Unbekanntes Datumsformat: X»**: Die Zeile fehlt in der Vorschau. Korrigiere das Datum in der Datei.

**«N Zeile(n) ohne Betrag in der Datei — der Betrag wird aus Menge × Kurs berechnet.»**: Vergleiche die Beträge mit deiner Abrechnung. Fremdwährungs-Kurse prüfst du unter [Währung falsch](#waehrung-falsch).

**«Ticker «X» enthält Leer- oder Sonderzeichen»**: Setze nach dem Import den Ticker für die Kursdaten, siehe [Kurs fehlt oder ist alt](#kurs-fehlt-oder-alt).

## Duplikate

OpenFolio erkennt ein Duplikat an der Auftragsnummer des Brokers mit gleichem Typ. Es erkennt es auch an gleicher Position, gleichem Datum, gleichem Typ und gleichem Betrag. Die Vorschau markiert die Zeile mit «Duplikat» und importiert sie nicht. Mit dem Häkchen «Trotzdem importieren» erzwingst du den Import.

**«N Zeile(n) sind bereits erfasst, dort aber mit einem anderen Betrag …»**: Das Label «anderer Betrag» markiert diese Zeilen. Die alte Zeile stammt wohl aus einem fehlerhaften Import. Lösche sie unter «Transaktionen» und importiere neu.

## Fehler beim Bestätigen

**«Import überschreitet die maximale Anzahl Positionen (500)»** und **«… Transaktionen (10000)»**: Du hast das Limit pro Konto erreicht.

**«Für dieses Konto läuft bereits ein Import. Bitte kurz warten und erneut versuchen.»**: Warte kurz und bestätige erneut.
