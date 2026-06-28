# DESIGN — Trade-Journal (Scope, überarbeitet)

> **⚠️ PIVOT 27.06.2026 — Plan-Quelle gewechselt.** Das Kill-Gate (Abschnitt 4) wurde gegen Prod-Daten gemessen: `pending_orders` deckt nur **11 %** der Trades (NO-GO). Auf Maintainer-Hinweis ist die echte Plan-Quelle der **Report-Vault** (`reports` category=`trade`, 86 Trade-Pläne von claude-finance) — Coverage 25 % / Plan-Follow-Through 47 % und qualitativ weit reicher (Rationale im Body, teils gebuchte Txn-ID). Umgesetzt wird daher der **Vault-basierte** Plan→Ist-Link am Schreibzeitpunkt: `reports.ticker/side/linked_transaction_id` (Migration 089), von claude-finance beim Buchen gesetzt, Read-View `/api/analysis/trade-journal`. Das untenstehende pending-orders-Design ist für die **Plan-Quelle überholt**; die Adhärenz-/View-/Ehrlichkeits-Überlegungen (Preis-Abweichung nur bei gleicher Währung, „nicht ausgeführt" als legitimer Status, neutrale Sprache) gelten weiter.

> Änderungen ggü. Entwurf basieren auf einer Code-Verifikation gegen `orders.py`, `external_v1.py`, `pending_order_service.py`, `pending_order.py`, `transaction.py`. Alle neun Red-Team-Befunde wurden am echten Code bestätigt und sind unten eingearbeitet.

## 1. Problem & Ziel (Adhärenz-Hälfte der Handlungsbrücke)

Die "Handlungsbrücke" hat heute nur ihre **Plan-Hälfte**: Das Rebalancing-Cockpit (`get_rebalancing_plan`) zeigt Soll/Ist/Delta je Bucket — read-only, end-state-only, on-demand berechnet. Es fehlt die **Adhärenz-Hälfte**: die Rückkopplung *"Habe ich meinem Plan gefolgt?"*.

Der Clou: Diese Hälfte existiert in OpenFolio bereits zu ~80% **latent**. `pending_orders.linked_transaction_id` verbindet über die bestehende Auto-Fill-Reconciliation (`try_auto_fill_order`: Ticker+Seite+Stück exakt, +/-35d, FIFO) den **Plan** (Order) mit dem **Ist** (Transaction). Was fehlt, ist nur:

- **(a) ein strukturiertes "Warum"** pro geplanter Order (Rationale), und
- **(b) eine Sicht**, die den Plan->Ist-Sprung pro Trade sichtbar macht plus zwei ehrlich gelabelte Adhärenz-Kennzahlen.

Ziel des MVP: aus vorhandenen Daten Adhärenz-Feedback machen — **ohne ein zweites Order-System zu erschaffen**.

**Was das Feature ehrlich NICHT leisten kann (vorab klargestellt, siehe Abschnitt 4 & 9):** Die zugrunde liegende Verknüpfung ist ein **exakter** Auto-Match (gleiche Stückzahl). Teil-Fills, Gebühren-in-Shares oder Rundungs-Abweichungen verlinken nie und bleiben dauerhaft als "offen" stehen. Die Kennzahl "Fill-Rate" ist deshalb **eine Auto-Fill-Quote exakt gematchter Pending-Orders, KEINE Plan-Treue-Quote**. Diese Ehrlichkeit ist Teil des Scopes, nicht eine spätere Korrektur.

---

## 2. Was schon existiert / NICHT neu bauen — und die pending_orders-Abgrenzung

**Bereits vorhanden, wird nur GELESEN (nie nachgebaut):**

| Baustein | Datei | Rolle im Journal |
|---|---|---|
| Plan->Ist-Brücke | `pending_orders.linked_transaction_id` (FK `ON DELETE SET NULL`) | DER Join Plan<->Ausführung |
| Auto-Fill-Reconciliation | `pending_order_service.try_auto_fill_order` (`ORDER_FILL_MATCH_WINDOW_DAYS=35`, FIFO, `shares ==` exakt) | erzeugt die Verknüpfung — **bleibt unangetastet** |
| Effektiv-Status | `pending_order_service.compute_effective_status` (Python: `gtd` + `expiry_date < today` -> `expired`) | Status-Ableitung; `expired` ist **kein** DB-Wert |
| Currency-Guard | `pending_order_service.compute_distance_pct` (None bei Currency-Mismatch) | Vorlage für `preis_abweichung_pct` |
| Plan-Felder | `pending_orders`: ticker, side, shares, limit_price, currency, bucket_id_target, created_at, status, expiry_type, expiry_date | Plan-Block der Zeile |
| Ist-Felder | `transactions`: price_per_share, shares, date, currency, total_chf, position_id, bucket_id_at_sale | Ist-Block der Zeile |
| Soll/Drift | `rebalancing_service.get_rebalancing_plan` | bleibt separat, kein Umbau |
| Multi-User-Scoping | `user_id` auf beiden Tabellen | wird automatisch geerbt |

**Erweitern oder eigenständig? -> ENTSCHEIDUNG: erweitern, NICHT eigenständig.**

Die ehrliche Wahrheit: Dieses Feature *ist* `pending_orders` plus eine Sicht. Eine eigene `trade_intents`/`trade_journal_entries`-Tabelle (Medium/Full-Ansatz) wäre im MVP eine **parallele Plan-Entität mit zwei konkurrierenden Auto-Match-Pfaden gegen dieselben Transaktionen** — Doppel-Bau und Doppel-Anrechnungs-Risiko, das die Adhärenz-Quote verfälscht. Die Judge-Scores bestätigen das: Minimal 24/25 vs. Medium 16 vs. Full 16, mit `lean` und `low_build_cost` jeweils 5 vs. 2.

Die separate Tabelle ist **erst gerechtfertigt, wenn das Kill-Gate (Abschnitt 4) sie erzwingt** — nämlich wenn relevant viele echte Trades *ohne* vorherige Pending-Order laufen. Bis dahin: eine Spalte, eine Sicht, **kein neuer Sidebar-Eintrag** (siehe Abschnitt 7).

**NICHT neu bauen:** keine zweite Matching-Logik, kein Partial-Fill-Tracking, kein Worker-Expiry-Job, kein gewichtetes Adhärenz-Scoring, kein Rebalancing-Plan-Snapshot, keine Signal-Verknüpfung, **keine neue `api_write_log`-action** (Begründung Abschnitt 5/6).

---

## 3. Empfohlener MVP-Cut + bewusst ausgelassene Ausbauten

**Empfehlung: Scope-Level MINIMAL** ("Adhärenz-Sicht auf bestehende Pending-Orders"), mit drei Pflicht-Änderungen aus den Findings.

**Begründung aus den Scores:**
- Minimal `total=24/25` (lean 5, overlap_avoidance 5, low_build_cost 5, invariant_safety 5, value 4) — der einzige Ansatz, der lean-first sauber umsetzt: 1 nullable Spalte, 1 read-only Service mit *einem* LEFT JOIN, 2 GET-Endpoints, 1 zusätzliches PATCH-Feld (intern **und** extern), 1 Tab.
- Medium/Full committen beide *sofort* zur teuren, schwer rückbaubaren separaten Tabelle und verschieben ihr eigenes Kill-Gate auf *nach* den Vollbau — exakt die lean-first-Inversion, die der User-Philosophie widerspricht.
- Der echte Mehrwert (Preis-Abweichung, Timing-Drift, Rationale) steckt vollständig im Minimal-Cut. Die teuersten Schichten der grossen Ansätze (Trend-Analytik, Disziplin-Heatmap) sind bei der erwarteten Trade-Kadenz statistisch Rauschen (Forward-Return-Harness-Lehre: grosses n hilft nicht bei einem Regime/zu wenig Events).

**Drei Pflicht-Änderungen gegenüber dem ursprünglichen Minimal-Vorschlag:**
1. **Kill-Gate ist Vor-Bedingung, kein Nachtrag** (Abschnitt 4) — und misst **drei** Coverage-Zahlen statt nur `linked_rate`, weil eine hohe `linked_rate` allein keinen Mehrwert über die bestehende "Erledigt"-Sicht garantiert.
2. **`bucket_treffer`-Kennzahl gestrichen** im MVP: `bucket_id_target` bedeutet "wohin die auto-erstellte Position landet", nicht "strategische Absicht" — die Kennzahl wäre nahezu tautologisch. Bleiben **zwei** ehrlich gelabelte Kennzahlen: Preis-Abweichung und Timing-Drift, plus das Rationale-Feld.
3. **Surface ist ein Tab auf der bestehenden Pending-Orders-Seite**, keine neue Route, kein neuer Sidebar-Eintrag (Abschnitt 7, Default-Entscheid zu Offene-Frage 7). Das eliminiert den stärksten verbleibenden Scope-Creep-Vektor.

**Bewusst ausgelassen (Folge-Ausbauten, gated):**
- Separate Plan-Entität für ungeplante/Markt-/Impuls-Trades (nur falls Kill-Gate kippt -> dann Pivot, Abschnitt 4)
- Partial-Fill-/Near-Miss-Verlinkung (abweichende Stückzahl) — bewusst raus, aber im Kill-Gate **gemessen** (Abschnitt 4), damit die stille Verzerrung der Headline-Zahl sichtbar wird, statt unbemerkt zu bleiben
- Adhärenz-Trend über Zeit / Disziplin-Heatmap / Quoten-Zeitreihe (braucht Kadenz-Nachweis)
- Gewichtetes Adhärenz-Scoring + Display-Mapping (braucht Forward-Return-Validierung — bewusst raus)
- Multi-Leg/Pair-Trades, Stornierungs-Gründe-Enum, Worker-Expiry
- Bucket-Treffer-Kennzahl (erst wenn `bucket_id_target` eine echte strategische Semantik bekommt)
- `from-rebalancing`-Button (Plan-Capture aus dem Cockpit) — wertvoll, aber erst nach bestandenem Gate
- Eigene `/trade-journal`-Route — nur falls das Tab-Layout nachweislich nicht reicht (Abschnitt 7)

---

## 4. Die kippende Decision (3-teiliges Kill-Gate, VOR dem Bau)

> **Die EINE Frage bleibt:** Erstellt der Nutzer überhaupt Pending-Orders, BEVOR er handelt — oder kommen seine echten Trades primär per CSV-Import (Swissquote/IBKR/Pocket) ohne vorgelagerte Order an?

Wenn Trades per Import eintreffen *ohne* vorher angelegte Pending-Order, dann gibt es keine Order, an die `try_auto_fill_order` koppeln könnte -> `linked_transaction_id` bleibt leer -> **die Journal-Sicht ist nahezu leer.**

Aber `linked_rate` allein reicht nicht: Die bestehende "Erledigt"-Sicht der Pending-Orders-Seite zeigt den Plan->Ist-Sprung (inkl. `linked_transaction_id` und `effective_status`) bereits. Der **Netto-Mehrwert** des Journals hängt daran, ob die **zwei neuen Kennzahlen überhaupt Werte tragen**. Beide haben Code-bedingte Leerlauf-Risiken:

- **Currency-Guard** (`compute_distance_pct`): `preis_abweichung_pct` ist `null`, wenn Plan-Währung != Txn-Währung. `pending_orders.currency` defaultet auf `'USD'`, `transactions.currency` auf `'CHF'` und stammt aus dem Import — die Spalten können systematisch divergieren.
- **Exakt-Stück-Match** (`try_auto_fill_order`: `PendingOrder.shares == txn.shares`): Teil-Fills/Gebühren-in-Shares verlinken nie. Bei verlinkten Paaren ist die Stückzahl deshalb **per Konstruktion immer** gleich — diese Zahl bei verlinkten Paaren zu messen wäre tautologisch (immer 100%). Die aussagekräftige Messung ist die **Near-Miss-Quote**: nicht-verlinkte Transaktionen, für die es eine passende Order (gleicher Ticker+Seite, im +/-35d-Fenster) mit **abweichender** Stückzahl gibt.

**Konkreter Prüfpunkt VOR dem Bau (lean probe, runnable), drei Zahlen:**

```sql
-- (1) linked_rate: Anteil der buy/sell-Txns mit gesetztem linked_transaction_id
WITH recent AS (
  SELECT id, ticker, type, shares, date, currency
  FROM transactions
  WHERE user_id = :uid AND type IN ('buy','sell')
    AND date >= (CURRENT_DATE - INTERVAL '6 months')
),
linked AS (
  SELECT t.id, t.shares, t.currency AS txn_ccy,
         po.currency AS plan_ccy, po.shares AS plan_shares
  FROM recent t
  JOIN pending_orders po ON po.linked_transaction_id = t.id
)
SELECT
  -- (1) linked_rate
  (SELECT count(*) FROM linked)::float / NULLIF((SELECT count(*) FROM recent), 0)
    AS linked_rate,
  -- (2) Currency-Match-Anteil bei verlinkten Paaren (Coverage von preis_abweichung)
  (SELECT count(*) FILTER (WHERE upper(plan_ccy) = upper(txn_ccy)) FROM linked)::float
    / NULLIF((SELECT count(*) FROM linked), 0)
    AS ccy_match_rate;

-- (3) Near-Miss-Quote: NICHT verlinkte Txns, fuer die eine Order mit gleichem
--     Ticker+Seite im +/-35d-Fenster existiert, aber mit ABWEICHENDER Stueckzahl
WITH recent AS (
  SELECT t.id, t.ticker, t.type, t.shares, t.date
  FROM transactions t
  WHERE t.user_id = :uid AND t.type IN ('buy','sell')
    AND t.date >= (CURRENT_DATE - INTERVAL '6 months')
    AND NOT EXISTS (SELECT 1 FROM pending_orders po
                    WHERE po.linked_transaction_id = t.id)
)
SELECT
  count(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM pending_orders po
    WHERE po.user_id = :uid
      AND po.ticker = recent.ticker
      AND po.side = (CASE WHEN recent.type = 'buy' THEN 'buy' ELSE 'sell' END)
      AND po.created_at >= recent.date - INTERVAL '35 days'
      AND po.created_at <  recent.date + INTERVAL '36 days'
      AND po.shares <> recent.shares
  ))::float / NULLIF(count(*), 0) AS near_miss_rate
FROM recent;
```

**Entscheidungsregel (GO nur wenn alle drei tragen):**
- **`linked_rate` >= ~30-40 %** UND
- **`ccy_match_rate` ausreichend** (sonst läuft `preis_abweichung_pct` leer; konkrete Schwelle vom Maintainer, Vorschlag >= ~70 %) UND
- **`near_miss_rate` niedrig** (sonst verbirgt die Fill-Rate systematisch echte, aber stück-abweichende Trades; je höher, desto irreführender die Headline-Zahl).

-> **GO:** Minimal-Cut wie spezifiziert.
-> **NO-GO / Pivot:** Ist `linked_rate` zu tief, **Pivot** zu einer dünnen Plan-Capture-Entität (eigene Tabelle), die ungeplante/Markt-Trades *nachträglich* erfasst — **erst dann**, nicht präventiv (Medium-Scope, separat ge-gated). Ist `ccy_match_rate` oder `near_miss_rate` das Problem, liefert das Journal zwar Zeilen, aber leere/verzerrte Kennzahlen — dann entweder Kennzahl-Cut (nur Rationale + Plan->Ist-Sicht ausliefern) oder Datenhygiene zuerst.

**Sekundär-Kipper:** Setzt der Nutzer fast nie `bucket_id_target`, ist jede Bucket-bezogene Kennzahl wertlos -> bestätigt nur die ohnehin getroffene Entscheidung, `bucket_treffer` im MVP wegzulassen.

---

## 5. Datenmodell

**Keine neue Tabelle. Eine neue nullable Spalte.**

```python
# models/pending_order.py — neue Spalte
rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- **Migration: JA**, analog `086_position_count_as_cash.py` — `op.add_column("pending_orders", sa.Column("rationale", sa.Text(), nullable=True))`, kein `server_default`, kein Backfill.
- **Trennung von `notes`:** `notes` ist taktisch ("Limit an Widerstand") und hat bereits API-Provenienz-Felder (`notes_last_api_write_at`, `notes_last_api_token_name`). `rationale` ist strategisch ("Core untergewichtet -CHF 5k laut Rebalancing"). Saubere Trennung, kein Konflikt mit External-API-Provenienz.
- **user_id-scoped:** automatisch über `pending_orders.user_id` + `transactions.user_id` (kein neues Scoping nötig).
- **PII:** Nein. `rationale` ist strategischer Freitext, keine Broker-/Kontodaten -> **keine Fernet-Verschlüsselung** (plain Text wie `notes`). Falls der Maintainer Broker-Bezug erwartet, siehe Abschnitt 11.
- **Keine Berührung** von `transactions`, Snapshots, `cost_basis`, XIRR/Dietz, Assetklassen-Ausschluss.

**Kein neuer `api_write_log`-action-Wert.** `rationale` wird in **beide** bestehenden PATCH-Pfade aufgenommen (Abschnitt 6). Der externe Pfad (`update_pending_order_external`) loggt bereits mit `action='pending_order_update'` — dieser Wert wird **wiederverwendet**, kein neuer Wert eingeführt. Das vermeidet die dokumentierte CHECK-Constraint-Falle (Test-DB via `create_all` sieht die `api_write_log.action`-Whitelist nicht -> sonst Prod-500).

> **Korrektur ggü. Entwurf:** Die frühere Behauptung "`rationale` läuft über den bestehenden PATCH-Pfad, der bereits geloggt wird" ist **faktisch falsch** und wird gestrichen. Der **interne** `update_pending_order` (`orders.py`) schreibt **keinen** `ApiWriteLog` — das gilt für alle internen Order-Edits, nicht nur für `rationale`, und ist bestehendes, konsistentes Verhalten (Session-Auth, kein Token). Geloggt wird ausschliesslich der **externe** Pfad. Logging-Parität entsteht also dadurch, dass `rationale` auch extern editierbar ist (s.u.), nicht durch eine angebliche interne Logging-Eigenschaft.

---

## 6. API-Endpoints (FastAPI)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/trade-journal?status=all\|filled\|offen&page=N` | Liefert pro Zeile `{plan, ist\|null, adhaerenz\|null}`. **Ein LEFT JOIN** `pending_orders` -> `transactions` über `linked_transaction_id` (kein N+1). `effective_status` wird in Python aus den geladenen Rows berechnet (`compute_effective_status`). user_id-scoped. |
| GET | `/api/trade-journal/summary` | Aggregat: `{anzahl_geplant, anzahl_gefuellt, anzahl_offen, anzahl_storniert, anzahl_abgelaufen, fill_rate_pct, avg_preis_abweichung_pct}`. `fill_rate_pct` ist ehrlich gelabelt (Auto-Fill-Quote, s.u.). |
| PATCH | `/api/orders/pending/{id}` (**erweitert, intern**) | Akzeptiert zusätzlich `rationale` (Text). `rationale` wird in `_FILLED_EDITABLE_FIELDS` aufgenommen -> auch auf `status='filled'` erlaubt. Kein neuer Mutations-Endpoint. |
| PATCH | `/api/v1/pending-orders/{id}` (**erweitert, extern**) | Akzeptiert zusätzlich `rationale`; `rationale` wird in `_FILLED_EDITABLE_FIELDS_EXT` aufgenommen. Reuse von `action='pending_order_update'` im bestehenden `ApiWriteLog`. Erhält die seit v0.45 dokumentierte UI-Schreib-Parität. |

**Zwei Code-genaue Pflicht-Änderungen (sonst ist der Kern-Use-Case nicht baubar):**

1. **`_FILLED_EDITABLE_FIELDS` (orders.py:111) und `_FILLED_EDITABLE_FIELDS_EXT` (external_v1.py:1485) erweitern: `{"notes"}` -> `{"notes", "rationale"}`.** Beide Whitelists werfen heute `400` für jedes Feld ausser `notes`, sobald `status='filled'`. **Genau die gefüllten Orders sind aber die journal-relevantesten** — ein Rationale-PATCH auf sie würde ohne diese Änderung mit `400` scheitern. Der `ExternalPendingOrderUpdate`- bzw. `PendingOrderUpdate`-Pydantic-Schema muss `rationale: Optional[str]` zusätzlich kennen.

2. **External-Parität:** `rationale` in `update_pending_order_external` durchreichen; das bestehende `ApiWriteLog(action='pending_order_update', ...)` deckt es automatisch ab. Kein neuer action-Wert, keine Migration für die action-Whitelist.

**Response-Form `/api/trade-journal` (pro Zeile):**
```json
{
  "plan": {"ticker","side","shares","limit_price","currency","bucket_id_target",
           "bucket_name|null","rationale","created_at","effective_status"},
  "ist":  {"transaction_id","actual_shares","actual_price","actual_date",
           "actual_currency","total_chf"},   // null wenn offen
  "adhaerenz": {"preis_abweichung_pct|null","timing_drift_tage",
                "timing_nach_ausfuehrung": false}   // ganzer Block null wenn offen
}
```

**Explizit NICHT angefasst:** `try_auto_fill_order`, `/api/orders/pending/{id}/fill`, das +/-35d-/FIFO-/Exact-Shares-Matching. Der Diff berührt die Reconciliation-Logik **nicht** — nur die zwei Filled-Whitelists, die zwei PATCH-Schemas und ein read-only Service.

---

## 7. UI

**Surface-Entscheid (Default zu Offene-Frage 7): Tab auf der bestehenden Pending-Orders-Seite. Keine neue Route, kein neuer Sidebar-Eintrag.**

Begründung: Die Pending-Orders-Seite zeigt im Tab "Erledigt" bereits gefüllte Orders inkl. `linked_transaction_id` und `effective_status`. Eine komplett neue Seite + Sidebar-Eintrag würde diese Sicht weitgehend duplizieren (stärkster Scope-Creep-Vektor). Der echte Netto-Mehrwert — Rationale + 2 Kennzahlen + nebeneinanderliegender Plan/Ist-Block — passt als zusätzlicher **Tab/Modus** in die vorhandene Seite und erbt deren Tab-Counts. Eine eigene `/trade-journal`-Route wird nur gebaut, **falls** das Tab-Layout nachweislich nicht reicht.

- **Kein neues Order-Formular.** Der Tab ist read-only/abgeschlossen-fokussiert (zeigt den Plan->Ist-Sprung + Rationale). Das operative Anlegen/Füllen von Orders bleibt in den bestehenden Tabs derselben Seite.
- **Aufbau des Journal-Tabs:**
  1. **Summary-Header** (Karten): "Auto-Fill-Quote (exakt)" und "Durchschnittliche Preis-Abweichung" — aus `/summary`. Die Fill-Rate-Karte trägt einen Tooltip/Untertitel: *"Anteil exakt automatisch verknüpfter Orders. Teil-Fills und stück-abweichende Trades sind hier nicht erfasst."* — keine Plan-Treue-Behauptung.
  2. **Tabelle mit den vorhandenen Tabs** Offen / Erledigt / Alle (Pattern aus `PendingOrders.jsx`, Counts immer ungefiltert). Je Zeile: **Plan-Block** (Ticker, Seite, Stück @ Limit, Ziel-Bucket, Rationale) -> **Ist-Block** (Stück @ Ausführungspreis am Datum) -> **Adhärenz-Badges**.
  3. **Rationale inline editierbar** pro Zeile via bestehendem PATCH (`useApi`) — **auch in "Erledigt"/"Alle"** (gefüllte Orders), da die Filled-Whitelists `rationale` jetzt zulassen.
- **Adhärenz-Badges (Display-Hygiene):**
  - `preis_abweichung_pct = null` (Currency-Mismatch) -> Badge "Währung abweichend, kein Vergleich", **kein** falscher Prozentwert.
  - `timing_drift_tage < 0` (Order **nach** der Ausführung erfasst) -> explizit gelabelt "Order nach Ausführung erfasst" statt eines irreführenden negativen Drift-Werts (man kann keinem Plan folgen, den man erst danach anlegt). Solche Zeilen fliessen in **keine** Timing-Aggregation ein (im MVP gibt es ohnehin nur das Per-Zeilen-Badge, keine Timing-Summary-Kennzahl).
  - `bucket_id_target = null` (Bucket gelöscht, FK `SET NULL`) bzw. `bucket_name = null` -> als "—" rendern, kein Crash.
- **Reuse:** `RebalancingCard`-Tabellenstil, `useApi`-Hook, Badge-Farblogik für Delta, bestehende Tab-Komponente von `PendingOrders.jsx`.
- **Sprache:** Deutsch, neutral. "Plan erfasst", "Abweichung +X%", "Auto-Fill-Quote". **Keine Wertung** wie "schlecht ausgeführt", keine imperativen Anweisungen. Korrekte Umlaute im UI-Text (ae/oe/ue nur Fallback, nie sichtbar).

---

## 8. User Stories

1. Als Anleger sehe ich für jede ausgeführte (gefüllte) Pending-Order direkt nebeneinander, was ich geplant (Stück @ Limit) und was ich tatsächlich bekommen habe (Stück @ Ausführungspreis, Datum).
2. Als Anleger kann ich pro Order eine Begründung (rationale) festhalten — auch **nachträglich auf einer bereits gefüllten Order** — und sie später wiederfinden.
3. Als Anleger sehe ich je Trade die Preis-Abweichung gegenüber meinem Limit (nur bei gleicher Währung) und den Timing-Drift; eine nach der Ausführung erfasste Order ist klar als solche gekennzeichnet.
4. Als Anleger sehe ich eine Zusammenfassung: die Auto-Fill-Quote (exakt verknüpfte Orders) und die durchschnittliche Preis-Abweichung — mit klarem Hinweis, dass die Quote keine Plan-Treue misst.
5. Als selbst-hostender Multi-User-Anleger sehe ich ausschliesslich meine eigenen Orders und Transaktionen (user_id-scoped).
6. Als API-Nutzer kann ich `rationale` über die externe API genauso setzen wie über die UI (Schreib-Parität seit v0.45), und der Schreibvorgang erscheint im Audit-Log.

---

## 9. Akzeptanzkriterien (testbar)

1. `GET /api/trade-journal` liefert pro gefüllter Order genau eine Zeile mit `plan`, verknüpftem `ist` (über `linked_transaction_id`) und `adhaerenz`; **offene Orders** erscheinen mit `ist=null` und `adhaerenz=null`.
2. `preis_abweichung_pct = (actual_price - limit_price) / limit_price * 100`, **aber nur wenn** `plan.currency == transaction.currency`, sonst `null` (gleicher Währungs-Guard wie `compute_distance_pct`).
3. `timing_drift_tage = (transaction.date - order.created_at::date).days`, vorzeichenbehaftet. **Bei negativem Wert** (Order nach der Ausführung angelegt — möglich, weil das Match-Fenster `created_at` bis `txn.date + 35d` zulässt) setzt die Antwort `timing_nach_ausfuehrung=true`; die UI labelt die Zeile entsprechend und nimmt sie aus jeder Timing-Aggregation aus.
4. `PATCH /api/orders/pending/{id}` mit `rationale` speichert den Text und gibt ihn in `/api/trade-journal` zurück; bestehende PATCH-Felder bleiben unverändert. **`rationale`-PATCH ist auch auf `status='filled'` erlaubt (200)**; alle anderen Nicht-`notes`/Nicht-`rationale`-Felder bleiben auf `filled` weiterhin `400`.
5. `PATCH /api/v1/pending-orders/{id}` mit `rationale` (Scope `write`) speichert den Text, ist auf `status='filled'` erlaubt, und schreibt **genau einen** `ApiWriteLog` mit `action='pending_order_update'` (kein neuer action-Wert).
6. `try_auto_fill_order`, `/fill` und die +/-35d-/FIFO-/Exact-Shares-Matching-Logik werden **NICHT verändert** (der Diff berührt das Pending-Order-Matching nicht — per Test/Review verifiziert).
7. Ein zweiter Nutzer-Token sieht **keine** fremden Journal-Zeilen (IDOR-Test: 403 oder leere Liste), sowohl auf `/api/trade-journal` als auch `/summary`.
8. `summary.fill_rate_pct = gefuellt / (gefuellt + storniert + abgelaufen)` und ist **0/None-sicher** bei keinen abgeschlossenen Orders. **"abgelaufen" verwendet exakt die `compute_effective_status`-Definition** (`expiry_type='gtd' AND expiry_date < today`); da `expired` kein DB-Wert ist, wird `/summary` entweder über geladene Rows in Python berechnet **oder** über ein Aggregat, das dieses Prädikat in SQL repliziert — beides ist erlaubt. Das Label kommuniziert, dass dies eine Auto-Fill-Quote ist, **keine** Plan-Treue.
9. `GET /api/trade-journal` macht **kein N+1**: ein LEFT JOIN lädt Plan+Ist gemeinsam; `effective_status` wird aus den bereits geladenen Rows in Python abgeleitet (kein Per-Zeile-Query). *(Diese N+1-Freiheit ist die testbare Form von "eine Query"; das frühere starre "genau eine DB-Query" wird hier relativiert, weil `/summary`'s `expired`-Definition Python-Ableitung erlauben muss — vgl. AC8.)*
10. UI baut sauber (`cd frontend && npm run build`); UI-Texte Deutsch, neutral, korrekte Umlaute; `null`-Bucket/`null`-`preis_abweichung_pct`/negativer Drift rendern ohne Crash.

---

## 10. Test-Plan (Invarianten/Pfade pinnen)

- **Reine Rechen-Tests:** `preis_abweichung_pct` (inkl. buy/sell-Vorzeichen), `timing_drift_tage` (inkl. **negativer** Wert -> `timing_nach_ausfuehrung=true`), `fill_rate_pct` (0/None-Kanten) — pur, SQLite-fähig.
- **Currency-Guard:** unterschiedliche Währung Plan vs. Ist -> `preis_abweichung_pct = null` (kein falscher Prozentwert).
- **Expired-Konsistenz:** `fill_rate_pct`-Nenner zählt eine GTD-Order mit `expiry_date < today` als `expired`, obwohl `status='open'` in der DB steht — gleiche Definition wie `compute_effective_status`.
- **Filled-Whitelist-Pin (neu, Kern-Use-Case):** `PATCH` `rationale` auf eine `status='filled'`-Order -> `200`; `PATCH` eines anderen Feldes (z.B. `limit_price`) auf dieselbe Order -> weiterhin `400`. Spiegeltest für **beide** Pfade (`orders.py` und `external_v1.py`).
- **External-Logging-Pin (neu):** externer `rationale`-PATCH schreibt genau einen `ApiWriteLog` mit `action='pending_order_update'`; **kein** neuer action-Wert (Schutz gegen die CHECK-Constraint-Falle — neue action-Werte bräuchten Migration).
- **IDOR / Multi-User:** Fremd-Token auf `/api/trade-journal` und `/api/trade-journal/summary` -> 403/leer (Muster `test_transactions_api.py`).
- **Reconciliation-Unberührtheit (Schutz-Pin):** `try_auto_fill_order` und die +/-35d/FIFO/Exact-Shares-Pfade verlinken nach dem Diff identisch; `test_pending_order_autofill.py` bleibt unverändert grün.
- **Invarianten-Pin (Korrektheits-Invarianten):** Snapshots, XIRR/Dietz, `cost_basis`, Assetklassen-Ausschluss sind **read-only** berührt -> `test_golden_master_calculations.py` bleibt unverändert grün. Kein neuer Recalc-/Snapshot-Pfad.
- **PATCH-Rückwärts-Kompatibilität:** `rationale`-PATCH verändert keine anderen `pending_orders`-Felder; bestehende Order-Update-Tests bleiben grün.
- **Migration:** `086`-Muster, idempotent up/down; Modell-Sync (`create_all` deckt die neue Spalte ab, keine neue CHECK-Constraint).

---

## 11. Offene Entscheidungen für den Maintainer

1. **Kill-Gate-Schwellen (jetzt dreiteilig):** Sind ~30-40 % `linked_rate`, ~70 % `ccy_match_rate` und eine "niedrige" `near_miss_rate` die richtigen GO/NO-GO-Cuts? Die Probe-Queries (Abschnitt 4) auf den eigenen Daten laufen lassen; alle drei Zahlen entscheiden, nicht nur `linked_rate`.
2. **`rationale` vs. `notes`:** Wirklich getrennte Spalte (strategisch vs. taktisch), oder reicht `notes`? Empfehlung: getrennt, wegen sauberer Semantik und weil `notes` an External-API-Provenienz hängt.
3. **Verschlüsselung:** `rationale` plain (wie `notes`) ist im MVP angenommen. Falls Broker-/Kontobezug erwartet wird -> `encrypt_field`-Muster wie bei Transaction-Notes.
4. **Bucket-Treffer-Kennzahl:** Im MVP gestrichen (Semantik von `bucket_id_target` ist "wo landet die Position", nicht "strategische Absicht"). Soll `bucket_id_target` perspektivisch eine echte Absichts-Semantik bekommen?
5. **Pivot-Pfad bei kippendem Gate:** Falls `linked_rate` zu niedrig — separate, dünne Plan-Capture-Entität (Medium-Scope), die ungeplante/Markt-Trades nachträglich erfasst? Eigenes Design-Gate, nicht Teil dieses MVP.
6. **`from-rebalancing`-Button:** Plan-Capture direkt aus dem Rebalancing-Cockpit (untergewichteter Bucket -> vorbefüllte Rationale) ist hochwertig, aber bewusst Post-MVP. Früher ziehen?
7. **Surface-Ort — entschieden (bestätigen):** Default = **Tab auf der bestehenden Pending-Orders-Seite** (0 neue Route, 0 neuer Sidebar-Eintrag, Reuse der Tab-Counts). Eigene `/trade-journal`-Seite nur, falls das Tab-Layout nachweislich nicht reicht. Bitte bestätigen oder zur eigenen Seite zurücksteuern.
