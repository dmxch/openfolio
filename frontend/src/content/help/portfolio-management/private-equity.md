---
id: "private-equity"
title: "Direktbeteiligungen (Private Equity)"
summary: "Nicht-liquide Beteiligungen mit eigener Bewertungslogik tracken — getrennt von der liquiden Performance."
section: "portfolio-management"
order: 120
---

Direktbeteiligungen (Private Equity) bilden Anteile an nicht-börsengehandelten Gesellschaften ab. Sie werden wie Immobilien und Vorsorge **getrennt vom liquiden Vermögen** geführt.

## Warum separat?

Private-Equity-Anteile sind nicht frei handelbar und haben keinen laufenden Marktkurs. Deshalb werden sie bewusst **nicht in die liquide Performance** (unrealisierte/realisierte Gewinne, Snapshots, Daily Change, Monatsrenditen) eingerechnet. Sie zählen aber zum Gesamtvermögen — mit dem **Netto-Wert je Anteil** (nach Discount, entspricht dem Steuerwert), nicht mit dem Brutto-Wert — und haben einen eigenen [System-Bucket](#buckets) «Private Equity».

## Bewertung erfassen

Statt eines Börsenkurses erfasst du periodische **Bewertungen** pro Anteil: den **Brutto-Wert je Anteil** (gross value), einen **Discount in %** (z.B. Illiquiditäts- oder Holding-Abschlag) und daraus den **Netto-Wert je Anteil**. Der Positionswert ergibt sich aus Anzahl Anteile × Netto-Wert je Anteil.

## Dividenden und Rendite

Ausschüttungen erfasst du als **Dividende pro Anteil**; daraus berechnet OpenFolio die Dividendenrendite bezogen auf den Brutto-Wert. So behältst du Wertentwicklung und Cash-Rückflüsse deiner Beteiligungen im Blick.

> Hinweis: Aktualisiere die Bewertung periodisch (z.B. nach jeder neuen Finanzierungsrunde oder dem Jahresabschluss der Gesellschaft). Zwischen zwei Bewertungen bleibt der erfasste Wert konstant.
