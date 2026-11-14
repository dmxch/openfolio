# Korrektheits-Invarianten und Konventionen

Verbindliche Definition der Regeln, auf die sich Code-Kommentare in diesem Repo berufen.

Diese Datei ist **versioniert**, und das ist ihr Zweck: 40 Stellen in 21 versionierten Dateien
verweisen mit `Invariante #1/#2/#3` auf die Regeln unten (Zählung ohne die beiden Changelogs;
daneben existiert eine ältere Schreibweise ohne Raute in vier Dateien — siehe die Warnung zum
dritten Altschema unten). Solange die Definition nur in der gitignorten `CLAUDE.md` stand, zeigten
diese Verweise aus dem Repo heraus ins Nichts — wer das Repo klonte, bekam die Referenz ohne den
Referenten. `CLAUDE.md` verweist deshalb hierher, statt die Regeln selbst zu führen.

**Schutz durch Tests, nicht durch Verbot.** Die Invarianten sind änderbar — sie dürfen sich nur
nicht *still* ändern. Nutzer vergleichen Zahlen über die Zeit; ein subtiler Bruch ist unsichtbar und
zerstört Vertrauen dauerhaft. Ändern ist erlaubt, wenn:

(a) Definition und historische Vergleichbarkeit erhalten bleiben oder bewusst migriert werden,
(b) ein Golden-Master-Test den Bruch rot färbt (`backend/tests/test_golden_master_calculations.py`),
(c) bei echter Bedeutungsänderung kurz beim Maintainer rückgefragt wird.

Wo ein Test noch fehlt, hier vorsichtig arbeiten und im Zweifel rückfragen.

Abschnitte **„Abweichung"** halten fest, wo der Code die Regel heute nicht sauber durchhält. Sie
sind Bestandsaufnahme, nicht Freibrief: wer dort arbeitet, weiss, dass er auf dünnem Eis steht.

## Korrektheits-Invarianten

### Invariante #1 — Rendite-Definitionen

Betrifft `backend/services/portfolio_service.py`, `recalculate_service.py`, `price_service.py`,
`performance_history_service.py`, `total_return_service.py` und `backend/services/utils.py`.

> `services/utils.py` (435 Zeilen: FX-Raten, Moving Averages, Mansfield-RS) — **nicht**
> `backend/utils.py` (`get_client_ip()` und `rate_limit_key()`).

- **`cost_basis_chf`** = Summe der `total_chf` der bestandsbildenden Buchungen (`buy`,
  `delivery_in`) in CHF zum Buchungszeitpunkt, Gebühren darin enthalten. Verkäufe reduzieren sie
  proportional über den gewichteten Durchschnittspreis (`cost_basis_chf *= 1 − sell_ratio`); der
  zugeordnete Anteil landet als `cost_basis_at_sale` auf der Verkaufsbuchung
  (`recalculate_service.py:74-92`). Nach einem Verkauf ist das Feld also nicht mehr der Wert zum
  Kaufzeitpunkt.
- **`value_chf`** = `shares × current_price × fx_rate`, auch für manuell bepreiste Positionen
  (`portfolio_service.py:402`). `current_price` schreibt der Worker, ausser `pricing_mode` und
  `price_source` sind beide `manual` (`models.position.has_manual_price`): nur dann gilt der Kurs
  als von Hand gepflegt. `pricing_mode: manual` mit einer anderen Preisquelle heisst: Bestand von
  Hand geführt (Schutz im Recalc), Kurs vom Worker. Edelmetall und Krypto mit `coingecko_id`
  werden immer mit ihrer eigenen Kursquelle bewertet (`models.position.has_own_price_source`). Im Payload und in der API heisst die Grösse `market_value_chf`
  (`portfolio_service.py:288`) — nicht zu verwechseln mit `AllocationItem.value_chf`, dem Betrag
  eines Allokations-Eimers.
- **`perf_pct`** = `((value_chf / cost_basis_chf) − 1) × 100` — im Code als `pnl_pct`
  (`portfolio_service.py:209`), aggregiert als `total_pnl_pct` (`:327`).
