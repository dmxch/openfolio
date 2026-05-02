# Changelog

Alle wichtigen Änderungen an OpenFolio werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

## [0.30.0] — 2026-05-02

### Entfernt (Backward-Compat-Cleanup aus v0.29.0)

Die in v0.29.0 angekündigte 1-Release-Übergangsfrist ist abgelaufen. Folgende Aliase wurden vollständig entfernt:

- **`core_overlap`-Top-Level-Field aus dem Score-API-Response** (`/api/analysis/score/{ticker}`): Der Key ist ab sofort nicht mehr vorhanden. Gültig ist ausschliesslich `concentration` (eingeführt in v0.29.0). Externe Konsumenten, die noch gegen `core_overlap` lesen, müssen auf `concentration.single_name.overlaps` migrieren.
- **`backend/services/core_overlap_service.py`**: Das Alias-Modul wurde gelöscht. Imports müssen auf `services.concentration_service` umgestellt werden.
- **`frontend/src/components/CoreOverlapBanner.jsx`**: Der Re-Export-Alias wurde gelöscht. Die Komponente heisst ab sofort ausschliesslich `ConcentrationBanner`.
- **Deprecated Wrapper-Funktion `get_overlap_for_ticker`** aus `concentration_service.py`: Ersetzt durch `get_concentration_for_ticker`. Bewusst beibehalten wurde `get_overlap_max_weight_for_tickers` — diese Funktion war in v0.29.0 keine deprecated-Funktion, sondern eine bewusste Achsen-Trennung (Watchlist-Spalte zeigt ETF-Overlap-Max-Gewicht, kein N+1-Problem).
- **Interner Import-Pfad in `watchlist_service.py`** umgestellt von `services.core_overlap_service` auf `services.concentration_service`.

### Dokumentiert (Forschungs-Output Long-Accumulation-Detector)

Der Long-Accumulation-Detector war als Feature für v0.30.0 geplant. Die Held-Out-Validation hat den im Plan vorgesehenen Bail-out-Mechanismus aktiviert: **Recall 0/3, Precision 1/9**. Der Feature-Versuch wird transparent dokumentiert — Plan-Disziplin wurde gewahrt (kein Tuning gegen das Held-Out-Set).

Der Forschungs-Code bleibt als Baseline für v0.31.x bestehen:

- **`detect_long_accumulation_pattern()`** Pure-Function in `chart_service.py` (mit Forschungs-Header und Bail-out-Befund im Docstring)
- **`LONG_ACCUMULATION_*`-Konstantenblock** in `analysis_config.py` (als Forschungs-Code markiert, nicht produktiv)
- **`TestLongAccumulationPattern`** (7 Tests) prüfen weiterhin die Geometrie-Korrektheit der Pure-Function
- **`backend/scripts/long_accumulation_held_out_check.py`** (neu): Reproduzierbarer Held-Out-Check (Positiv-Set + Negativ-Set)
- **`LONG_ACCUMULATION_HELD_OUT_RESULTS.md`** (neu): Falsifikations-Dokument mit vollständigem Befund — Pflichtlektüre vor jedem v0.31.x-Forschungs-Release
- **`WYCKOFF_TEXTBOOK_RESULTS.md`** um Step-1b-Sektion erweitert: Pin-Sweep vs. Window-End-Sweep als Diagnose-Achse dokumentiert

Drei methodische Erkenntnisse als Pflichtlektüre für den nächsten Forschungs-Release:

1. **Pin-Methodik vs. Window-End** ist die richtige Sweep-Diagnose-Achse (nicht Threshold-Tuning).
2. **ATR-Compression allein ist auf Textbook-Akkumulationen nicht trennscharf**: Verteilungs-Overlap 42–67 % zwischen Akkumulation und anderen Phasen.
3. **Smooth-Topping ist eine eigene Pattern-Klasse** mit niedrigem ATR (AAPL 2015) — geometrisch fast nicht von Akkumulation unterscheidbar. Heartbeat-Geometrie (Touch-Cluster + ATR-Compression) ist das falsche Pattern-Modell für Long-Accumulations.

Konsequenz: v0.31.x braucht einen anderen Methoden-Approach. Die Pure-Function und die Validierungs-Skripte bleiben als Baseline.

Entfernt wurde ausschliesslich der produktive Pfad (API-Endpoint `/long-accumulation/{ticker}` und Service-Wrapper `get_long_accumulation_pattern()`). Die Konstante `LONG_ACCUMULATION_DETECTOR_VERSION` wurde ebenfalls entfernt — sie wurde nur für den nicht gebauten Logging-Pfad gebraucht.

### Tests

- **722/722 grün** — keine Verluste durch den Cleanup. Die 7 `TestLongAccumulationPattern`-Tests bleiben plan-konform bestehen.

## [0.29.1] — 2026-05-01

### Hinzugefügt

- **Wyckoff-Volumen-Profil als Qualitäts-Sub-Signal des Heartbeat-Patterns** (Phase 2): Das Heartbeat-Panel zeigt jetzt einen dreistufigen Volumen-Score — bestätigt (schrumpfendes Volumen über die Range, Akkumulationsindiz), neutral (Buffer-Zone) und atypisch (steigendes Volumen, Distributions-Verdacht). Der Score wird rein als Anzeige geführt und fliesst nicht in den Setup-Score ein (Score-Modifier-Integration ist explizit Out-of-Scope und erfordert Backtest-Pflicht).
- **Spring-Bonus-Marker**: Kurze Penetration unter Support (max. 2% darunter) am Tag mit dem höchsten Volumen der Range wird als Spring-Sub-Tag mit Datum und Volumen-Ratio angezeigt — Wyckoff-treues Signal für das Aussetzen schwacher Hände vor dem Markup.
- **Panel-Degradierung bei Distributions-Verdacht**: Bei `wyckoff.score = -1` (atypisch) erhält das gesamte Heartbeat-Panel einen roten Border und einen farbigen Header-Hinweis, damit die Warnung im Listing nicht übersehen wird.
- **4 neue Konstanten in `analysis_config.py`**: `HEARTBEAT_WYCKOFF_VOLUME_SLOPE_SHRINKING_PCT` (-0.5%/Tag), `HEARTBEAT_WYCKOFF_VOLUME_SLOPE_RISING_PCT` (+0.5%/Tag), `HEARTBEAT_WYCKOFF_SPRING_PENETRATION_FLOOR_PCT` (2%), `HEARTBEAT_WYCKOFF_MIN_RANGE_VOLUME_DAYS` (30). Alle Schwellen zentral konfigurierbar.
- **Glossar-Eintrag "Wyckoff-Volumen-Profil"** und erweiterter Hilfetext im Heartbeat-Block von `helpContent.js`.
- **`backend/scripts/wyckoff_textbook_check.py`** (neu): Standalone-Skript für historische Textbook-Cases via `yf_download`. Dient als manuelles Verifikations-Tool ausserhalb des regulären Test-Laufs.
- **`WYCKOFF_TEXTBOOK_RESULTS.md`** als Falsifikations-Dokument committet (analog zum Coverage-Sweep aus v0.29.0): Dokumentiert zwei Sweep-Pässe über 5 historische Textbook-Cases (AMD 2015, NVDA 2020, NFLX 2018, SPY 2007, AAPL 2015). Alle 5 Cases werden vom Heartbeat-Detector geometrisch verworfen (primär `no_compression`, bei AAPL `no_alternation`) — erwartbar, da der Detector auf Live-Stocks mit kurzer Konsolidierung kalibriert ist, nicht auf langwierige historische Akkumulationen. Das Wyckoff-Sub-Layer feuert korrekt, sobald die Geometrie eine Range erkennt (Unit-Tests belegen das). Eine "Long-Accumulation"-Variante mit angepassten Schwellen für historische Cases ist Kandidat für v0.30+.
- **8 neue Unit-Tests** (`TestHeartbeatWyckoffVolume` in `test_chart_pattern_detectors.py`): 715/715 Tests grün (707 + 8 Wyckoff-Cases), keine Regression.

### Geändert

- **Heartbeat-Cache-Key auf `v2` gebumpt** (`heartbeat:v2:{ticker}` statt `heartbeat:{ticker}`): Erzwingt Re-Compute beim ersten Read nach dem Deploy. Verhindert Inkonsistenz im Watchlist-Vergleich, da alte v1-Einträge das neue `wyckoff`-Sub-Dict nicht enthalten und nicht mehr gelesen werden.
- **`HeartbeatPanel` in `StockDetail.jsx`**: Wyckoff-Badge (grün/grau/rot) ergänzt, Spring-Sub-Tag bei `spring_detected=True` hinzugefügt, Panel-Degradierung bei `wyckoff.score = -1` implementiert. Phase-1-Hinweis "ohne Volume-Confirm" entfernt.

### Nicht in diesem Release (Out-of-Scope, kommen separat)

- **Score-Modifier-Integration**: Der Wyckoff-Score beeinflusst den Setup-Score noch nicht. Eine Gewichtungsänderung erfordert Forward-Return-Validation (Backtest-Pflicht).
- **Touch-Asymmetry-Analyse** und **Watchlist-Wyckoff-Spalte**: Folgen in eigenen Releases.

## [0.29.0] — 2026-04-30

### Hinzugefügt

- **Konzentrations-Banner mit Single-Name + Sektor-Achse** (Phase 1.1 — Schwur Nr. 3 vollständig operativ): Das bisherige Core-Overlap-Banner zeigt jetzt zwei Informationsebenen. Erste Zeile: Direkt-Position + Indirekt-via-ETF = Gesamt-Exposure mit CHF-Zahlen (Beispiel: JNJ Direkt 9'520 CHF + 320 CHF via OEF = 9'840 CHF, 3.29% des Liquid-Portfolios). Zweite Zeile: Sektor-Gesamt-Exposure — Σ aller Direkt-Aktien in einem Sektor + ETF-anteilig (Beispiel: Healthcare-Total 14.2%). Soft-Warn ab 25% (gelb), Hard-Warn ab 35% (rot).
- **Sektor-Aggregation mit konfigurierbaren Schwellen**: Zwei absolute Schwellen `SECTOR_CONCENTRATION_SOFT_WARN_PCT` (25%) und `SECTOR_CONCENTRATION_HARD_WARN_PCT` (35%) in `analysis_config.py`. Keine Benchmark-Tilt-Logik (Phase 1.2, geplant separat). Sektor-Zeile erscheint nur bei Schwellenüberschreitung — kein Banner-Rauschen unterhalb 25%.
- **TradingView-Industry → GICS-Sektor-Mapping** (kritischer Fix): Die bisherige `INDUSTRY_TO_SECTOR`-Map (Finviz-Style) deckte nur ca. 20 von 130 TradingView-Industries ab, was zu einer ETF-Coverage von nur 31% führte. Neues `TRADINGVIEW_INDUSTRY_TO_SECTOR`-Dict in `sector_mapping.py` mit allen 130 TradingView-Industries. OEF-Coverage steigt damit auf 97% out-of-the-box.
- **`sector_classification_service.py`** (neu): Sektor-Klassifikation mit 3-stufiger Cascade — (1) `SECTOR_OVERRIDES` (manuell, versioniert, initial mit BRK-A/BRK-B), (2) `ticker_industries.industry_name` → `TRADINGVIEW_INDUSTRY_TO_SECTOR` (mit Finviz-Fallback), (3) "Unclassified". `classify_tickers_bulk` macht einen SQL-Roundtrip für N Ticker statt N einzelne Roundtrips (kein N+1-Problem).
- **`concentration_service.py`** (neu, erweitert): Zusammenführung von Phase-B-Single-Name-Logik und neuer Sektor-Aggregation. Strukturierter API-Response mit Top-Level-Key `concentration` und Sub-Struktur `single_name` / `sector`. Der bisherige Key `core_overlap` bleibt bis v0.30.x als Alias auf `concentration.single_name.overlaps`.
- **Vier-Status-Diskriminator** für den Sektor-Block: `below_threshold` / `ok` / `low_coverage` / `no_sector`. Das Frontend kann differenzieren, ob der Sektor-Block gerendert werden soll und mit welchem Hinweis (Coverage-Warning vs. keine Daten vs. kein Trigger).
- **Coverage-Suppression-Logik**: ETF mit ≥10% Portfolio-Gewicht und <95% Sektor-Coverage → die gesamte Sektor-Aggregation wird auf `low_coverage` gesetzt. Verzerrte Zahlen werden unterdrückt, statt falsche Sicherheit zu vermitteln.
- **Post-Refresh-Coverage-Check im `etf_holdings_refresh_job`** (worker.py): Nach dem wöchentlichen FMP-Holdings-Pull wird die Sektor-Coverage neu berechnet. Bei Drop unter 95% erscheint ein Log-Warning. Schützt gegen stillen Decay, wenn FMP einen neu aufgenommenen Ticker rotiert, der noch nicht klassifiziert ist.
- **`scripts/sector_coverage_check.py`** (neu, manuelles Pre-Deployment-Tool): Gibt pro ETF die Coverage-Quote aus, listet unklassifizierte Ticker und generiert `SECTOR_OVERRIDES`-Vorschläge. Nicht Teil des regulären Cron-Laufs — reines Diagnose-Tool.
- **3 neue Glossar-Einträge**: "Konzentration (Gesamt)", "Sektor-Aggregation" und Erweiterung des bestehenden "Core-Overlap"-Eintrags um Phase-1.1-Scope.
- **8 neue Unit-Tests** (`test_sector_classification.py`): 3-Stufen-Cascade, SECTOR_OVERRIDES-Priorität, Finviz-Fallback, bulk-SQL-Logik, Coverage-Berechnung, Suppression-Schwelle. 707/707 Tests grün (699 + 8 neu), keine Regression.

