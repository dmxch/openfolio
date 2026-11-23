---
id: "waehrung-falsch"
title: "Währung falsch oder Faktor 100 daneben"
summary: "Warum ein Kurs oder Wert in der falschen Währung oder um den Faktor 100 abweicht und wo du die Währung einer Position korrigierst."
section: "fehlerbehebung"
order: 30
---

Stimmt ein Wert nicht, prüfe zuerst die Währung der Position. OpenFolio rechnet den Wert als Anzahl × Kurs × Wechselkurs, und zwar mit dem Wechselkurs der Währung, die bei der Position steht.

## Währung der Position sehen und ändern

In der Portfolio-Tabelle steht vor dem Preis in der Spalte «Kurs» die Kurswährung, zum Beispiel «USD 123.45». Die Spalte «Wert CHF» zeigt den umgerechneten Wert.

**Schritt 1:** Öffne das Menü «Aktionen» der Position und wähle «Bearbeiten».

**Schritt 2:** Ändere im Reiter «Stammdaten» das Feld «Währung». Zur Wahl stehen CHF, USD, EUR, CAD, GBP und JPY.

**Schritt 3:** Klicke auf «Speichern».

Passt der Ticker nicht zu CAD oder GBP, erscheint ein Hinweis, ob du das Suffix .TO oder .L meinst.

## Pence bei London-Titeln

Das Suffix .L sagt nichts über die Währung. Manche Titel an der Londoner Börse notieren in Pence, andere in USD. OpenFolio liest die Kurswährung beim Kursdaten-Anbieter. Bei Pence teilt es den Kurs durch 100 und rechnet in GBP. Ist die Kurswährung nicht bekannt, übernimmt OpenFolio den Kurs nicht.

Trägst du bei einer GBP-Position von Hand einen Pence-Kurs ein, ist der Wert 100-fach zu hoch. Trage den Kurs in Pfund ein.

## Wechselkurs in importierten Buchungen

Die Vorschau des Imports zeigt je Zeile die Währung und den FX-Kurs. Der Punkt neben dem FX-Kurs nennt die Quelle, zum Beispiel «Aktueller Marktkurs». Du kannst den FX-Kurs dort ändern. Krypto und Gold bewertet OpenFolio direkt in CHF.

Mehr zu Fremdwährungen: [Aktien und ETFs](#aktien-etfs). Fehlt der Kurs ganz: [Kurs fehlt oder ist alt](#kurs-fehlt-oder-alt).
