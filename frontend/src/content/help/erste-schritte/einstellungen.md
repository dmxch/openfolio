---
id: "einstellungen"
title: "Einstellungen konfigurieren"
summary: "API-Keys, E-Mail-Benachrichtigungen und persönliche Präferenzen einrichten."
section: "erste-schritte"
order: 50
---

Unter **Einstellungen** konfigurierst du OpenFolio nach deinen Bedürfnissen. Hier verwaltest du API-Keys, E-Mail-Versand und Anzeigeoptionen.

## API-Keys

Einige Funktionen benötigen externe API-Keys. Der **FRED API Key** schaltet Makro-Indikatoren wie den Buffett Indicator und die Zinsstrukturkurve frei. Der **FMP API Key** liefert Fundamentaldaten für US-Aktien. Beide Keys sind kostenlos erhältlich und optional — OpenFolio funktioniert auch ohne sie, aber mit eingeschränktem Funktionsumfang.

> Tipp: Alle API-Keys werden mit Fernet (AES-128 mit HMAC-SHA256) verschlüsselt in der Datenbank gespeichert. Sie sind zu keinem Zeitpunkt im Klartext sichtbar.

## E-Mail-Benachrichtigungen

Konfiguriere einen **SMTP-Server**, um E-Mail-Benachrichtigungen für Alerts zu erhalten. Du brauchst: SMTP-Host, Port, Benutzername und Passwort. Die meisten E-Mail-Anbieter unterstützen SMTP — eine Anleitung findest du bei deinem Provider.

## Zahlenformat

Wähle dein bevorzugtes **Zahlenformat**: Schweiz (1'000.00), Deutschland (1.000,00) oder Englisch (1,000.00). Das Format wird überall in der App angewendet — bei Beträgen, Kursen und Prozentzahlen.

## Sicherheit

Unter Sicherheit kannst du dein Passwort ändern und die **Zwei-Faktor-Authentifizierung (MFA)** aktivieren. MFA schützt deinen Account mit einem zusätzlichen TOTP-Code. Nach der Aktivierung erhältst du Backup-Codes für den Notfall.

## Sitzungen

Du siehst alle aktiven Sitzungen und kannst einzelne Geräte abmelden. Refresh-Tokens sind 30 Tage gültig und rotieren automatisch.