### Geändert

- **`ConcentrationBanner.jsx`** (ehemals `CoreOverlapBanner.jsx`): Zwei Sub-Zeilen statt einer. Single-Name-Zeile zeigt Direkt + Indirekt = Total. Sektor-Zeile zeigt Sektor-Gesamt mit Soft/Hard-Warn-Farbe. Der bisherige `CoreOverlapBanner.jsx` bleibt 1 Release als Re-Export-Alias bestehen und wird in v0.30.x entfernt.
- **`StockDetail.jsx`**: Import-Pfad auf `ConcentrationBanner` aktualisiert, Props auf die neue `concentration`-Struktur des API-Response angepasst.
- **`analysis_config.py`**: 5 neue Phase-1.1-Konstanten ergänzt — `SECTOR_CONCENTRATION_SOFT_WARN_PCT`, `SECTOR_CONCENTRATION_HARD_WARN_PCT`, `SECTOR_AGGREGATION_SUPPRESS_ETF_WEIGHT_PCT`, `SECTOR_COVERAGE_MIN_PCT`, `SECTOR_OVERRIDES`.
- **`helpContent.js`**: Konzentrations-Sektion um Sektor-Aggregation, Suppression-Logik und Phase-1.2-Ausblick erweitert.

### Abwärtskompatibilität (Deprecation-Pfad v0.30.x)

Vier parallele Aliase sind bis v0.30.x aktiv und werden dort entfernt:

1. **Service-Modul**: `backend/services/core_overlap_service.py` ist Re-Export-Alias auf `concentration_service`.
2. **Frontend-Komponente**: `CoreOverlapBanner.jsx` ist Re-Export-Alias auf `ConcentrationBanner.jsx`.
3. **API-Field**: JSON-Key `core_overlap` ist Alias auf `concentration.single_name.overlaps`.
4. **Function-Name**: Public API von `core_overlap_service` bleibt unverändert via Re-Export.

### Deploy-Hinweis

- **Migration-Order**: Backend muss den neuen `concentration`-Key im `/score`-Response liefern, bevor das Frontend den neuen Banner rendert. `docker compose up --build -d` ist unbedenklich, weil der Backend-Container schneller als der Frontend-Container startet. Zusätzlich deckt der Backward-Compat-Alias Race-Conditions ab.
- **ETF-Holdings**: Kein manueller Pull nötig — Holdings sind seit Phase-B-Release (v0.28.0) in der DB persistiert.
- **Sektor-Coverage-Check**: Läuft automatisch nach dem nächsten Mo-04:30-CET-ETF-Holdings-Refresh.

### Nicht in diesem Release (Out-of-Scope)

- **Phase 1.2 — Benchmark-Tilt-Logik**: Sektor-Gewichtung relativ zum S&P-500-Sektor-Benchmark (Übergewichtung vs. Index). Ist separates Feature und erfordert Backtest-Validierung.
- **v0.29.1 — Wyckoff-Volume im Heartbeat**: Geplant als separates Patch-Release.

## [0.28.0] — 2026-04-30

### Hinzugefügt

- **Core-Overlap-Banner auf der Aktiendetailseite** (Schwur Nr. 3 — Klumpenrisiko operativ): Wenn ein Direkt-Ticker mit ≥2% in einem Portfolio-ETF enthalten ist, erscheint ein Banner mit konkreten CHF-Zahlen. Beispiel: NVDA 11.39% von OEF → 1'546 CHF indirekte Exposure bei einer OEF-Position von 13'576 CHF. Der Banner prüft gegen den Single-Name-Cap (~6–8%) und weist auf mögliche Klumpenbildung hin. Hard-Information statt Bauchgefühl.
- **Overlap-Spalte in der Watchlist**: Zeigt pro Watchlist-Eintrag das maximale ETF-Gewicht über alle Portfolio-ETFs des Benutzers. Ermöglicht schnelle Triage beim Watchlist-Scan ohne jeden Titel einzeln aufrufen zu müssen. Sortierbar.
- **ETF-Holdings-Service mit FMP-Stable-API-Integration**: Neuer Service `etf_holdings_service.py` zieht Holdings über den Endpoint `/stable/etf/holdings?symbol={ticker}` (der ursprünglich geplante Endpoint `/api/v3/etf-holder/{ticker}` gibt HTTP 403 bei Standard-Tiers zurück — Korrektur direkt beim ersten Live-Test). Self-Reference-Filter gegen FMP-Response-Quirks (OEF liefert drei Cash-Rows mit `asset=="OEF"` zurück, die einen Composite-PK-Konflikt ausgelöst hätten). UPSERT mit Dedup-Map für idempotente Verarbeitung.
- **Wöchentlicher Cron `etf_holdings_refresh_job`** (Mo 04:30 CET, `0 4 * * 1`): Zieht Holdings aller ETF-Positionen im User-Portfolio nach. 30-Tage-TTL-Check macht den Job robust gegen einzelne API-Failures — ETFs mit frischen Daten werden übersprungen.
- **Neue DB-Tabelle `etf_holdings`** (Alembic 056): Composite-PK `(etf_ticker, holding_ticker)`, Index auf `holding_ticker` für Sub-50ms-Reverse-Lookup bei 100+ Watchlist-Items.
- **Async-Aggregation ohne N+1**: Bulk-IN-Query für die Watchlist-Overlap-Spalte; `score_stock` bleibt user-agnostisch (Architektur-Disziplin aus Phase A). User-Scope verbleibt ausschliesslich im API-Wrapper-Layer.
- **5 neue Konstanten in `analysis_config.py`**: `CORE_OVERLAP_MIN_WEIGHT_PCT`, `CORE_OVERLAP_SINGLE_NAME_CAP_LOW`, `CORE_OVERLAP_SINGLE_NAME_CAP_HIGH`, `CORE_OVERLAP_HYPOTHETICAL_BUY_PCT`, `CORE_OVERLAP_THRESHOLD_PCT`. Alle Schwellen zentral anpassbar ohne Code-Suche.
- **11 neue Unit-Tests** (`test_etf_holdings_service.py`): Pure-Function-Tests für Self-Reference-Filter, TTL-Check, Dedup-Logik und Threshold-Berechnung. 699/699 Tests grün (688 vorher + 11 neu), keine Regression.
- **Tooltip-Datums-Logik** im Overlap-Banner: Drei Branches — FMP liefert `as_of` → "Holdings-Stand laut FMP: YYYY-MM-DD"; FMP liefert kein `as_of` (Stable-Endpoint-Normal) → "Stichtag unbekannt, typisch 30–60 Tage Lag"; `updated_at` (Pull-Zeitpunkt) wird nie als Holdings-Stand kommuniziert.
- **Glossar-Eintrag "Core-Overlap"** und neue Sektion in `helpContent.js` inkl. explizitem Phase-1-Scope-Hinweis.

### Einschränkungen Phase 1 (bekannt, dokumentiert)

- **Nur US-ETFs** (FMP-Coverage): Non-US-ETFs (CHSPI.SW, SWDA.L, EIMI.L u.a.) werden beim Holdings-Pull geskipped. Für den aktuellen User-Scope irrelevant, da OEF der einzige ETF mit relevanter Mag7-Klumpenexposure ist.
- **Direkt-Position-Baseline**: Die eigene Direkt-Position in der Einzelaktie fliesst noch nicht in den Gesamt-Klumpencheck ein (Phase 1.1, geplant ~2 Wochen).
- **Sektor-Aggregation** (z.B. Gesamt-Tech-Exposure über alle ETFs) ist Phase 1.1 — der Banner weist explizit darauf hin, um Falsch-Sicherheit zu verhindern.

### Deploy-Hinweis

Nach dem ersten Deploy von v0.28.0 auf einem frischen System müssen die ETF-Holdings einmalig befüllt werden, da der Cron-Job erst am nächsten Montag 04:30 CET läuft. Prüfung: `SELECT COUNT(*) FROM etf_holdings` — sollte nach dem Pull ≥100 sein (OEF allein: 101 Holdings). Wenn der Wert 0 ist, manuellen Trigger über das Django-Management-Interface oder direkt via `docker compose exec backend python -c "..."` ausführen (Beispiel in den Deployment-Notes im Repository-Wiki).

## [0.27.0] — 2026-04-30

### Hinzugefügt

