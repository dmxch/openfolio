---
id: "import-generisches-csv"
title: "Generisches CSV mit Spaltenzuordnung"
summary: "So importierst du eine CSV-Datei, die kein bekanntes Broker-Format hat: Spalten zuordnen, Typen zuordnen, Vorschau prüfen."
section: "import"
order: 40
---

Erkennt OpenFolio das Broker-Format nicht, führt der Import-Assistent dich durch eine Zuordnung. Du sagst dem Assistenten, welche Spalte deiner Datei welche Bedeutung hat. Die Schritte heissen «Upload», «Spalten», «Typen», «Preview» und «Import».

## Spalten zuordnen

OpenFolio schlägt die Zuordnung anhand üblicher Spaltennamen vor, zum Beispiel «Datum», «Symbol», «Anzahl» oder «Kurs». Pflichtfelder sind mit einem roten Stern markiert: «Datum», «Typ», «Ticker», «Anzahl», «Preis» und «Währung». Optional sind «ISIN», «Gebühren», «Nettobetrag», «Name», «Auftragsnummer», «FX-Rate» und «Notizen». Eine Spalte darf nur einem Feld zugeordnet sein. Sonst erscheint «Spalte bereits verwendet», und «Weiter» bleibt gesperrt.

## Typen zuordnen

**Schritt 1:** Ordne jedem Wert der Typ-Spalte einen OpenFolio-Typ zu, zum Beispiel «Kauf» oder «Verkauf». Werte, die OpenFolio nicht kennt, stehen zunächst auf «Überspringen».

**Schritt 2:** Wähle «Überspringen» für Zeilen, die du nicht importieren willst.

Ist die Typ-Zelle einer Zeile leer, behandelt OpenFolio die Zeile als Kauf.

## Was die Datei erfüllen muss

Das Datum liest OpenFolio als JJJJ-MM-TT oder TT-MM-JJJJ (beide auch mit Uhrzeit), TT.MM.JJJJ, TT/MM/JJJJ oder MM/TT/JJJJ. Fehlt in einer Zeile das Datum, lässt der Import sie ohne Hinweis weg. Bei Zahlen entfernt OpenFolio Apostrophe als Tausendertrenner. Steht nur ein Komma in der Zahl, gilt es als Dezimaltrenner.

Heisst die Betragsspalte «Total CHF», gilt der Betrag als CHF. Bei Käufen und Verkäufen in Fremdwährung, die Anzahl, Preis und Wechselkurs tragen, rechnet OpenFolio den Betrag aus Anzahl × Preis × Wechselkurs plus Gebühren neu. Fehlt der Betrag, berechnet OpenFolio ihn aus Anzahl × Preis und warnt dich.

## Vorschau

In der Vorschau kannst du Datum, Ticker, Name, Anzahl, Kurs, FX, Gebühren, Steuern, Total und Klasse ändern oder eine Zeile entfernen. Fehler und Warnungen: [Häufige Importfehler](#import-fehler). Allgemeines zum Import: [CSV-Import](#csv-import).
