# DESIGN — CH-Steuer/Vorsorge (Scope)

> **⛔ KILL-GATE GEMESSEN 28.06.2026 = NO-GO (Einkommens-Verzeichnis), PARKED.**
> Probe gegen Prod (External API, Steuerjahr 2025): **0 gebuchte Ertrags-Zeilen** im Kalenderjahr 2025; gebuchte Dividenden nach Jahr 2023:2 / 2024:6 / 2025:0 / 2026:19. Alle 4 gehaltenen ETFs „still“ (100 % des ETF-Vermögens ohne gebuchte Ausschüttung: CHSPI/EIMI/IB01 thesaurierend, OEF ausschüttend aber ungebucht). Die Kern-Annahme „Einkommensdaten liegen schon im Ledger“ ist für die Einkommens-Seite **falsch** — die Dividenden-Erfassung ist sparsam/neu (erst ab 2026 via Detection-Feature), nicht pro-Steuerjahr vollständig.
>
> **User-Entscheid:** parken bis Daten reif. **Re-Gate-Kriterium:** ein VOLLSTÄNDIG gebuchtes Steuerjahr (2026 sieht gut aus → baubar ~Anfang 2027). Alternativ-Pivot „Vermögenssteuer-Wertschriftenverzeichnis“ (Jahresend-Steuerwert, unabhängig von Dividenden-Buchungen) blieb ungenutzt.
>
> Das untenstehende Scope (MVP = CH-Ertragsverzeichnis, Judge 23/25) bleibt gültig für den Re-Build, sobald das Gate besteht.

---


> Status: Scope-Entwurf, Kill-Gate-gated. Kein Bau vor bestandener Prod-Probe (Abschnitt 4).
> Workflow: Lean-First mit Kill-Gate. Verdichtet aus Terrain-Sondierung, Ansatz "CH-Ertragsverzeichnis (read-only + CSV)" und Bewertung (Score 23/25, `recommend_with_changes`).
> Revision nach Red-Team: Kill-Gate von ISIN-Klassifizierbarkeit auf **Einkommens-Vollstaendigkeit** umgestellt (thesaurierende Fonds), Multi-User-Residenz adressiert, Probe user-scoped. Damit `recommend_with_changes` → bedingt GO erst nach der schaerferen Probe.

---

## 1. Problem & Ziel (der CH-Differenzierer)

OpenFolio ist ein selbst-gehosteter CH-Portfolio-Manager. Luecke #4 — CH-Steuer/Vorsorge — ist der "uneinholbare" Differenzierer: Kein generisches Auslands-Tool kann die Schweizer Steuer-Eigenheiten sauber abbilden, weil sie kontraintuitiv sind (Kapitalgewinne steuerfrei, Verrechnungssteuer rueckforderbar, DA-1 fuer auslaendische Quellensteuer).

**Der einzigartige Winkel:** Ein Grossteil der dafuer noetigen Daten liegt **bereits im Ledger** — Dividenden-Transaktionen mit Brutto, Quellensteuer, Waehrung, FX-Kurs; Positionen mit ISIN/Waehrung. Wir muessen nichts Neues erfassen, sondern nur **synthetisieren, was schon da ist**.

**Ziel des MVP:** Pro Steuerjahr genau die Zahlen liefern, die der CH-Steuerpflichtige sonst aus Belegen zusammensucht und ins Wertschriftenverzeichnis abtippt:
1. **Steuerbares Kapitaleinkommen aus ausgeschuetteten Ertraegen** (Dividenden + Zinsen, brutto/netto in CHF) — das **Ertragsverzeichnis**.
2. **Rueckforderbare CH-Verrechnungssteuer** (35 % auf CH-Quellen) plus separat ausgewiesene **auslaendische Quellensteuer** (DA-1-Hinweis).
3. **Sichtbar gemachte Luecke:** gehaltene Fonds-Positionen **ohne** Ausschuettung im Jahr (Verdacht thesaurierend/akkumulierend) — als explizite "via ICTax ergaenzen"-Liste, damit der Nutzer nicht unbemerkt unterdeklariert.

**Wichtige Ehrlichkeit ab Tag 1:** Das MVP deckt **nur ausgeschuettete** Ertraege aus dem Ledger ab. Thesaurierende (akkumulierende) UCITS-ETFs erzeugen **gar keine** Dividenden-/Zins-Transaktion, ihr in der CH dennoch voll steuerbarer Ertrag (ICTax-Bruttoertrag pro Anteil) ist **nicht** im Ledger. Diese Luecke wird **nicht versteckt, sondern namentlich ausgewiesen** (Punkt 3 oben, Banner + Disclaimer). Genau das ist die zentrale Korrektheits-Anforderung, nicht die ISIN-Coverage.

