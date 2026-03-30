# Performance-Audit — OpenFolio

**Datum:** 30.03.2026
**Scope:** Backend (API, Services, Worker), Frontend (React), Datenbank, Docker/nginx
**Methode:** Statische Code-Analyse aller kritischen Pfade

---

## Zusammenfassung

Es wurden **27 Findings** identifiziert, davon **4 Kritisch**, **9 Hoch**, **10 Mittel** und **4 Niedrig**. Die grössten Performance-Probleme liegen in:

1. **Sequenziellen Blocking-Calls** in der Market-Climate-API (3 aufeinanderfolgende `asyncio.to_thread`-Calls statt parallel)
2. **Redundanten `get_market_climate()`-Aufrufen** in der Macro-Gate-Berechnung (bis zu 4× pro Request)
3. **`yf.Ticker().info`-Call** im `score_stock()` — blockiert für 2-5s pro Ticker, zusätzlich zum `yf_download`
4. **Sync HTTP-Calls in Thread-Kontext** (`get_crypto_price_chf`, `get_gold_price_chf`) — blockieren den Thread-Pool

---

## Kritisch (4)

### K-1: Market Climate API — Sequenzielle statt parallele Datenabfrage

**Datei:** `backend/api/market.py`, Zeilen 28-31
**Code:**
```python
climate = await asyncio.to_thread(get_market_climate)
macro = await asyncio.to_thread(fetch_all_indicators)
extra = await asyncio.to_thread(fetch_extra_indicators)
gate = calculate_macro_gate()
```

**Problem:** Drei `await asyncio.to_thread()`-Calls werden nacheinander ausgeführt. Jeder kann 3-15 Sekunden dauern (yfinance-Downloads, FRED-API, Web-Scraping von multpl.com). Bei Cache-Miss betraegt die Gesamtladezeit bis zu 30-45 Sekunden.

**Impact:** Die Dashboard-Seite ("Markt & Sektoren") ist der langsamste Endpoint der gesamten Applikation. Jeder Aufruf blockiert.

**Loesung:** `asyncio.gather()` verwenden:
```python
climate, macro, extra = await asyncio.gather(
    asyncio.to_thread(get_market_climate),
    asyncio.to_thread(fetch_all_indicators),
    asyncio.to_thread(fetch_extra_indicators),
)
gate = calculate_macro_gate()
```

### K-2: Macro-Gate ruft `get_market_climate()` 3× redundant auf

**Datei:** `backend/services/macro_gate_service.py`, Zeilen 17, 24, 33

**Problem:** `calculate_macro_gate()` ruft in drei separaten Check-Funktionen (`_check_sp500_above_150dma`, `_check_sp500_structure`, `_check_vix_below_20`) jeweils `get_market_climate()` auf. Obwohl das Ergebnis im Cache liegt, sind das trotzdem 3 unnoetige Cache-Lookups und JSON-Deserialisierungen.

Zusaetzlich: In `market_climate` (api/market.py Zeile 31) wird `calculate_macro_gate()` nach den drei Thread-Calls aufgerufen. `calculate_macro_gate()` ruft intern `get_market_climate()` und `get_sector_rotation()` nochmals auf — Daten die gerade erst geladen wurden.

**Impact:** Bei Cache-Miss werden `get_market_climate()` und `fetch_all_indicators()` mehrfach ausgefuehrt, da der Cache erst am Ende der jeweiligen Funktion gesetzt wird.

**Loesung:** Climate-Daten einmal laden und an die Gate-Checks uebergeben:
```python
def calculate_macro_gate(climate=None, rotation=None, sector=None):
    if climate is None:
        climate = get_market_climate()
    ...
```

### K-3: `score_stock()` macht separaten `yf.Ticker().info`-Call

**Datei:** `backend/services/stock_scorer.py`, Zeilen 240-243
```python
try:
    info = t.info
except Exception:
    info = {}
```

**Problem:** `_download_and_analyze()` (Zeile 48) laedt bereits 2 Jahre historische Daten via `yf_download()`. Danach ruft `score_stock()` nochmals `yf.Ticker(ticker).info` auf — ein separater HTTP-Call an Yahoo Finance, der 2-5 Sekunden dauert. Dieser Call liefert nur `marketCap`, `averageVolume`, `shortName`, `sector`, `industry` und `currency`.

