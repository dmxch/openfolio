---
id: "import-pocket-relai"
title: "Import aus Pocket und Relai"
summary: "Welche Bitcoin-Dateien von Pocket und Relai OpenFolio liest und wie Abhebungen und Einzahlungen behandelt werden."
section: "import"
order: 30
---

Für Pocket besteht ein eigener Parser. Relai erkennt OpenFolio an den Spaltennamen und liest die Datei mit einer vorbereiteten Zuordnung. Beide Importe buchen Käufe in Bitcoin auf die Position «BTC-USD».

## Pocket

Die Datei braucht diese Spalten: «type», «date», «reference», «price.currency», «price.amount», «cost.currency», «cost.amount», «fee.currency», «fee.amount», «value.currency» und «value.amount». Das Trennzeichen darf Komma oder Semikolon sein. OpenFolio prüft beide. Das Datum steht im ISO-Format, zum Beispiel «2024-12-20T11:11:08.000Z».

Eine Zeile vom Typ «exchange» wird zu einem Kauf. Die Anzahl Bitcoin steht in «value.amount», der Kurs in «price.amount». Der Betrag ist «cost.amount» plus «fee.amount». Die Spalte «reference» dient als Auftragsnummer für die Duplikat-Erkennung.

Zeilen vom Typ «deposit» (Einzahlung in CHF) überspringt der Import. Bei einer «withdrawal» (Abhebung auf deine Wallet) bucht er nur die Netzwerkgebühr in BTC als Abgang. Die abgehobenen Bitcoin bleiben im Bestand, weil sie nur den Aufbewahrungsort wechseln. Die Vorschau meldet die Summe der Netzwerkgebühren.

## Relai

OpenFolio erkennt eine Relai-Datei an den Spalten «Date», «Transaction Type», «BTC Amount», «BTC Price», «Currency Pair» und «Operation ID». Für die Zuordnung nutzt es ausserdem «Fiat Currency», «Fee» und «Fiat Amount (excl. fees)». Die Typen «Buy» und «Sell» werden zu Kauf und Verkauf. Der Betrag ist «Fiat Amount (excl. fees)» plus «Fee». «Operation ID» dient als Auftragsnummer.

Der Assistent überspringt bei Relai die Spalten- und Typ-Zuordnung und zeigt gleich die Vorschau. Er verarbeitet dabei nur die erste ausgewählte Datei. Importiere mehrere Relai-Dateien deshalb nacheinander.

Fehlermeldungen und Duplikate: [Häufige Importfehler](#import-fehler). Zur Position selbst: [Crypto](#crypto).