Nicht-Ziel: ein vollautomatischer, behoerdlich einreichbarer Steuerauszug. Wir bauen ein **glaubwuerdiges, pruefbares Arbeitsblatt fuer den Nutzer und seinen Treuhaender** — kein eCH-0196-Surrogat.

---

## 2. Was schon im Ledger liegt — und was bewusst NICHT

### Vorhanden und fuer den Report ausreichend (reine Aggregation)
- **`Transaction.type`** unterscheidet `dividend` / `interest` (Einkommens-Buckets) sauber von `buy` / `sell` / `capital_gain`.
- **`Transaction.user_id`** existiert direkt (Multi-User-Scoping ohne Position-Join).
- **`Transaction.gross_amount`** (Brutto in Originalwaehrung), **`tax_amount`** (Quellensteuer in Originalwaehrung).
- **`Transaction.total_chf`** (Netto in CHF, NOT NULL), **`taxes_chf`** (Quellensteuer in CHF), **`fees_chf`**, **`fx_rate_to_chf`**.
- **`Transaction.isin`** bzw. Fallback **`Position.isin`** fuer die Domizil-Klassifizierung; **`Position.is_etf`**, **`Position.shares`**, **`Position.cost_basis_chf`** fuer die Akkumulierer-Erkennung.
- **Query-Pattern** existiert bereits in `total_return_service.get_fee_summary` (Jahres-Aggregation via `func.extract`, user-scoped).

### CH-Kernfakt, der den Report glaubwuerdig macht: Kapitalgewinne sind STEUERFREI
Private **Kapitalgewinne** (`realized_pnl_chf`, `sell`-Transaktionen) sind in der Schweiz **einkommenssteuerfrei**. Sie tauchen im Report **nirgends** auf. Das eliminiert die **haeufigste Selbstbau-Fehlerquelle** (Verkaufsgewinne faelschlich als Einkommen deklarieren).

### Die eigentliche Daten-Luecke: thesaurierende Fonds erzeugen KEINE Transaktion
- **Akkumulierende UCITS-ETFs** schuetten nicht aus → **keine** `dividend`/`interest`-Zeile im Ledger. Ihr CH-steuerbarer Ertrag (ICTax) ist **nicht** rekonstruierbar aus dem Ledger.
- Genau die in Abschnitt 3 als Zielgruppe genannten **IE-UCITS-lastigen Depots** bestehen oft mehrheitlich aus Akkumulierern. Ohne Gegenmassnahme waere "Steuerbares Kapitaleinkommen" **systematisch zu niedrig** → Unterdeklarations-/Haftungsrisiko.
- **Gegenmassnahme (lean, keine neue Quelle):** Eine `LEFT JOIN`-Erkennung auf derselben Query listet **gehaltene** (`shares > 0`) Fonds-Positionen (`is_etf`) **ohne** Ausschuettung im Jahr als eigenen Block "Moegliche thesaurierende Fonds — Ertrag NICHT im Ledger". **Keine** ICTax-Wertberechnung im MVP (das waere eine zweite Quelle → Folge-Welle).

### Multi-User: Die CH-Resident-Annahme ist explizit zu machen
- `constants/withholding.py` dokumentiert, dass `WITHHOLDING_BY_COUNTRY` einen **CH-Resident-User** voraussetzt. Die ganze Interpretation (CH-WHT = rueckforderbar, Auslands-WHT = DA-1) ist **nur** fuer CH-Residenten korrekt.
- **Gegenmassnahme:** Die **Betraege** kommen ausschliesslich aus dem real gebuchten `taxes_chf` (nicht aus der globalen Rate-Map); die Map/der Laendercode dient **nur** der Domizil-Bucketierung. Die CH-Resident-Annahme wird im Banner + CSV-Kopf **explizit** als Annahme deklariert. Wo gesetzt, spiegeln die gebuchten `taxes_chf` ohnehin die tatsaechlichen Saetze (inkl. `position.dividend_withholding_pct`-Overrides aus dem Import) — der Report erfindet keine Saetze.

### Bewusst NICHT neu erfasst (kein Modell-Risiko, keine Migration)
- **Kein** `gross_amount`-Backfill — Brutto wird zur Laufzeit rekonstruiert (Abschnitt 5).
- **Kein** `country_of_domicile`-Feld — Domizil zur Laufzeit aus `COALESCE(transaction.isin, position.isin)[:2]`.
- **Kein** `tax_value_year_end`-Feld, **kein** PositionSnapshot (Vermoegenssteuer = separates Scope).
- **Kein** ICTax-Wertberechnung fuer Akkumulierer (nur sichtbar machen, nicht beziffern).
- **Kein** `rueckgefordert`-Flag, **kein** DA-1-`statutory_rate`-Feld.

---

## 3. Empfohlener MVP-Cut + Begruendung