**Impact:** Jeder Score-Request dauert doppelt so lang wie noetig. Bei Batch-Scoring (Sektor-Holdings mit 30 Tickers) summiert sich das auf 60-150 Sekunden.

**Loesung:** `marketCap` und `averageVolume` koennen aus den bereits heruntergeladenen Daten approximiert werden (Volume aus dem DataFrame, MarketCap = current_price * sharesOutstanding aus dem Cache). Alternativ: `info`-Daten mit laengerem TTL (24h) separat cachen.

### K-4: Sync HTTP-Calls (`httpx.get`) blockieren den Thread-Pool

**Datei:** `backend/services/price_service.py`, Zeilen 86-103 (`get_crypto_price_chf`) und Zeilen 136-164 (`get_gold_price_chf`)

**Problem:** Diese synchronen Funktionen werden von `portfolio_service.py` -> `_compute_market_value()` aufgerufen, das wiederum NICHT in einem Thread laeuft (es wird direkt aus der async `get_portfolio_summary()` aufgerufen). Der Aufruf von `httpx.get()` blockiert den gesamten Event-Loop.

Konkret: In `portfolio_service.py` Zeile 272-275:
```python
if pos.type == AssetType.crypto and pos.coingecko_id:
    crypto = get_crypto_price_chf(pos.coingecko_id)
```
Dies wird fuer jede Crypto-Position aufgerufen — synchron, im Event-Loop.

**Impact:** Bei Cache-Miss fuer Crypto/Gold-Preise blockiert der gesamte API-Worker fuer 10-15 Sekunden (Timeout der HTTP-Calls).

**Loesung:** `_compute_market_value()` sollte nur gecachte Preise verwenden. Wenn der Cache leer ist, Fallback auf `cost_basis_chf` (wie bereits fuer den "no price" Fall). Die Live-Preise werden ohnehin alle 60 Sekunden vom Worker aktualisiert.

---

## Hoch (9)

### H-1: Portfolio Summary berechnet MA/MRS fuer alle Positionen bei jedem Aufruf

**Datei:** `backend/services/portfolio_service.py`, Zeilen 143-156

**Problem:** Bei jedem Aufruf von `/api/portfolio/summary` (TTL 30s) werden Moving Averages und Mansfield RS fuer alle tradable Positionen berechnet. Das erfordert:
- `prefetch_close_series()` — 2× yf_download (1y + 2y) fuer alle uncached Tickers + ^GSPC
- `_compute_all_ma_mrs()` — pandas-Berechnungen fuer jeden Ticker

Bei 20+ Positionen und Cold-Cache (nach Worker-Neustart oder nach 15min Cache-Ablauf) dauert dies 10-30 Sekunden.

**Impact:** Der wichtigste und am haeufigsten aufgerufene Endpoint (30s Polling) ist bei Cache-Miss sehr langsam.

**Loesung:** MA/MRS-Daten sollten vom Worker vorberechnet und im Cache abgelegt werden (wie bereits fuer Preise). Der Portfolio-Summary-Endpoint sollte nur gecachte MA/MRS-Daten lesen, nie selbst berechnen. Alternativ: MA/MRS-Daten lazy aus dem Summary excluden und ueber einen separaten Endpoint nachladen.

### H-2: `fetch_all_indicators()` macht 7+ sequenzielle HTTP-Calls

**Datei:** `backend/services/macro_indicators_service.py`, Zeilen 247-436

**Problem:** `fetch_all_indicators()` ruft sequenziell auf:
1. `_scrape_shiller_pe()` — httpx.get zu multpl.com + BeautifulSoup Parse
2. `_fred_get("NCBEILQ027S")` — httpx.get zu FRED API
3. `_fred_get("GDP")` — httpx.get zu FRED API
4. `_fred_get_series("UNRATE", 6)` — httpx.get zu FRED API
5. `_fred_get("T10Y2Y")` — httpx.get zu FRED API
6. `get_vix()` — Cache oder yf_download
7. `_fred_get("BAMLH0A0HYM2")` — httpx.get zu FRED API

Jeder Call hat ein 10s Timeout. Total: bis zu 70 Sekunden bei Timeouts.

