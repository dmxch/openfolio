---
id: "performance"
title: "Performance verstehen"
summary: "Wie OpenFolio die Rendite berechnet: XIRR, Modified Dietz, Kostenbasis und Währungseffekte."
section: "portfolio-management"
order: 100
---

Die Performance-Berechnung in OpenFolio ist exakt und berücksichtigt Währungseffekte, Gebühren und Cashflows.

## Berechnungsmethode

OpenFolio nutzt bewusst unterschiedliche Methoden je nach Zeithorizont:

- **Monatsrenditen** werden mit **Modified Dietz** berechnet — einer zeitgewichteten Methode, die Cashflows nach ihrem Zeitpunkt im Monat gewichtet. Ideal für den Monatsvergleich in der Heatmap, unabhängig vom Timing deiner Ein-/Auszahlungen.
- **Jahresrenditen, YTD- und Gesamtrendite** nutzen **XIRR** (Extended Internal Rate of Return) — eine geldgewichtete Methode (MWR). XIRR berücksichtigt Zeitpunkt und Höhe aller Cashflows und zeigt deine tatsächlich erzielte Rendite. Das ist der Industriestandard bei unregelmässigen Ein- und Auszahlungen.
- **Risiko-Kennzahlen** (Sharpe, Sortino, Volatilität, Drawdown) werden aus täglichen Snapshot-Renditen abgeleitet und sind **zeitgewichtet (TWR)** — bewusst getrennt von der geldgewichteten XIRR-Gesamtrendite, damit das Risiko unabhängig vom Cashflow-Timing gemessen wird.

## Kostenbasis

Die **Kostenbasis** ist der Gesamtbetrag, den du für eine Position bezahlt hast — inklusive Gebühren. Bei Aktien in Fremdwährung wird der historische CHF-Wechselkurs zum Kaufzeitpunkt verwendet. Die Formel: Kostenbasis CHF = Anzahl × Kaufpreis × FX-Rate + Gebühren.

## Aktuelle Bewertung

Der **aktuelle Wert** einer Position berechnet sich als: Anzahl × aktueller Kurs × aktueller FX-Rate. Die Performance in Prozent ist dann: ((Wert / Kostenbasis) - 1) × 100.

> Wichtig: Die Performance enthält sowohl die Kursänderung als auch den Währungseffekt. Eine US-Aktie kann im Kurs steigen, aber trotzdem in CHF verlieren, wenn der Dollar fällt.

## Monatsrenditen und YTD

OpenFolio erstellt tägliche **Snapshots** deines Portfoliowerts (Marktwert plus Netto-Cashflows des Tages). Daraus werden die Monatsrenditen per **Modified Dietz** berechnet und in der Heatmap dargestellt. Die YTD-Rendite (Year-to-Date) zeigt die geldgewichtete Entwicklung seit Jahresbeginn (XIRR, für das laufende Jahr auf die Teiljahres-Rendite umgerechnet).

## Die Performance-Seite

In der Seitenleiste unter **Performance** sind alle Auswertungen gebündelt: Gesamtrendite, Equity-Curve gegen Benchmark, Monatsrenditen-Heatmap, Top-Gewinner/-Verlierer, realisierte Gewinne, Gebühren, Allokation und Diversifikation. Hast du eigene Buckets, gibt es zusätzlich eine Vergleichsleiste und je Bucket ein aufklappbares Akkordeon mit dem vollen Widget-Satz.

## Risiko-Kennzahlen

Die Risiko-Karte fasst die wichtigsten Kennzahlen des liquiden Rendite-Risikobuchs zusammen:

- **Sharpe-Ratio** — Überrendite je Einheit Gesamtschwankung (Volatilität).
- **Sortino-Ratio** — wie Sharpe, misst aber nur die Abwärtsschwankung.
- **Calmar-Ratio** — annualisierte Rendite im Verhältnis zum grössten Drawdown.
- **Volatilität (p.a.)** — annualisierte Standardabweichung der Tagesrenditen.
- **Information-Ratio** — Mehrrendite gegenüber dem Benchmark je Einheit aktivem Risiko.
- **Rolling-Returns** — Rendite über die letzten 1M/3M/6M/1J.

Der **risikofreie Zinssatz** für Sharpe/Sortino/Calmar ist standardmässig 0 (Excess-Return über Cash) und lässt sich serverseitig (Umgebungsvariable RISK_FREE_RATE_PCT) z.B. auf den SARON-/CHF-Geldmarktsatz setzen. Die hier gezeigte annualisierte Rendite ist zeitgewichtet (TWR) und damit bewusst von der geldgewichteten XIRR-Gesamtrendite der Total-Return-Karte getrennt.

## Faktor-Exposure (Alpha/Beta)

Die Faktor-Karte zerlegt deine liquiden Tagesrenditen per OLS-Regression in das **Alpha** (faktor-bereinigte Überrendite) und die **Betas** gegenüber Markt, Momentum, Value, Quality, Small-Cap, Gold, Krypto und CHF-Wechselkurs. Der t-Wert zeigt, wie verlässlich ein Beta ist (≥ 2 = signifikant), R² wie viel der Schwankung die Faktoren erklären.

## Drawdown

Der **Underwater-Drawdown** zeigt fortlaufend, wie weit das Portfolio unter seinem bisherigen Höchststand liegt — eine anschauliche Risiko-Perspektive neben der reinen Rendite.

> Hinweis: Alle Risiko- und Faktor-Kennzahlen sind rein beschreibend und beziehen sich auf die Vergangenheit. Sie sind keine Anlageempfehlung.
