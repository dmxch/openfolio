---
id: "api-schluessel-erstellen"
title: "API-Token erstellen und widerrufen"
summary: "So erzeugst du einen API-Token für eigene Skripte und widerrufst ihn wieder."
section: "api"
order: 10
---

Mit einem API-Token greifen eigene Skripte oder externe Programme auf deine OpenFolio-Daten zu, ohne dass sie dein Passwort kennen. Du verwaltest die Tokens in den Einstellungen.

## Token erzeugen

**Schritt 1:** Öffne **Einstellungen** und wähle den Tab **API-Tokens**. Dort klickst du auf **Token erzeugen**.

**Schritt 2:** Gib im Fenster «Neuen API-Token erstellen» einen **Namen** ein, höchstens 100 Zeichen. Der Name hilft dir, den Token später wiederzuerkennen.

**Schritt 3:** Trage bei «Ablauf in Tagen (optional)» eine Zahl zwischen 1 und 3650 ein. Lässt du das Feld leer, läuft der Token nicht ab.

**Schritt 4:** Gib zur Bestätigung dein **aktuelles Passwort** ein und klicke auf **Erstellen**. Pro 15 Minuten kannst du höchstens 5 Tokens erstellen.

## Rechte

Jeder Token darf lesen. Mit dem Schalter **Schreiben** erlaubst du zusätzlich Änderungen über die API. Ohne diesen Schalter lehnt OpenFolio jede Änderung mit dem Fehler 403 ab. Du kannst das Recht nach dem Erstellen nicht mehr ändern. Brauchst du andere Rechte, widerrufe den Token und erstelle einen neuen.

## Der Token erscheint nur einmal

Nach dem Erstellen zeigt das Fenster «Token erstellt» den vollständigen Token. Er beginnt mit `ofk_`. OpenFolio zeigt ihn **nur einmal**. Kopiere ihn mit **Kopieren** und bewahre ihn zum Beispiel in einem Passwort-Manager auf. In der Liste siehst du danach nur noch den Anfang des Tokens, den Namen, die Rechte («Lesen», «Schreiben») und das Datum der letzten Nutzung.

## Token widerrufen

Klicke in der Liste auf das Papierkorb-Symbol und bestätige mit **Widerrufen**. Der Token ist sofort ungültig, und Programme, die ihn nutzen, verlieren den Zugriff. Setzt du dein Passwort über den Link «Passwort vergessen?» zurück, widerruft OpenFolio alle Tokens automatisch.

Wie du den Token einsetzt, steht unter [Erste Abfrage gegen die externe API](#api-erste-abfrage).