**Impact:** Betroffen sind `/api/market/climate` und `/api/market/macro-indicators`. Bei Cache-Miss (alle 15 Minuten) extrem langsam.

**Loesung:** Alle FRED-Calls parallel ausfuehren (`concurrent.futures.ThreadPoolExecutor` oder die Calls in einen Thread mit internem `asyncio.gather` verschieben). Die Funktion ist sync, daher waere ein Thread-Pool am einfachsten:
```python
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {
        "shiller": pool.submit(_scrape_shiller_pe),
        "mktcap": pool.submit(_fred_get, "NCBEILQ027S"),
        "gdp": pool.submit(_fred_get, "GDP"),
        ...
    }
```

### H-3: `fetch_extra_indicators()` macht 6 sequenzielle Preis-Lookups

**Datei:** `backend/services/macro_indicators_service.py`, Zeilen 440-560

**Problem:** `fetch_extra_indicators()` ruft sequenziell auf:
- `get_stock_price("CL=F")` — WTI Oil
- `get_stock_price("BZ=F")` — Brent
- `_fred_get_with_date("DFF")` — Fed Rate
- `_fred_find_last_change_date("DFF")` — nochmal FRED fuer Last Change
- `get_stock_price("USDCHF=X")` — FX Rate

Jeder `get_stock_price()` kann bei Cache-Miss einen `yf.Ticker().fast_info`-Call ausloesen (1-3s).

**Impact:** Addiert sich zum Market-Climate-Request (wird in K-1 beschrieben).

**Loesung:** Parallel ausfuehren (analog H-2). Zusaetzlich: `_fred_find_last_change_date()` sollte das Ergebnis cachen (wird bei jedem Call neu abgefragt).

### H-4: `total_return` Endpoint ruft `get_portfolio_summary()` erneut auf

**Datei:** `backend/services/total_return_service.py`, Zeile 21

**Problem:** `get_total_return()` ruft `get_portfolio_summary(db, user_id)` auf, was die gesamte Portfolio-Berechnung inkl. MA/MRS nochmal durchfuehrt (falls der 30s Cache abgelaufen ist). Der Portfolio-Summary-Cache ist nur 30s gueltig.

**Impact:** Wenn der User die Portfolio-Seite laedt, werden `/portfolio/summary`, `/portfolio/total-return`, `/portfolio/daily-change` und `/portfolio/monthly-returns` parallel aufgerufen. `total-return` laedt intern nochmal `summary` — potenziell doppelte Berechnung.

**Loesung:** `get_total_return()` sollte nur die aggregierten Werte aus der Summary verwenden (unrealized P&L) und nicht die gesamte Summary neu berechnen. Alternativ: Den Summary-Cache TTL auf 60s erhoehen.

### H-5: `get_stock_price()` faellt synchron auf `yf.Ticker().fast_info` zurueck

**Datei:** `backend/services/price_service.py`, Zeilen 29-39

**Problem:** Wenn weder Redis-Cache noch DB-Cache einen Preis haben, wird `yf.Ticker(ticker).fast_info` aufgerufen — ein synchroner HTTP-Call. Diese Funktion wird u.a. von `_compute_market_value()` in `portfolio_service.py` aufgerufen (im Event-Loop-Kontext).

Das ist ein versteckter Blocking-Call, der den gesamten API-Worker blockiert.

**Impact:** Bei neuem Ticker oder nach DB-Bereinigung blockiert jeder Portfolio-Request fuer 1-3s pro Ticker ohne Cache.

**Loesung:** `get_stock_price()` sollte nie live-Daten fetchen, wenn es aus dem Event-Loop-Kontext aufgerufen wird. Nur Cache + DB-Fallback. Worker kuemmert sich um Live-Preise.

### H-6: StockDetail-Seite feuert 5+ parallele API-Requests

**Datei:** `frontend/src/pages/StockDetail.jsx`

**Problem:** Die StockDetail-Seite laedt bei jedem Seitenaufruf:
1. `/portfolio/summary` (via `useApi`, fuer "Meine Position")
2. `/portfolio/summary` (nochmal, via `EtfSectorPanelWrapper`)
3. `/analysis/score/{ticker}` (via `MrsPanel`)
4. `/analysis/breakouts/{ticker}` (via `BreakoutEvents`)
5. `/analysis/levels/{ticker}` (via `LevelsPanel`)
6. `/analysis/reversal/{ticker}` (via `ReversalPanel`)
7. `/analysis/watchlist` (via `useApi`, fuer Watchlist-Status)

