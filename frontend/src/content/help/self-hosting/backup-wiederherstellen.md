---
id: "backup-wiederherstellen"
title: "Backup und Wiederherstellung"
summary: "Datenbank und Schlüssel sichern und auf einer neuen Installation zurückspielen."
section: "self-hosting"
order: 30
selfhostOnly: true
---

Deine Daten liegen in der PostgreSQL-Datenbank. Zu einem vollständigen Backup gehören ein Datenbank-Dump und deine `.env`.

## Was du sicherst

Der Compose-Dienst `db` speichert die Datenbank im Volume `finance-dashboard_pgdata`. Redis ist so konfiguriert, dass es nichts auf die Festplatte schreibt. Dort liegt nur ein Zwischenspeicher. Das Volume `import_uploads` hält Dateien aus dem CSV-Import, die ein Worker-Job wieder aufräumt.

Sichere ausserdem die Datei `.env`. Sie enthält `ENCRYPTION_KEY` und `POSTGRES_PASSWORD`. Ohne den Schlüssel bleiben verschlüsselte Werte in der Datenbank unlesbar. Dazu gehören gespeicherte API-Keys und Notizen. OpenFolio meldet das nicht als Fehler. Bewahre die `.env` getrennt vom Dump auf, denn sie enthält alle Secrets.

## Backup erstellen

Der Befehl `docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backup.sql` schreibt die Datenbank in die Datei `backup.sql`. Die Variablen liest die Shell im Container aus der Konfiguration des Dienstes `db`. Führe den Befehl im Ordner `openfolio` aus, solange die Container laufen. Kopiere die Datei danach auf einen anderen Datenträger.

## Wiederherstellen

**Schritt 1:** Lege die gesicherte `.env` in den Ordner `openfolio`. Der Wert `ENCRYPTION_KEY` muss derselbe sein wie beim Backup.

**Schritt 2:** Starte nur die Datenbank mit `docker compose up -d db`. Das Backend legt beim Start sonst selbst leere Tabellen an.

**Schritt 3:** Spiele den Dump ein mit `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < backup.sql`.

**Schritt 4:** Starte alles mit `docker compose up -d --build`. Das Backend erkennt die bestehende Datenbank und führt bei Bedarf die Migrationen aus.

> Hinweis: Ein bestehendes Datenbank-Volume behält das Passwort, mit dem es angelegt wurde. Eine neu erzeugte `.env` mit anderem `POSTGRES_PASSWORD` sperrt das Backend aus.