- **Monatlich = Modified Dietz** (`performance_history_service._monthly_returns_modified_dietz`)
- **Jahres-/YTD-Total = XIRR (MWR)** auf 365-Tage-Basis. Die Fallbacks sind Teil der Definition,
  nicht ihr Bruch, und je Kennzahl verschieden: Beim **Jahres-Total** werden die Modified-Dietz-
  Monate verkettet, wenn XIRR nicht konvergiert; die betroffenen Jahre stehen im Payload-Feld
  `annual_totals_dietz_fallback_years` (`performance_history_service.py:281-287`). Beim **YTD**
  greift ein einfacher Snapshot-Return (`total_return_service.py:226-229`), beim **All-time-Total**
  eine nicht annualisierte Geld-auf-Geld-Zahl (`:152`).

Definierte Ausnahmen, keine Verletzungen:

- **Cash und Vorsorge** tragen in `cost_basis_chf` ihren Saldo — abweichend vom Feldnamen in
  **Positionswährung**, nicht in CHF; die CHF-Umrechnung passiert erst beim Lesen über FX
  (`portfolio_service.py:357-377`). P&L ist 0, weil `invested` auf den FX-konvertierten Marktwert
  gesetzt wird (`:199-205`).
- **Krypto** (CoinGecko) und **Gold** (Gold.org) liefern den Preis bereits in CHF, der FX-Faktor
  entfällt daher in der Portfolio-Formel (`portfolio_service.py:379-398`). **Silber, Platin und
  Palladium** kommen als USD-Futures (`SI=F`, `PL=F`, `PA=F`) und werden in
  `price_service.get_metal_price_chf` (`price_service.py:251-267`) mit USDCHF umgerechnet — die
  FX-Umrechnung findet dort statt, nicht im `portfolio_service`.

### Invariante #2 — Assetklassen-Ausschluss

**Auf der Wert-Seite** sind Immobilien und Private Equity vollständig ausgeschlossen: aus dem
Snapshot-Wert (`total_value_chf`, `cash_chf`), aus der History, aus dem Daily Change und damit aus
der Wertreihe von Modified Dietz und XIRR (`snapshot_service._calc_portfolio_value_fast` im
Tageslauf, `snapshot_service._replay_ledger` im Regen).

> **Abweichung (Cashflow-Seite):** Die Transaktionen dieser Positionen zählen mit.
> `net_cash_flow_chf` der Portfolio-Zeile summiert alle Transaktionen des Users seit dem letzten
> Portfolio-Snapshot bis zum Stichtag, ohne Positionstyp-Filter
> (`snapshot_service._daily_txn_cash_flow` im Tageslauf, `snapshot_service._replay_ledger` im
> Regen). Der Regen schreibt Portfolio-Zeilen nur an Werktagen; Buchungen vom Wochenende stehen
> deshalb in der nächsten Zeile. Ohne Vorzeile zählt im Tageslauf nur der Stichtag. Die
> Cashflow-Seite von Dietz/XIRR liest genau diesen Wert plus dieselben ungefilterten Rows. Trägt
> eine Zeile genau die Buchungen seit der Zeile davor nach, zählt XIRR diese Buchungen einmal, an
> ihrem Buchungsdatum (`performance_history_service._rolled_up_snapshot_cfs`). Eine
> PE-Kapitalabrufung wirkt dort als Zufluss ohne Wertzuwachs. Auf Bucket-Ebene ist das über
> `snapshot_service._EXCLUDED_FROM_BUCKET_SUMS` gefiltert, auf Portfolio-Ebene nicht.

> **Abweichung (Daily Change):** `performance_service.py:17` schliesst per Typ nur `cash`,
> `pension` und `private_equity` aus — `real_estate` fehlt. Immobilien fallen dort nur über einen
> Feld-Guard heraus (kein `price_cache`-Eintrag, weil `real_estate` in `_NON_YAHOO_TYPES` steht).