Requests 3-6 loesen jeweils separate yfinance-Downloads im Backend aus. Das ist besonders problematisch, weil `/analysis/score/{ticker}` bereits intern MRS, Breakout und Levels berechnet.

**Impact:** Die StockDetail-Seite laedt 3-10 Sekunden wegen redundanter Backend-Calls.

**Loesung:**
- `/analysis/score/{ticker}` liefert bereits MRS, Breakout-Daten und Levels. Die separaten Requests fuer MRS, Breakouts und Levels sind weitgehend redundant.
- `/portfolio/summary` wird 2× angefragt — sollte ueber `usePortfolioData()` aus dem DataContext geteilt werden (statt `useApi`).

### H-7: Portfolio-Seite laedt 5 API-Endpoints parallel beim Seitenaufruf

**Datei:** `frontend/src/pages/Portfolio.jsx`, Zeilen 31-35

```javascript
const { data: summary } = useApi('/portfolio/summary')
const { data: reData } = useApi('/properties')
const { data: dailyChange } = useApi('/portfolio/daily-change')
const { data: monthlyReturns } = useApi('/portfolio/monthly-returns')
const { data: totalReturn } = useApi('/portfolio/total-return')
```

**Problem:** Alle 5 Requests feuern gleichzeitig. Mehrere davon sind rechenintensiv:
- `monthly-returns`: Laedt alle Snapshots + Transaktionen, berechnet Modified Dietz + XIRR
- `total-return`: Ruft intern `get_portfolio_summary()` auf (s. H-4)
- `daily-change`: 3 DB-Queries

**Impact:** Der Backend-Server wird mit 5 gleichzeitigen schweren Requests pro User belastet. Bei mehreren gleichzeitigen Usern kann das den Connection-Pool ueberlasten.

**Loesung:** Waterfall-Loading: `summary` zuerst, dann die abhaengigen Endpoints erst nach erfolgreichem Summary-Load. `total-return` und `monthly-returns` lazy laden (erst wenn User den Tab sieht). Oder: Einen kombinierten Endpoint `/portfolio/overview` anbieten.

### H-8: `history_service.get_portfolio_history()` iteriert Tag fuer Tag

**Datei:** `backend/services/history_service.py`, Zeilen 247-285

**Problem:** Die History-Berechnung iteriert ueber jeden einzelnen Tag im Zeitraum (typ. 365 Tage) und ruft fuer jeden Tag `calc_portfolio_value()` auf. Innerhalb von `calc_portfolio_value()` wird fuer jede Position der Preis nachgeschlagen — insgesamt `365 × N_Positionen` Lookups.

Die Lookups selbst sind O(1) (Dict-Lookup), aber der Overhead durch die Python-Schleife ist bei 20 Positionen × 365 Tagen = 7'300 Iterationen merkbar (0.5-2s).

**Impact:** `/api/portfolio/history` ist bei Cache-Miss langsam (TTL 15min). Beim ersten Aufruf laedt zusaetzlich `yf_download` fuer alle Tickers.

**Loesung:** Vektorisierte Berechnung mit pandas statt Tag-fuer-Tag-Schleife. Die Daten liegen bereits als DataFrames vor — Matrix-Multiplikation waere 10-50× schneller.

### H-9: Precious-Metals-Endpoint macht 3 sequenzielle blocking Calls

**Datei:** `backend/api/market.py`, Zeilen 182-185

```python
gold_spot = await asyncio.to_thread(get_gold_price_chf)
gold_comex = await asyncio.to_thread(get_stock_price, "GC=F")
silver_comex = await asyncio.to_thread(get_stock_price, "SI=F")
```

**Problem:** Drei `asyncio.to_thread()`-Calls werden nacheinander ausgefuehrt statt parallel.

**Impact:** Bei Cache-Miss dauert der Endpoint 3-9 Sekunden statt 1-3 Sekunden.

**Loesung:** `asyncio.gather()` verwenden.

---

## Mittel (10)

