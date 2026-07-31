# Branchen-Flow Re-Gate

Forward-Return-Gate auf `market_industries` — prüft, ob Flow-Metriken (`rvol_20d`,
`turnover_ratio`) auf Branchen-Ebene eine Vorhersagekraft haben, die über reines
Preis-Momentum (`perf_1m`) hinausgeht. Read-only, läuft im Backend-Container gegen die
Produktions-DB.

Die **Fragestellung** kommt aus dem `finance`-Workspace (dort steht die produktive
Branchen-Rotations-Methode), das **Werkzeug** gehört hierher: es importiert `db` und
`models.market_industry` und bricht bei Schema-Änderungen an `MarketIndustry` — also dort,
wo diese Änderungen gemacht werden.

## Stand: abgeschlossen, kein Build

| Lauf | Ergebnis |
|---|---|
| Phase-0, 2026-05-25 (vorzeichen-blind) | turnover-Level ohne Kante; `rvol` nur auf 9 Tagen testbar |
| Re-Gate, 2026-07-06 (direction-signed, 3 Arme) | Skript meldet GRÜN auf Arm A — **Auswertung 2026-07-31 kommt zum Gegenteil** |

**Verdikt (Auswertung liegt in `finance`, nicht hier):**
`finance/Output/event-study/2026-07-31_branchen_flow_regate_verdikt.md` — inklusive
vollständigem Roh-Output als Anhang, also ohne dieses Repo lesbar.

Kurzfassung: Die GRÜN-Bedingung des Skripts misst jeden Arm gegen den *Markt*, nicht gegen
sein *eigenes Momentum-Gate*. Der mitgelaufene Kontrolllauf „Momentum allein" ist mehr als
doppelt so stark (+0.38 pp vs. +0.16 pp), und Arm C — die produktiv eingesetzte Regel
`momentum_pass ∧ flow_pass` — ist forward **negativ** (−0.37 pp). Bei n_eff ≈ 7–10
unabhängigen Wochen in einem einzigen Regime trägt aber auch das negative Urteil nicht.
Der Skill `/branchen-flow` wird nicht gebaut, `/sektor-only` bleibt.

## Ausführen

```bash
./run.sh          # fährt backend+db hoch (idempotent), wartet auf Healthiness, schreibt result_<ts>.txt
```

Der auslösende Cron (`0 7 6 7 *`) ist am 2026-07-31 entfernt — er war als Einmal-Lauf gemeint,
hätte als Kalender-Ausdruck aber jeden 6. Juli erneut gefeuert. Start ist manuell.

## Wenn dieses Gate je wieder laufen soll

Nicht einfach neu starten — das Verdikt-File (Abschnitt 5.2) nennt drei Vorbedingungen:

1. **≥ 180 Snapshot-Tage** in `market_industries` (n_eff ≈ 25 statt 10).
2. Das Fenster enthält **mindestens einen Rücksetzer ≥ 5%** auf Index-Ebene — bisher wurde
   ausschliesslich in einem Aufwärtsregime gemessen.
3. **Zwei zusätzliche Arme** sind Pflicht, sonst wird wieder gegen den falschen Massstab
   gemessen:
   - **Arm D:** `momentum_pass` allein (gleiche Universum-/REST-Definition wie A/B/C) — die
     Baseline, gegen die A/B/C hätten antreten müssen.
   - **Arm E:** `momentum_pass ∧ ¬flow_pass` — misst direkt, was heute nur rechnerisch
     abgeleitet ist.

Sind 1. oder 2. nicht erfüllt: **nicht laufen lassen**, Termin verschieben.

## Dateien

| Datei | Was |
|---|---|
| `phase0_regate.py` | Das Gate (3 direction-signed Arme + 3 vorzeichen-blinde Kontext-Läufe), read-only |
| `phase0_regate.py.bak_2026-07-02` | Vorgänger-Fassung vom Umbautag (vorzeichen-blind). Funktional redundant — die Semantik lebt als `run_blind()` im aktuellen Skript weiter. Einmal mitgenommen, damit die Phase-0-Fassung in der Git-Historie liegt; ab dem ersten Commit gefahrlos löschbar |
| `run.sh` | Wrapper: Stack hochfahren, Skript hineinpipen, Ergebnis + Log schreiben |
| `result_20260706_0700.txt` | Ergebnis des Laufs vom 06.07.2026 |
| `regate.log` | Lauf-Historie (eine Zeile pro Lauf) |

## Herkunft

Lag bis 2026-07-31 als `~/branchen-flow-regate/` **ausserhalb jedes Repos** im Home-Verzeichnis,
wurde bei einem Hygiene-Durchgang gefunden, kurzzeitig nach `finance/scripts/` verschoben und
nach der Auswertung hierher. Kontext-Memories: `project_branchen_flow_killgate` (openfolio-Seite,
Methode) und `project_branchen_flow` (finance-Seite, Verwertung).
