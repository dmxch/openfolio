---
id: "aktien-etfs"
title: "Aktien & ETFs"
summary: "So verwaltest du Aktien und ETFs in deinem Portfolio."
section: "portfolio-management"
order: 40
---

Aktien und ETFs sind die Hauptbausteine deines liquiden Portfolios. OpenFolio unterstützt Titel von allen grossen Börsenplätzen.

## Aktien hinzufügen

Beim Hinzufügen einer Aktie gibst du den **Ticker** ein (z.B. AAPL, NESN.SW, NOVO-B.CO). OpenFolio erkennt den Börsenplatz und lädt automatisch den aktuellen Kurs. Für Schweizer Aktien wird das Suffix .SW verwendet, für britische .L.

> Hinweis: Britische Aktien (.L) werden von yfinance in **Pence** geliefert. OpenFolio rechnet automatisch durch 100, um den Kurs in Pfund darzustellen.

## ETFs und Sektoren

Bei ETFs wird die **Sektorverteilung** automatisch aufgeschlüsselt. Ein S&P-500-ETF wird beispielsweise anteilig auf Technology, Healthcare, Financials usw. verteilt. Das gibt dir ein realistisches Bild deiner tatsächlichen Sektorgewichtung.

## Fremdwährungen

Aktien in Fremdwährung (USD, EUR, GBP usw.) werden automatisch in **CHF umgerechnet**. Der aktuelle Wechselkurs wird laufend aktualisiert. Deine Kostenbasis wird zum historischen Wechselkurs des Kaufdatums berechnet — so ist die Performance-Berechnung exakt.

## Dividenden

Dividendenzahlungen kannst du als Transaktion erfassen oder per [CSV-Import](#csv-import) importieren. Dividenden in Fremdwährung werden automatisch zum Tageskurs in CHF umgerechnet und fliessen in die Gesamtperformance ein.
