# Pre-Deploy-Audit: Equity-only-Universum-Filter (Item A.1)

**Datum:** 2026-05-21
**Trigger:** Plan-Item-A.1 BLOCKING-Gate — verifiziere, dass die 27 heute silent-skipped Tickers wirklich alle Junk sind, BEVOR der `resolve_equity_universe()`-Helper deployed wird.
**Status:** ⚠️ **CONDITIONAL GREEN** — Filter-induzierte Coverage-Lücke ausgeschlossen, aber neue FMP-Free-Tier-Coverage-Gap entdeckt (unabhängig von Item A.1).

---

## Universum-Auflistung (33 Tickers)

Aggregiert aus `DISTINCT positions.ticker ∪ DISTINCT watchlist.ticker WHERE is_active`.

### Snapshots erhalten (6) — alles `type=stock` oder vergleichbar US-Equity

| Ticker | Type | Currency | Quelle |
|---|---|---|---|
| INTC | stock | USD | position |
| JNJ | stock | USD | position |
| MSFT | (watchlist-only) | — | watchlist |
| PEP | stock | USD | position |
| SBUX | stock | USD | position |
| TSLA | stock | USD | position |

### Silent-skipped (27) — Klassifikation

#### 21 Junk-Tickers (KORREKT skipped — Filter würde diese korrekt rausfiltern)

| Ticker | Filter-Grund | Type | Begründung |
|---|---|---|---|
| CASH_RAIFFEISEN___LOHNKONTO___CHF | type=cash | cash | Bank-Konto, nicht handelbar |
| BTC-USD | type=crypto | crypto | Crypto, FMP-Equity-Endpoint nicht zuständig |
| XAUCHF=X | type=commodity | commodity | Gold-FX-Cross |
| ISLN.L | format `.L` | commodity | London-Listing |
| PAAS.TO | format `.TO` | commodity | Toronto-Listing |
| OEF | type=etf | etf | iShares S&P 100 ETF |
| CHSPI.SW | format `.SW` + etf | etf | SIX-Swiss-Listing |
| COMO.L | format `.L` + etf | etf | LSE-Listing |
| EIMI.L | format `.L` + etf | etf | LSE-Listing |
| GDIG.L | format `.L` + etf | etf | LSE-Listing |
| JPNA.L | format `.L` + etf | etf | LSE-Listing |
| SPXS.L | format `.L` + etf | etf | LSE-Listing |
| WOSC.L | format `.L` + etf | etf | LSE-Listing |
| PE_4E1D1AB1 | type=private_equity | private_equity | Buyout-Fund-Holding |
| CHDVD.SW | format `.SW` | stock | Swiss-Dividend-ETF mit stock-Misclassification (Iteration-3-Cleanup?) |
| ICHN.L | format `.L` | stock | LSE-Listing |
| NOVN.SW | format `.SW` | stock | Novartis CH-Listing |
| ROG.SW | format `.SW` | stock | Roche CH-Listing |
| SSV.TO | format `.TO` | stock | Toronto-Listing |
| SWDA.L | format `.L` | stock | iShares Core MSCI World LSE |
| XNJP.L | format `.L` | stock | LSE-Listing |

→ Alle 21 würden vom `resolve_equity_universe()`-Helper sauber rausgefiltert. **Filter-Logik validiert.**

#### 6 US-Stocks mit HTTP 402 Payment Required (NEW FINDING)

| Ticker | Type | Currency | Direkt-Probe gegen FMP `/stable/analyst-estimates?period=annual` |
|---|---|---|---|
| ASML | stock | USD | **402 Payment Required** (auch nach 2 Retries) |
| PM | stock | USD | **402 Payment Required** |
| RSG | stock | USD | **402 Payment Required** |
| WM | stock | USD | **402 Payment Required** |
| PAAS | (watchlist) | — | **402 Payment Required** |
| TYL | (watchlist) | — | **402 Payment Required** |

→ Diese 6 sind echte US-Stocks (NYSE/NASDAQ). FMP-Free-Tier blockt sie selektiv mit HTTP 402.

**Bestätigt funktional via Direkt-Probe:** MSFT + INTC liefern saubere FY1-EPS-Daten. ASML/PM/RSG/WM/PAAS/TYL liefern alle 402.

---

## Gate-Entscheidung

**Original-Gate:** "Wenn ≥1 US-Stock unter den skipped Tickers → STOP, Root-Cause-Analyse vor jedem Helper-Code."

