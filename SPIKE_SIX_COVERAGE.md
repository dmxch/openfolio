# Spike: Non-US-Coverage (SIX/LSE/TO) — Datenquellen-Probe

**Datum:** 2026-06-05
**Auslöser:** Claude-Finance-Feedback Tier-1 #2 — "Finnhub ist US-only, ein guter Teil
des Core-Sleeves (RSG, NOVN, CHSPI, EIMI, CH-Listings) ist für Fundamentals/Flow unsichtbar.
Ein zweiter Daten-Adapter für SIX/Europa würde das schliessen."
**Decision, die der Spike kippt:** Lohnt ein SIX-SER-Adapter (echter Build), oder reicht
yfinance (in-stack, gratis)?

## TL;DR — Decision

**KILL: kein SIX-SER-Adapter.** Die Annahme "fehlende Datenquelle" ist falsch. Der echte
Non-US-**Fundamentals**-Bedarf sind genau **zwei** operative Aktien (Novartis, Roche) — beide
liefert yfinance gratis. Alles andere im Non-US-Sleeve sind ETFs, für die nur MA-Status
(= Kurshistorie) zählt, und die deckt yfinance/TradingView bereits ab.

Das reale Problem ist **Symbol-Resolution**, nicht Coverage: jede Quelle (Finnhub, yfinance,
TradingView) hat eigene Symbol-Konventionen, und das im Portfolio gespeicherte Ticker mappt
auf keine sauber (z.B. Roche).

## Geerdet am echten Portfolio (nicht an der Beispielliste)

Claude Finances Beispiel **RSG ist gar nicht im Bestand**. Realer Non-US-Sleeve (aktiv,
tradable): ~18 Positionen — SIX (.SW), LSE (.L), Toronto (.TO).

Davon **operative Aktien mit Fundamentals-Bedarf:** nur **NOVN.SW (Novartis)** und
**ROG.SW (Roche)**. Der Rest (CHSPI, CHDVD, EIMI, SWDA, COMO, GDIG, WOSC, JPNA, XNJP,
ICHN, ISLN, SPXS, PAAS, SSV …) sind ETFs/Fonds → nur MA-Status relevant.

## Befunde der Probe

| Quelle | MA-Status (Kurse) | Fundamentals | Ergebnis |
|---|---|---|---|
| **Finnhub** (free) | — | NOVN.SW → **HTTP 403** "no access"; AAPL → voll | Non-US hart geblockt. Lücke real bestätigt. |
| **yfinance** (in-stack) | 6/8 Ticker sauber ~855 Tage (.SW/.L/.TO); 200-DMA berechenbar | **NOVN.SW 8/8** (P/E 21.3, ROE 34.9 %, Margin 23.9 %); **RO.SW 6/6** (Roche, ROE 37.3 %) | Deckt beide Aktien + MA-Status. Symbol-abhängig. |
| **TradingView-MCP** | NOVN/SIX → voll, **SMA200 direkt** (111.38) | keine (get_indicators = rein technisch) | Gute MA-Status-Quelle, kein Fundamentals-Ersatz. |

### Symbol-Resolution ist der Knackpunkt
- **Roche:** `ROG.SW` (Genussschein, im Portfolio geführt) → yfinance **komplett leer**
  (0 Zeilen, 2 saubere Läufe). `RO.SW` (Inhaberaktie) → 354 Zeilen + volle Fundamentals.
- TradingView: `NOVN`/SIX klappt, aber `ROG`/SIX und `COMO`/LSE → "no data" (andere
  Symbol/Exchange-Kodierung nötig).
- yfinance: `COMO.L` ebenfalls leer.
→ Jede Quelle braucht ihr eigenes Symbol-Mapping; das naive Portfolio-Ticker reicht nicht.

## Nebenbefund (Folge-Bug — VERIFIZIERT am Live-System)

**`ROG.SW` (Roche-Genussschein) ist auf yfinance leer → Roche-Preis ist live stale.**
- `price_cache` für ROG.SW endet **2026-05-19** (17 Tage stale; sauberer Cliff = strukturelle
  yfinance-Deprecation, kein transienter 429). Kontrolle NOVN.SW/CHSPI.SW: 0 Tage stale.