### MVP = "CH-Ertragsverzeichnis (read-only + CSV)"
Eine read-only Jahres-Sicht aller `dividend`/`interest`-Transaktionen (Brutto / Quellensteuer / Netto, alles in CHF), getrennt nach **CH-Quelle** (rueckforderbare Verrechnungssteuer), **Ausland** (DA-1-Hinweis) und **unklassifiziert** — **plus** ein separater Block **"Moegliche thesaurierende Fonds"** (gehaltene Fonds ohne Ausschuettung im Jahr) — plus CSV-Export. Komplett aus dem Ledger, **eine Query, keine neue Quelle, ohne neue Tabelle, ohne Migration, ohne Worker**.

### Begruendung aus den Scores (Total 23/25, `recommend_with_changes`)
| Kriterium | Score | Warum |
|---|---|---|
| Lean | 5/5 | Keine Migration, reine Query-Synthese auf verifiziertem `get_fee_summary`-Pattern. |
| Value | 4/5 | Genau die Zahlen, die der Nutzer abtippt; CH-Kapitalgewinn-Freiheit korrekt abgebildet; Akkumulierer-Luecke sichtbar statt still. |
| Data Feasibility | 4/5 | Alle Felder existieren; das **primaere** Gate ist jetzt die Einkommens-Vollstaendigkeit (Akkumulierer-Anteil), sekundaer die ISIN-Coverage der ausgeschuetteten Zeilen → Kill-Gate. |
| Low Build Cost | 5/5 | ~2–3 Tage gesamt. |
| Correctness Safety | 5/5 | Reine Aggregation beruehrt **keine** Golden-Master-Invariante. |

### Aufloesung des Kill-Gate-Selbstwiderspruchs (Red-Team high)
Der fruehere Entwurf argumentierte zugleich "IE-UCITS-lastig → rueckforderbare Verrechnungssteuer nahe null → wenige/keine `ch_rows`" **und** verlangte "`ch_rows` haben mehrheitlich `taxes_chf > 0`". Bei `ch_rows = 0` (typischer Zielfall) ist das undefiniert. **Korrektur:** Das `ch_rows`-Mehrheits-Kriterium wird **gestrichen**. GO/NO-GO entscheidet sich ueber (a) Einkommens-Vollstaendigkeit (Akkumulierer-Anteil am ETF-Vermoegen) und (b) ISIN-Coverage der **ausgeschuetteten** Zeilen. Die rueckforderbare Verrechnungssteuer darf legitim klein/null sein — das ist kein NO-GO, sondern der erwartete Normalfall.

### Drei verbindliche Aenderungen
1. **Kill-Gate-Probe ZWINGEND gegen Prod-Daten, user-scoped** (Abschnitt 4) — nicht gegen die lokale Dev-Seed-DB (16 kuratierte Zeilen sind NICHT der Gate). Primaer misst sie die **Einkommens-Stille** (Akkumulierer), sekundaer die ISIN-Klassifizierbarkeit der ausgeschuetteten Zeilen.
2. **Headline-KPI = "Steuerbares Kapitaleinkommen CHF (ausgeschuettet)"** als Primaerzahl, mit unmittelbar danebenstehendem Hinweis "+ N Fonds ohne Ausschuettung (ICTax ergaenzen)". Fuer typische CH-Depots (ueberwiegend IE-UCITS) ist die rueckforderbare Verrechnungssteuer oft nahe null; Wert liegt in Einkommen + Auslands-WHT + sichtbarer Akkumulierer-Luecke.
3. **Minimal-Cut zuerst:** interne JSON-View + Golden-Master-Pin als erster, eigenstaendig wertvoller Schritt. CSV- und External-Endpoint als unmittelbarer Folge-Schritt (gleiche Service-Funktion, kein neuer Atemzug).

### Bewusst ausgelassene Ausbauten (Folge-Wellen, nicht MVP)
- **ICTax-Bewertung der Akkumulierer** (Bruttoertrag pro Anteil): braucht ICTax als zweite Datenquelle + Stichtags-Bestand → eigenes Scope. MVP macht die Luecke nur sichtbar.
- **Wertschriftenverzeichnis / Jahresend-Steuerwert** (Vermoegenssteuer): braucht per-Position-31.12-Bewertung → eigenes Scope (PositionSnapshot oder On-Demand-Replay via `regenerate_snapshots`). Daten-Reife laut Terrain ~40 %.
- **DA-1-Formular-Prefill** (per-Country-Aggregation + Treaty-Lookup): MVP zeigt nur Auslands-Summe + Hinweis.
- **eCH-0196-XML-Export**: Haftungs-/Naming-Falle — ein Excel/CSV ist KEIN eCH-0196. Bewusst nicht.
- **Saeule 3a** (Beitrags-/Entnahme-Tracking): 0 % Daten heute, eigenes Feature (~20–30 h).
- **Private-Equity-Dividenden** (`private_equity_dividends`): waeren eine **zweite Aggregationsquelle** → bricht den Lean-Claim "eine Query, keine neue Quelle". Im MVP **draussen**; spaeter nur als bewusster eigener Atemzug mit eigenem Test.
- **Verrechnungssteuer-Rueckforderungs-Status** (`rueckgefordert`-Flag) und **Gewerbsmaessiger-Wertschriftenhaendler-Fruehwarner** (ESTV KS 36): spaeter.

