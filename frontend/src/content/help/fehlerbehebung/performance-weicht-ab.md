---
id: "performance-weicht-ab"
title: "Performance weicht vom Broker ab"
summary: "Welche Renditemasse OpenFolio zeigt und warum sie von der Auswertung deines Brokers abweichen können."
section: "fehlerbehebung"
order: 20
---

OpenFolio rechnet mit festen Definitionen. Zahlen deines Brokers können abweichen, weil Mass, Währung und Datenbasis verschieden sind. Die folgenden Punkte helfen dir, die Ursache zu finden.

## Welche Masse OpenFolio zeigt

Die Performance einer Position ist ((Wert / Kostenbasis) − 1) × 100. Der Wert ist Anzahl × Kurs × Wechselkurs. Die Kostenbasis ist die Summe der CHF-Beträge von Käufen und Einlieferungen zum Buchungszeitpunkt, inklusive Gebühren. Ein Verkauf senkt sie anteilig über den gewichteten Durchschnittspreis.

Monatsrenditen berechnet OpenFolio mit Modified Dietz. Jahres-, YTD- und Gesamtrendite sind XIRR, also geldgewichtet auf 365-Tage-Basis. Konvergiert die XIRR eines Jahres nicht, verkettet OpenFolio die Monatsrenditen. Mehr dazu: [Performance verstehen](#performance).

## Häufige Ursachen

**Anderes Mass:** Zeigt dein Broker eine andere Methode, etwa eine zeitgewichtete Rendite, stimmen die Zahlen nicht überein. Vergleiche nur gleiche Masse.

**Währung:** Die Kostenbasis nutzt den Kurs zum Kaufzeitpunkt, der Wert den aktuellen. «Perf %» enthält deshalb den Währungseffekt. Die Spalte «FX %» zeigt den Währungsanteil. Der Tooltip trennt Kursanteil und Währungsanteil.

**Dividenden und Gebühren:** «Perf %» einer Position enthält Gebühren, aber keine Dividenden. Die «Gesamtrendite» auf der Seite «Performance» zählt Dividenden nach Quellensteuer, Kapitalgewinne und Zinsen mit.

**Ausgeschlossene Klassen:** Immobilien und Private Equity fehlen in der Wertreihe von Dietz und XIRR. Ihre Buchungen zählen aber als Cashflow. Vorsorge gehört zum Gesamtvermögen, fehlt aber in den liquiden Sichten. Cash und Vorsorge zeigen keinen Gewinn und keinen Verlust.

**Fehlende oder falsche Daten:** Ein fehlender Kauf, ein falsches Datum oder eine falsche Währung verändern die Kostenbasis. Fehlt ein Kurs ganz, zeigt OpenFolio den Einstandswert, siehe [Kurs fehlt oder ist alt](#kurs-fehlt-oder-alt). Prüfe deine Buchungen unter [Transaktionen](#transaktionen).