- `positions.current_price = 321.70` eingefroren seit **2026-03-24** (~2,5 Monate).
- Roche läuft damit auf totem Preis durch Performance/200-DMA/MRS/Score — **silent**, kein Alert
  (vgl. [[feedback_scheduled_jobs_need_liveness]], [[feedback_external_api_silent_deprecation]]).

**Ursache (Web-verifiziert):** Roches **Genussschein wurde an der GV vom 2026-03-10 in einen
Partizipationsschein umgewandelt**. Neuer SIX-Ticker = **ROP** (Inhaberaktie = RO). Yahoo liess
`ROG.SW` ~19.5. fallen; `current_price` fror Ende März bei der Umwandlung ein.

**Fix = `ROP.SW` (verifiziert):** ROP.SW ist frisch (6.6., P/E 20.4, ROE 37.3 %) und deckt sich
exakt mit der alten Genussschein-Kurslinie (ROP 18.5. = 321.70 = ROG 19.5.) — trägt **nicht**
den RO-Aufschlag. `RO.SW` (Inhaberaktie, ~2–5 % Aufschlag, 19.5.: 338.40) wäre **falsch** —
anderes Wertpapier, hätte einen zu hohen Preis in `value_chf` gespeist (HEILIGE Regel #1).
Alle Lese-Pfade (inkl. `portfolio_service`) lösen per `yfinance_ticker or ticker` auf → es
genügt, `positions.yfinance_ticker` auf `ROP.SW` zu setzen.

**Status:** Auf Dev angewandt (`UPDATE positions SET yfinance_ticker='ROP.SW' WHERE ticker='ROG.SW'`)
+ Refresh → ROP.SW frisch, `current_price` 321.70 → 327.50. **Prod separat nachziehen.**

### Systemischer Fix gebaut: Price-Staleness-Guard
Der eigentliche Bug war, dass ein Feed **17 Tage still sterben konnte**. Neuer Worker-Job
(`price_staleness_check`, 07:40 CET) flaggt aktive Positionen, deren letzter Kurs > 5 Tage
hinter dem frischesten Ticker liegt (oder keine `price_cache`-Zeile haben) und mailt den
Operator. `services/price_staleness_service.py` + Tests (`test_price_staleness.py`, 5/5).

**Der Guard fand beim Erstlauf 5 von 26 Tickern kaputt — nicht nur Roche:**
- `ROG.SW` — 17 Tage stale (→ jetzt via ROP.SW behoben).
- `XNJP.L`, `COMO.L`, `ICHN.L`, `SSV.TO` — **gar keine** `price_cache`-Zeile, laufen still auf
  cost_basis-Fallback. Eigene Folge-Aufgabe: pro Ticker korrektes Yahoo-Symbol verifizieren
  (wie bei Roche — nicht raten).

## Empfehlung (lean, falls überhaupt gebaut wird)

1. **Kein Adapter.** SIX-SER = echter Build für ~null inkrementelle Coverage.
2. **Folge-Bug zuerst:** Live-Preis von Roche prüfen; falls stale → Ticker auf `RO.SW`.
   Das ist der einzige verifizierte Wert-Hebel hier ([[feedback_value_first_not_risk_first]]).
3. **Optional, wenn Claude Finance Non-US-Fundamentals über OpenFolio braucht:** ein dünner
   yfinance-gestützter `/fundamentals/{ticker}`-External-Endpoint (n=2 Aktien: NOVN.SW,
   RO.SW) + bestehender Kurs-Pfad für MA-Status. Klein, kein Adapter.
4. **Eigentlicher struktureller Hebel:** per-Quelle-Symbol-Map (Portfolio-Ticker →
   yfinance/finnhub/TV-Symbol), startend mit ROG.SW→RO.SW. Behebt Folge-Bug und künftige
   Non-US-Fälle in einem.

## Caveats / Methodik
- yfinance nur via `yf_download()`-Wrapper; Fundamentals via `yf.Ticker().info` sequenziell
  (Burst-429-Schutz). yf_download droppt Ticker in Batches gelegentlich still — Einzel-Retry
  nötig, um Flakiness von echter Lücke zu trennen.
- Ticker NICHT aus Memory verifiziert, sondern gegen die Quellen-Responses.
