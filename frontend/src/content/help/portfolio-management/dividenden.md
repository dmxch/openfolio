---
id: "dividenden"
title: "Dividenden automatisch erfassen"
summary: "OpenFolio erkennt fällige Dividenden automatisch und schlägt sie zur Bestätigung vor."
section: "portfolio-management"
order: 130
---

OpenFolio kann Dividenden für deine Positionen automatisch erkennen, damit du sie nicht manuell nachtragen musst.

## Automatische Erkennung

Ein täglicher Job (09:30 CET) prüft anhand der Ex-Dividenden-Termine, ob für deine Positionen eine Ausschüttung fällig war. Erkannte Dividenden landen als **Vorschläge** in der Liste der ausstehenden Dividenden — du musst sie nur **bestätigen** oder **verwerfen**.

## Berechnung

Für jeden Vorschlag schätzt OpenFolio den erwarteten Bruttobetrag: Anzahl Anteile × Dividende pro Anteil × Wechselkurs, inklusive einer Berücksichtigung der Quellensteuer. Erst beim Bestätigen wird daraus eine echte Dividenden-Transaktion, die in die Performance einfliesst.

## Wöchentliche Zusammenfassung

Optional sendet OpenFolio sonntags um 09:00 CET eine **Digest-Mail** mit allen noch offenen Dividenden-Vorschlägen der Woche. Aktivierbar unter **Einstellungen → Alerts**.

> Vorteil: Der Vorschlags-Workflow verhindert Doppelerfassungen. Hast du eine Dividende bereits per [CSV-Import](#csv-import) erfasst, kannst du den passenden Vorschlag einfach verwerfen.