### M-1: In-Memory Cache auf 1000 Eintraege limitiert

**Datei:** `backend/services/cache.py`, Zeile 49

**Problem:** `_MAX_SIZE = 1000` fuer den In-Memory-LRU-Cache. Bei einem Portfolio mit 30 Positionen werden pro Ticker mehrere Keys angelegt: `price:X`, `close:X:1y`, `close:X:2y`, `ma:X:...`, `mrs:X`, `52w:X`, `scorer_data:X`. Das sind ~7 Keys pro Ticker. Bei 30 Positionen + 10 Watchlist + 11 Sektor-ETFs + 7 Market-Tickers = ~58 Tickers × 7 = ~406 Keys. Dazu kommen Assessments, FX-Rates, etc.

Bei 1000 Keys wird der LRU-Eviction schnell aktiv und verdraengt wichtige Eintraege (z.B. `close:^GSPC:2y` — eine grosse pandas Series).

**Impact:** Haeufige Cache-Misses fuehren zu wiederholten yfinance-Downloads.

**Loesung:** `_MAX_SIZE` auf 2000-3000 erhoehen. pandas-Series-Daten sind nur im Memory (nicht Redis) und benoetigen mehr Platz.

### M-2: `prefetch_close_series()` laedt 1y UND 2y separat

**Datei:** `backend/services/utils.py`, Zeilen 109-146

**Problem:** `prefetch_close_series()` macht zwei separate `yf_download()`-Calls — einmal fuer 1y-Daten und einmal fuer 2y-Daten. Die 1y-Daten sind eine Teilmenge der 2y-Daten.

**Impact:** Doppelter Download-Overhead bei Cold-Cache. Besonders relevant fuer den Portfolio-Summary-Endpoint (H-1).

**Loesung:** Nur 2y-Daten herunterladen und daraus die 1y-Serie ableiten (letzte 252 Handelstage).

### M-3: `calculate_xirr_for_period()` laedt ALLE Snapshots und Transaktionen

**Datei:** `backend/services/performance_history_service.py`, Zeilen 92-112

**Problem:** Fuer jede XIRR-Berechnung werden ALLE Snapshots und ALLE Transaktionen aus der DB geladen (`select(PortfolioSnapshot).order_by(...)` ohne Date-Filter). Bei mehreren Jahren Daten koennen das tausende Rows sein.

In `get_monthly_returns()` (Zeile 219-233) wird dies korrekt optimiert — die Daten werden einmal geladen und fuer alle Jahre wiederverwendet. Aber `calculate_xirr_for_period()` wird auch von `get_total_return()` aufgerufen und laedt dort alles nochmal.

**Impact:** Redundante DB-Loads bei `/portfolio/total-return`.

**Loesung:** `get_total_return()` sollte die bereits in `get_monthly_returns()` vorberechneten XIRR-Werte nutzen, oder die Snapshot/Transaction-Daten einmal laden und uebergeben.

### M-4: `_fred_get_api_key()` macht bei jedem Aufruf einen DB-Query

**Datei:** `backend/services/macro_indicators_service.py`, Zeilen 36-54

**Problem:** Jeder FRED-API-Call ruft `_get_fred_api_key()` auf, das eine synchrone DB-Session oeffnet und den Key aus `UserSettings` laedt. Bei 5+ FRED-Calls pro `fetch_all_indicators()` sind das 5+ unnoetige DB-Queries.

**Impact:** 5+ zusaetzliche DB-Connections pro Macro-Indicator-Refresh.

**Loesung:** Den API-Key einmal pro Funktionsaufruf laden und als Parameter durchreichen. Oder: Im Cache ablegen (TTL 5 min).

### M-5: `get_cached_price_sync()` oeffnet jedes Mal eine neue Sync-Session

**Datei:** `backend/services/cache_service.py`, Zeilen 489-513

**Problem:** `get_cached_price_sync()` wird von `get_stock_price()`, `get_fx_rates_batch()` und `get_fallback_fx()` aufgerufen — oft mehrfach pro Request. Jeder Aufruf oeffnet eine neue `SyncSessionLocal()`-Session, fuehrt die Query aus und schliesst sie. Das verbraucht Connections aus dem synchronen Pool (max 15).