**Refined-Gate-Anwendung:**

Die 6 US-Stocks fallen NICHT durch einen Filter raus — sie werden auf API-Ebene durch FMP-Free-Tier (HTTP 402) blockiert. Item A.1 (Equity-only-Filter) kann diese Lücke **nicht schliessen und nicht verbreitern**. Sie ist orthogonal zur Universums-Filter-Logik.

**Entscheidung:** ⚠️ **CONDITIONAL GREEN für Item A.1.** Helper-Deploy ist sicher, weil:
1. Filter-Verhalten ist korrekt — alle 21 Junk-Tickers würden sauber rausfallen.
2. Die 6 paywall-Tickers bleiben im Universum (type=stock, kein Junk-Format), würden weiter HTTP 402 erzeugen — **identisch zum heutigen Verhalten**. Item A.1 ändert daran nichts.
3. Log-Noise sinkt um die 21 Junk-Aufrufe pro Refresh-Lauf — netto-positiv.

---

## Parallel-Befund: Quant-Probe-Trial-Universum

Die heutige use-log-Notiz "Full-Refresh persistiert 6 Snapshots" war kein Ein-Tages-Fenster — die `estimate_revisions`-Pipeline kann auf diesem Setup **maximal 6 Snapshots/Lauf** persistieren (MSFT, INTC, JNJ, PEP, SBUX, TSLA), nicht 33 wie die Universums-Grösse suggeriert.

**Implikationen für Quant-Probe-Trial (Kill-Gate 2026-08-15):**
- Effektive Probe-Universum-Grösse: **6 Tickers**, nicht 33
- Decision-Counter-Kalibrierung sollte das berücksichtigen — Erwartungswert für `signals.estimate_revision`-Hits über 90-Tage-Horizont auf 6 Tickern ist deutlich niedriger
- ASML, PM, RSG, WM, PAAS, TYL können aus diesem Pipeline-Pfad keine `signals.estimate_revision`-Hits generieren

**Folge-Backlog (NICHT Iteration 2):**
- Investigation, ob FMP-Paid-Tier oder Alternative-Source (z.B. Skill-Layer's `grades-historical`) das schliessen kann
- Klärung mit Finance-Claude, ob die Trial-Kalibrierung das `n=6`-Universum schon kennt oder ob die Counter-Konfiguration angepasst werden muss

---

## Empfehlung

1. ✅ **Item A.1 GO** — Helper + estimate_revisions-Edit deploybar nach Tag-12-Retro.
2. 📋 **FMP-Coverage-Gap als separates Backlog-Item** (Iteration 3 oder eigener Workstream) — kein Block für Iteration 2.
3. 🔁 **Notify Finance-Claude** — die 6-Tickers-Realität sollte in der Probe-Trial-Auswertung explizit dokumentiert sein.

---

## Hard-Add-ons VOR A.1-Deploy (Finance-Workspace-Seite, NICHT OpenFolio-Scope)

Damit die Kill-Gate-Mathematik nicht unter falscher Annahme läuft, sind zwei Anpassungen im Finance-Workspace nötig BEVOR A.1 auf VM220 geht:

1. **Memory `project_openfolio_quant_probe.md` updaten** auf echtes Probe-Universum n=6 (nicht n=33). Namentliche Auflistung der 6 FMP-Coverage-Tickers (MSFT, INTC, JNJ, PEP, SBUX, TSLA) vs. der 6 FMP-Paywall-Tickers (ASML, PM, RSG, WM, PAAS, TYL).
2. **Kill-Gate-Threshold in `scripts/quant_probe_kill_check.sh` neu kalibrieren**: ≥3 Decision-Changes von n=6 ist ~50% Hit-Rate, vermutlich zu hoch. Vorschlag: Threshold auf ≥2/n=6 (~33%), ODER Kill-Gate-Datum 2026-08-15 nach hinten schieben für mehr Sample-Volumen. DRY_RUN-Test vor scharf.

Backlog-Detail Iteration 3 / eigener Workstream:
- "FMP-Coverage-Gap für 6 Tickers (ASML, PM, RSG, WM, PAAS, TYL). Optionen: (a) FMP Starter-Tier evaluieren, (b) Finnhub-Fallback für estimate_revision testen, (c) Manuelle Watchlist-Trigger ohne Quant-Signal für diese 6. Entscheidung nach Iteration-1-GO 2026-06-01 und nach Kill-Gate-Kalibrierung."