---

## 4. Das Kill-Gate (entscheidet VOR dem Bau)

> **Die EINE Frage (umgestellt):** Taugen die schon gebuchten Daten, um ein **glaubwuerdiges Ertragsverzeichnis OHNE manuelle Nacherfassung** zu erzeugen? Das kippt **nicht** an der ISIN-Klassifizierbarkeit allein, sondern primaer an der **Einkommens-Vollstaendigkeit**: Sitzt ein materieller Teil des ETF-Vermoegens in **ausschuettungslosen** (also vermutlich thesaurierenden) Fonds, deren CH-steuerbarer Ertrag NICHT im Ledger ist, dann ist die Headline systematisch zu niedrig — und das MVP muss diese Luecke ehrlich ausweisen (oder bei zu grossem Anteil als NO-GO neu zugeschnitten werden).
>
> **Warum nicht ISIN-Coverage als Primaer-Gate:** `gross_amount`-Nullability ist via `total_chf + taxes_chf` rekonstruierbar. Fehlende ISIN landet sichtbar in `unclassified` und verfaelscht die Headline nicht. Die **stille Untererfassung durch Akkumulierer** ist der einzige Fehler, den der Nutzer nicht sieht — deshalb ist er das Kill-Risiko.

### Ausfuehrbare Probe (Prod, **je `user_id`**)
```sql
WITH yr AS (SELECT 2025::int AS y)
SELECT
  p.user_id,
  count(*) FILTER (WHERE p.shares > 0)                                          AS held,
  -- PRIMAER: gehaltene Fonds ohne Ausschuettung im Jahr (Akkumulierer-Verdacht)
  count(*) FILTER (WHERE p.shares > 0 AND d.n IS NULL AND p.is_etf)             AS silent_funds,
  round(100.0 * coalesce(sum(p.cost_basis_chf)
        FILTER (WHERE p.shares > 0 AND d.n IS NULL AND p.is_etf), 0)
      / nullif(sum(p.cost_basis_chf) FILTER (WHERE p.shares > 0 AND p.is_etf), 0), 1)
                                                                               AS pct_etf_value_income_silent,
  -- SEKUNDAER: ISIN-Coverage NUR der ausgeschuetteten Zeilen (user-scoped)
  count(*) FILTER (WHERE t2.id IS NOT NULL)                                     AS dist_rows,
  count(*) FILTER (WHERE t2.id IS NOT NULL AND left(upper(coalesce(t2.isin, p.isin)), 2)
                   IN ('CH','US','DE','AT','FR','NL','GB','IE','LU'))           AS classifiable,
  -- TERTIAER (Red-Team low): separat gebuchte 'tax'-Zeilen (WHT nicht auf der Dividenden-Zeile)
  count(*) FILTER (WHERE t3.id IS NOT NULL)                                     AS separate_tax_rows
FROM positions p
LEFT JOIN (
  SELECT t.position_id, count(*) n FROM transactions t, yr
  WHERE t.type IN ('dividend','interest') AND extract(year FROM t.date) = yr.y
  GROUP BY t.position_id
) d  ON d.position_id = p.id
LEFT JOIN transactions t2 ON t2.position_id = p.id
   AND t2.type IN ('dividend','interest') AND extract(year FROM t2.date) = (SELECT y FROM yr)
LEFT JOIN transactions t3 ON t3.position_id = p.id
   AND t3.type = 'tax' AND extract(year FROM t3.date) = (SELECT y FROM yr)
GROUP BY p.user_id;
```

### Wo ausfuehren (WICHTIG)
- **Prod-Daten, nicht Seed.** Die Prod-DB laeuft auf `10.10.70.10` und ist von der Dev-Box **nicht** per SSH erreichbar. Die lokale Postgres haelt nur Dev-Seed-Daten.
- **Maintainer-Instanz = effektiv single-user** (eigenes Portfolio). Damit misst der einzige ausfuehrbare Pfad — **External API** (X-API-Key + Custom-User-Agent, Key in `~/.config/finance-alerts/openfolio.env`; Cloudflare blockt Default-Python-UA mit 403) — dieselbe Population wie die `user_id`-gruppierte SQL. **Falls** die Instanz doch mehrere User traegt, wird **je User** ausgewertet und gegatet; die SQL ist deshalb bereits user-scoped (`GROUP BY p.user_id`).
- Liegt kein direkter SQL-Read vor, die drei Kennzahlen ueber vorhandene Read-Endpoints (Positionsliste + Transaktionsliste je Jahr) client-seitig nachbilden.