**Vorsorge (`pension`) ist anders geschnitten und darf nicht mit ihnen in einen Topf.** Sie fliesst
als Saldo (`cost_basis_chf` × FX) in `total_value_chf` **und** `cash_chf` des Snapshots ein
(`snapshot_service._calc_portfolio_value_fast` / `_calc_position_value_chf`) und damit auch in
Dietz und XIRR. Draussen ist sie in den liquiden Sichten: `allocation_service.EXCLUDE_LIQUID`,
`performance_service.calculate_daily_change`, die invested-Basis des Renditeprozents
(`total_return_service.py:116-122`), History mit `liquid=True` und die FIRE-Kapitalbasis
`capital_base="liquid"`.

> **Achtung, uneinheitlicher Begriff:** „liquide" ist im Code nicht ein Kriterium. Das liquide
> Portfolio-Summary schliesst nur RE/PE aus, Vorsorge zählt dort mit. Wer einen neuen „liquiden"
> Aggregatwert baut, muss sich für eine der beiden Lesarten entscheiden und sie benennen.

Der Golden Master pinnt beide Seiten: `test_cash_and_pension_in_total_and_cash` und
`test_bond_counts_while_re_pe_pension_stay_excluded`.

### Invariante #3 — Signal-Definitionen

Parameter sind **tunebar**, aber nur mit Forward-Return-Backtest — keine stille Änderung.

- **MRS** (Titel-MRS) = EMA(13) auf Weekly-Daten, Benchmark `^GSPC`. Drei deckungsgleiche
  Implementierungen (`services/utils.compute_mansfield_rs`, `stock_scorer._compute_mrs_from_close`,
  `chart_service.get_mrs_history`).
- **Breakout** = Donchian Channel 20d, `current_price > 20-Tage-Hoch` (strict `>`), Volumen
  ≥ 1.5× 20d-Durchschnitt.

> **Abweichung (Rundung):** Die 1.5× gelten nicht überall exakt. Ungerundet verglichen wird in
> `stock_scorer.py:324` und `chart_service.py:266`. Gerundet — und damit faktisch ab ~1.45×
> wirksam — sind das **Score-Kriterium id=9** (`vol_ratio_20 = round(…, 1)` auf
> `stock_scorer.py:411`, verglichen auf `:628`) und `chart_service.get_breakout_events`
> (`chart_service.py:164-165`). Der Watchlist-Alert vergleicht zusätzlich gegen ein auf 2 Dezimalen
> gerundetes `channel_high`. Der meistgelesene Konsument der Regel, das Scoring-Kriterium, gehört
> also zur gerundeten Fraktion.

> **Namenskollision:** Im Scoring läuft unter dem Namen MRS zusätzlich eine **Industry-MRS** mit
> anderer Formel. Wer „MRS" liest, muss prüfen, welche der beiden gemeint ist.

## Konventionen

Normale Standards. Kein Golden-Master-Schutz, aber verbindlich.

- **yfinance nur über die Wrapper in `backend/yf_patch.py`**, nie `yf.download()` / `yf.Ticker()`
  direkt. Erlaubt sind `yf_download()`, `yf_ticker_attr()`, `yf_fast_info()`, `yf_search()`,
  `yf_earnings_dates()`, `yf_quote_currency()`. Alle sechs sind blockierend und gehören aus
  async-Kontext in einen Thread: `yf_download()` in `asyncio.to_thread(...)`, die Aufrufe am
  Ticker-Lock (`yf_ticker_attr()`, `yf_fast_info()`, `yf_search()`, `yf_earnings_dates()`,
  `yf_quote_currency()`) in `yf_to_thread(...)`. `yf_to_thread()` hat einen eigenen Thread-Pool:
  wartende Ticker-Abrufe belegen so nicht den Standard-Pool, den auch die DB- und Rechenaufrufe
  nutzen.
  `yf_fast_info(ticker, fields)` liest `fast_info`-Felder unter dem Lock und ersetzt
  `yf_ticker_attr(ticker, "fast_info")`. `yf_download()` erwartet eine Liste mit einem Symbol je
  Element; jedes Symbol wird gegen `MARKET_TICKER_PATTERN` geprüft, ungültige entfallen.
  `import yf_patch` steht in beiden Entrypoints vor jedem Service-Import
  (`main.py:6`, `worker.py:21`) — der Import hat Seiteneffekte.
