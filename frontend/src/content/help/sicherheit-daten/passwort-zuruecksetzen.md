---
id: "passwort-zuruecksetzen"
title: "Passwort zurücksetzen und ändern"
summary: "Was du tust, wenn du dein Passwort vergessen hast oder es ändern willst, und welche Regeln gelten."
section: "sicherheit-daten"
order: 30
---

Du kannst dein Passwort ändern, solange du angemeldet bist. Hast du es vergessen, setzt du es über einen Link per E-Mail zurück.

## Passwort ändern

**Schritt 1:** Öffne **Einstellungen** und wähle den Tab **Konto & Sicherheit**.

**Schritt 2:** Fülle im Abschnitt **Passwort ändern** die Felder «Aktuelles Passwort», «Neues Passwort» und «Neues Passwort bestätigen» aus.

**Schritt 3:** Klicke auf **Passwort ändern**.

## Passwort vergessen

**Schritt 1:** Klicke auf der Anmeldeseite auf **Passwort vergessen?**. Den Link zeigt die Seite nur, wenn deine Instanz E-Mails versenden kann.

**Schritt 2:** Gib deine E-Mail-Adresse ein und klicke auf **Link senden**. Die Meldung lautet immer gleich, ob die Adresse bekannt ist oder nicht. Prüfe auch den Spam-Ordner.

**Schritt 3:** Öffne den Link aus der Mail innerhalb von 30 Minuten und setze ein neues Passwort. Der Server nimmt höchstens drei Anforderungen pro Stunde an.

Ist der Link abgelaufen oder bereits benutzt, zeigt die Seite «Ungültiger Link» und bietet **Neuen Link anfordern** an. Kann deine Instanz keine Mails senden, wende dich an den Admin. Er kann dir ein temporäres Passwort setzen, das du bei der nächsten Anmeldung ersetzen musst.

## Anforderungen an das Passwort

Der Server verlangt mindestens 12 Zeichen, einen Grossbuchstaben, einen Kleinbuchstaben, eine Zahl und ein Sonderzeichen aus `!@#$%^&*()_+-=[]{}|;:,.<>?`. Das Passwort darf höchstens 72 Bytes lang sein, Umlaute zählen doppelt. Sehr verbreitete Passwörter lehnt der Server ab.

## Was mit deinen Sitzungen passiert

Nach jeder Änderung und nach jedem Reset beendet OpenFolio alle bestehenden Sitzungen. Du meldest dich auf jedem Gerät neu an. Ein Reset über den Link oder ein temporäres Passwort vom Admin macht zusätzlich alle [API-Tokens](#api-schluessel-erstellen) ungültig.

Mehr zu Sitzungen steht unter [Sitzungen verwalten](#sitzungen-verwalten).
