# Tag-11-Retro — Smart-Money-Dashboard (Iteration 1)

**Datum:** 2026-05-31 (vorgezogen 1 Tag vor dem geplanten 2026-06-01)
**Feature:** `/smart-money`
**Use-Phase:** 2026-05-21 (Tag 1, Deploy + Iter-2-Hardening) bis heute (Tag 11)
**Datenbasis:** Use-Log (`/home/harry/projects/finance/Output/product/iteration1_use_log.md`, Tage 1, 2, 4, 7 dokumentiert; 8–11 leer im Daily-Block, Newsletter-Einträge 24./29./31. vorhanden) + 11 vollständige Composite-Scans (21.5.–31.5.)

---

## Verdikt: **FIX**

Nicht GO (Differentiator-Kriterium 2 verfehlt). Nicht KILL (Backend solid, Skill-Disziplin greift, Schwur-1 schützt ehrlich). Re-Retro nach Snapshot-Warmlauf 2026-06-22+.

---

## Kriterien-Auswertung

### 1) ≥5/7 Tagen aktive Nutzung — gemischt

| Lesart | Tage | Stand |
|---|---|---|
| Smart-Money-Daten via Skill konsumiert | 6/11 (1, 2, 4, 7, 9, 11) | OK |
| Harry browsed UI aktiv | 1 dokumentiert (Tag 1) | dünn |

Daten werden integriert genutzt, das UI selbst aber kaum direkt besucht. Konsumtion läuft fast nur über Claude-Skill-Pulls aus `/screening/latest`, nicht über Dashboard-Browse. Das ist nicht zwingend ein Problem — das Dashboard erfüllt als API-Quelle seine Aufgabe — aber das ursprüngliche UI-Browse-Kriterium ist nicht der dominante Konsum-Pfad geworden.

### 2) ≥1 Trade-Plan-Idee, die ohne Dashboard nicht entstanden wäre — **0/1 (KERN-MISS)**

- 5 konkrete Trade-Pläne in 11 Tagen erstellt: CMPS, VLO, AKAM, NET, SATS.
- Alle aus **Watchlist-Breakout** oder **Branchen-Radar** getriggert, NICHT aus dem Smart-Money-Funnel.
- Funnel-Realität (letzter Scan, 31.5.): 317 Rows → **6** ≥ Display 50 → **2** ≥ 60 → **0** ≥ 70.
- Schwur-1-Filter (SMA150) lässt aus den **11 distinct Tickern**, die über 11 Tage überhaupt mal ≥50 erreicht haben, konsistent nur **TSM** (Bestandsposition) durch — kein NEW-Hit.

Root-Cause: Marktphase × Schwur-1-strict × Signal-Sparseness (siehe Item-C-Diagnose `diagnose_score_verteilung_2026-05-29.md` — 96.4 % der Rows unter Display 33, 0 über 67).

Wichtig: **11 Tage sind zu kurz, um Kriterium 2 fair zu bewerten.** Zwei der drei Probe-Pipelines (`form4_cluster`, `estimate_revision`) sind noch im Snapshot-Warmlauf (Auto-Suppression bis 2026-06-22). Erst danach kann der Funnel überhaupt mehr Signale stiften als heute.

### 3) ≤3 Friction-Items — ✓

1 Item (TradingView-Chart im Detail-Modal) am Tag 1 gemeldet, Tag 2 final-resolved (`e76c567` — Refactor auf `TradingViewMiniChart`).

---

## Backend-Health (11 Tage)

| Metrik | Wert |
|---|---|
| Completed Scans | 11/11 (100 %) |
| Laufzeit | 74–110 s, Median ~80 s |
| Result-Count | 317–350 Rows pro Scan |
| Pipeline-Stati | 14/14 done jeden Tag (form4_cluster + estimate_revision dokumentiert empty bis 2026-06-22) |
| Concurrency-Race | gefixt (`c16054f`), kein Re-Auftritt |
| Liveness-Monitor | aktiv (`/api/health/composite-scan`), Sonntags-Fehlalarm eliminiert |

