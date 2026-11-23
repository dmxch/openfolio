---
id: "update"
title: "OpenFolio aktualisieren"
summary: "Eine neue Version einspielen und prüfen, was sich geändert hat."
section: "self-hosting"
order: 20
selfhostOnly: true
---

Ein Update holt den neuen Code und baut die Container neu. Die Datenbank-Migrationen laufen dabei von selbst.

## Vor dem Update

Sichere zuerst die Datenbank und die `.env`. Die Schritte stehen unter [Backup und Wiederherstellung](#backup-wiederherstellen). Lies danach den Changelog der neuen Version.

## Update durchführen

**Schritt 1:** Wechsle in den Ordner `openfolio` und hole den neuen Code mit `git pull`.

**Schritt 2:** Baue und starte die Container mit `docker compose up -d --build`.

Diesen Befehl nennt auch `init.sh` am Ende der Installation. Er behält die Volumes und damit deine Daten.

## Migrationen

Beim Start des Backends läuft das Skript `entrypoint.sh`. Findet es eine bestehende Datenbank, führt es `alembic upgrade head` aus. Du startest keine Migration von Hand. Eine leere Datenbank legt das Skript neu an.

Der Worker startet erst, wenn das Backend als gesund meldet. Den Verlauf der Migration zeigt `docker compose logs -f backend`.

## Änderungen nachlesen

Der Changelog steht in der Datei `CHANGELOG.md` im Repository. In der App öffnest du ihn über die Versionsnummer unten in der Seitenleiste. Er gliedert sich nach Version und Datum.

## Wenn ein Container nicht startet

Prüfe zuerst die Logs mit `docker compose logs backend`. Fehlt ein Pflichtwert wie `JWT_SECRET` oder `ENCRYPTION_KEY`, meldet das Backend «FATAL» und beendet sich.
