# Prod-Deploy v0.53.0 (+ Dependency-Patch-Runde) — Schritt für Schritt

Stand: 2026-07-02. Ziel: Prod (openfolio.cc, 10.10.70.10) von 0.51.0 auf main
`e2c7377` (= Tag v0.53.0 + Security-Patch-Runde). Enthält Migration **093**.

**Besonderheit dieses Deploys:** Der Backend-Container migriert beim Start
automatisch (`prod_deploy.sh` Schritt 3). Die 093-Vorprüfung MUSS deshalb
VOR dem Skript laufen — der Unique-Index auf
`pending_orders.linked_transaction_id` scheitert an Alt-Dubletten.

---

## 1. Ist-Zustand festhalten (Prod-Box, Projekt-Root)

```bash
curl -s http://127.0.0.1:8000/api/health
# erwartet: {"status":"ok","version":"0.51.0","db":"connected","redis":"connected"}
docker compose ps --format "table {{.Name}}\t{{.Status}}"   # alles healthy?
```

## 2. Migration-093-Vorprüfung (ZWINGEND vor dem Deploy)

```bash
docker compose exec -T db psql -U openfolio openfolio -c "
SELECT linked_transaction_id, count(*)
FROM pending_orders
WHERE linked_transaction_id IS NOT NULL
GROUP BY 1 HAVING count(*) > 1;"
```

- **0 Zeilen** → weiter mit Schritt 3.
- **Treffer** → pro Duplikat die jüngeren Verlinkungen lösen (die älteste
  Order behält den Link), danach die Prüfung wiederholen:

```bash
docker compose exec -T db psql -U openfolio openfolio -c "
WITH d AS (
  SELECT id, row_number() OVER (
    PARTITION BY linked_transaction_id ORDER BY created_at ASC
  ) AS rn
  FROM pending_orders
  WHERE linked_transaction_id IS NOT NULL
)
UPDATE pending_orders p SET linked_transaction_id = NULL
FROM d WHERE p.id = d.id AND d.rn > 1;"
```

## 3. Deploy-Skript

```bash
./scripts/prod_deploy.sh
```

Das Skript macht der Reihe nach: pg_dump-Backup → `git pull origin main` →
Backend build + up (**Migration 093 läuft hier automatisch**) →
alembic-Head-Abgleich (DB == Code, Abort bei Mismatch) → Sanity-Counts →
Frontend + Worker build + up → Health-Check → Scheduler-Check.

## 4. Verifikation

```bash
curl -s http://127.0.0.1:8000/api/health
# erwartet: "version":"0.53.0"

docker compose exec -T db psql -U openfolio openfolio -tAc \
  "SELECT version_num FROM alembic_version;"
# erwartet: 093

docker compose logs backend worker --since 5m 2>&1 | grep -icE "error|traceback"
# erwartet: 0

docker compose logs worker --since 3m 2>&1 | grep "tickers updated" | tail -2
# erwartet: Batch-Kurs-Refresh läuft ("N tickers updated, 0 errors")
```

Im Browser (openfolio.cc):
- Portfolio + Performance laden, Zahlen plausibel (Stichprobe gegen vorher)
- Buckets → **Import-Regeln-Liste** lädt (war bis 0.52 durch Route-Shadowing tot)
- Watchlist → „Score neu laden" an einem Titel (war wirkungslos)
- Aktien-Detail: nur EIN TradingView-Chart lädt (Desktop ODER Mobile)

## 5. Erwartete Nachwirkungen (kein Bug, dokumentiert im CHANGELOG)

- **Einmalig doppelte Preis-Alert-Mails** für Alerts der letzten 24h vor dem
  Deploy möglich (`notification_sent` war historisch ungepflegt).
- **Heartbeat/Wyckoff-Tiers verschieben sich** (Skalen-Korrektur, Werte jetzt
  niveau-unabhängig); **Macro-Gate** hat ohne Sektor-Kontext max_score 8
  statt 9 (None-Semantik).
- **Grafana**: Dashboards/Alerts mit `endpoint`-Label-Regex prüfen — die
  Werte wechseln auf Routen-Templates (z.B.
  `/api/portfolio/buckets/{bucket_id}`), Kardinalität sinkt deutlich.
- Bekannt und NICHT neu: Counter-Sprünge durch 2 uvicorn-Worker
  (multiprocess-mode offen, siehe Monitoring-Memory).

## 6. Rollback (nur falls nötig)

Das Skript druckt am Ende die Restore-Kommandos (Backup-File aus Schritt 3
einspielen). Nur die Migration zurücknehmen:

```bash
docker compose exec backend alembic downgrade 092
```

Code zurück: `git checkout v0.52.0 && docker compose up -d --build`
(Migration 093 ist abwärtskompatibel — nur Indizes/FK, kein Datenverlust).