- **Setup-Score Phase A — 2-Tages-Bestätigung für Donchian-Breakouts** (Kriterium id=8): Ein Breakout gilt erst am Folgetag als bestätigt. Vier Zustände: `confirmed` / `awaiting_day2` / `fakeout` / `no_breakout`. Email-Alerts bleiben Tag-1-Frühwarnung. Das Breakouts-Widget in der Aktiendetailseite zeigt "am Folgetag bestätigt" mit Pending-Hourglass und Tooltip.
- **Earnings-Proximity-Veto** (Kriterium id=19, Gruppe Risiken): Wenn der nächste Quartalsbericht weniger als 7 Tage entfernt ist, wird `setup_quality` auf BEOBACHTEN gecapt — unabhängig vom Score. Bei Score ≥ 15 + MRS > 1.0 + Branchen-Rückenwind und ohne aktive Risk-Modifier erscheint ein Split-Entry-Banner (halbe Position vor Earnings möglich). Datenquelle: bestehender `earnings_service` mit 24h-Cache.
- **Distance-from-MA50** (Kriterium id=20, Modifier): Dreiwertige Anpassung basierend auf dem Abstand zur 50-Tage-Linie. Bis 15% über MA50: +1 (gesund), 15–25%: neutral (0), über 25%: -1 (überstreckt, Mean-Reversion-Risiko).
- **Volume-Confirmation** (Kriterium id=21, Modifier): Misst die Divergenz zwischen Preis-Trend (Linear-Regression der letzten 20 Closes) und Volumen-Ratio (winsorized 20d/60d, Top-3 Ausreisser entfernt gegen Earnings-Volumen-Spikes). Vier-Quadranten-Logik: steigender Kurs auf fallendem Volumen = Distribution (-1), steigender Kurs auf steigendem Volumen = gesunde Bestätigung (+1). Mega-Caps über 500 Mrd. MCap (90-Tage-geglättet) verwenden engere Schwellen (0.75/1.25 statt 0.85/1.15).
- **Industry-MRS** (Kriterium id=22, neue Gruppe "Industry-Stärke"): Vergleicht die 3-Monats-Performance der TradingView-Industry des Tickers mit der S&P-500-Performance. Puffer von ±2 Prozentpunkten gegen Endpunkt-Sensitivität. Phase-2-Stub (rolling Mansfield-Style EMA-13) vorbereitet für spätere Aktivierung.
- **Asymmetrische Score-Aggregation (Risk-First)**: `display_pct = base_pct + modifier_sum × 3` (kosmetisch, beide Vorzeichen wirken). `quality_pct = base_pct + negative_modifier_sum × 8` (nur negative Modifier degradieren die Quality-Einstufung). Die Setup-Quality-Bestimmung läuft über `quality_pct`, nicht `display_pct` — verhindert dass positive Modifier ein schwaches oder Late-Stage-Setup künstlich auf STARK heben. Beispiel: 89%-Setup mit zwei negativen Modifiern → quality_pct 73% (BEOBACHTEN), display_pct 83%.
- **Migration-Logging `pct_legacy`**: Der bisherige Score-Wert wird vier Wochen parallel im Response geloggt (Feld `pct_legacy`) für Drift-Validierung. Kein Breaking Change an der API.
- **25 neue Unit-Tests**: 14 Tests in `test_chart_pattern_detectors.py` (5 für 2-Tages-Confirm, 9 für Volume-Confirmation) und 11 Tests in `test_stock_scorer_phase_a.py` (Aggregationslogik, Asymmetrie, Earnings-Cap). Alle 688 Tests grün, keine Regression.
- **6 neue Glossar-Einträge**: Modifier, Distance from MA50, Volume-Confirmation, Industry-MRS, Earnings-Proximity, Trendbestätigung — mit ausführlicher Erklärung der asymmetrischen Logik.
- **Tunables zentral in `analysis_config.py`**: 14 neue Konstanten für alle Phase-A-Schwellen (`DONCHIAN_CONFIRM_DAYS`, `EARNINGS_PROXIMITY_DAYS`, `MA50_DISTANCE_*`, `VOLUME_CONFIRM_*` inkl. Winsorization und Mega-Cap-Schwelle, `INDUSTRY_OVERRIDES`, `INDUSTRY_MRS_BUFFER_PCT`, `MODIFIER_WEIGHT_PCT_DISPLAY/QUALITY`). Schwellen können ohne Code-Hunt angepasst werden.

### Geändert

- **`StockScoreCard.jsx`**: GROUP_ORDER auf 9 Gruppen erweitert (Modifier und Industry-Stärke als neue Gruppen, Risiken vorgezogen). Modifier-Kriterien werden mit PlusCircle/MinusCircle/CircleCheck gerendert. Pending-Breakout zeigt Hourglass-Icon. Earnings-Banner erscheint über den Alerts. Color-Coding läuft über `setup_quality`, nicht über `pct` — verhindert grüne Darstellung bei BEOBACHTEN-Quality.
- **`StockDetail.jsx` Breakouts-Widget**: Header zeigt "(am Folgetag bestätigt)", Pending-Tag und Tooltip mit Day-2-Bestätigung sichtbar.
- **`helpContent.js`**: Neue Sektionen "Modifier (2 Kriterien, asymmetrisch)" und "Industry-Stärke", erweiterte Sektion "Risiken (3 Kriterien)" mit Earnings-Proximity-Erklärung.
- **`chart_service.py`**: `get_breakout_events` auf 4-State umgebaut, 4 neue Hilfsfunktionen für Confirm-Logik, Volume-Slope und Quadranten-Klassifikation.
- **`stock_scorer.py`**: Kriterium id=8 auf 4-State-Confirm umgebaut, Kriterien id=19–22 hinzugefügt, asymmetrische Aggregation und Earnings-Cap implementiert, `pct_legacy`-Parallel-Logging aktiv.

## [0.26.0] — 2026-04-30

### Hinzugefügt

- **Branchen-Rotation als Layer im Smart Money Screener**: TradingView-Industries (129 US-Branchen) fliessen als zusätzliches Signal in den Smart-Money-Score ein. Jede Aktie erhält eine Branchen-Klassifikation (Tailwind / Headwind / Neutral / Konzentriert / Unbekannt) basierend auf 1M- und 3M-Performance sowie relativem Volumen (RVOL). Tailwind-Branchen erhalten einen konservativen Bonus von +1 Punkt (validierungspflichtig vor Erhöhung).
- **Konzentrations-Block**: Branchen mit Top-1-MCap-Anteil > 50% oder effektiver Mitgliederzahl < 5 werden als "Konzentriert" markiert und erhalten keinen Bonus, da die Performance einzelner Mega-Caps das Branchensignal verzerren würde. NVDA, TSLA, AMZN und XOM werden korrekt klassifiziert.
- **Stock→Industry-Mapping persistiert**: 11'895 Ticker werden aus dem bestehenden TradingView-Scanner-Lauf in der neuen Tabelle `ticker_industries` gespeichert. Kein separater API-Call nötig; Race-Schutz durch atomare Transaktion (MarketIndustry-Snapshot + Ticker-UPSERT gemeinsam).
- **Wöchentlicher Stale-Detection-Cron** (`sector_rotation_stale_check`, Mo 06:30 CET): Prüft, ob Ticker-Industry-Mappings veraltet sind (> 10 Tage kein Update). Bei Orphans wird eine Mail-Eskalation ausgelöst.
- **Frontend — Branchen-Badge in der Signale-Spalte**: Neue farbige Badges (T / H / K) in der Signale-Spalte des Smart-Money-Screeners zeigen die Branchen-Klassifikation auf einen Blick. Tooltip enthält Branchen-Namen und Klassifikationsgrund.
- **Frontend — Branchen-Filter-Dropdown**: Neuer Filter "Nur Tailwind-Branchen" / "Nur Headwind-Branchen" im Screener, unabhängig von den bestehenden Signal-Filtern bedienbar.
- **Frontend — Score-Breakdown im ExpandedRow**: Branchen-Rotation erscheint als eigene Zeile im detaillierten Score-Breakdown ("Schritt 11 — Branchen-Rotation (TradingView)").
- **Score-Telemetrie**: Nach jedem Scan wird eine Verteilungs-Log-Zeile geschrieben (Median-Score, Tailwind-Anteil, Headwind-Anteil, Konzentrations-Anteil).
- **14 neue Unit-Tests** für `classify_ticker` (`test_sector_rotation_service.py`), alle grün.
- **Alembic-Migration 055**: Neue Tabelle `ticker_industries` (Ticker→Industry-Mapping mit Timestamp), dazu `sector_rotation` und `industry_name` als neue Felder auf `ScreeningResult`.

### Geändert

- **Branchen-Rotation**: Branchen-Namen in der Tabelle sind jetzt klickbare Links auf die jeweilige TradingView-Detailseite. Öffnet in neuem Tab (`rel="noopener noreferrer"`). Dezentes External-Link-Icon fadet beim Row-Hover ein.
- **TradingView-Scan-Pagination deterministisch**: Der Scanner-Aufruf nutzt jetzt `sortBy: market_cap_basic, sortOrder: desc`, damit grosse Positionen (NVDA, TSLA, AMZN, XOM) nicht durch instabile Seiten-Splits aus dem Ergebnis fallen.

### Behoben

- **Mega-Caps fehlten im TradingView-Industry-Scan**: Ohne expliziten Sort lieferte die TradingView-Scanner-API eine nicht deterministische Reihenfolge, was bei Pagination dazu führte, dass Ticker mit sehr hoher Market Cap gelegentlich übersprungen wurden. Fix: stabiler `market_cap_basic desc`-Sort.

## [0.25.0] — 2026-04-23

### Hinzugefügt

- **Branchen-Rotation (129 US-Industries)**: Neue Seite `/branchen` mit sortierbarer Tabelle auf Branchen-Ebene parallel zur bestehenden Sektor-Rotation (11 SPDR-ETFs). Datenquelle: TradingView Scanner API (`scanner.tradingview.com/america/scan`, `symbols.query.types=["industry"]`), taeglicher DB-Snapshot um 01:30 CET via neuem Worker-Job `industries_refresh`. Englische Branchen-Namen ("Semiconductors", "Integrated Oil"), Perf-Spalten 1W/1M/3M/6M/YTD/1Y, Quick-Filter (Alle / Top 15 / Bottom 15), Zeitraum-Switcher mit Auto-Sort. Neue Tabelle `market_industries` (Alembic 052), neue Endpoints `GET /api/market/industries` (intern, 1h-Cache) + `GET /api/v1/external/market/industries` (extern, 24h-Cache, X-API-Key). Initial-Populate via `python -m populate_industries`.
- **HHI-Card auf investiertem Kapital**: Herfindahl-Index wurde vorher auf das handelbare Matrix-Subset renormalisiert, wodurch die Groesste-Position-Anzeige inkonsistent mit dem Rest der UI war (z.B. Gold 39 % statt echter 18,5 %). PE und Real Estate fielen komplett raus. Neue Logik `_compute_portfolio_concentration` rechnet auf stock/etf/crypto/commodity/private_equity/real_estate (Cash/Pension raus), liefert zusaetzlich `max_weight_name` (lesbare Firmennamen statt `PE_4E1D1AB1`). HEILIGE Regeln 4/6 unveraendert (betreffen Performance, nicht Risikometriken).
- **Edelmetall-Ausgaben**: Neue Sektion im Edelmetalle-Widget zum Erfassen von Lagergebühren, Versicherung und sonstigen Kosten. Wiederkehrende Ausgaben (monatlich / quartalsweise / jährlich) werden annualisiert und in drei Summary-Karten (Lager, Versicherung, Gesamt pro Jahr) angezeigt. Optional pro Metallart zuordenbar. Neue Tabelle `precious_metal_expenses` (Alembic 051), neue Endpoints unter `/api/precious-metals/expenses`
- **Preisalarme und Notizen direkt in der Portfolio-Tabelle**: Zwei neue Spalten in der Positions-Tabelle — Bell-Icon öffnet den bereits aus der Watchlist bekannten AlertPopover (Kurs über/unter, Tagesveränderung %), MessageSquare-Icon erlaubt Inline-Editieren der Positions-Notiz ohne Umweg über den Bearbeiten-Dialog. Aktive Alarme werden mit Zähler-Badge angezeigt. Portfolio-Summary liefert `notes` (entschlüsselt) und `active_alerts` pro Ticker
- **Smart Money Screener V2 — 5 neue Signal-Quellen** (Scope-Dokumente V2→V4 mit vollständiger Architektur-Dokumentation)
- **Block 0a — Screening-History-Retention**: ScreeningScan/ScreeningResult werden jetzt 365 Tage akkumuliert statt aggressiv überschrieben. Neuer APScheduler-Job `cleanup_old_screening_scans` (04:00 CET, löscht Scans > 365 Tage via CASCADE). Neues CLI-Tool `backtest_harness.py` für zukünftige Signal-Gewichts-Validierung (Skelett, Forward-Return-Berechnung als Stub bis +90 Tage History akkumuliert)
- **Block 1 — CFTC COT Macro-Tab**: Neues isoliertes Macro/Positioning-Panel mit 5 Futures-Instrumenten (Gold, Silber, Crude Oil ICE Brent-WTI, USD Index, 10Y Treasury). Eigene Tabelle `macro_cot_snapshots`, eigener Endpoint `GET /api/screening/macro/cot`, APScheduler-Job `cot_weekly_refresh` (Sa 09:00 CET). Perzentil-Bars über 52-Wochen-Range, Extremzonen-Markierung (≤10, ≥90). CL nutzt ICE Brent-WTI statt NYMEX WTI Financial (dünnerer Kontrakt mit leerer MM-Position)
- **Block 3 — 13F Q/Q-Diffs mit Konsens-Architektur**: Quartalsweise Holdings-Diffs über 9 verifizierte Value-Fonds (Berkshire, Scion, Pershing Square, Appaloosa, Pabrai, Third Point, Oaktree, Baupost, Greenlight). Konsens-Signal: ≥3 Fonds gleiche Action → `superinvestor_13f_consensus` (+3). Single-Fund → `superinvestor_13f_single` (+1 informativ). Tag-75-Regel für deterministische Quartalsstichtag-Aggregation. Neue Tabelle `fund_holdings_snapshot` (Alembic 050). CIK-Verifikations-Skript gegen SEC EDGAR
- **Block 4 — 13D Brief-Volltext Anreicherung**: Bestehendes `activist`-Signal erweitert um `letter_excerpt` (Item 4 Purpose-of-Transaction, max 500 Zeichen) und `purpose_tags` (11 Regex-basierte Kategorien: board_representation, strategic_review, spinoff, merger, governance, capital_return, management_change, going_private, operational, valuation, passive_investment). Kein Score-Impact (enrichment_only)
- **Block 5 — SIX Insider Management-Transaktionen (CH)**: Erster Non-US-Block. 75 Schweizer Emittenten gemappt (SMI-30 vollständig + SMIM). Neues Signal `six_insider` (+3 provisional). Quelle: SIX SER API (`ser-ag.com/sheldon/management_transactions/v1/`). `MIN_ABSOLUTE_VOLUME_CH = 5'000` für `.SW`-Ticker. Universe-Hint-Tooltip auf CH-Tickern ("weniger Signalquellen verfügbar als bei US-Titeln")
- **Alembic-Migrationen 048–050**: 048 dokumentiert Retention-Entscheidung (No-Op), 049 `macro_cot_snapshots`, 050 `fund_holdings_snapshot`

