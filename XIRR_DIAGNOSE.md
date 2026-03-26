# XIRR / MWR Diagnose-Report

**Generiert:** 2026-03-26
**User:** hwfo@proton.me
**Snapshot-Zeitraum:** 2023-06-14 bis 2026-03-26
**Snapshots total:** 727 (regeneriert, PE-frei)
**Transaktionen total:** 85

## 1. XIRR-Ergebnis

| Metrik | Wert |
|---|---|
| **XIRR (annualisiert, MWR)** | **39.18%** |
| NPV-Check bei 39.18% | 3.90 (~ 0, korrekt) |
| Cashflow-Eintraege | 46 |
| Start-Wert (Snapshot 2023-06-14) | CHF 67'336.80 |
| End-Wert (Snapshot 2026-03-26) | CHF 91'748.35 |

## 2. Plausibilitaets-Check

| Metrik | Wert |
|---|---|
| Total Geld investiert (alle Inflows) | CHF 338'813.60 |
| Total Geld erhalten (alle Outflows + Endwert) | CHF 397'873.21 |
| Netto-Gewinn | CHF 59'059.61 |
| Investitionszeitraum | 1'016 Tage (2.78 Jahre) |
| **XIRR (geldgewichtet)** | **39.18%** |

### Warum 39% bei nur 59K Gewinn?

Die XIRR (Money-Weighted Return) misst die annualisierte Rendite auf das **tatsaechlich investierte Kapital zu jedem Zeitpunkt**. Der hohe Wert erklaert sich durch gutes Cashflow-Timing:

1. **Okt 2024:** Grosse Verkaeufe (CHF 163K) nahe Markt-Hochs — Geld war draussen waehrend Korrektur
2. **Feb/Maerz 2026:** Wiedereinstieg mit CHF ~100K zu tieferen Kursen
3. **Ergebnis:** Durchschnittlich investiertes Kapital war relativ gering, aber die Rendite auf dieses Kapital war hoch

Die XIRR belohnt korrektes Timing — wer bei Hochs verkauft und bei Tiefs kauft, erzielt eine hoehere MWR als eine einfache Renditeberechnung zeigen wuerde.

## 3. Aktive Positionen (in Performance enthalten)

| Ticker | Name | Typ | Shares | Cost Basis CHF | Marktwert CHF |
|---|---|---|---:|---:|---:|
| OEF | ISHARES S&P 100 ETF | etf | 48.91 | 12'386.27 | 15'710.92 |
| CHSPI.SW | ISHARES CORE SPI CH | etf | 83.69 | 12'256.11 | 12'879.37 |
| JNJ | JOHNSON & JOHNSON | stock | 53.00 | 10'186.71 | 12'716.29 |
| WM | WASTE MANAGEMENT | stock | 55.00 | 10'069.61 | 12'366.75 |
| RSG | REPUBLIC SERVICES | stock | 56.00 | 9'982.65 | 12'070.80 |
| PEP | PEPSICO | stock | 77.00 | 10'197.23 | 11'683.21 |
| NOVN.SW | NOVARTIS | stock | 77.00 | 9'977.65 | 9'210.74 |
| BTC-USD | Bitcoin | crypto | 0.15 | 10'000.00 | 8'401.24 |
| EIMI.L | iSh MSCI EM IMI | stock | 150.59 | 5'507.81 | 7'092.67 |
| LHX | L3HARRIS TECHNOLOGIES | stock | 16.00 | 4'626.41 | 5'632.32 |
| **TOTAL** | | | | **95'190.45** | **107'764.31** |

Plus 18 verkaufte Positionen mit Shares = 0 (historisch).

## 4. Ausgeschlossene Positionen (illiquid)

| Ticker | Name | Typ | Shares | Cost Basis CHF | Marktwert CHF |
|---|---|---|---:|---:|---:|
| PE_4E1D1AB1 | Kibernetik AG | private_equity | 2'076 | 89'268.00 | 119'370.00 |

**Korrekt ausgeschlossen:** Private Equity fliesst weder in Snapshot-Werte noch in XIRR-Cashflows ein.

## 5. Ausgeschlossene Transaktionen

Keine Transaktionen fuer illiquide Positionen (pension, real_estate, private_equity) gefunden.

> **Korrekt:** Private Equity Positionen verwenden Position-Sync (keine Transaktionen), daher fliessen keine PE-Cashflows in die XIRR-Berechnung ein.

## 6. Korrektheit der Private Equity Ausschliessung

### Gepruefte Stellen

| Datei | Was | PE ausgeschlossen? |
|---|---|---|
| `snapshot_service.py:47` | Daily Snapshot (fast calc) | Ja — PE komplett uebersprungen |
| `snapshot_service.py:207` | Snapshot Regen (price download) | Ja — PE uebersprungen |
| `snapshot_service.py:334` | Snapshot Regen (value calc) | Ja — PE uebersprungen |
| `history_service.py:90` | Portfolio History (tradable) | Ja — PE uebersprungen |
| `history_service.py:222` | Portfolio History (daily value) | Ja — PE uebersprungen |
| `performance.py:71` | Daily Change API | Ja — `notin_(private_equity)` |
| `performance.py:173` | Core/Satellite Allocation | Ja — EXCLUDE_LIQUID |
| `total_return_service.py:22` | Unrealized PnL | Ja — PE PnL subtrahiert |
| `total_return_service.py:94` | Total Invested | Ja — PE cost_basis subtrahiert |
| `PerformanceCard.jsx:104` | Liquides Vermoegen | Ja — PE abgezogen |
| `AllocationCharts.jsx:273` | Liquid/Total Toggle | Ja — ILLIQUID_TYPES |
| XIRR Cashflows | PE Transaktionen | N/A — PE hat keine Transaktionen |
| XIRR Cashflows | PE in Snapshots | Ja — Snapshots enthalten PE nicht |

## 7. Schlussfolgerung

1. **XIRR von 39.18% ist mathematisch korrekt** — NPV bei dieser Rate ist ~0. Der hohe Wert reflektiert gutes Cashflow-Timing (grosse Verkaeufe bei Hochs, Wiederkaeufe bei Tiefs).

2. **Private Equity korrekt ausgeschlossen** — alle 12 relevanten Stellen geprueft und verifiziert. Keine PE-Kontamination in Snapshots oder XIRR-Cashflows.

3. **Snapshot-Integritaet** — 727 Snapshots nach Regeneration sauber (keine PE-Werte).

4. **Keine weitere Aktion noetig** — Die angezeigte Rendite ist korrekt.
