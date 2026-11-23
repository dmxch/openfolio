---
id: "import-interactive-brokers"
title: "Import aus Interactive Brokers"
summary: "Welche Abschnitte und Felder einer Flex-Query-Datei OpenFolio liest und was beim Import übersprungen wird."
section: "import"
order: 20
---

OpenFolio importiert CSV-Dateien aus Flex Queries von Interactive Brokers. Es gibt zwei Formate: Trades und Cash Transactions. OpenFolio erkennt beide an den Spaltennamen der ersten Zeile.

## Trades

Die Datei braucht Komma als Trennzeichen und die Spalte «Buy/Sell». Erkannt wird sie an Spalten wie «Symbol», «AssetClass», «IBCommission», «TradePrice» und «TradeMoney». Zusätzlich liest OpenFolio «TradeDate», «Quantity», «Taxes», «ISIN», «CurrencyPrimary», «ListingExchange», «FXRateToBase» und «Description». Das Datum steht als JJJJMMTT oder JJJJ-MM-TT.

Importiert werden die Anlageklassen «STK» und «ETF», und zwar nur Zeilen vom Typ «ExchTrade» oder «FracShare». Übersprungen werden Forex, Optionen, Futures, Anleihen, Warrants und CFDs. Die Vorschau nennt die Zahl der übersprungenen Zeilen je Kategorie. Direktanleihen sind ein anderes Datenmodell. Anleihen-ETFs wie IB01 liefert Interactive Brokers als ETF, sie werden normal importiert.

Enthält die Datei mehrere Abschnitte, liest OpenFolio nur den ersten. Ein Wechselkurs-Abschnitt dahinter stört nicht.

Teilausführungen mit gleichem Datum, Symbol und gleicher Richtung fasst OpenFolio zusammen. Als Gebühren gelten «IBCommission» plus «Taxes». Fehlt «FXRateToBase», holt OpenFolio den historischen Wechselkurs. Das Börsen-Suffix leitet OpenFolio aus «ListingExchange» ab, sonst aus dem Länderkürzel der ISIN.

## Cash Transactions

Dieses Format braucht die Spalten «ClientAccountID», «Amount», «Type», «FXRateToBase» und «CurrencyPrimary». OpenFolio liest daraus Zeilen vom Typ «Dividends» und «Payment In Lieu Of Dividends». Die Quellensteuer («Withholding Tax») rechnet es der Dividende mit gleichem Symbol und Datum zu.

Zinsen, Einzahlungen und Auszahlungen, sonstige Gebühren und alle anderen Typen überspringt der Import. Eine negative Dividende (Storno) importiert er nicht. Buche sie von Hand, siehe [Transaktionen](#transaktionen).

Allgemeine Hinweise und Fehlermeldungen: [CSV-Import](#csv-import) und [Häufige Importfehler](#import-fehler).