Hardening-Wins parallel zur Use-Phase:
- Iteration 2 komplett (A.1 Equity-only-Universum, B Server-Side-Filter+Pagination, A.2 sec_form4)
- Iteration 3 vorgezogen (Liveness-Endpoint, Report-Vault mit 120 Briefen, Monitor-Migration ohne API-Token)
- Iteration 2.5 Item-C-Spike done — Verdict SCHEDULE (Score-Formel-Swap confirmed)
- CUSIP-First-13F-Resolver (`d18013e`) — hebt Signal-Qualität aller 10 Fonds, Aschenbrenner ins Tracking
- Backlog-Item `watchlist_items.type` vorgezogen (Iteration 4 → Iteration 2)
- Freshness-Hebel Phase 0 deployed (Alters-Badges Modal)

---

## FIX-Inhalt (drei Spuren)

### Spur 1: Re-Retro 2026-06-22+

- Daily-Use bis dahin fortsetzen, Kriterium-2-Counter ehrlich zählen.
- Re-Retro nach Pipeline-Warmlauf — `form4_cluster` und `estimate_revision` liefern erst dann echte Signal-Treffer (30d-Delta + 22.6.-Hard-Date-Cutoff).
- Dauer: ~3 Wochen ab heute.

### Spur 2: Iteration 2.5 (Score-Formel-Swap) jetzt bauen

- Spec siehe `/home/harry/.claude/plans/iteration-2.5-score-formel-swap.md` (gleichzeitig geschrieben).
- Macht den UI-Slider semantisch (heute Range 70–100 faktisch leer).
- Forward-Return-Backtest auf 6 Wochen Composite-History (first scan 2026-04-03).
- **Gated bis Re-Retro-Daten reinkommen** — wenn die Pipeline-Warmlauf-Treffer ab 2026-06-22 die Verteilungs-Form ändern, fällt der Backtest evtl. anders aus. Sicherer: 2.5-Bau jetzt, Live-Switch erst nach Backtest auf POST-Warmlauf-Daten (~Anfang Juli).

### Spur 3: Schwur-Filter-Toggle vorziehen (Iteration 4 → 2.6)

- Schwur 1 (Trend-Filter SMA150) hat in 11 Tagen genau 1 Survivor produziert (TSM, Bestandsposition).
- Hypothese: zu strict für aktuelles Marktregime (Value-Akkumulation in Downtrends — POOL, SPGI, CSGP, OLED, WTW alle unter SMA150).
- Schwur-2/3-Optionen sollen empirisch testen, ob ein weicheres Filter mehr verwertbare NEW-Hits produziert.
- **Constraint:** kein Live-Schwur-Filter-Default-Change ohne Backtest (`feedback_signal_weights_need_backtest`) — Toggle ist nur ein UI-Filter, kein Score-Change → unproblematisch.
- Aufwand: Frontend-Filter-Component, Backend-Filter-Param (analog Item B).
- Optional, je nach Bandbreite. Re-Retro funktioniert auch ohne.

---

## Nicht-Aktion (explizit)

- Kein KILL des Dashboards.
- Kein Code-Rollback.
- Keine Schwur-1-Aufweichung ohne Backtest.
- Keine Display-Mapping-Änderung live ohne 2.5-Backtest (`feedback_signal_weights_need_backtest`).

---

## Anhang — Trade-Plan-Idee-Quellen (Tag 1–11)

| Datum | Ticker | Quelle | Outcome |
|---|---|---|---|
| 2026-05-21 | TSM | Smart-Money (Test-Trigger) | wait |
| 2026-05-24 | CMPS | Watchlist-Breakout | wait |
| 2026-05-24 | VLO | Watchlist-Breakout (Branchen-Filter ✓) | wait |
| 2026-05-29 | AKAM | Branchen-Radar | (Weekly vorgeschlagen) |
| 2026-05-31 | NET | (Weekly) | (Weekly vorgeschlagen) |
| 2026-05-31 | SATS | (Weekly) | (Weekly vorgeschlagen) |

Smart-Money-Dashboard-originiert: 0. TSM war ein Skill-Validation-Test, nicht ein Trade-Trigger.