### Gate-Entscheidung
- **GO**, wenn: `pct_etf_value_income_silent` **<= ~10–15 %** (Akkumulierer-Anteil unkritisch — die sichtbare "ICTax ergaenzen"-Liste reicht) **UND** `classifiable / dist_rows >= 0.90` (auf der **ausgeschuetteten** Subpopulation; `dist_rows = 0` → ISIN-Kriterium entfaellt, da nichts zu klassifizieren ist).
- **NO-GO / Zuschnitt aendern**, wenn `pct_etf_value_income_silent` **materiell > 15 %**: Der Report waere als "Steuerbares Kapitaleinkommen" irrefuehrend. Dann MVP **ehrlich auf "nur ausgeschuettete Ertraege" umbenennen**, die Akkumulierer-Liste prominent (nicht nur als Fussnote) fuehren, oder Bau bis zur ICTax-Welle zuruecksetzen.
- **NO-GO / erst Stammdaten**, wenn `classifiable / dist_rows < 0.90`: zuerst **ISIN-Backfill** auf den betroffenen Positionen, dann Report. Unklassifizierte Zeilen niemals still in CH/Ausland mischen.
- **`separate_tax_rows > 0`:** bekannte Luecke dokumentieren (rueckforderbare Verrechnungssteuer dann potenziell untererfasst) — im MVP als Hinweis, Aggregation der `tax`-Zeilen als kleiner Folge-Schritt.

---

## 5. Datenmodell (Wiederverwendung vs. neu)

**Wiederverwendung (keine Migration, keine neue Tabelle):**

| Quelle | Feld | Verwendung im Report |
|---|---|---|
| `Transaction` | `type` | Filter `IN ('dividend','interest')`; `tax` nur fuer Probe/Hinweis |
| `Transaction` | `user_id` | direkter user-Scope |
| `Transaction` | `date` | Jahres-Filter via `func.extract('year', date)` |
| `Transaction` | `gross_amount`, `tax_amount`, `taxes_chf`, `total_chf`, `fees_chf`, `fx_rate_to_chf`, `currency`, `isin` | Brutto/Netto/WHT in CHF |
| `Position` | `isin`, `ticker` | Domizil-Fallback, Anzeige |
| `Position` | `is_etf`, `shares`, `cost_basis_chf` | Akkumulierer-Erkennung (gehalten + keine Ausschuettung) |
| `constants/withholding.py` | `WITHHOLDING_BY_COUNTRY` | **nur** Domizil-Bucketierung (Laendercode-Set), **nicht** Betragsberechnung |

**Abgeleitete Groessen (Laufzeit):**
- `brutto_chf = COALESCE(gross_amount * fx_rate_to_chf, total_chf + taxes_chf)`. **Gebuehren-Definition (Red-Team med):** `fees_chf` gehoeren **nicht** in den Brutto-Ertrag (steuerbar ist der Bruttoertrag; Depotgebuehren sind ggf. separat als Vermoegensverwaltungskosten abziehbar, ausserhalb dieses Reports). Damit gilt der Abgleich: `netto_chf = brutto_chf − taxes_chf − fees_chf` (statt der naiven Gleichheit ohne Gebuehren).
- `domizil = left(upper(COALESCE(transaction.isin, position.isin)), 2)` → Bucket `ch` / `foreign` / `unclassified`.
- `recoverable_verrechnungssteuer_chf = SUM(taxes_chf) WHERE domizil == 'CH'` (aus real gebuchtem `taxes_chf`, nicht aus der Rate-Map).
- `income_silent_funds = Positionen mit shares > 0 AND is_etf AND keiner dividend/interest-Zeile im Jahr` (LEFT JOIN, kein Betrag).

**Neu:** nichts am Datenmodell. Eine Service-Funktion `get_tax_income_report(db, user_id, year)` (eigenes `income_tax_service.py` empfohlen, siehe offene Entscheidung 3) — eine Hauptquery + eine Silent-Funds-Query, Klassifizierung in Python.

---

## 6. API (intern + extern — Paritaet ist Pflicht)

**Intern (`get_current_user`, user_id-scoped):**
- `GET /api/portfolio/tax-income-report?year=YYYY`
- `GET /api/portfolio/tax-income-report.csv?year=YYYY` (Content-Type `text/csv`, Semikolon-getrennt fuer Excel-DE)

**Extern (`get_api_user`, X-API-Key — byte-identische Payload):**
- `GET /api/v1/external/tax-income-report?year=YYYY`