**Impact:** Bei einem Portfolio-Request mit 10 Tickers ohne Redis-Cache werden 10+ Sync-Sessions geoeffnet. Bei gleichzeitigen Requests kann der Sync-Pool erschoepft werden.

**Loesung:** Session-Reuse oder Connection-less Raw-SQL fuer einfache Lookups. Oder: DB-Fallback komplett vermeiden und nur Redis + Memory verwenden.

### M-6: Portfolio-Summary decrypted bank_name/IBAN fuer jede Position

**Datei:** `backend/api/portfolio.py`, Zeilen 36-56

**Problem:** Nach dem `get_portfolio_summary()`-Aufruf wird fuer jede Position ein zusaetzlicher DB-Query gemacht (`select(Position.id, Position.bank_name, Position.iban, ...)`), gefolgt von Fernet-Decryption fuer `bank_name` und `iban`. Fernet-Decryption ist CPU-intensiv.

**Impact:** Bei 30 Positionen sind das 30 Decrypt-Operationen pro Summary-Request. In Kombination mit dem 30s Cache-TTL: alle 30 Sekunden.

**Loesung:** Bank/IBAN-Daten nicht im Summary mitliefern, sondern nur im Position-Detail-View. Die meisten Frontends brauchen diese Daten nicht in der Uebersicht.

### M-7: Watchlist-Endpoint laedt alle PriceCache-Rows fuer alle Tickers

**Datei:** `backend/api/analysis.py`, Zeilen 181-205

**Problem:** Die Watchlist-Query laedt alle `PriceCache`-Rows fuer alle Watchlist-Tickers, sortiert nach Datum, und filtert dann in Python auf die letzten 2 Rows pro Ticker. Bei 50 Watchlist-Tickers × 400 Tage = 20'000 Rows.

**Impact:** Ueberfluessige DB-IO und Python-Verarbeitung. Bei grosser Watchlist merkbar.

**Loesung:** Window-Funktion oder Subquery verwenden:
```sql
SELECT DISTINCT ON (ticker) ticker, close, currency, date
FROM price_cache WHERE ticker IN (...) ORDER BY ticker, date DESC
```
Oder: Nur die neuesten 2 Rows pro Ticker via `LATERAL JOIN`.

### M-8: `daily-change` Endpoint macht N+1 FX-Lookups

**Datei:** `backend/api/performance.py`, Zeilen 122-136

**Problem:** Die `get_fx(currency)`-Funktion wird fuer jede Position einzeln aufgerufen und macht jeweils eine DB-Query (`select PriceCache.close where ticker = "XXXCHF=X"`). Bei 20 Positionen in 3 verschiedenen Waehrungen: bis zu 20 DB-Calls (obwohl viele redundant sind).

Es gibt zwar ein `fx_cache`-Dict, das Duplikate vermeidet, aber es wird pro Waehrung trotzdem eine DB-Query gemacht. Die `get_fx_rates_batch()`-Funktion aus utils.py waere besser.

**Impact:** Mehrere unnoetige DB-Roundtrips.

**Loesung:** `get_fx_rates_batch()` verwenden (wie in anderen Endpoints) und alle FX-Rates in einem Call laden.

### M-9: `sector_holding_scores` berechnet Scores einzeln in Schleife

**Datei:** `backend/api/market.py`, Zeilen 120-158

**Problem:** Fuer jeden der 30 Holdings eines Sektor-ETFs wird `assess_ticker()` einzeln aufgerufen. Jeder Aufruf loest intern `score_stock()` aus, was einen 2y-yfinance-Download macht. Da `_download_and_analyze()` jeden Ticker einzeln herunlerlaedt (plus ^GSPC als Benchmark — 31 Downloads statt 1 Batch-Download), ergibt das potenziell 31 HTTP-Calls.

**Impact:** Erste Aufruf eines Sektor-Scoring kann 2-5 Minuten dauern.

**Loesung:** Batch-Download aller 30 Tickers + ^GSPC in einem einzigen `yf_download()`-Call, dann die Analyse fuer jeden Ticker aus dem DataFrame ableiten.

### M-10: `crypto_metrics` Endpoint macht 3 sequenzielle API-Calls

**Datei:** `backend/api/market.py`, Zeilen 206-259

