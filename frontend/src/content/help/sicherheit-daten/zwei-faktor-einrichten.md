---
id: "zwei-faktor-einrichten"
title: "Zwei-Faktor-Anmeldung einrichten"
summary: "So aktivierst du die Anmeldung mit Authenticator-App und sicherst dir die Backup-Codes."
section: "sicherheit-daten"
order: 10
---

Mit der Zwei-Faktor-Authentifizierung (MFA) brauchst du bei jeder Anmeldung zusätzlich einen 6-stelligen Code aus einer Authenticator-App. Ein gestohlenes Passwort reicht dann nicht mehr für den Zugriff.

## Einrichten in den Einstellungen

**Schritt 1:** Öffne **Einstellungen** und wähle den Tab **Konto & Sicherheit**. Im Abschnitt **Zwei-Faktor-Authentifizierung** steht der Status «Inaktiv».

**Schritt 2:** Klicke auf **MFA aktivieren**. OpenFolio zeigt einen QR-Code und darunter den Schlüssel als Text.

**Schritt 3:** Scanne den QR-Code mit deiner Authenticator-App. Du kannst den Schlüssel auch von Hand in die App eintragen.

**Schritt 4:** Gib den 6-stelligen Code aus der App in das Feld «6-stelliger Code» ein und klicke auf **Verifizieren**.

## Backup-Codes sichern

Nach dem Verifizieren öffnet sich das Fenster **Backup-Codes** mit 8 Codes. Jeder Code hat die Form XXXXXXXX-XXXXXXXX und gilt nur einmal.

Die App zeigt die Codes nur in diesem Fenster. Klicke auf **Kopieren**, speichere sie in einem Passwort-Manager oder drucke sie aus, und schliesse das Fenster mit **Fertig**. Unter dem Status siehst du später, wie viele Backup-Codes noch übrig sind.

## Neue Backup-Codes erzeugen

Sind nur noch wenige Codes übrig oder hast du die Liste verloren, erzeugst du neue. Du brauchst dafür deine Authenticator-App.

**Schritt 1:** Öffne **Einstellungen** und wähle den Tab **Konto & Sicherheit**.

**Schritt 2:** Klicke im Abschnitt **Zwei-Faktor-Authentifizierung** auf **Neue Backup-Codes erzeugen**.

**Schritt 3:** Gib den 6-stelligen Code aus der Authenticator-App ein und klicke auf **Codes erzeugen**.

**Schritt 4:** Speichere die 8 neuen Codes und schliesse das Fenster mit **Fertig**.

> Die bisherigen Codes sind ab diesem Moment ungültig, auch die unbenutzten.

## Wenn die Pflicht gilt

Der Betreiber deiner Instanz kann MFA für alle Konten, nur für Admins oder für ausgewählte Konten vorschreiben. Betroffene Konten sehen nach der Anmeldung die Seite **Zwei-Faktor-Authentifizierung einrichten** und klicken dort auf **MFA einrichten**. Die App ist erst danach nutzbar. Der Ablauf bleibt derselbe.

## Anmelden mit MFA

Nach E-Mail und Passwort fragt OpenFolio nach dem **Authenticator-Code**. Gibst du den Code fünfmal falsch ein, sperrt OpenFolio den zweiten Faktor für 15 Minuten.

Hast du keinen Zugriff mehr auf die Authenticator-App, hilft dir [Gerät oder Authenticator verloren](#zwei-faktor-geraet-verloren).

Weitere Konto-Einstellungen findest du unter [Einstellungen konfigurieren](#einstellungen).
