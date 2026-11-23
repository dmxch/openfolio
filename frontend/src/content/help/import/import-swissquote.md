---
id: "import-swissquote"
title: "Import aus Swissquote"
summary: "Welche Swissquote-Datei OpenFolio erwartet, welche Transaktionsarten der Import erkennt und was er überspringt."
section: "import"
order: 10
---

OpenFolio liest den Transaktionsexport von Swissquote direkt ein. Du lädst die CSV-Datei unverändert hoch. OpenFolio erkennt das Format an den Spaltennamen.

## Welche Datei vorliegen muss

Es braucht eine CSV-Datei mit deiner Transaktionshistorie, deutschen Spaltenüberschriften und Semikolon als Trennzeichen. OpenFolio erkennt sie an den Spalten «Transaktionen» und «Stückpreis». Gelesen werden ausserdem «Datum», «Auftrag #», «Symbol», «Name», «ISIN», «Anzahl», «Kosten», «Nettobetrag», «Währung Nettobetrag» und «Nettobetrag in Kontowährung».

Das Encoding erkennt OpenFolio selbst. Datumsangaben wie «TT-MM-JJJJ hh:mm:ss» (auch mit Punkten, auch ohne Uhrzeit) sind lesbar. Zahlen brauchen einen Dezimalpunkt. Apostrophe als Tausendertrenner entfernt der Import. Eine Datei darf höchstens 10 MB und 20000 Zeilen haben.

## Import starten

**Schritt 1:** Öffne die Seite «Transaktionen» und klicke auf «Batch-Import». Alternativ öffnest du Einstellungen, Reiter «Daten», und klickst auf «Transaktionen importieren (CSV)».

**Schritt 2:** Wähle eine oder mehrere Dateien aus.

**Schritt 3:** Prüfe die Vorschau und klicke auf «N Transaktionen importieren».

## Erkannte Transaktionsarten

Der Import erkennt Kauf, Verkauf, Dividende, Capital Gain, Zahlung, Auszahlung, Depotgebühren, Spesen, Zinsen, Berichtigungen sowie Forex-Gutschriften und Forex-Belastungen. Bei Dividenden gilt «Stückpreis» als Bruttobetrag und «Kosten» als Quellensteuer. Zeilen ohne Symbol und ohne ISIN, zum Beispiel Einzahlungen, bucht OpenFolio nicht.

## Was der Import überspringt

Unbekannte Transaktionsarten stehen als Warnung in der Vorschau. Direktanleihen, erkennbar am Prozentzeichen im «Stückpreis», überspringt OpenFolio ebenfalls. Börsengehandelte Anleihen-ETFs importiert es normal.

## Teilausführungen und Fremdwährungen

Zeilen mit gleicher «Auftrag #» und gleichem Symbol fasst OpenFolio zu einer Transaktion zusammen. Den Wechselkurs nimmt es zuerst aus den Forex-Paaren der Datei, dann aus den Datei-Spalten, dann als historischen Kurs. Fehlt auch der, gilt der aktuelle Marktkurs. Die Farbe des Punkts neben dem FX-Kurs in der Vorschau zeigt die Quelle.

Aus dem Länderkürzel der ISIN bildet OpenFolio das Ticker-Suffix: CH ergibt .SW, IE, LU und GB ergeben .L, CA ergibt .TO. Bei anderen Ländern bleibt das Suffix leer. Prüfe diese Ticker, siehe [Kurs fehlt oder ist alt](#kurs-fehlt-oder-alt). Fehlermeldungen findest du unter [Häufige Importfehler](#import-fehler).