**Problem:** Die Crypto-Metrics werden sequenziell geladen:
1. CoinGecko /global
2. alternative.me Fear & Greed
3. `get_stock_price("DX-Y.NYB")` via `asyncio.to_thread`
4. CoinGecko /coins/bitcoin

Diese Calls laufen nacheinander statt parallel.

**Impact:** 3-10 Sekunden Ladezeit bei Cache-Miss.

**Loesung:** `asyncio.gather()` fuer alle unabhaengigen Calls.

---

## Niedrig (4)

### N-1: `DataContext` pollt alle 60s, `STALE_MS` aber auch 60s

**Datei:** `frontend/src/contexts/DataContext.jsx`, Zeilen 7, 73-79

**Problem:** `setInterval` feuert alle 60'000ms. In `useCachedFetch` gilt `STALE_MS = 60_000`. Da der Timer und der Stale-Check exakt gleich sind, kann es bei leichtem Timing-Drift dazu kommen, dass der Fetch uebersprungen wird (Daten gelten noch als "fresh"). Oder umgekehrt: Daten werden als "stale" markiert, obwohl der naechste Fetch unmittelbar bevorsteht.

**Impact:** Gering — leichte Inkonsistenz in der Refresh-Frequenz.

**Loesung:** `STALE_MS` auf 55'000 setzen oder den Interval-Fetch immer mit `force=true` aufrufen.

### N-2: nginx gzip-Kompression fehlt fuer SVG und Webfonts

**Datei:** `frontend/nginx.conf`, Zeile 12

**Problem:** `gzip_types` enthaelt keine SVG (`image/svg+xml`) und keine Webfonts (`font/woff2`, `application/font-woff`). SVG-Icons und Webfonts koennen signifikant komprimiert werden.

**Impact:** Leicht erhoehte Uebertragungsgroesse fuer Assets.

**Loesung:** `gzip_types` erweitern:
```nginx
gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript image/svg+xml application/font-woff font/woff2;
```

### N-3: Kein HTTP/2 in nginx konfiguriert

**Datei:** `frontend/nginx.conf`, Zeile 2

**Problem:** nginx lauscht auf Port 5173 ohne `http2`-Direktive. HTTP/2 ermoeglicht Multiplexing — mehrere API-Calls ueber eine einzige TCP-Verbindung statt separat.

**Impact:** Bei den 5+ gleichzeitigen API-Calls der Portfolio-Seite wuerde HTTP/2 die Latenz leicht reduzieren. Erfordert allerdings TLS (oder `http2 on` in neueren nginx-Versionen).

**Loesung:** Wenn hinter einem Reverse-Proxy mit TLS: `listen 5173 http2;`

### N-4: `snapshot_service.regenerate_snapshots()` ohne Fortschritts-Feedback

**Datei:** `backend/services/snapshot_service.py`, Zeilen 185-403

**Problem:** Die Regenerierung aller Snapshots iteriert Tag fuer Tag vom ersten Transaktionsdatum bis heute. Bei 3 Jahren Daten sind das ~780 Tage mit jeweils N Positionen. Die Funktion gibt kein Fortschritts-Feedback — der HTTP-Request haengt bis zum Abschluss (kann Minuten dauern).

**Impact:** User erhaelt keine Rueckmeldung und kann den Tab schliessen, was die Berechnung abbricht.

**Loesung:** Regenerierung als Background-Task im Worker ausfuehren (wie Daily Refresh) statt synchron im API-Request. Status-Polling ueber separaten Endpoint.

---

## Architektur-Empfehlungen

### A-1: Worker soll alle rechenintensiven Daten vorberechnen

Aktuell berechnet der Worker nur Preise (alle 60s). Folgende Daten sollten ebenfalls vom Worker vorberechnet und im Cache abgelegt werden:
- **MA-Status** fuer alle aktiven Positionen (nach jedem Price-Refresh)
- **MRS** fuer alle aktiven Positionen
- **Macro-Indikatoren** (nur 1× pro Stunde statt bei jedem Request)
- **Sektor-Rotation** (nur 1× pro Stunde)
- **Setup-Scores** fuer Watchlist-Tickers (1× taeglich)

So werden API-Requests zu reinen Cache-Reads — schnell und konsistent.

### A-2: Portfolio-Summary in zwei Stufen teilen

