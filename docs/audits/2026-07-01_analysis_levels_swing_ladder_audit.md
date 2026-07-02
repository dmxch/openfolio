# Audit Report — 2026-07-01

**Scope:** Pre-merge, diff-scoped audit of branch `feat/analysis-levels-swing-ladder`
(`main...HEAD`, commits `b34bb2e` + `cd743b1`).
**Change:** `get_support_resistance_levels` rewritten from close-only 52W extremes into an
OHLC swing-pivot ladder for trailing-stop anchoring; API/external params + 18 tests + roadmap note.

## Zusammenfassung

**Verdict: GO-WITH-NITS** (effektiv ein starkes GO — alle Findings sind informational/Design-Politur, kein Blocker).

Security 0 · QA PASS (18/18 neu, 94/94 im Kombilauf inkl. Golden-Master) · Perf OK · Arch PASS · UX N/A (0 Frontend-Change).

Die Geometrie ist korrekt, der Contract ist rückwärtskompatibel und formstabil, der zuvor
gefundene MED-Bug (close-only Gap-up-Degeneration) ist sauber gefixt **und** durch einen echten
Regressionstest abgesichert. Kein Migration, kein Frontend-Change, externe-API-Parität strukturell
garantiert (Shared-Service-Fn). §8 (kompletter server-seitiger AST) ist korrekt als NO-GO gegatet.

## Findings

