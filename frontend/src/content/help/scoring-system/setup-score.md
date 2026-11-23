---
id: "setup-score"
title: "Setup-Score — technische Qualität"
summary: "Rein technische Kriterien bewerten die einzelne Aktie als Prozentwert."
section: "scoring-system"
order: 30
---

Der Setup-Score bewertet eine Aktie anhand von bis zu 23 rein technischen Kriterien aus neun Kategorien. Der Score ist kein fester Punktwert, sondern der prozentuale Anteil der erfüllten an den **bewertbaren** Kriterien — angepasst durch Modifier (siehe unten). Kriterien, die mangels Daten nicht beurteilt werden können, bleiben grau und zählen weder im Zähler noch im Nenner ([Tri-State-Logik](#glossar-link)).

## Moving Averages (7 Kriterien)

Preis über MA50, MA150 und MA200. MA50 über MA150 und MA200. MA150 über MA200. MA200 steigend. Das stellt sicher, dass die Aktie in einem intakten Aufwärtstrend ist.

## Breakout (5 Kriterien, Donchian Channel)

20-Tage-Hoch Breakout (mit 2-Tages-Bestätigung), Volumen mindestens 1.5× Durchschnitt, über 150-DMA, maximal 25% unter 52-Wochen-Hoch, mindestens 30% über 52-Wochen-Tief.

## Relative Stärke (3 Kriterien)

Die **Mansfield Relative Stärke** (MRS) muss positiv sein (> 0), stark (> 0.5) und idealerweise Sektor-Leader (> 1.0). Das zeigt, dass die Aktie besser performt als der Gesamtmarkt (S&P 500). Mehr dazu unter [Mansfield RS](#mansfield-rs).

## Volumen & Liquidität (2 Kriterien)

Marktkapitalisierung über 2 Mrd. und durchschnittliches Volumen über 200'000. Das stellt sicher, dass die Aktie institutionell gehandelt wird.

## Trendbestätigung (1 Kriterium)

**Bullish MA-Cross 50/150 (20 Tage)** — die 50-Tage-MA hat die 150-Tage-MA in den letzten 20 Handelstagen von unten nach oben gekreuzt. Dies ist eine Trend-Bestätigung (kein Reversal): wenn die 50-DMA steigt, ist der mittelfristige Trend bereits gedreht. Whipsaws (zwei Crosses unterschiedlicher Richtung im Window) und Failed Crosses (Preis seit dem Cross >5% gegen die Richtung gelaufen) werden ausgefiltert.

## Modifier (2 Kriterien, -1/0/+1, asymmetrisch)

Modifier wirken **asymmetrisch**: negative Modifier (-1) wirken auf die Quality-Klassifikation und können ein STARK-Setup auf BEOBACHTEN herabstufen (Risk-First-Logik gegen Late-Stage-Stocks mit Distribution-Verdacht). Positive Modifier (+1) verbessern nur die Anzeige, **nicht** die Quality — ein schwaches Setup kann nicht durch positive Modifier künstlich auf STARK gehoben werden.

- **Distance from MA50** — Mean-Reversion-Risiko: <15% über MA50 = +1 (gesund), 15-25% = 0 (etwas gestreckt), >25% = -1 (überstreckt). Wenn Kurs ≤ MA50 wird das Kriterium nicht bewertet (id=3 prüft das schon klassisch).
- **Volume-Confirmation (Slope vs Vol-Ratio)** — Divergenz zwischen Preis-Trend und Volumen-Trend. Steigender Kurs auf fallendem Volumen = Distribution-Verdacht (-1). Mega-Caps (>500B MCap, 90d-smoothed) verwenden verschärfte Schwellen 0.75/1.25 statt 0.85/1.15 wegen institutioneller Liquidität.

> **Aggregation**: Display-pct = base_pct + modifier_sum × 3 (kosmetisch). Quality-pct = base_pct + negative_modifier_sum × 8 (nur negative Modifier degradieren). Das verhindert, dass ein 16/18-Setup mit Distribution-Verdacht trotzdem als STARK durchgewunken wird.

## Industry-Stärke (1 Kriterium)

**Industry-MRS (perf_3m vs S&P, ±2pp Buffer)** — vergleicht den 3-Monats-Performance der TradingView-Industry des Tickers mit der 3-Monats-Performance des S&P 500. Eine Aktie in einer Branche, die gegen den breiten Markt schwimmt, ist ein fragiles Setup. ±2pp-Buffer-Zone gegen Endpunkt-Sensitivität: nur wenn die Industry mindestens 2 Prozentpunkte über/unter dem S&P liegt, wird das Kriterium passed=True/False, sonst neutral (None).

## Trendwende (1 Kriterium)

3-Punkt-Umkehr erkannt — nur relevant für Aktien unter der 150-DMA. Drei tiefere Tiefs gefolgt von einem höheren Tief deuten auf eine mögliche Trendwende hin.

## Risiken (3 Kriterien)

Die Risiken-Gruppe sammelt aktive Warnsignale separat von positiven Score-Kriterien:

- **Death-Cross 50/150 (20 Tage)** — die 50-Tage-MA kreuzt die 150-Tage-MA von oben nach unten (bearisches Continuation-Signal).
- **Distribution Day (Volumen-Spike-Down)** — Volumen > 3× 20-Tage-Durchschnitt UND Schlusskurs unter Eröffnung in den letzten 20 Tagen (institutioneller Verkaufsdruck).
- **Earnings-Proximity (≥ 7 Tage)** — hartes Veto: wenn next_earnings_date < 7 Tage entfernt, wird das Kriterium passed=False UND setup_quality wird auf BEOBACHTEN gecapt. Bei Score≥15 + MRS>1.0 + Industry-MRS+ + keinen aktiven Risk-Modifiern wird Split-Entry-Eligibility (halbe Position vor Earnings) im Banner kommuniziert. Earnings-Datum unbekannt → Kriterium grau, kein Cap.

> **Tri-State-Logik**: Ein graues Häkchen heisst "nicht bewertbar" (z.B. zu kurze Historie, Whipsaw, unbekanntes Earnings-Datum) und fliesst NICHT in den Score ein — so wird verhindert, dass IPOs ohne 150-Tage-MA durch Daten-Mangel bessere Scores bekommen. Nur explizit bewertete Kriterien (grün = kein Risiko, rot = aktives Risiko) zählen.

## Konzentrations-Banner (StockDetail + Watchlist-Spalte)

Sichtbarkeit für Klumpenrisiko (Schwur Nr. 3). Phase 1.1 (v0.29.0) zeigt zwei Achsen in einem Banner:

**Single-Name-Achse** (Direkt + Indirekt = Total):
- Direkt-Position wenn vorhanden (du hältst NVDA bereits 4'500 CHF direkt)
- Plus indirekte Exposure via deine ETFs (NVDA in OEF mit ~7%)
- Total in CHF und % Liquid-Portfolio
- Hypothetischer 5%-Direktkauf-Hebel mit Single-Name-Cap-Check (~6-8%)

**Sektor-Achse** (aggregiert über alle Direkt-Holdings + ETF-anteilig):
- Tech-Sektor-Total = Σ direkter Tech-Aktien + Σ (ETF-Position × Tech-Anteil)
- **Soft-Warn ≥25%**: gelb, "am oberen Rand der Strategie-Range (15-25%)"
- **Hard-Warn ≥35%**: rot, "Konzentrationsrisiko"
- Hypothetischer Direktkauf bei Sektor-Schwellen-Überschreitung explizit angezeigt

**Watchlist-Spalte "Overlap"**: max-Gewicht über alle deine abgedeckten ETFs (nicht nur US — siehe Anbieter-Abdeckung unten; nur Single-Name-Achse, nicht Sektor — für Triage-Pattern in der Watchlist)

**Sektor-Klassifikation** (3-stufige Cascade):
1. SECTOR_OVERRIDES-Dict (manuell, in Git, reviewbar)
2. TradingView-Industry-Klassifikation → INDUSTRY_TO_SECTOR-Mapping
3. "Unclassified" (zählt in Coverage-Lücke)

**Coverage-Schutz**: wenn ein ETF mit ≥10% Portfolio-Weight unter 95% Sektor-Coverage fällt → ganze Sektor-Aggregation suppressed mit explizitem Hinweis. Lieber gar nichts zeigen als verzerrte Zahl.

**Anbieter-Abdeckung**: Look-Through deckt US-ETFs (FMP) sowie iShares, Xtrackers, SPDR, Amundi/Lyxor, HSBC, JPMorgan und Fidelity über deren eigene Holdings-Feeds ab. UBS, L&G und WisdomTree bieten keinen ohne Login abrufbaren Kanal und werden bewusst ausgelassen statt mit einer ungenauen Schätzung angenähert.

**Frische**: FMP-Daten hinken 30-60 Tage Filings-Lag. Tooltip im Banner zeigt den as_of-Stichtag falls verfügbar, sonst "Stichtag unbekannt".

> Bewertung: Der Score ist der Anteil der erfüllten an den bewertbaren Kriterien (angepasst durch Modifier). 70% oder mehr = **STARK**, 45–69% = **MODERAT**, unter 45% = **SCHWACH**. Nur starke Setups mit Breakout-Bestätigung erfüllen die Kaufkriterien.
