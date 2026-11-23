---
id: "installation"
title: "OpenFolio installieren"
summary: "OpenFolio mit Docker Compose auf dem eigenen Rechner oder Server aufsetzen."
section: "self-hosting"
order: 10
selfhostOnly: true
---

OpenFolio läuft als Docker-Compose-Stack. Das Skript `init.sh` richtet die Konfiguration ein und startet die Container.

## Voraussetzungen

Du brauchst Docker, Docker Compose v2 und Git. `init.sh` braucht ausserdem `openssl`. Auf Windows klonst du das Repository am besten in WSL2. Läuft OpenFolio in einer virtuellen Maschine, aktivierst du CPU-Host-Passthrough, zum Beispiel mit `--cpu host` bei QEMU/KVM.

## Installation mit init.sh

**Schritt 1:** Klone das Repository mit `git clone https://github.com/dmxch/openfolio.git` und wechsle in den Ordner `openfolio`.

**Schritt 2:** Starte `./init.sh`. Das Skript generiert JWT-Secret, Verschlüsselungsschlüssel sowie Datenbank- und Redis-Passwort und schreibt sie in die `.env`.

**Schritt 3:** Gib E-Mail und Passwort für das Admin-Konto ein. Das Passwort braucht mindestens 12 Zeichen, Gross- und Kleinbuchstaben, eine Zahl und ein Sonderzeichen.

**Schritt 4:** Wähle die Ports. Vorgabe sind 5173 für die Oberfläche und 8000 für die API.

Danach baut und startet `init.sh` die Container. Sobald der Admin in der Datenbank steht, entfernt das Skript `ADMIN_PASSWORD` wieder aus der `.env`.

## Manuelle Installation

Kopiere `.env.example` nach `.env` und ersetze alle `CHANGE_ME`-Werte. Pflicht sind `POSTGRES_PASSWORD`, `JWT_SECRET`, `ENCRYPTION_KEY` und `REDIS_PASSWORD`. Das Backend bricht ohne gültigen `JWT_SECRET` und `ENCRYPTION_KEY` beim Start ab. Für das erste Admin-Konto trägst du `ADMIN_EMAIL` und `ADMIN_PASSWORD` ein. Starte dann mit `docker compose up -d --build`.

## Erster Aufruf

Öffne `http://localhost:5173` im Browser, bei geändertem Port den Wert aus `FRONTEND_PORT`. Melde dich mit dem Admin-Konto an. Je nach MFA-Richtlinie leitet OpenFolio dich danach zur Einrichtung der Zwei-Faktor-Authentifizierung weiter.

> Hinweis: Alle Ports sind an `127.0.0.1` gebunden. Für den Zugriff von aussen schaltest du einen Reverse-Proxy davor.

Sichere die `.env` sofort, wie unter [Backup und Wiederherstellung](#backup-wiederherstellen) beschrieben. Optionale Datenquellen richtest du danach ein: [API-Schlüssel für Datenquellen](#api-schluessel-datenquellen).