### Geändert

- **Screening-Retention**: `.offset(1)`-Löschlogik in `start_scan` und Pre-Insert-Delete in `run_scan` entfernt — Scans werden jetzt akkumuliert. Fixt als Nebeneffekt einen schlafenden Bug (doppelter `run_scan` mit identischer `scan_id` hätte Results verloren)
- **Screening-UI**: Neuer Tab "Macro / Positionierung" neben "Smart Money Screener". Header-Subtitle aktualisiert auf "US- und CH-Aktien"

### Behoben

- **Edelmetall-Kurse — „Veraltete Kursdaten"-Alert bei warmem Worker**: `_compute_market_value` in `portfolio_service.py` fiel bei leerem `gold_chf`-Redis-Cache (z.B. direkt nach Backend-Restart oder längerer Gold.org-Aussetzer) fälschlich auf den yfinance-Spot-Ticker `XAUCHF=X` zurück, den yfinance nicht kennt → cost_basis-Fallback mit `is_stale=True`, obwohl der Worker `positions.current_price` alle 60 s aktualisiert hält. Neuer Fallback-Pfad: Redis-Cache → `pos.current_price` (DB, vom Worker gepflegt) → cost_basis. Als Nebeneffekt: Silber/Platin/Palladium (`XAGCHF=X/XPTCHF=X/XPDCHF=X`) bekommen erstmals einen echten Live-Preis via yfinance-Futures `SI=F/PL=F/PA=F` × `USDCHF=X`. Bisher hatte `gold_org=True` nur Gold, alle anderen physischen Metalle waren dauerhaft stale. Neues Helper-Modul `METAL_FUTURES`/`get_metal_futures` in `precious_metals_service.py`, neue Funktion `get_metal_price_chf` in `price_service.py`. `gold_org`-Flag ist jetzt der Edelmetall-Marker (historischer Name bleibt). 7 neue Unit-Tests (`test_precious_metals_pricing.py`), 3 neue Cases in `test_portfolio_service.py::TestComputeMarketValue`
- **Screening — Unusual-Volume lieferte nie Ergebnisse**: `period="25d"` ist kein gültiger yfinance-Wert (akzeptiert: `1d/5d/1mo/3mo/...`) und führte zu einem leeren DataFrame. Über 30 Tage hinweg war der Flag in 0 von 3028 Results gesetzt, obwohl der Step als "done" abgeschlossen hat. Fix: `period="1mo"` (~22 Handelstage). `MAX_TICKERS` zusätzlich von 150 auf 500 angehoben.
- **Screening — Unusual-Volume lieferte identische Werte über mehrere Ticker**: yfinance ist nicht thread-safe — concurrent `asyncio.to_thread`-Calls teilten internen State (`yfdata.YfData._instances`), dadurch bekamen z.B. SNAP/RDDT/PRIM alle den Volumen-Wert des zuletzt geladenen Tickers. Ersetzt durch Batch-Aufruf `yf.download(list, group_by="ticker")` — ein HTTP-Request, MultiIndex-DataFrame mit je einer Spaltengruppe pro Ticker, seriell in Batches von 50.
- **Screening — Insider-Personennamen im `sector`-Feld**: OpenInsider Cluster-Buys und Large-Buys haben unterschiedliche Spalten-Layouts, beide gingen aber durch denselben `_parse_table`. Bei Large-Buys ist `row[5]` der Insider-Name (nicht Industry) und `row[6]` der Title (nicht Ins-Count). Getrennter Parser `_parse_large_buy_rows` mit `industry=""`, `insider_count=1`, plus Filter auf `"P - Purchase"` (der Screener lieferte auch Sales zurück).
- **Screening — `price_usd` immer null**: Column seit Migration 041 vorhanden, wurde aber nie beschrieben (0 von 3028 Results befüllt). Der neue Batch-Download aus dem UV-Fix liefert den Close-Preis ohnehin mit — jetzt wird er in `ScreeningResult.price_usd` geschrieben.
- **Cache — `last_refresh` bei Timeout/Error auf null**: Fehler im Kurs-Refresh setzten `last_refresh` fälschlich auf null statt den vorherigen Wert beizubehalten.

### Nicht umgesetzt

- **Block 2 — TRACE Credit-Stress**: Discovery-Spike negativ. FINRA TRACE API erfordert OAuth 2.0 Authentifizierung, kein freier Zugang zu Issuer-Level Bond Spreads. Fallback: FRED IG/HY-Sektor-Spreads im Macro-Tab als optionaler Follow-up

## [0.24.0] — 2026-04-09

### Hinzugefuegt

- **Externe REST-API (`/api/v1/external/*`)**: Vollstaendige read-only API mit X-API-Key Auth — unabhaengig von der JWT-Frontend-Session. Alle Endpoints erfordern einen persoenlichen API-Token aus den User-Settings.
- **API-Token-Verwaltung in Settings → Integrationen**: Tokens generieren, kopieren und widerrufen; kopierbare Base-URL und Link zur Entwickler-Dokumentation direkt im UI.
- **Externe API — Portfolio-Endpoints**: `/portfolio/summary`, `/portfolio/positions`, `/portfolio/performance`, `/portfolio/daily-change`, `/portfolio/realized-gains` (inkl. `transaction_id` und `order_id`), `/portfolio/total-return`, `/portfolio/upcoming-earnings`
- **Externe API — Analyse-Endpoints**: `/analysis/score`, `/analysis/mrs`, `/analysis/levels`, `/analysis/reversal`, `/analysis/correlation-matrix` (inkl. HHI-Konzentrations-Klassifikation)
- **Externe API — Screening-Endpoint**: `/screening` mit aktuellem Smart-Money-Score
- **Externe API — Immobilien und Vorsorge**: `/real-estate` inkl. Hypotheken, `/pension`
- **Externe API — CH-Makro-Snapshot (`/macro/ch`)**: SNB Leitzins, SARON, CHF/EUR + CHF/USD, Schweizer CPI (HICP), CH-10Y-Rendite, SMI vs. S&P 500 — Quellen: SNB Data Portal (Cube `snbgwdzid`), Eurostat HICP, FRED, yfinance
- **Datenbank-Migration 045**: Neue Tabelle `api_tokens` fuer tokenbasierte Authentifizierung
- **HHI-Konzentrations-Card auf Portfolio-Seite**: Herfindahl-Hirschman-Index des Portfolios mit Klassifikations-Badge (niedrig / moderat / hoch)
- **CH-Makro-Card auf dem Dashboard**: Analoges Layout zur US-MarketClimate-Card mit den wichtigsten Schweizer Indikatoren
- **Upcoming-Earnings-Banner auf dem Dashboard**: Zeigt anstehende Quartalszahlen aus dem Portfolio mit Angabe ob vor (bmo) oder nach Boersenhandel (amc) — klickbar auf das Stock-Detail
- **Import-Sektion in Settings → Daten**: Import-Bereich war bisher ausgeblendet, zeigt jetzt den bestehenden ImportWizard direkt in den Einstellungen
- **IBKR-Parser erkennt Dividenden aus Cash Transactions Flex Query**: Interactive-Brokers-Exporte mit Dividenden-Eintraegen im Cash-Transactions-Abschnitt werden korrekt importiert
- **Integrations-Einstellungen fuer FRED, FMP, Finnhub**: Je ein separater Block in Settings → Integrationen mit Save-, Test- und Delete-Aktion sowie Signup-Links zu den jeweiligen Anbietern

### Geaendert

- **BREAKING — News, KI-Zusammenfassung und Newsletter vollstaendig entfernt** (Migration 046): Die Tabelle `news_articles` sowie 6 Spalten in `user_settings` (Newsletter-Frequenz, -Scope, KI-Anbieter, -Modell, -API-Key, Ollama-URL) werden gedroppt. Bestehende Installationen muessen `alembic upgrade head` ausfuehren. Die Worker-Jobs fuer News-Abruf (06:30/18:00) und Newsletter (07:30) entfallen. Der Sidebar-Eintrag `/news` und der zugehoerige Settings-Tab sind entfernt.
- **BREAKING — Per-User API-Keys fuer FRED, FMP und Finnhub; Env-Fallback entfernt** (Migration 047): Die globalen Umgebungsvariablen `FRED_API_KEY`, `FMP_API_KEY` und `FINNHUB_API_KEY` werden nicht mehr ausgewertet. Jeder Nutzer traegt seine eigenen Keys in Settings → Integrationen ein (verschluesselt in `user_settings`). FRED nutzt ein "first user with key"-Sharing-Pattern fuer globale Marktdaten; FMP und Finnhub sind strikt per-user. Die drei Env-Eintraege koennen aus `docker-compose.yml` und `.env` entfernt werden.
- **CH-Makro: CPI-Quelle auf Eurostat HICP umgestellt**: Die bisherigen FRED/OECD-Serien fuer den Schweizer CPI waren seit April 2025 nicht mehr aktualisiert worden — die Quelle wechselt auf die monatlich publizierten Eurostat-HICP-Daten.
- **CH-Makro: SNB-Datenpunkt korrigiert** (Cube `snbgwdzid`): Der zuvor angenommene Cube-Name war falsch und lieferte keine Daten.
- **realized-gains liefert `transaction_id` und `order_id` mit**: Ermoeglicht die eindeutige Zuordnung bei echten Teilausfuehrungen (mehrere Transaktionen zum selben Kauf).
- **Finnhub-FINNHUB_API_KEY aus docker-compose.yml und config.py bereinigt**: Env-Mapping und Config-Feld entfernt, da Keys jetzt per-user verwaltet werden.