| # | Bereich | Severity | Problem | Empfehlung |
|---|---------|----------|---------|------------|
| 1 | Arch/Korrektheit | LOW (info) | 52W-Skalar-Basis wechselte von „yfinance-`1y`-Range" (alt) zu „trailing 252 Bars aus `2y`" (`chart_service.py:667` `close.iloc[-LEVELS_52W_BARS:]`). Bedeutung (52W-Close-Extrem) bleibt erhalten, aber der exakte Wert kann für Rand-Ticker um Bruchteile abweichen. Kein stiller Definitions-Drift (Invariante #-Set enthält S/R nicht; Label „52W" bleibt wahr). | Bewusst so lassen; ggf. 1-Zeilen-Kommentar „252 Bars ≈ 1 Handelsjahr". |
| 2 | Korrektheit/Design | LOW | `_dedup_typed` behält bei geclusterten Swing-Lows (< 0.5×ATR) den **höheren** (näher an Spot) Repräsentanten → der Trail-Anker `swing_lows[0]` ist die *engere* zweier benachbarter Strukturen. Für einen Support-„Boden" wäre der tiefere sicherer (weniger Wick-Stop-Out). Innerhalb 0.5×ATR marginal; der Trail legt seinen eigenen ATR-Buffer darunter. | Design-Entscheid dokumentieren; kein Fix nötig. |
| 3 | API-Contract | NIT | `gap_bases` enthält **sowohl** echte Gap-up-Bases **als auch** k1-Reaction-Lows (gemischt) — Name etwas locker. Im Docstring aber korrekt als „reaction lows / gap bases" beschrieben. | Optional Rename/Doc-Klarstellung. |
| 4 | UX | NIT (kosmetisch) | „Marken"-Panel (`StockDetail.jsx`) rendert jetzt bis zu 8+8 Leiter-Zeilen statt 5+5 (`LEVELS_MAX_LADDER=8`). Dichtere Liste, kein Break (Frontend re-sortiert nach Preis). | Beobachten; ggf. UI-Cap. |
| 5 | QA/Parität | INFO | Kein expliziter External-API-Paritätstest ergänzt (Feature-Memory verlangt einen); Parität ist über die Shared-Fn strukturell garantiert, `test_analysis_api.py` prüft nur 200 des internen Endpoints. | Kleiner Paritäts-Assert (intern==extern) wäre nice-to-have. |
| 6 | API-Contract | INFO (kosmetisch) | `as_of` nutzt `…T00:00:00Z` für Tages-Bars (Z ⇒ UTC auf einem reinen Datums-Bar). | Belanglos. |

## Verifizierte Korrektheits-/Contract-Punkte

- **Anker-Invarianten halten:** alle `swing_lows` strikt `< spot`, nearest-first (`_dedup_typed`
  Preis-desc; Test `test_swing_lows_nearest_first` + `_strictly_ordered_by_dist_atr`);
  alle `swing_highs` `>= spot`, nearest-first. `swing_lows[0]` = nächster bestätigter Low unter Spot = korrekter Trail-Anker.
- **MED-Fix sound + guarded:** close-only-Fallback (`high==low==close`) — die Gap-up-Prüfung
  `low > prev_high` würde zu „jeder Up-Tag" degenerieren; jetzt gegatet auf `if low is not None and high is not None`
  (`chart_service.py:721`). Der k1-Reaction-Low-Zweig bleibt (kein Degenerieren auf echten lokalen Minima).
  `test_close_only_steep_parabola_has_no_phantom_gap_staircase` fällt, wenn das Gate entfernt wird
  (asserted `gap_bases==[]` **und** Anker==echter k2-Pivot 40.0) → echte Regressionswache.
- **Skeleton-Parität:** `_empty_levels` und der Erfolgs-Dict haben identisches 16-Key-Set
  (`test_empty_data_returns_full_skeleton`); alle Fehler-/Kurzhistorie-Pfade geben Full-Shape → kein KeyError beim Konsumenten.
- **Backward-Compat:** `support`/`resistance` bleiben 52W-Close-Extreme; `support_historical`/
  `resistance_historical` bleiben flache Float-Listen → `StockDetail.jsx` (unverändert) funktioniert
  weiter, 0 Frontend-Change (Frontend liest nur die flachen Arrays + Skalare, nie die Metadaten-Objekte).
- **Param-Validierung doppelt abgesichert:** API `Query(ge/le)` == Service-Clamps (`max/min`) in
  `analysis.py` + `external_v1.py`; `Query` in beiden Dateien importiert (kein Import-Crash).
- **Caching:** Key `levels:{ticker}:{lookback}:{pivot_k}:{int(below_only)}` (alle Params), TTL 900 (verifiziert `test_cache_ttl_short`).
- **Robustheit empirisch geprüft:** MultiIndex-yf-Spalten (`data["Close"].squeeze()` + `"Close" in data`)
  → ATR/Ladder rechnen korrekt, kein Crash (Auditor-Probe). DB-Fallback liefert `DatetimeIndex`
  (`cache_service.py:814`) → `.strftime`/`pd.to_datetime`-Vergleiche im Parabel-Zweig sicher.
- **ATR/Parabel-Math:** ATR(22) via bestehendem `_compute_atr`, korrekt auf `dropna`-aligned OHLC;
  Parabel-Gate (SMA50×1.25 ODER ≥+20 % über ≤5 Bars) sinnvoll; Reaction-Lows strikt `> last_pivot_low`
  (Ratchet nach oben, Test `test_reaction_above_base`).
- **Governance:** §8 (kompletter server-seitiger AST) korrekt NO-GO gegatet (kein RSI/Stoch im Backend,
  SoT bleibt FLAG-not-Auto-Stop, Spec-Beispiel selbst inkonsistent) — im Einklang mit „keine Scoring-Gewichte ohne Backtest".

## Stärken

- Full-Shape-Skeleton auf **jedem** Rückgabepfad — konsumentensicher, per Test gepinnt.
- „Additive"-Contract sauber umgesetzt: keine stille Definitions-Drift auf `support`/`resistance`, 0 Frontend-Change.
- Der frühere MED-Bug ist präzise gescoped gefixt (nur der degenerierende Gap-up-Zweig deaktiviert,
  der valide k1-Zweig bleibt) und durch einen Test bewacht, der genau die Bug-Signatur prüft.
- 18 deterministische, netz-/DB-freie Tests; 94/94 im Kombilauf grün inkl. Golden-Master (Invarianten intakt).
- Kein Migration; externe-API-Parität automatisch via Shared-Service-Fn.