Read-only → **kein** Write-Scope noetig. External-Paritaet ist Pflicht (Memory: External API hat seit v0.45 volle UI-Paritaet).

**Response-Shape (JSON):**
```json
{
  "year": 2025,
  "assumed_residence": "CH",
  "ch_source":    { "rows": [], "gross_chf": 0, "withholding_chf": 0, "net_chf": 0 },
  "foreign":      { "rows": [], "gross_chf": 0, "withholding_chf": 0, "net_chf": 0 },
  "unclassified": { "rows": [], "gross_chf": 0, "withholding_chf": 0, "net_chf": 0 },
  "income_silent_funds": { "rows": [], "count": 0 },
  "taxable_capital_income_chf": 0,
  "recoverable_verrechnungssteuer_chf": 0,
  "foreign_withholding_chf": 0,
  "unclassified_count": 0
}
```
Jede Ertrags-`row`: `{ date, ticker, isin, currency, gross_chf, withholding_chf, fees_chf, net_chf, source }`.
Jede `income_silent_funds`-`row`: `{ ticker, isin, currency, note: "Ertrag nicht im Ledger - via ICTax ergaenzen" }` (kein Betrag).

`taxable_capital_income_chf` = Brutto ueber CH + Ausland + unklassifiziert (**nur ausgeschuettet**). `foreign_withholding_chf` = WHT-Summe Ausland (DA-1-relevant). `assumed_residence` macht die CH-Resident-Annahme maschinenlesbar (Default `"CH"`).

---

## 7. UI + Export-Format

**Neuer Tab/Abschnitt "Steuern" (Desktop-only — OpenFolio ist reines Desktop-Tool):**
- **Jahr-Selector** (Dropdown ueber die in den Transaktionen vorhandenen Jahre) — `year` ist Pflicht-Parameter.
- **Zwei KPI-Kacheln** zuoberst:
  1. **"Steuerbares Kapitaleinkommen CHF (ausgeschuettet)"** (Primaerzahl) — direkt darunter klein: "+ N Fonds ohne Ausschuettung (ICTax ergaenzen)" wenn `income_silent_funds.count > 0`.
  2. **"Rueckforderbare Verrechnungssteuer CHF"** (sekundaer).
- **Drei Ertrags-Tabellen:** CH-Quelle / Ausland / Unklassifiziert. Spalten: Datum, Titel, ISIN, Waehrung, Brutto CHF, Quellensteuer CHF, Gebuehren CHF, Netto CHF.
- **Block "Moegliche thesaurierende Fonds"** (wenn nicht leer): gehaltene Fonds ohne Ausschuettung im Jahr, Spalten Titel / ISIN / Waehrung / Hinweis "Ertrag nicht im Ledger — via ICTax ergaenzen". Bewusst **ohne** Betrag.
- **Hinweisbanner** (Disclaimer, Abschnitt 10): CH-Resident-Annahme, Kapitalgewinne steuerfrei (nicht enthalten), thesaurierende Fonds nicht im Ertrag, auslaendische WHT via DA-1 nur bis DBA-Satz/gedeckelt, keine verbindliche Steuerberatung.
- **Button "CSV exportieren"** → ruft `.csv`-Endpoint mit aktuellem Jahr.
- Komponente lehnt sich an `FeeSummary.jsx` an.

**Export-Format:** CSV (Semikolon, Excel-DE-kompatibel), inkl. Disclaimer-Kopfzeile und der Silent-Funds-Liste als eigener Abschnitt. **Kein** eCH-0196-XML — bewusst (Naming-/Haftungsfalle). Sprache neutral, Schweizer Deutsch (kein scharfes S, korrekte Umlaute).

---

## 8. User Stories

1. Als CH-Steuerpflichtiger waehle ich ein Steuerjahr und sehe sofort alle Dividenden und Zinsen mit Brutto, Quellensteuer und Netto in CHF, damit ich das Ertragsverzeichnis nicht aus Belegen zusammensuchen muss.
2. Als Nutzer sehe ich das steuerbare Kapitaleinkommen (ausgeschuettet) prominent als Primaerzahl, damit ich weiss, was ins Ertragsverzeichnis kommt.
3. Als Nutzer sehe ich die Summe der rueckforderbaren CH-Verrechnungssteuer (35 %), damit ich weiss, welchen Betrag mir die Steuererklaerung zurueckbringt.
4. Als Nutzer sehe ich auslaendische Quellensteuer separat mit DA-1-Hinweis, damit ich die pauschale Steueranrechnung beantragen kann — im Wissen, dass sie nur bis zum DBA-Satz und gedeckelt anrechenbar ist.
5. Als Halter thesaurierender ETFs sehe ich eine explizite Liste meiner ausschuettungslosen Fonds mit dem Hinweis, ihren Ertrag via ICTax zu ergaenzen, damit ich nicht unbemerkt unterdeklariere.
6. Als Nutzer exportiere ich die Jahresliste als CSV, um sie meinem Treuhaender zu geben oder ins Steuertool zu uebernehmen.
7. Als Nutzer mit External-API-Zugriff hole ich den Jahresreport per X-API-Key, damit ich ihn in eigene Tools einbinde.

