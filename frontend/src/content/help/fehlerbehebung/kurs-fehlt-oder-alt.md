---
id: "kurs-fehlt-oder-alt"
title: "Kurs fehlt oder ist alt"
summary: "Warum eine Position keinen oder einen alten Kurs zeigt und wie du Zeitplan, Anzeige und Ticker prüfst."
section: "fehlerbehebung"
order: 10
---

Zeigt eine Position keinen oder einen alten Kurs, liegt es am Abruf-Zeitplan, an einem falschen Ticker oder am Kursdaten-Anbieter. Prüfe die Punkte in dieser Reihenfolge.

## Wann OpenFolio Kurse abruft

Ein Hintergrundprozess holt die Kurse täglich um 07:00 Uhr (Zürcher Zeit). Montag bis Freitag zwischen 08:00 und 23:00 Uhr wiederholt er den Abruf jede Minute. Ausserhalb dieser Zeiten, also abends, nachts und am Wochenende, läuft nur der Abruf um 07:00 Uhr. Dazwischen zeigt OpenFolio den zuletzt gespeicherten Kurs, solange er höchstens 5 Tage alt ist. Für neue Positionen aus einem Import holt OpenFolio sofort einen Kurs.

## Woran du einen alten Kurs erkennst

Die Seitenleiste zeigt den Stand der Abrufe. «Kurse aktuell» mit Uhrzeit heisst: letzter Abruf vor weniger als einer Stunde. «Kurse von» mit Uhrzeit heisst: bis zu 12 Stunden alt. Danach steht dort «Kurse veraltet». Bei Problemen steht «Timeout» oder «Fehler» mit der Uhrzeit des letzten Erfolgs.

Hat eine Position keinen Kurs, zeigt die Spalte «Kurs» ein «–». Der Wert erscheint mit einem Warndreieck und entspricht dem Einstandswert. Der Hinweis lautet «Kein aktueller Kurs verfügbar — Einstandswert wird angezeigt».

## Manuell aktualisieren

Ein Klick auf die Anzeige in der Seitenleiste startet einen Abruf. Das dürfen nur Administratoren. Andere Konten sehen «Refresh fehlgeschlagen».

## Ticker prüfen

**Schritt 1:** Öffne in der Portfolio-Tabelle das Menü «Aktionen» der Position und wähle «Bearbeiten».

**Schritt 2:** Öffne den Reiter «Kursdaten». Dort steht der Ticker, mit dem OpenFolio den Kurs beim Kursdaten-Anbieter sucht. Klicke auf «Testen».

**Schritt 3:** Meldet OpenFolio «Kein Kurs für 'X' gefunden», stimmt der Ticker oder sein Börsensuffix nicht. Schweizer Titel enden auf .SW, britische auf .L, kanadische auf .TO. Klassen-Aktien schreibst du mit Bindestrich, zum Beispiel BRK-B.

Willst du den Kurs selbst pflegen, stelle «Pricing-Modus» und «Preisquelle» auf «manual» und trage den «Manuellen Kurs» ein. Zu Krypto und Edelmetallen: [Crypto](#crypto) und [Edelmetalle](#edelmetalle).
