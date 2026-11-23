---
id: "dividende-fehlt"
title: "Dividende fehlt"
summary: "Wie Dividenden in OpenFolio entstehen, wann die automatische Erkennung greift und welche Grenzen sie hat."
section: "fehlerbehebung"
order: 40
---

Eine Dividende erscheint in OpenFolio auf drei Wegen: als automatischer Vorschlag, per Import oder durch deine Eingabe. Fehlt sie, prüfe diese Wege nacheinander.

## Automatischer Vorschlag

Ein Hintergrundprozess prüft täglich um 09:30 Uhr (Zürcher Zeit) die Ex-Dividenden-Termine deiner Aktien, ETFs und Anleihen. Er schaut beim ersten Lauf 90 Tage zurück, danach 35 Tage. Gefundene Dividenden stehen auf dem Dashboard unter «Kommende Dividenden». Du klickst auf «Erfassen» oder «Ignorieren». Das Widget erscheint nur, wenn Vorschläge vorliegen. Es zeigt höchstens sechs.

Die Erkennung hat Grenzen. Sie ist nicht vorgesehen für Krypto, Edelmetalle, Cash, Vorsorge, Immobilien und Private Equity. Sie überspringt eine Position, wenn im Prüffenster ein Aktiensplit liegt. Sie überspringt Termine, an denen du keine Anteile hattest. Liefert der Kursdaten-Anbieter für den Ticker keine Dividendendaten, entsteht kein Vorschlag. Das passiert auch bei einem falschen Ticker, siehe [Kurs fehlt oder ist alt](#kurs-fehlt-oder-alt).

## Import

Aus Swissquote importierst du Dividenden und Capital Gains, aus Interactive Brokers die Cash-Transactions-Datei. Passt eine importierte Dividende zu einem offenen Vorschlag (innerhalb von 35 Tagen), gilt dieser als erfasst. Siehe [Import aus Swissquote](#import-swissquote) und [Import aus Interactive Brokers](#import-interactive-brokers).

## Von Hand erfassen

Öffne das Menü «Aktionen» der Position und wähle «Dividende erfassen». Das geht für Aktien, ETFs und Anleihen. Löschst du die Buchung später, wird der Vorschlag wieder offen.

## Wöchentliche Mail

Unter Einstellungen, Reiter «Alerts», stellst du den Digest «Offene Dividenden» ein. Er erinnert sonntags um 09:00 Uhr an nicht erfasste Dividenden. Mehr zur Erkennung: [Dividenden automatisch erfassen](#dividenden).