### Entfernt

- **News-Feature komplett**: `news_service.py`, `newsletter_service.py`, `ai_summary_service.py`, `models/news_article.py`, `api/news.py`, `pages/News.jsx`, `components/StockNews.jsx`
- **Globale Env-API-Keys**: `FRED_API_KEY`, `FMP_API_KEY`, `FINNHUB_API_KEY` als Env-Vars haben keine Wirkung mehr
- **Verwaiste Markdown-Reports aus dem Repo-Root**: `ARCHITEKTUR.md`, `AUDIT_2026-04-02.md`, `SCREENING_API_SPIKE.md`, `SCREENING_SCOPE.md`

### Behoben

- **Scorer-Cache bei Downloader-Fehler**: Defekte Setups wurden bis zu 15 Minuten lang gecached — die TTL bei Fehlern liegt jetzt bei 60 Sekunden, was den "stuck on 2/18"-Bug behebt
- **`score_stock` crasht nicht mehr bei Tickern ohne MA150**: Ein Cache-Roundtrip korrumpierte die `close_series`-Variable bei kurzlaufenden Titeln
- **ScreeningScan/ScreeningResult JSONB-Spalten SQLite-kompatibel**: Die Test-Suite schlug fehl, weil `JSONB` nicht auf SQLite verfuegbar ist — ersetzt durch `JSON` mit SQLite-Fallback
- **Korrelations-Matrix: HHI auf gefiltertes Matrix-Universum**: HHI wurde vorher ueber alle Positionen berechnet, auch solche die nicht in der Matrix enthalten waren — jetzt konsistent mit dem `tickers[]`-Filter; ausserdem Umlaute in den Klassifikations-Strings korrigiert
- **Eurostat HICP / SNB-Endpunkte korrigiert**: Zwei Datenpunkte im CH-Makro-Snapshot lieferten keine Werte, weil Serien-IDs und Cube-Names veraltet waren
- **Finnhub 403 (keine Coverage) landet in `warnings` statt `no_earnings_in_window`**: Titel ohne Finnhub-Coverage wurden bisher als "keine Earnings" interpretiert — jetzt korrekt als Warnung signalisiert
- **FMP API-Key-Test nutzt `/stable/quote`**: Der bisherige Legacy-v3-Endpoint wurde im August 2025 deprecated und lieferte 404
- **HHI-Card / CH-Makro-Card / Upcoming-Earnings-Banner**: Visuelles Styling an bestehendes KPI-Card-Pattern angeglichen

## [0.23.0] — 2026-04-04

### Hinzugefuegt
- **News-Feed (/news)**: Neue Seite mit aktuellen Finanznachrichten aus Yahoo Finance RSS — filterbar nach Portfolio, Watchlist oder allen Titeln
- **StockNews auf StockDetail**: Aktuelle Nachrichten direkt auf der Aktien-Detailseite, ersetzt die nicht mehr funktionsfaehige FMP-Integration
- **News-Newsletter**: Taeglich oder woechentlich per E-Mail — mit KI-generierter Zusammenfassung der relevanten Nachrichten fuer die eigenen Positionen
- **KI-Zusammenfassung**: Unterstuetzt Anthropic Claude, OpenAI GPT und Ollama (lokal) als LLM-Anbieter — ohne KI-Konfiguration ist der Newsletter deaktiviert
- **LLM-Einstellungen in Settings → Integrationen**: Anbieter, Modell und API-Key konfigurierbar pro Benutzer
- **Worker-Jobs**: News-Abruf taeglich um 06:30 und 18:00 Uhr CET, Newsletter-Versand um 07:30 Uhr CET

## [0.22.0] — 2026-04-03

### Hinzugefuegt
- **Smart Money Tracker (Screening)**: Neuer Bereich in der Sidebar zur systematischen Analyse institutioneller Aktivitaet rund um einzelne Aktien
- **Smart Money Score (0–10)**: Aggregierter Score aus 9 unabhaengigen Datenquellen — Insider-Cluster (+3), Superinvestor (+2), Aktivist 13D/13G (+2), Aktienrueckkauf (+2), Grosser Insider-Kauf (+1), Kongresskauf (+1), Unusual Volume (+1) sowie Warn-Signale Short-Trend (−1) und Fails-to-Deliver (−1)
- **Datenquellen**: FINRA Short Volume, OpenInsider (SEC Form 4), SEC EDGAR Submissions, Capitol Trades, Dataroma (13F Superinvestoren), yfinance Volumendaten — alle live aggregiert bei jedem Scan
- **Scan-Fortschritt**: Live-Anzeige per Quelle mit Timer und regulatorischem Warnhinweis (Daten nicht als Anlageberatung zu verstehen)
- **SmartMoneyPanel**: Neue Detailansicht auf der StockDetail-Seite zeigt alle aktiven Smart Money Signale fuer die angezeigte Aktie
- **Company Logos (TickerLogo)**: Firmenlogos ueber Clearbit/Logo.dev API werden jetzt in Screening-Tabelle, Watchlist, Portfolio und StockDetail-Header angezeigt
- **Sortierung und Filterung im Screening**: Score-Filter (Standard >= 3), Sortierung nach Score, Ticker, Name; Spalten-Sortierung per Klick
- **Glossar-Eintraege**: 9 neue Eintraege fuer alle Smart Money Indikatoren mit ausfuehrlichen Erklaerungen und Quellen-Angaben

### Geaendert
- Score-Berechnung verfeinert: Short-Trend und FTD reduzieren den Score (neg. Punkte), Unusual Volume ist Flag-only ohne Score-Einfluss

## [0.21.24] — 2026-04-02

### Geaendert
- Architektur: stoploss_service.py erstellt — Business-Logik aus api/stoploss.py extrahiert (ARCH-H1)
- Architektur: allocation_service.py erstellt — Core/Satellite-Allocation aus api/performance.py extrahiert (ARCH-H2)
- Architektur: admin_service.py erstellt — Token/PW/Session-Logik aus api/admin.py extrahiert (ARCH-H3)
- Architektur: analyze_csv_structure() in import_service.py extrahiert — 250 LOC aus api/imports.py (ARCH-H4)
- Architektur: precious_metals_service.py erstellt — _sync_position aus api/precious_metals.py extrahiert (ARCH-H5)
- Architektur: Write-Operationen in property_service.py extrahiert (12 CRUD-Funktionen) (ARCH-M4)
- Architektur: watchlist_service.py erstellt — get_watchlist aus api/analysis.py extrahiert (ARCH-M5)
- Architektur: fix_total_chf in transaction_service.py, refresh_earnings in earnings_service.py extrahiert (ARCH-M1, M2)

## [0.21.23] — 2026-04-02

### Behoben
- Security: httpx.get() → httpx.Client() Context-Manager in price_service.py (SEC-M1)
- Security: target_value Constraint gt=0 auf AlertCreate/AlertUpdate (SEC-L1)
- Security: requests-Import in yf_patch.py dokumentiert (SEC-L2)
- Performance: N+1 Query in admin invite-codes, recalculate, batch_position_type behoben (ARCH-H6, PERF-M1, ARCH-M3)
- Performance: Frontend-Poll auf 65s erhoeht (> 60s Backend-Cache-TTL) (PERF-M2)
- Performance: Composite-Index (user_id, is_active) auf positions (PERF-L1)
- DevOps: HEALTHCHECK in Backend- und Frontend-Dockerfiles (DEVOPS-H1)
- DevOps: .env.example vervollstaendigt (SMTP, FRED, Grafana, Uptime-Kuma) (DEVOPS-H3)
- DevOps: Uptime-Kuma Image auf 1.23.16 gepinnt (DEVOPS-H4)
- DevOps: Health Checks + Grafana anon-auth deaktiviert im Monitoring-Stack (DEVOPS-MON1, MON3)
- DevOps: Loki auth-Entscheidung dokumentiert (DEVOPS-K2)
- DevOps: Worker-Heartbeat beim Start initialisiert (DEVOPS-L1)
- DevOps: Sicherheitshinweis fuer ADMIN_PASSWORD nach Setup (DEVOPS-L2)
- DevOps: .dockerignore fuer backend/ und frontend/ erstellt (DEVOPS-MON5)
- DevOps: nginx server_tokens off, Proxy-Timeouts, Rate-Limiting (DEVOPS-M1, M2, M3)
- UX: PreciousMetals-Modals mit role="dialog", Focus-Trap, Escape, ScrollLock (UX-C1)
- UX: AlertPopover mit role="dialog", aria-modal, Focus-Trap (UX-H1)
- UX: HoldingCtxMenu mit Keyboard-Navigation (Pfeiltasten, Enter, Escape) (UX-H2)
- UX: Register Terms-Checkbox mit explizitem id/htmlFor, Fehler mit role="alert" (UX-M1)
- UX: IndustryDropdown mit aria-expanded, aria-haspopup, role="listbox/option" (UX-M2)
- UX: SignalDot mit role="img" und aria-label statt nur Farbe (UX-M3)
- UX: AccountTab — catch {} durch Error-Toasts ersetzt (UX-M4)
- UX: Core/Satellite-Buttons mit aria-pressed (UX-L1)
- UX: HoldingRow confirmDelete mit useEscClose (UX-L2)
- QA: exc_info=True in imports.py, recalculate_service, snapshot_service, settings_service (QA-M1, M3, M4, ARCH-L3)
- QA: trigger_snapshot_regen in Transaction/Position-Tests gemockt (QA-M2)
- Code: Dead Import yfinance in stock.py entfernt (ARCH-L1)
- Code: Redundanter asyncio-Import in benchmark_returns entfernt (ARCH-L2)

## [0.21.22] — 2026-04-02

### Behoben
- Critical: MA/MRS-Berechnung war im falschen Code-Branch — Portfolio-Summary zeigte nie 150-DMA-Warnungen oder Mansfield-RS (PERF-C1)
- Security: Starlette>=0.49.1 explizit gepinnt gegen CVE-2025-62727 DoS (SEC-H1)
- Bug: Transaktionstyp-Aenderung (buy→sell) konnte Positionsdaten korrumpieren — type-Feld aus TransactionUpdate entfernt (QA-H1)
- DevOps: init.sh Passwort-Minimum von 8 auf 12 Zeichen erhoeht + Komplexitaetspruefung (DEVOPS-K1)
- Performance: Blocking yfinance-Call in etf_200dma_alert_service in asyncio.to_thread gewrapped (PERF-H1)
- Security: Benchmark-Returns-Endpoint akzeptiert nur noch erlaubte Ticker (SEC-M2)
- DevOps: security_opt no-new-privileges + cap_drop ALL auf backend, worker, frontend (DEVOPS-H5)
- DevOps: Frontend + Uptime-Kuma Ports auf 127.0.0.1 gebunden (DEVOPS-H2)

## [0.21.21] — 2026-04-02

### Hinzugefuegt
- Frontend Test-Framework: Vitest + jsdom eingerichtet mit `npm run test` Script (QA-L1)
- 42 Unit-Tests fuer `format.js` (formatCHF, formatPct, formatNumber, formatDate, pnlColor, climateColor, configureFormats) und `tradingview.js` (alle 11 Exchange-Mappings + Edge Cases)

## [0.21.20] — 2026-04-02

### Behoben
- Architektur: Alembic Migration mit Hash-Prefix (`68c381537c96_`) auf numerisches Schema (`038_`) umbenannt (ARCH-M1)
- UX: Glossar-Link in Sidebar hinzugefuegt — Glossar ist jetzt direkt erreichbar statt nur ueber Hilfe-Seite (UX-L1)
- Docs: README.md Drift korrigiert — Rate-Limiting-Zaehler aktualisiert (120 Decorators/18 Router), veralteten Mobile-UX Beitragspunkt entfernt (DOCS-L1)