---

## 9. Akzeptanzkriterien

1. Report ist **user_id-scoped** ueber `Transaction.user_id` (kein Cross-User-Leak) und nimmt `year` als **Pflichtparameter**.
2. Nur `type IN ('dividend','interest')` erscheint im Ertrag; `buy`/`sell`/`capital_gain` und `realized_pnl_chf` tauchen **nirgends** auf (CH-Kapitalgewinn-Steuerfreiheit korrekt abgebildet).
3. Brutto CHF wird ueber `COALESCE(gross_amount*fx_rate_to_chf, total_chf + taxes_chf)` berechnet; Zeilen mit `gross_amount IS NULL` erscheinen trotzdem korrekt.
4. CH vs. Ausland vs. **unklassifiziert** wird ueber `COALESCE(transaction.isin, position.isin)[:2]` gegen das bekannte Laendercode-Set klassifiziert; nicht klassifizierbare Zeilen landen sichtbar im **eigenen `unclassified`-Bucket** — niemals still in CH/Ausland gemischt.
5. `recoverable_verrechnungssteuer_chf == SUM(taxes_chf)` der CH-Zeilen (aus real gebuchtem `taxes_chf`); je Bucket gilt `Brutto − Quellensteuer − Gebuehren == Netto` auf den Rappen (Gebuehren explizit beruecksichtigt).
6. `interest`-Zeilen: `total_chf` als Netto zeigen, WHT = 0 wenn `taxes_chf = 0` — **nicht raten**, ob Brutto/WHT aufgeschluesselt sind.
7. **Akkumulierer-Sichtbarkeit:** Gehaltene Fonds (`shares > 0`, `is_etf`) ohne Ausschuettung im Jahr erscheinen im `income_silent_funds`-Block mit Ergaenzungs-Hinweis und **ohne** Betrag; sie fliessen **nicht** in `taxable_capital_income_chf` ein.
8. **CH-Resident-Annahme** ist in JSON (`assumed_residence`), UI-Banner und CSV-Kopf explizit deklariert.
9. CSV-Export liefert exakt dieselben Zeilen/Summen wie die JSON-View fuer dasselbe Jahr; Trennzeichen Excel-DE-kompatibel.
10. External-Endpoint liefert **byte-identische** Payload zur internen Route (Paritaet).
11. **Golden-Master/Unit-Test** pinnt einen Fixtures-Satz auf erwartete Brutto/Netto/WHT/recoverable-Summen, der **beide** `COALESCE`-Zweige und den Gebuehren-Divergenzfall abdeckt: (a) CH-Dividende mit `gross_amount` gesetzt, (b) US-Dividende mit `gross_amount IS NULL` (Rekonstruktion aus `total_chf + taxes_chf`), (c) Dividende mit `fees_chf > 0` (Netto-Abgleich), (d) IE-UCITS-Ausschuettung, (e) Zeile ohne ISIN → `unclassified`, (f) gehaltener Akkumulierer ohne Transaktion → `income_silent_funds`.
12. UI-Text neutral und in Schweizer Deutsch (kein scharfes S, korrekte ae/oe/ue als ä/ö/ü).

---

## 10. Korrektheits-/Haftungs-Risiken + Disclaimer-Strategie

**Groesstes Risiko (umgestellt):** Eine als autoritativ wahrgenommene **falsche, weil unvollstaendige** Steuerzahl — konkret die **systematische Untererfassung durch thesaurierende Fonds**. Das MVP loest das **nicht** rechnerisch (keine ICTax-Quelle), aber macht es **sichtbar** und benennt es im Banner namentlich; die Headline traegt explizit den Zusatz "(ausgeschuettet)".

