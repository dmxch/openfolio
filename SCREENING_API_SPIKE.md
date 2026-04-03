# Screening API Spike — Ergebnisse (2026-04-03)

## Zusammenfassung

10 Datenquellen getestet, 9 funktionieren. FMP ist ausgefallen (Legacy-API abgeschaltet). Alle funktionierenden Quellen sind gratis und brauchen keinen API-Key.

## Getestete Quellen

### 1. FINRA Short Volume — FUNKTIONIERT

- **URL:** `https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`
- **Auth:** Keine (User-Agent Header nötig)
- **Format:** Pipe-delimited: `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`
- **Umfang:** ~11'400 Symbole pro Tag, ~487 KB pro Datei
- **14-Tage-Download:** ~10 Sekunden für 14 Dateien
- **Wochenenden/Feiertage:** Keine Dateien (nur Handelstage)

**Datenqualität:**
- Short-Ratio = ShortVolume / TotalVolume
- ~2'300 Aktien mit Short-Ratio > 50% (bei Volume > 100k) — zu viele für absoluten Schwellwert
- Empfehlung: Trend-basiertes Signal (14-Tage-Anstieg), nicht absoluter Wert
- ETFs/Fonds filtern (Market-Maker-Shorts sind kein echtes Signal)

**Trend-Beispiel (16.03 → 02.04.2026):**
AAPL: 25.1% → 54.8% (+118%), NVDA: 42.1% → 50.8% (+21%), GME: 59.6% → 53.2% (-11%)

### 2. OpenInsider Cluster Buys — FUNKTIONIERT

- **URL:** `http://openinsider.com/latest-cluster-buys`
- **Auth:** Keine
- **Format:** HTML-Tabelle, 17 Spalten, Standard-HTMLParser
- **Umfang:** ~100 Cluster-Buy-Einträge (letzte ~60 Tage)
- **Download + Parse:** ~2 Sekunden

**Spalten:** Filing Date | Trade Date | Ticker | Company Name | Industry | Ins (Anzahl) | Trade Type | Price | Qty | Owned | ΔOwn | Value | 1d | 1w | 1m | 6m

**Beispiel:** ZBIO (4 Insider, $9.3M), VTS (2 Insider, $372k), WTW (2 Insider, $1.0M)

### 3. OpenInsider Grosse Käufe — FUNKTIONIERT

- **URL:** `http://openinsider.com/screener?...&t=1&min=500&minprice=5&maxown=25`
- **Auth:** Keine
- **Format:** Gleich wie Cluster Buys
- **Umfang:** ~73 Ticker (30 Tage, >$500k)
- **Download + Parse:** ~2 Sekunden

### 4. SEC EDGAR 8-K Buybacks — FUNKTIONIERT

- **URL:** `https://efts.sec.gov/LATEST/search-index?q="share repurchase" OR "stock buyback"&forms=8-K&...`
- **Auth:** Keine (User-Agent mit Email nötig)
- **Format:** JSON (Elasticsearch)
- **Umfang:** ~454 Filings in 30 Tagen
- **Speed:** ~3 Sekunden

Ticker direkt in Filing-Metadaten: `display_names` enthält Company + Ticker (z.B. "PINTEREST, INC. (PINS)")

**Beispiel:** Salesforce (CRM), Broadcom (AVGO), Pinterest (PINS), ADT (ADT), Kroger (KR)

### 5. Capitol Trades (Congressional Trading) — FUNKTIONIERT

- **URL:** `https://www.capitoltrades.com/trades?per_page=96&txDate=90d`
- **Auth:** Keine (RSC-Header: `RSC: 1` nötig)
- **Format:** Next.js React Server Components Streaming
- **Umfang:** ~36 Trades (90 Tage), 25 unique Tickers
- **Speed:** ~5 Sekunden (3 Pages)

**Parsing:** `txType` (buy/sell), `issuerTicker` (z.B. "AAPL:US"), `issuerName`, Politiker-IDs. Buy: 17, Sell: 19 in 90 Tagen.