## [0.21.19] — 2026-04-02

### Behoben
- UX: format.js respektiert jetzt User-Settings fuer number_format (CH/DE/EN) und date_format (DD.MM.YYYY/YYYY-MM-DD) — bisher hardcodiert auf de-CH (UX-M2)
- Security: generate_alerts() Signatur auf mehrzeilig refactored fuer bessere Lesbarkeit (SEC-L1)
- Docs: Redis ohne Persistence als bewusste Designentscheidung dokumentiert (DEVOPS-L1)
- Docs: Monitoring Stack als optional und nicht CI-integriert dokumentiert (DEVOPS-L2)

## [0.21.18] — 2026-04-02

### Behoben
- Performance: 3 sequentielle FMP-API-Calls in get_fundamentals() parallelisiert via asyncio.gather (PERF-M1)
- DevOps: Non-root User (appuser) im Frontend Dockerfile — nginx laeuft nicht mehr als root (DEVOPS-M1)
- Architektur: Unbenutzten ttl-Parameter aus _get_cached() in stock_service.py entfernt (ARCH-L1)
- Architektur: 3 stille except-pass Bloecke in Alembic Migration 023 durch logger.warning() ersetzt (ARCH-L2)

## [0.21.17] — 2026-04-02

### Behoben
- Security: 10 synchrone httpx.get() Aufrufe auf async httpx.AsyncClient umgestellt — stock_service (FMP API), macro_indicators_service (FRED API, Shiller PE Scrape), cache_service (CoinGecko Batch) (SEC-H1)
- Architektur: ~100 Zeilen Business-Logik aus performance.py Router in performance_service.calculate_daily_change() extrahiert (ARCH-M2)
- UX: Unbenutzte EmptyState.jsx Komponente entfernt (Dead Code) (UX-M1)
- Docs: CLAUDE.md Rate-Limit-Zaehler aktualisiert — 109 Decorators/15 Router auf 120 Decorators/18 Router (DOCS-M1)

## [0.21.16] — 2026-04-02

### Behoben
- UX: CommandPalette mit vollstaendigem A11y-Pattern — role="dialog", aria-modal, Focus Trap (useFocusTrap), Scroll Lock (useScrollLock) (UX-H1)
- Security: Watchlist-Limit 200 aus hardcodiertem Wert in zentrale Konstante MAX_WATCHLIST_PER_USER in limits.py verschoben (SEC-M2)
- Security: Private-Equity-Limits (MAX_HOLDINGS=20, MAX_VALUATIONS=50, MAX_DIVIDENDS=50) aus Router in zentrale Konstanten in limits.py verschoben (SEC-M3)

## [0.21.15] — 2026-04-02

### Behoben
- Security: Rate Limits auf 8 Performance-Endpoints hinzugefuegt — history, monthly-returns, total-return, realized-gains, daily-change (5/min), benchmark-returns, fee-summary, core-satellite (60/min) (SEC-H2)
- Security: Rate Limits auf GET /price-alerts, GET /price-alerts/triggered, GET /sectors/taxonomy (60/min) (PERF-M3)
- Dependencies: pytest-cov zu requirements.txt hinzugefuegt — war fuer dokumentierten Coverage-Befehl noetig (PERF-M2)

## [0.21.14] — 2026-04-02

### Behoben
- Worker: Yahoo-Batch-Timeout von 30s auf 120s erhöht — bei vielen Tickern (>100) lief der Download auf langsameren VMs in ein Timeout, wodurch keine Kurse aktualisiert wurden
- Worker: Fetch-Fehler (Yahoo/Crypto/Gold) werden jetzt explizit geloggt statt nur im State gespeichert

## [0.21.13] — 2026-04-01

### Behoben
- Performance: FX-Rates und Close-Series-Prefetch in portfolio_service.py parallelisiert via asyncio.gather (H-1)

## [0.21.12] — 2026-04-01

### Behoben
- Docs: Datenschutzseite um 3 neue PII-Felder ergänzt — Hypothekenbank, Mietername, PE-Firmendaten (DRIFT-4)
- Docs: helpContent.js — D/E Ratio nicht mehr als Setup-Score-Kriterium bezeichnet (DRIFT-1)
- Docs: helpContent.js — Makro-Gate als informativer Indikator statt Kaufblocker beschrieben (DRIFT-2)
- Docs: helpContent.js — MRS-Kriterien von "zwei" auf "drei" korrigiert (MRS > 0, > 0.5, > 1.0) (DRIFT-3)
- Docs: helpContent.js — Kauf-Checkliste Fundamentals-Verweis aktualisiert (DRIFT-5)
- Docs: CLAUDE.md — Rate-Limit-Zähler von 77 auf 109 Decorators aktualisiert, PII-Liste ergänzt (DRIFT-6)

## [0.21.11] — 2026-04-01

### Behoben
- Security: Mortgage.bank und PropertyIncome.tenant werden jetzt mit Fernet verschluesselt (PII), Alembic-Migration String->Text (MED-1)
- Security: fred_api_key in UserSettings von String(500) auf Text geaendert — Alembic-Migration (MED-2)
- Security: FRED API-Key wird jetzt 5 Min gecacht statt bei jedem Call aus DB geladen (M-2)
- Architecture: Rate Limit (60/min) auf /api/portfolio/summary (M10)
- Architecture: Export-Logik aus settings.py Router in settings_service.py verschoben (M9)
- Performance: Grafana alerts.yml — email Contact-Point entfernt, verhindert Restart-Loop ohne SMTP (H-3)
- Performance: close:{ticker} Cache-TTL fuer 1y/2y/5y Perioden von 900s auf 86400s erhoeht (L-2)
- Performance: crypto_metrics cache.set mit explizitem TTL 900s (L-1)
- UX: WatchlistTable Notizen-Textarea mit aria-label (F-A11)
- UX: teal-Farbe als "etf" Design-Token in tailwind.config.js registriert (F-A12)
- UX: StockDetail — 3 Panels mit catch { /* ignore */ } zeigen jetzt Fallback-Meldung bei Fehler (K4)
- Docs: CLAUDE.md + README.md — Hilfe-Artikel (31->37), Finanzbegriffe (107->~120) aktualisiert (D-COUNT)

## [0.21.10] — 2026-04-01

### Behoben
- Performance: N+1 MA-Berechnungen in /api/alerts behoben — Broad-ETF-Tickers werden jetzt vorgefiltert, prefetched und in einem Thread berechnet (C-1)
- Performance: N+1 DB-Queries in batch_stop_loss behoben — alle Positionen werden jetzt in einer Query mit IN() geladen (C-2)
- Performance: Portfolio-Summary Cache-TTL von 30s auf 60s erhoeht, passend zum Frontend-Polling-Intervall (M-1)
- Security: Rate Limiter auf 12 fehlenden Auth-Endpoints (logout, MFA, change-password, delete-account, sessions, force-change-password) (AUTH-RL)
- Security: ConfirmRequest in imports.py verwendet jetzt typisierte Pydantic Models statt list[dict] (HIGH-2)
- Security: Worker-Heartbeat von /tmp nach /app/data/ verschoben (MED-4)
- Architecture: _decrypt_field Duplikation in property_service.py entfernt — verwendet jetzt encryption_helpers.decrypt_field (H3)
- UX: Settings-Tabs mit ARIA tablist/tab/aria-selected Pattern (F-A09)
- UX: AlertPopover mit useEscClose und Toast-Fehlermeldungen statt stiller console.error (F-A10)
- Docs: helpContent.js auf 18-Punkte-Scoring aktualisiert (war 21 Punkte) — 6 Stellen korrigiert (D-CRIT)
- Docs: glossary.js — ROE-Duplikat entfernt, Modified Dietz hinzugefuegt, 3 veraltete Eintraege korrigiert (D-GLOSS)

## [0.21.9] — 2026-04-01

### Hinzugefügt
- Tests: test_recalculate_service.py — 19 Tests für gewichteten Durchschnittspreis, realisierte P&L, Teilverkäufe, Fractional Shares, Edge Cases (H5)
- Tests: test_price_service.py — 20 Tests für 4-Layer-Preisauflösung (Cache → DB → Live → Fallback), VIX-Grenzwerte, Crypto/Gold-Preise (H5)
- Tests: test_portfolio_service.py — 31 Tests für MA-Status-Badges, MRS, Market-Value-Berechnung aller Asset-Typen, Allocation-Bucketing (H5)

## [0.21.8] — 2026-04-01

### Behoben
- Security: CSP in nginx verschärft — /api/ und /assets/ Locations haben jetzt restriktive CSPs ohne unsafe-eval/unsafe-inline; root CSP dokumentiert warum TradingView-Widgets unsafe-eval/unsafe-inline erfordern (MED-2)
- Architecture: Settings.jsx von 1231 auf 51 Zeilen aufgeteilt — 6 Tab-Komponenten in eigene Dateien unter pages/settings/ extrahiert (M1)
- Architecture: Verbleibende grosse Dateien (ImportWizard 1190, Transactions 925, ImmobilienWidget 855) als kohäsive Einheiten dokumentiert — kein künstliches Splitting (M1)
- Architecture: Backend-Services über 500 Zeilen geprüft — swissquote_parser, alert_service, macro_indicators_service, cache_service, settings_service sind kohäsive Module ohne sinnvolle Splitpunkte; heilige Dateien nicht betroffen (M2)

## [0.21.7] — 2026-04-01

### Behoben
- Markt & Sektoren: HTTP 500 behoben — fehlender AsyncSession-Import in macro_indicators_service.py

### Hinzugefügt
- Tests: test_sector_mapping.py — 18 Tests für ETF-Whitelist, is_broad_etf(), FINVIZ-Taxonomie-Integrität (H5)
- Tests: test_encryption_helpers.py — 12 Tests für encrypt/decrypt Roundtrip, Legacy-Fallback, IBAN-Maskierung (H5)
- Tests: test_swissquote_parser.py — 30 Tests für CSV-Erkennung, Typ-Mapping, Datum-Parsing, Ticker-Mapping, Teilausführungs-Aggregation (H5)
- Tests: test_stock_scorer.py — 16 Tests für Signal-Bestimmung, Breakout-Trigger, Formatierungs-Helfer (H5)
- Tests: test_scoring_service.py — 5 Tests für assess_ticker Signal-Logik, ETF 200-DMA Override, Cache (H5)

## [0.21.6] — 2026-04-01

### Behoben
- Architecture: settings.py Router von 733 auf 267 Zeilen refactored — Business-Logik und DB-Queries in neuen settings_service.py extrahiert (H4, M4)
- Accessibility: aria-label auf 17 Inputs ohne programmatische Labels in 8 Komponenten (ImportWizard, WatchlistTable, StopLossWizard, EtfSectorPanel, EditPositionModal, Hilfe, Glossar, Transactions) (F-A04)
- Accessibility: text-muted Farbe von #64748b auf #7a8ba3 aufgehellt — Kontrastratio auf bg-card von 3.84:1 auf 5.27:1 verbessert, besteht jetzt WCAG AA fuer kleine Schriftgroessen (F-A07)

## [0.21.5] — 2026-04-01