Subtile Fehl-Pfade, die das MVP bewusst NICHT ausrechnet:
- **Thesaurierende UCITS-ETFs:** kein Ledger-Eintrag → CH-steuerbarer ICTax-Ertrag fehlt im Betrag. **Gegenmassnahme:** `income_silent_funds`-Block + Banner.
- **Nicht-CH-Resident:** Die CH-WHT-rueckforderbar / Auslands-DA-1-Interpretation gilt nur fuer CH-Residenten. **Gegenmassnahme:** explizite Annahme-Deklaration (`assumed_residence`, Banner, CSV-Kopf); Betraege stammen aus real gebuchtem `taxes_chf`, nicht aus einer Resident-Annahme-Map.
- **CH-Fonds mit Auslandsanteil:** `taxes_chf` einer CH-Zeile == "rueckforderbare Verrechnungssteuer" ist eine Vereinfachung; bei CH-Fonds mit auslaendischem Unterbau nicht exakt.
- **US-Position mit 35 %-Abzug (fehlendes W-8BEN):** erscheint als auslaendische WHT; der DBA-Satz (15 %) ist nicht garantiert angewendet, der Rest nur via US-Refund.
- **Separat gebuchte `tax`-Zeilen:** Swissquote/IBKR buchen WHT verifiziert AUF der Dividenden-Zeile (`taxes_chf`); manuelle/andere Quellen koennten WHT als separate `tax`-Zeile buchen → dann untererfasst. **Gegenmassnahme:** Probe zaehlt `separate_tax_rows`; falls vorhanden, als bekannte Luecke dokumentiert.
- **ISIN-Coverage:** Zeilen ohne ISIN landen korrekt in `unclassified`, separat sichtbar — verfaelschen die Headline nicht.

**Korrektheits-Invarianten:** Reine Aggregation, **kein** Touch an Rendite-Definitionen, Assetklassen-Ausschluss oder Signal-Logik. Golden-Master bleibt unberuehrt; der neue Test (Krit. 11) pinnt die Report-Outputs selbst.

**Disclaimer-Strategie (Banner + CSV-Kopf, woertlich praezisiert):**
> "Arbeitshilfe, keine verbindliche Steuerberatung. Annahme: Steuerdomizil Schweiz (CH-Resident). Werte aus dem Ledger abgeleitet — vor Einreichung pruefen. Private Kapitalgewinne sind in der CH steuerfrei und hier nicht enthalten. Thesaurierende (akkumulierende) Fonds schuetten nicht aus und erscheinen NICHT im Ertrag — ihr in der CH steuerbarer Ertrag (ICTax-Bruttoertrag pro Anteil) muss separat ergaenzt werden (siehe Liste 'Moegliche thesaurierende Fonds'). Auslaendische Quellensteuer ist ggf. bis zum DBA-Satz via DA-1 anrechenbar, gedeckelt auf die geschuldete CH-Steuer und nicht zwingend voll erstattet."

- **Read-only**, kein Schreibpfad, kein behoerdliches Format. **Kein** "eCH-0196"-Naming irgendwo. `unclassified`- und `income_silent_funds`-Bloecke machen Daten-Luecken sichtbar statt sie zu verstecken. **Keine** Anrechnungsbetraege berechnet (nur Summe + neutraler Hinweis).

---

## 11. Offene Entscheidungen fuer den Maintainer

1. **Kill-Gate-Run:** Wer fuehrt die Einkommens-Vollstaendigkeits-Probe (Abschnitt 4) wann aus? Direkter Read-SQL-Pfad zur Prod oder Nachbildung ueber External-Read-Endpoints? **Bau startet erst nach GO.**
2. **Akkumulierer-Schwelle:** Bei `pct_etf_value_income_silent` zwischen ~10–15 %: MVP mit prominenter Silent-Funds-Liste trotzdem ausliefern, oder erst nach ICTax-Welle? (Vorschlag: ausliefern, da sichtbar gemacht.)
3. **Multi-User-Realitaet:** Ist die Prod-Instanz effektiv single-user (eigenes Portfolio)? Falls mehrere User: Gate je User entscheiden. Soll die CH-Resident-Annahme spaeter aus `user_settings` hart gegatet werden statt nur deklariert?
4. **ISIN-Backfill bei NO-GO:** Falls `classifiable/dist_rows < 0.90` — ISIN-Stammdaten zuerst nachpflegen oder MVP mit grossem `unclassified`-Bucket trotzdem ausliefern?
5. **Service-Ort:** Neue Funktion in `total_return_service.py` einhaengen oder eigenes `income_tax_service.py` (empfohlen wegen klarer Domaene)?
6. **`interest`-Semantik:** Sind Swissquote-"Zinsen auf Einlagen" brutto-mit-Verrechnungssteuer oder bereits netto gebucht? Falls unklar → im MVP konservativ als Netto zeigen (Krit. 6); Klaerung im `swissquote_parser` als Folge-Ticket.
7. **Gebuehren auf Dividenden:** Bestaetigung, dass `fees_chf` auf Dividenden NICHT in den steuerbaren Brutto gehoeren (nur Netto-Abgleich) — so im Entwurf angenommen.
8. **Reihenfolge der Folge-Wellen:** Was zuerst — ICTax-Bewertung der Akkumulierer, Wertschriftenverzeichnis (Vermoegenssteuer, braucht PositionSnapshot) oder DA-1-Prefill? Drei eigene Scopes; PE-Dividenden bleiben im read-only-MVP bewusst draussen.