### 6. Dataroma Superinvestor Real-Time — FUNKTIONIERT

- **URL:** `https://www.dataroma.com/m/rt.php`
- **Auth:** Keine (Chrome-ähnlicher User-Agent nötig + Referer)
- **Format:** HTML-Tabelle
- **Umfang:** ~25 aktuelle Transaktionen
- **Speed:** ~2 Sekunden

**Beispiel-Daten:**
- Carl Icahn: CVR Energy ($5.9M), Centuri Holdings ($75M), Monro Inc ($9.7M)
- Abrams Capital: ContextLogic ($12.3M)

### 7. Dataroma Grand Portfolio — FUNKTIONIERT

- **URL:** `https://www.dataroma.com/m/g/portfolio_b.php`
- **Auth:** Keine (Chrome-ähnlicher User-Agent nötig + Referer)
- **Format:** HTML-Tabelle
- **Umfang:** 100 Top-Holdings, 82 Superinvestoren
- **Speed:** ~2 Sekunden

**Top Holdings:** AMZN (11 Investoren), META (10), RKT (6), LYV (6), KEX (1 aber 0.169 Portfolio-Gewicht)

### 8. SEC EDGAR 13D/13G (Aktivisten-Tracking) — FUNKTIONIERT

- **URL:** `https://data.sec.gov/submissions/CIK{cik}.json`
- **Auth:** Keine (User-Agent mit Email nötig)
- **Format:** JSON (Submissions-Metadaten)
- **Speed:** ~3s × 15 Investoren = ~45s

**Getestete Aktivisten (12/16 aktiv in 2026):**
Carl Icahn (7 Filings), Berkshire Hathaway (2621), Trian (40), ValueAct (22), Baupost (6), Elliott (2), Greenlight (2), u.a.

13D XML enthält Zielunternehmen: `issuerName`, `issuerCIK`, `CUSIP`.

### 9. SEC Fails-to-Deliver — FUNKTIONIERT

- **URL:** `https://www.sec.gov/files/data/fails-deliver-data/cnsfails{YYYYMM}{a|b}.zip`
- **Auth:** Keine
- **Format:** ZIP → Pipe-delimited Text
- **Umfang:** 56'000 Zeilen pro Halbmonat (~1.2 MB ZIP)
- **Speed:** ~3 Sekunden

**Spalten:** `SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE`

**Top FTDs (März 2026):** IDEF (65M shares), MSTX (44M), BMNU (43M), ELPW (37M)

### 10. FMP (Financial Modeling Prep) — AUSGEFALLEN

- **Status:** Legacy-API seit August 2025 abgeschaltet
- **Fehlermeldung:** "Legacy Endpoint: Due to Legacy endpoints being no longer supported"
- **Betroffen:** Alle v3/v4 Endpoints
- **Key:** `FMP_API_KEY=fAoRXSVNl93tfRK6aiq2HoOQtW3uo6DC` — wertlos

**Hinweis:** FMP wird auch in `backend/services/stock_service.py` verwendet — vermutlich dort ebenfalls defekt.

## Quellen die NICHT funktionieren

| Quelle | Problem |
|--------|---------|
| FINRA ATS Dark Pool (per-Security) | API liefert nur Daten von 2023, nicht aktuell |
| CBOE Put/Call Ratio CSV | CDN blockiert (403 Forbidden) |
| House/Senate Stock Watcher S3 | Endpoints geben 403 zurück |
| Dataroma Activity Page | Gibt nur 2.6 KB zurück (vermutlich Bot-Protection auf /activity.php) |
| EDGAR EFTS für "SC 13D" Form-Typ | Liefert 0 Ergebnisse (Form-Typ nicht im Index) |

## Performance-Zusammenfassung

| Phase | Quellen | Scan-Zeit | Score-Range |
|-------|---------|-----------|-------------|
| Phase 1 | 4 Bulk-Quellen | ~20s | 0–7 |
| Phase 2 | +3 Quellen + Aktivisten | ~40s | 0–10 |
| Phase 3 | +FTD + Unusual Volume | ~70s | 0–10 + Bonus |