### Behoben
- Security: forgot-password Rate Limiter von In-Memory TTLCache auf Redis-backed slowapi umgestellt — kein split-brain mehr bei 2 Uvicorn Workers (HIGH-2)
- Security: X-Frame-Options von SAMEORIGIN auf DENY geaendert in allen nginx Location-Blocks (MED-1)
- Security: totp_secret Spaltentyp von String(255) auf Text geaendert — verschluesselte Felder muessen Text sein (MED-3, Alembic Migration 035)
- Architecture: INFLOW_TYPES/OUTFLOW_TYPES nach constants/cashflow.py extrahiert — Code-Duplikation in 3 Services beseitigt (H2)
- Architecture: Worker-Container Health Check hinzugefuegt — Docker erkennt jetzt haengende Worker (MED-6)
- Architecture: PostgreSQL Memory-Limit von 16GB auf 4GB reduziert — passend zu shared_buffers 1GB (M7)
- Quality: request_id in allen HTTPException-Responses — neuer Exception-Handler in main.py (QA-15, M5)
- Accessibility: aria-expanded auf allen Dropdown-Triggern (MoreVertical-Buttons, Filter-Toggle, Kalender) in 9 Dateien (F-A05)
- Accessibility: aria-live Regionen auf LoadingSpinner, CacheStatus, Skeleton, AlertsBanner — Screen-Reader erfahren von Statusaenderungen (F-A03)

## [0.21.4] — 2026-04-01

### Behoben
- Architecture: breakout_alert_service.py erstellt — Worker-Job fuer Watchlist Breakout-Alerts (Donchian 20d + Volumenbestaetigung) funktioniert jetzt korrekt (C1)
- Accessibility: useFocusTrap in alle 15 Modals mit role="dialog" eingebaut — Tab-Fokus bleibt jetzt im Dialog (F-A01, WCAG 2.4.3)
- Accessibility: useScrollLock in alle Modals eingebaut — Hintergrund scrollt nicht mehr bei offenem Dialog (F-A02)
- Accessibility: text-slate-400 durch text-text-secondary ersetzt in 13 Stellen — konsistentes Theming, besserer Kontrast bei kleinen Schriftgroessen (F-A06)
- Security: Unbenutzte ANTHROPIC_API_KEY aus docker-compose.yml entfernt (LOW-1)
- Quality: Silent Exception in stock.py _yf_search() behoben — Logging hinzugefuegt (QA-18)

## [0.21.3] — 2026-04-01

### Behoben
- Security: Per-User-Limits auf allen erstellbaren Entitäten — Edelmetalle (200), Immobilien (20), Hypotheken (10/Immobilie), Ausgaben/Einnahmen (500/Immobilie), Watchlist-Tags (50), Import-Profile (20)
- Quality: 27 ungenutzte Imports entfernt in 17 Dateien (api/ und services/) — kein Dead Code mehr
- Quality: Alle Limits zentralisiert in constants/limits.py

## [0.21.2] — 2026-04-01

### Behoben
- Security: Rate Limiter auf allen POST/PUT/PATCH/DELETE Endpoints (positions, imports, analysis, stock, market) — CRIT-2, CRIT-3
- Security: Rate Limiter auf rechenintensive GET Endpoints (market climate, sectors, scores, stock search/profile/news, analysis MRS/breakouts/levels/reversal/score) — 5-30/min je nach Aufwand
- Security: Pydantic Constraints (ge, gt, le, min_length, max_length) auf allen numerischen und String-Feldern in 10 Routern (positions, transactions, alerts, precious_metals, real_estate, analysis, settings, imports) — CRIT-5
- Quality: Silent Exception Handler behoben — Logging hinzugefügt in encryption_helpers, property_service, price_service (crypto, VIX) — CRIT-6

## [0.21.1] — 2026-04-01

### Behoben
- Security: 11 Backend-CVEs behoben — cryptography 44.0.0 -> 46.0.6, pyjwt 2.9.0 -> 2.12.1, python-multipart 0.0.20 -> 0.0.22, requests 2.32.3 -> 2.32.5, FastAPI 0.115.6 -> 0.121.3 (inkl. starlette 0.50.0)
- Security: 1 Frontend-CVE behoben — picomatch (ReDoS + Method Injection) via npm audit fix

## [0.21.0] — 2026-03-30

### Geändert
- Performance: Market Climate API — 3 sequenzielle API-Calls parallelisiert mit `asyncio.gather()` (K-1)
- Performance: Macro-Gate — Climate-Daten werden einmal geladen und durchgereicht statt 3× redundant (K-2)
- Performance: Precious-Metals-Endpoint — 3 sequenzielle Calls parallelisiert (H-9)
- Performance: Crypto-Metrics-Endpoint — 4 API-Calls (CoinGecko, Fear&Greed, DXY, BTC ATH) parallelisiert (M-10)
- Performance: Price-Service — Event-Loop-Schutz verhindert blockierende yfinance/httpx-Calls im API-Request (K-4, H-5)
- Performance: In-Memory Cache von 1'000 auf 2'500 Einträge erhöht (M-1)
- Performance: nginx gzip-Kompression für SVG und Webfonts aktiviert (N-2)
- Performance: `fetch_all_indicators()` — 7 FRED/VIX-Calls parallel mit ThreadPoolExecutor, API-Key einmal geladen (H-2, M-4)
- Performance: `fetch_extra_indicators()` — 5 Calls (WTI, Brent, Fed Rate, USD/CHF) parallelisiert (H-3)
- Performance: `score_stock()` — `yf.Ticker().info` wird mit 24h TTL gecacht statt bei jedem Call neu geladen (K-3)
- Performance: `get_total_return()` akzeptiert vorgeladene Summary, vermeidet redundante Neuberechnung (H-4)
- Performance: Daily-Change — FX-Rates in einem Batch-Query geladen statt N+1 (M-8)
- Performance: StockDetail — Portfolio-Summary aus DataContext statt 2× separater API-Call, Score-Daten einmal geladen und geteilt (H-6)
- Performance: Portfolio-Seite — Waterfall-Loading: abhängige Endpoints erst nach Summary laden (H-7)
- Performance: DataContext STALE_MS von 60s auf 55s reduziert, verhindert Timing-Drift (N-1)
- Performance: `prefetch_close_series()` — nur noch 2y-Download, 1y wird aus letzten 252 Tagen abgeleitet (M-2)
- Performance: `calculate_xirr_for_period()` akzeptiert vorgeladene Snapshots/Transaktionen (M-3)
- Performance: Neuer `get_cached_prices_batch_sync()` — eine DB-Session für mehrere Ticker statt N einzelne (M-5)
- Performance: Watchlist PriceCache-Query auf letzte 7 Tage beschränkt statt alle historischen Daten (M-7)

## [0.20.1] — 2026-03-28

### Hinzugefügt
- MIT LICENSE-Datei im Repository-Root
- Datenschutzerklärung: TradingView, Gold.org, multpl.com als externe Dienste ergänzt
- Datenschutzerklärung: Differenzierte Rechtsgrundlagen pro Verarbeitungszweck (Art. 6 DSGVO)
- Datenschutzerklärung: Kontaktadresse für Datenschutzanfragen
- TradingView-Hinweis: IP-Übermittlung und DSGVO-Drittlandtransfer dokumentiert
- Yahoo Finance-Hinweis: yfinance-Verfügbarkeit nicht garantiert

### Behoben
- Impressum: Platzhalter durch echte Betreiberdaten ersetzt (Imprint.jsx + Legal.jsx)
- Signal-Sprache: "Verkaufen!" → "Verkaufskriterien erreicht" in alert_service.py
- Signal-Sprache: "kaufe nicht", "Dann kaufe" → neutrale Formulierungen in helpContent.js
- Signal-Sprache: "Kaufsignal"/"Verkaufssignal" → "Kaufkriterien erfüllt"/"Verkaufskriterien erreicht" in glossary.js
- Hilfe-Texte: Makro-Gate korrekt als "informativer Indikator" beschrieben (war fälschlich als "Blocker" dokumentiert)
- AGB: Änderungsklausel differenziert (wesentliche Änderungen → erneute Zustimmung)
- AGB: Hinweis "sollte von Anwalt geprüft werden" entfernt

## [0.20.0] — 2026-03-28

### Hinzugefügt
- Rate Limiting auf allen ~60 schreibenden Endpoints (POST/PUT/PATCH/DELETE) — 30/min für CRUD, 5/min für rechenintensive Operationen
- CoinGecko Rate-Limiter (max 25 Calls/Minute mit Sliding-Window)
- DataContext Error-State: Netzwerkfehler werden geloggt und im Context verfügbar gemacht
- PriceCache Index auf `date`-Spalte für schnellere Queries
- Alembic-Migration 034 für PriceCache-Index
- Zentralisierte Encryption-Helpers (`services/encryption_helpers.py`)
- Shared Pydantic-Schemas (`api/schemas.py`) und Constants (`constants/limits.py`)

### Behoben
- Silent Exception in `price_service.py` — yfinance-Fehler werden jetzt geloggt (debug)
- Silent Exceptions in `utils.py` (FX-Rate, MRS, Close-Series) — alle mit Logging
- Silent Exceptions in `portfolio_service.py` (MA-Status, MRS-Lookup)
- Silent Exception in `stock.py` — yfinance Ticker-Fallback-Lookup
- User-Löschung: Private Equity Holdings und AdminAuditLog werden jetzt korrekt mitgelöscht
- nginx `/assets/` Location: Security Headers (HSTS, CSP, X-Frame-Options etc.) fehlten — nginx vererbt `add_header` nicht bei eigenen Direktiven
- `validate-reset-token` akzeptiert jetzt Pydantic-Model statt unvalidiertem `dict`
- `/api/errors` Body auf 10 KB limitiert
- CORS: `OPTIONS` aus `allow_methods` entfernt (wird automatisch von CORSMiddleware behandelt)

### Geändert
- `_encrypt_field`/`_decrypt_field`/`_decrypt_and_mask_iban` aus 7 Dateien in zentrale `services/encryption_helpers.py` konsolidiert
- `RecalculateRequest` aus `positions.py` und `performance.py` in `api/schemas.py` konsolidiert
- `MAX_POSITIONS_PER_USER`/`MAX_TRANSACTIONS_PER_USER` in `constants/limits.py` zentralisiert
- PriceCache-Query in daily-change Endpoint: nur benötigte Ticker statt alle laden
- Earnings-Refresh: parallel mit Semaphore (max 5 concurrent) statt sequentiell
- Alerts: Moving Averages nur für Broad-Index-ETFs berechnen (nicht alle Watchlist-Items)
- PE Holdings Count: `select(func.count())` statt `len(scalars.all())`

## [0.19.5] — 2026-03-27

### Entfernt
- Fundamentaldaten-Sektion komplett entfernt (Revenue, Margins, D/E, PE, PEG, FCF, Market Cap, ROIC, EPS, EPS Growth) — yfinance-Daten weichen systematisch von StockAnalysis ab und sind für Investitionsentscheidungen unzuverlässig
- 4 Fundamental-Kriterien aus dem Setup-Score entfernt (Umsatz steigend, EPS steigend, ROE > 15%, D/E unter Branche Ø) — Score von 22 auf 18 rein technische Kriterien reduziert
- `fundamental_service.py` gelöscht, API-Endpoints `/stock/{ticker}/key-metrics` und `/stock/{ticker}/fundamentals` entfernt
- Bollinger Bands Toggle "BB(20)" aus der TradingView-Chart Indikator-Leiste entfernt

### Hinzugefügt
- Aktien-Detailseite: Link zu StockAnalysis (US-Aktien) bzw. Yahoo Finance (Nicht-US) für Fundamentaldaten
- ETFs zeigen "ETF Holdings & Zusammensetzung" mit Link zu Yahoo Finance Holdings
- Backend: `quoteType` Feld im Company-Profile-Endpoint für ETF-Erkennung
- TradingView Chart: RSI standardmässig aktiv

### Geändert
- Setup-Score Schwellen bleiben prozentual gleich (≥70% STARK, 45-69% MODERAT, <45% SCHWACH)
- Glossar: Setup-Score Beschreibung aktualisiert (18 Kriterien, rein technisch)
- CLAUDE.md und README.md an neue Architektur angepasst