Der aktuelle Portfolio-Summary-Endpoint liefert alles auf einmal: Positionen, Allokationen, MA-Status, MRS, Stop-Loss, Earnings. Das erzwingt eine schwere Berechnung bei jedem Request.

Besser: Aufteilen in:
1. `/portfolio/summary` — Positionen, Werte, P&L (rein aus Cache/DB, keine Berechnungen)
2. `/portfolio/technicals` — MA-Status, MRS (vom Worker vorberechnet)

### A-3: Response-Caching auf nginx-Ebene evaluieren

Fuer Endpoints wie `/api/market/climate` und `/api/market/sectors`, deren Daten sich nur alle 15 Minuten aendern, koennte nginx-Level-Caching (`proxy_cache`) die Backend-Last deutlich reduzieren — besonders bei mehreren gleichzeitigen Benutzern.

---

## Zusammenfassungs-Tabelle

| ID | Severity | Komponente | Geschaetzter Impact | Aufwand |
|----|----------|------------|---------------------|---------|
| K-1 | Kritisch | market.py | -20s Ladezeit Dashboard | Klein (5 Zeilen) |
| K-2 | Kritisch | macro_gate_service.py | -5s redundante Berechnung | Mittel |
| K-3 | Kritisch | stock_scorer.py | -3s pro Score-Request | Mittel |
| K-4 | Kritisch | price_service.py | Event-Loop Blocking | Klein |
| H-1 | Hoch | portfolio_service.py | -10-30s Cold-Cache | Gross |
| H-2 | Hoch | macro_indicators_service.py | -30s Cold-Cache | Mittel |
| H-3 | Hoch | macro_indicators_service.py | -10s Cold-Cache | Mittel |
| H-4 | Hoch | total_return_service.py | Doppelte Summary-Berechnung | Klein |
| H-5 | Hoch | price_service.py | Event-Loop Blocking | Klein |
| H-6 | Hoch | StockDetail.jsx | 5+ redundante Requests | Mittel |
| H-7 | Hoch | Portfolio.jsx | Backend-Ueberlastung | Mittel |
| H-8 | Hoch | history_service.py | -1s History-Berechnung | Gross |
| H-9 | Hoch | market.py | -6s Precious-Metals | Klein |
| M-1 | Mittel | cache.py | Cache-Thrashing | Klein |
| M-2 | Mittel | utils.py | Doppelter yfinance-Download | Mittel |
| M-3 | Mittel | performance_history_service.py | Redundante DB-Loads | Mittel |
| M-4 | Mittel | macro_indicators_service.py | 5+ unnoetige DB-Queries | Klein |
| M-5 | Mittel | cache_service.py | Sync-Pool-Erschoepfung | Mittel |
| M-6 | Mittel | portfolio.py | CPU-Last durch Decryption | Klein |
| M-7 | Mittel | analysis.py | Ueberfluessige DB-IO | Mittel |
| M-8 | Mittel | performance.py | N+1 FX-Queries | Klein |
| M-9 | Mittel | market.py | 2-5 Min Sektor-Scoring | Gross |
| M-10 | Mittel | market.py | -7s Crypto-Metrics | Klein |
| N-1 | Niedrig | DataContext.jsx | Timing-Inkonsistenz | Klein |
| N-2 | Niedrig | nginx.conf | Leicht groessere Assets | Klein |
| N-3 | Niedrig | nginx.conf | Keine HTTP/2-Vorteile | Klein |
| N-4 | Niedrig | snapshot_service.py | Kein Fortschritt | Mittel |

---

## Priorisierte Quick-Wins (sofort umsetzbar)

1. **K-1**: `asyncio.gather()` in `/market/climate` — 5 Zeilen aendern, -20s Ladezeit
2. **H-9**: `asyncio.gather()` in `/market/precious-metals` — 3 Zeilen aendern
3. **M-10**: `asyncio.gather()` in `/market/crypto-metrics` — wenige Zeilen
4. **K-4 + H-5**: Price-Service nur aus Cache lesen, nie live-fetchen im Event-Loop
5. **M-1**: `_MAX_SIZE` von 1000 auf 2500 erhoehen — 1 Zeile
6. **M-8**: `get_fx_rates_batch()` im daily-change Endpoint verwenden
