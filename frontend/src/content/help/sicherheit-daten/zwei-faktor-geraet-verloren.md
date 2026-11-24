---
id: "zwei-faktor-geraet-verloren"
title: "Gerät oder Authenticator verloren"
summary: "Welche Wege du hast, wenn du den Code deiner Authenticator-App nicht mehr abrufen kannst."
section: "sicherheit-daten"
order: 20
---

Hast du dein Handy oder deine Authenticator-App verloren, brauchst du einen Backup-Code. OpenFolio kennt keinen anderen Weg an dir vorbei.

## Mit einem Backup-Code anmelden

Beim Einrichten von MFA hast du 8 Backup-Codes erhalten. Jeder Code gilt nur einmal.

**Schritt 1:** Melde dich mit E-Mail und Passwort an. OpenFolio fragt danach nach dem **Authenticator-Code**.

**Schritt 2:** Klicke über dem Feld auf **Backup-Code verwenden**. Das Feld heisst jetzt «Backup-Code».

**Schritt 3:** Gib einen deiner Codes ein und bestätige. Der Code hat die Form XXXXXXXX-XXXXXXXX. Das Feld setzt den Bindestrich selbst. Der Code ist danach verbraucht.

Wie viele Codes übrig sind, zeigt dir **Einstellungen** im Tab **Konto & Sicherheit** unter «Backup-Codes verbleibend».

## Nach der Anmeldung

Jede weitere Anmeldung ohne Authenticator braucht einen weiteren Backup-Code. In der App kannst du MFA nicht auf ein neues Gerät umziehen und keine neuen Backup-Codes erzeugen.

> Wende dich an den Betreiber deiner Instanz, solange du noch Backup-Codes hast. Sind alle Codes verbraucht, kommst du nicht mehr in das Konto.

## Was ein Passwort-Reset nicht ändert

Ein neues Passwort, ein Reset-Link oder ein temporäres Passwort vom Admin schaltet MFA nicht aus. Nach dem Reset fragt die Anmeldung weiterhin nach dem zweiten Faktor. Die Admin-Funktionen von OpenFolio enthalten keine Funktion, die MFA für ein Konto zurücksetzt.

## Ohne Backup-Code

Hast du weder Authenticator noch Backup-Code, bietet die App keinen Weg zurück in das Konto. Wende dich an den Betreiber deiner Instanz. Er entscheidet ausserhalb der App, ob und wie er dir hilft.

## Vorsorge

Bewahre die Backup-Codes getrennt vom Handy auf, zum Beispiel in einem Passwort-Manager. Wie du MFA einrichtest und die Codes erhältst, steht unter [Zwei-Faktor-Anmeldung einrichten](#zwei-faktor-einrichten).