- **Alle HTTP-Calls über httpx**, nicht `requests`. Im Backend ist `services/api_utils.py` der
  Standardweg (geteilter `AsyncClient`, `fetch_json()` / `fetch_text()`, Retry bei 429/5xx,
  4xx fail-fast; `fetch_json_once()` ohne Retry für Abrufe im Request-Pfad wie die
  Symbolsuche). Eigene Clients für abweichendes Timeout oder Streaming sind zulässig — dann aber
  ohne den gemeinsamen Retry. `requests` steht in `backend/requirements.txt` nur als transitiver
  Pin von yfinance.
- **Alle SMTP über aiosmtplib**, nicht `smtplib`, und nur über
  `services/email_service.send_smtp_message()`. Regelmässiger Weg ist `send_email()`;
  `price_alert_service.py` und `settings_service.py` bauen ihr MIME selbst und senden über
  `send_smtp_message()`. Die Funktion prüft den SMTP-Server eines Nutzers beim Senden und bindet
  die Verbindung an die geprüfte IP (`user_supplied=True`); interne Ziele gibt nur der Betreiber
  über `SMTP_ALLOWED_PRIVATE_HOSTS` frei.
- **Signal- und Alert-Texte tragen keine Kauf-/Verkaufs-Aufforderung**: „Kaufkriterien erfüllt"
  statt „Kaufsignal", „Verkaufskriterien erreicht" statt „Verkaufen!". Gilt für Alert-Titel und
  -Text, E-Mail, ntfy-Push und Signal-Labels in der UI. Nicht betroffen sind Bedienungs- und
  Sorgfaltshinweise („Fundamental-Check empfohlen", `alert_service.py:241`) sowie die Strategie-Doku
  der Hilfe-Seite und das Rebalancing-Cockpit, die Handlungsrichtungen bewusst benennen.

## Migrationstabelle: „HEILIGE Regel N" → heute

Bis `c5d004b` (27.06.2026) führte `CLAUDE.md` elf nummerierte „HEILIGE Regeln (NIEMALS brechen)".
Dieser Commit hat sie durch die kalibrierten Invarianten oben ersetzt — Schutz durch
Golden-Master-Tests statt Prosa-Verbot. Ein Teil der Code-Kommentare (und `docs/EXTERNAL_API.md`)
trägt noch die alte Nummerierung; diese Tabelle löst sie auf, bis sie umgeschrieben sind.

| alt | Gegenstand | heute |
|---|---|---|
| 1 | Performance-Berechnung | Invariante #1 |
| 2 | MRS-Berechnung | Invariante #3 |
| 3 | Breakout-Logik | Invariante #3 |
| 4 | Immobilien | Invariante #2 |
| 5 | Vorsorge | Invariante #2 |
| 6 | Private Equity | Invariante #2 |
| 7 | yfinance-Wrapper | Konvention |
| 8 | httpx statt requests | Konvention |
| 9 | aiosmtplib statt smtplib | Konvention |
| 10 | Neutrale Signal-Sprache | Konvention |
| 11 | Renditeberechnung (Dietz / XIRR) | Invariante #1 |

Die letzte getrackte Fassung der alten Liste steht in `git show 1451905:CLAUDE.md`.

> **Drittes Altschema, nicht verwechseln:** `backend/tests/test_golden_master_calculations.py`
> nummeriert seine Abschnittsüberschriften nach Formel und kennt damit eine „Invariante 4", die es
> hier nicht gibt: `:56` = Invariante 2 (XIRR), `:90` = Invariante 1 (cost_basis), `:137` =
> Invariante 3 (Modified Dietz), `:178` = Invariante 4 (MRS). Die Überschriften stehen im File also
> nicht in numerischer Reihenfolge. Das ist die Gliederung des Tests, nicht die Nummerierung dieser
> Datei.

Neue Kommentare verwenden ausschliesslich `Invariante #1/#2/#3` oder nennen die Konvention beim
Namen — die alte Nummerierung wird nicht fortgeschrieben, die Schreibweise ohne Raute gilt als alt.
