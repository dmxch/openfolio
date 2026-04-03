# Screening API Spike — Ergebnisse (2026-04-03)

## Zusammenfassung

3 von 4 geplanten Datenquellen funktionieren einwandfrei. FMP ist ausgefallen (Legacy-API abgeschaltet), wird durch SEC EDGAR + OpenInsider ersetzt.

## 1. FINRA Short Volume — FUNKTIONIERT

- **URL:** `https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`
- **Auth:** Keine (User-Agent Header nötig)
- **Format:** Pipe-delimited CSV: `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`
- **Umfang:** ~11'400 Symbole pro Tag, ~487 KB pro Datei
- **14-Tage-Download:** ~10 Sekunden für 14 Dateien
- **Wochenenden/Feiertage:** Keine Dateien (nur Handelstage), kein 404 sondern einfach nicht vorhanden

### Datenqualität

- Short-Ratio = ShortVolume / TotalVolume
- ~2'300 Aktien mit Short-Ratio > 50% (bei Volume > 100k) — **zu viele für ein Signal**
- Viele davon sind ETFs/Fonds mit Market-Maker-Shorts (keine echten Short-Positionen)
- **Empfehlung:** Filter auf Aktien (keine ETFs), und Trend-basiertes Signal (Anstieg über 14 Tage) statt absoluter Schwellwert

### Trend-Beispiel (14 Tage, 16.03 → 02.04.2026)

| Ticker | Start | Ende | Veränderung |
|--------|-------|------|-------------|
| AAPL | 25.1% | 54.8% | +118% |
| NVDA | 42.1% | 50.8% | +21% |
| TSLA | 43.4% | 47.5% | +9% |
| GME | 59.6% | 53.2% | -11% |
| AMC | 24.7% | 37.2% | +51% |

**Fazit:** Solide Bulk-Quelle, schnell, zuverlässig. Für Phase 1 geeignet.

## 2. OpenInsider Cluster Buys — FUNKTIONIERT

- **URL:** `http://openinsider.com/latest-cluster-buys`
- **Auth:** Keine
- **Format:** HTML-Tabelle, 17 Spalten
- **Umfang:** ~100 Cluster-Buy-Einträge (letzte ~60 Tage)
- **Download + Parse:** ~2 Sekunden
- **Scraping-Methode:** Standard HTMLParser, kein JavaScript nötig

### Spalten

`Filing Date | Trade Date | Ticker | Company Name | Industry | Ins (Anzahl Insider) | Trade Type | Price | Qty | Owned | ΔOwn | Value | 1d | 1w | 1m | 6m`

### Datenqualität

- Vorfiltriert: Nur Cluster-Buys (≥2 Insider kaufen denselben Ticker)
- Enthält Ticker, Industry, Anzahl Insider, Gesamtwert — alles was wir brauchen
- Performance-Spalten (1d, 1w, 1m, 6m) sind teilweise leer für neuere Einträge
- Mix aus Small-Caps und Large-Caps

### Beispiel-Daten (02.04.2026)

| Ticker | Company | Insider | Value |
|--------|---------|---------|-------|
| ZBIO | Zenas Biopharma | 4 | $9.3M |
| VTS | Vitesse Energy | 2 | $372k |
| WTW | Willis Towers Watson | 2 | $1.0M |
| PRU | Prudential Financial | 3 | $168k |

**Fazit:** Beste Quelle für Insider-Cluster-Detection. Vorfiltriert, gratis, schnell. Für Phase 1 als primäre Insider-Quelle.

## 3. FMP (Financial Modeling Prep) — AUSGEFALLEN

- **Status:** Legacy-API seit August 2025 abgeschaltet
- **Fehlermeldung:** "Legacy Endpoint: Due to Legacy endpoints being no longer supported"
- **Betroffen:** Alle v3/v4 Endpoints (Profile, Quote, Insider Trading, Senate Disclosure)
- **Vorhandener Key:** `FMP_API_KEY=fAoRXSVNl93tfRK6aiq2HoOQtW3uo6DC` — funktioniert nicht mehr

### Auswirkung

- FMP Insider RSS (Phase 1) → **Ersetzt durch OpenInsider + SEC EDGAR**
- FMP Senate Disclosure (Phase 2) → **Alternative nötig** (Finnhub Congressional Trading oder direkter Senate.gov Scrape)

### Hinweis für bestehendes OpenFolio

FMP wird in `backend/services/stock_service.py` verwendet. Diese bestehende Integration ist vermutlich ebenfalls defekt.

## 4. SEC EDGAR EFTS (Ersatz für FMP) — FUNKTIONIERT

- **URL:** `https://efts.sec.gov/LATEST/search-index?forms=4&dateRange=custom&startdt={}&enddt={}`
- **Auth:** Keine (User-Agent mit Email nötig)
- **Rate Limit:** 10 req/sec
- **Umfang:** 3'170+ Form-4-Filings in 2 Tagen (01-03.04.2026)
- **Format:** JSON (Elasticsearch-Response)

### XML-Parsing einzelner Filings

Jedes Filing enthält als XML:
- `issuerTradingSymbol` (Ticker)
- `issuerName`, `rptOwnerName`, `officerTitle`
- `transactionCode` (P=Purchase, S=Sale, A=Award, M=Exercise)
- `transactionShares`, `transactionPricePerShare`

### Performance-Problem

Bei ~1'500 Filings pro Tag und 10 req/sec dauert das Parsing ~2.5 Minuten pro Tag. Für 60 Tage History = ~2.5 Stunden. **Nicht praktikabel für On-Demand-Scan.**

### Empfehlung

SEC EDGAR als **Ergänzung in Phase 2** (Hintergrund-Job), nicht als primäre Quelle. OpenInsider liefert die Cluster-Buys bereits vorfiltriert und sofort.

## Revidierte Quellen-Strategie

### Phase 1 (MVP) — Scan < 30 Sekunden

| Quelle | Methode | Zeit | Signal |
|--------|---------|------|--------|
| FINRA Short Volume | 14 CSV-Downloads | ~10s | Short-Ratio-Trend |
| OpenInsider Cluster Buys | 1 HTML-Scrape | ~2s | Insider-Cluster |

**Total: ~12 Sekunden.** 2 Quellen, 2 Signale, 0 API-Keys nötig.

### Phase 2

| Quelle | Methode | Signal |
|--------|---------|--------|
| SEC EDGAR Form 4 | EFTS API + XML Parsing (Batch-Job) | Breite Insider-Käufe |
| Senate.gov / Finnhub | Scrape oder API | Congressional Trading |

### Gestrichen

| Quelle | Grund |
|--------|-------|
| FMP | Legacy-API abgeschaltet, Key funktioniert nicht |
| QuiverQuant | $25/Mo, nicht FOSS-kompatibel |
| yfinance Options | Per-Ticker, kein Bulk, zu langsam |