## [0.17.4] — 2026-03-27

### Hinzugefügt
- PEG Ratio als neue Fundamental-Karte auf der Aktien-Detailseite (PE Ratio / Earnings Growth)
- Farbcodierung: Grün < 1.0 (potenziell unterbewertet), Gelb 1.0–2.0 (fair), Rot > 2.0 (potenziell überbewertet)
- Backend: Primär `pegRatio` aus yfinance, Fallback-Berechnung aus `trailingPE / earningsGrowth`
- Glossar-Eintrag für PEG Ratio mit GlossarTooltip

## [0.17.3] — 2026-03-27

### Behoben
- S&P 500 Kurs im Marktklima-Widget zeigte 119.52 statt ~5'500 — korrupter In-Memory-Cache bereinigt
- `prefetch_close_series`: Single-Ticker mit `group_by="ticker"` schlug fehl wegen MultiIndex-Spaltenstruktur (KeyError auf `data["Close"]`)
- Sanity-Check für S&P 500 Kurs von >100 auf >1'000 angehoben (S&P war seit 2014 nie unter 1'000)

## [0.17.2] — 2026-03-27

### Geändert
- Monatsrenditen-Heatmap: Benchmark-Zeile (S&P 500) in neutralem Grau statt grün/rot — klare visuelle Trennung zwischen Portfolio (farbig) und Benchmark (grau)

## [0.17.1] — 2026-03-26

### Behoben
- Benchmark-Heatmap: yfinance MultiIndex-Columns korrekt geflattened — S&P 500 Zeile wird jetzt angezeigt

## [0.17.0] — 2026-03-26

### Hinzugefügt
- Monatsrenditen-Heatmap: Benchmark-Zeile (S&P 500) unter jeder Jahreszeile — zeigt Index-Monatsrenditen zum Vergleich
- Neuer Endpoint `GET /api/portfolio/benchmark-returns?ticker=^GSPC` mit 24h Redis-Cache
- Neuer Service `benchmark_service.py` berechnet Monatsrenditen aus yfinance-Kursdaten (5 Jahre Historie)

## [0.16.1] — 2026-03-26

### Behoben
- ROIC: Erweiterte Fallback-Kette (returnOnCapital → returnOnInvestedCapital → Financials-Berechnung → ROE als Annäherung)
- ROIC: Label wechselt automatisch zu "ROE" wenn nur Eigenkapitalrendite verfügbar ist
- EPS: Zeigt jetzt Währungssymbol (z.B. "$8.52" statt "8.52")

### Hinzugefügt
- Glossar: Neue Einträge für ROIC, ROE, EPS Growth mit GlossarTooltip auf den Fundamental-Karten

## [0.16.0] — 2026-03-26

### Hinzugefügt
- Aktien-Detailseite: Drei neue Fundamental-Kennzahlen — ROIC (Return on Invested Capital), EPS (TTM), EPS Growth (YoY)
- ROIC: Berechnet aus yfinance returnOnCapital oder operatingIncome / (totalAssets - currentLiabilities)
- Farbcodierung: ROIC grün > 12%, gelb 8–12%, rot < 8%; EPS grün wenn positiv; EPS Growth grün wenn wachsend

## [0.15.6] — 2026-03-26

### Behoben
- Direktbeteiligungen-Widget: Farbige Linie (emerald) an der oberen Kante hinzugefügt — konsistent mit allen anderen Portfolio-Widgets

## [0.15.5] — 2026-03-26

### Hinzugefügt
- Aktien & ETFs: "Dividende erfassen" im Drei-Punkte-Menü (⋮) — öffnet Transaktionsformular mit Typ Dividende vorausgewählt

## [0.15.4] — 2026-03-26

### Behoben
- Private Equity: Unrealisierter Gewinn/Verlust und investiertes Kapital werden jetzt aus der Gesamtrendite-Karte ausgeschlossen (total_return_service.py)
- Private Equity: PE-Positionen fliessen nicht mehr in MWR-Fallback-Berechnung ein
- Private Equity: Komplett aus Snapshot-Berechnungen entfernt (war faelschlicherweise als cost_basis inkludiert, verursachte -89K Phantom-Cashflow in XIRR)
- Private Equity: Aus Portfolio-History-Berechnung entfernt (history_service.py)
- Snapshots regeneriert nach PE-Entfernung (727 Snapshots, sauber)
- XIRR Diagnose-Report erstellt (XIRR_DIAGNOSE.md): 11.36% annualisiert, plausibel, alle 12 PE-Ausschluss-Stellen verifiziert

## [0.15.3] — 2026-03-26

### Behoben
- Private Equity: Wird jetzt korrekt aus allen liquiden Performance-Berechnungen ausgeschlossen (Heute, Gesamtrendite, YTD, Monatsrenditen, XIRR, Snapshots)
- Private Equity: current_price bleibt NULL wenn keine Bewertung hinterlegt ist (kein falscher −90K Verlust mehr)
- Private Equity: In Liquides Vermögen, Daily Change, History und Snapshot-Berechnung gleich behandelt wie Vorsorge/Immobilien

## [0.15.2] — 2026-03-26

### Geändert
- UI Polish: Alle Portfolio-Widgets an das Design des Direktbeteiligungen-Widgets angeglichen — grössere Titel, farbige Icons, ausgefüllte Add-Buttons

## [0.15.1] — 2026-03-26

### Behoben
- Direktbeteiligungen: Drei-Punkte-Menü (⋮) auf jeder Holding-Zeile mit Aktionen "Bewertung hinzufügen", "Dividende hinzufügen", "Bearbeiten", "Löschen"

## [0.15.0] — 2026-03-26

### Hinzugefügt
- Neues Widget: Direktbeteiligungen / Private Equity — nicht-börsenkotierte Unternehmensbeteiligungen mit jährlicher Steuerwert-Bewertung und Dividendenhistorie
- Private Equity: Drei neue Tabellen (Holdings, Valuations, Dividends) mit Fernet-Verschlüsselung für PII
- Private Equity: Vollständige CRUD-API mit 12 Endpoints (Holdings, Bewertungen, Dividenden)
- Private Equity: Position-Sync für Gesamtvermögen-Tracking (analog Edelmetalle)
- Private Equity: Automatische Berechnung von Netto-Steuerwert (Pauschalabzug) und Dividenden-Beträgen (Verrechnungssteuer)
- Private Equity: Detail-Ansicht mit Bewertungshistorie, Dividendenhistorie und Kennzahlen
- Private Equity: Eigene Kategorie "Private Equity" im Sektor-Chart
- Private Equity: Wird NICHT in liquide Performance eingerechnet (wie Vorsorge/Immobilien)

## [0.14.0] — 2026-03-26

### Hinzugefügt
- Neue Alert-Kategorie: "ETF unter 200-DMA (Kaufkriterien)" — benachrichtigt wenn breite Index-ETFs (27-Ticker Whitelist) unter die 200-Tage-Linie fallen
- ETF 200-DMA Alerts prüfen sowohl Portfolio-Positionen als auch Watchlist-Einträge
- E-Mail-Benachrichtigung für ETF 200-DMA Alerts (aktivierbar in Einstellungen, tägliche Deduplizierung)
- Worker-Job für ETF 200-DMA E-Mail-Alerts (täglich 22:35 CET nach US-Marktschluss)
- Positiver Alert-Stil (grün, TrendingUp-Icon) für Kaufkriterien-Alerts

### Geändert
- ETF 200-DMA Whitelist aus `scoring_service.py` in gemeinsame Konstante `sector_mapping.py` extrahiert (DRY)

## [0.13.0] — 2026-03-26

### Hinzugefügt
- Portfolio-Sektorchart: ETF-Sektorgewichtungen werden aufgelöst — OEF, CHSPI, EIMI verteilen ihren Marktwert anteilig auf die hinterlegten Sektoren statt als "Multi-Sector" zu klumpen

### Behoben
- TradingView Mini-Widget (Portfolio-Tabelle, Watchlist): Symbol-Mapping für .SW-Ticker (z.B. CHSPI.SW → SIX:CHSPI) — bisher wurde der rohe yfinance-Ticker übergeben
- TradingView-Widgets: Graceful Fallback bei nicht verfügbaren Symbolen (z.B. EIMI.L) — Mini-Widget zeigt "Chart nicht verfügbar", Hauptchart zeigt Fallback mit Link zu TradingView

### Geändert
- TradingView Symbol-Mapping in gemeinsame Utility-Funktion `toTradingViewSymbol()` extrahiert (DRY)

## [0.12.0] — 2026-03-25

### Hinzugefügt
- Immobilien: SARON-Hypotheken mit Marge — dynamische Zinsberechnung (Marge + SARON-Leitzins, Floor auf Marge)
- Immobilien: Effektiver Zinssatz wird im Hypothek-Formular live berechnet und in der Tabelle angezeigt
- Immobilien: Hypothek-Tabelle zeigt bei SARON Subtext "Marge X.XXX%"

## [0.11.0] — 2026-03-25

### Hinzugefügt
- Transaktionen: Ticker-Autocomplete mit Suche (bestehende Positionen + yfinance) ersetzt Positions-Dropdown
- Transaktionen: Positionen werden automatisch erstellt wenn Ticker neu ist (gleicher Flow wie CSV-Import)
- Transaktionen: Erweiterte Währungsauswahl (JPY, SEK, NOK, DKK, AUD, HKD, SGD)
- API: Neuer Endpoint `GET /api/stock/search?q=...` für Ticker-Suche
- Pocket (pocketbitcoin.com) CSV-Import mit Auto-Detection (nur BTC-Käufe, deposit/withdrawal werden übersprungen)
- Watchlist: Resistance-Level (Breakout) manuell setzen über Crosshair-Button im Actions-Bereich

### Geändert
- Watchlist: "Ticker analysieren" öffnet jetzt die volle Detailseite (Chart, Fundamentals, Score) statt nur den Score inline
- Portfolio: Resistance-Level aus dem Positions-Editor entfernt (jetzt nur noch über Watchlist)

## [0.10.0] — 2026-03-25

### Hinzugefügt
- Portfolio: "Position hinzufügen" Button bei Aktien & ETFs und Crypto mit Weiterleitung zu Transaktionen
- Portfolio: Empty States bei leeren Aktien/ETF- und Crypto-Tabellen mit Buttons "Transaktion erfassen" und "CSV importieren"
- Immobilien: Dreipunkte-Menü (⋮) als Mobile-Alternative zum Rechtsklick-Kontextmenü
- Immobilien: "Immobilie löschen" Option im Kontextmenü
- Changelog-Seite unter /changelog mit Versions-Link im Footer

### Behoben
- Immobilien: Netto-Berechnung rechnete Hypothekarkosten doppelt ein (Ausgaben + Zinsen/Amortisation statt nur Ausgaben)

## [0.9.0] — 2026-03-25

### Hinzugefügt
- IBKR Flex Query CSV-Import (Auto-Erkennung, 22 Börsen-Mappings)
- 3-Punkt-Umkehr-Erkennung im Setup-Score (Kriterium #19)
- Versionsnummer im Footer
- Self-Hosting-Dokumentation (Reverse Proxy, CORS, Override)

### Behoben
- JPY-Dividenden wurden nicht in CHF umgerechnet
- Portfolio-Daten nach Import/Erfassung erst nach Hard Refresh sichtbar
- Fresh Install: Fehlende Tabellen bei erstmaliger DB-Erstellung
- Admin-User Race Condition bei mehreren Uvicorn-Workers
- Immobilien-Akkordeon per Default aufgeklappt

### Geändert
- CORS_ORIGINS aus Environment statt hardcoded
- Backend-Port auf localhost für Reverse Proxy
- Score-System: 18 → 19 Kriterien (alle 4 Strategy-Regeln implementiert)
