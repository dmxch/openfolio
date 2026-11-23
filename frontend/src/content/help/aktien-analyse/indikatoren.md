---
id: "indikatoren"
title: "Indikatoren erklärt"
summary: "Die technischen Indikatoren in OpenFolio und ihre Bedeutung."
section: "aktien-analyse"
order: 20
---

OpenFolio verwendet eine Reihe technischer Indikatoren, um Aktien zu bewerten. Hier sind die wichtigsten erklärt.

## Gleitende Durchschnitte (DMA)

Der **50-DMA** zeigt den kurzfristigen Trend, der **150-DMA** den mittelfristigen. Wenn der Kurs über beiden liegt, ist der Trend intakt. Fällt er darunter, ist Vorsicht geboten. Die 150-DMA-Regel ist ein zentraler Baustein der [Stop-Loss Strategie](#schwur-1).

## Volumen

Das **Volumen** zeigt, wie viele Aktien gehandelt werden. Hohes Volumen bei steigenden Kursen deutet auf institutionelle Käufe hin. Hohes Volumen bei fallenden Kursen zeigt Verkaufsdruck. Das Verhältnis von Aufwärts- zu Abwärtsvolumen ist ein wichtiger Indikator.

## Widerstand (Resistance)

Der **Widerstand** ist das Preisniveau, an dem die Aktie in der Vergangenheit abgeprallt ist. Ein Breakout über den Widerstand — idealerweise mit hohem Volumen — deutet auf mögliche Stärke hin. OpenFolio berechnet das Widerstandsniveau automatisch.

## VIX

Der **Volatilitätsindex** misst die vom Markt erwartete Schwankungsbreite des S&P 500 für die nächsten 30 Tage. Er wird aus Optionspreisen abgeleitet.

## Heartbeat-Pattern (Felix-Prinz)

Das **Heartbeat-Pattern** erkennt horizontale Konsolidierungen: mindestens 3 Highs + 2 Lows (oder 2+3) innerhalb ±3% des Levels über mindestens 30 Tage, kombiniert mit einer ATR-Compression als Volatilitäts-Filter. Der Ausbruch aus der Range — nicht das Pattern selbst — ist das eigentliche Setup.

- **Wyckoff-Volumen-Profil**: Sub-Signal, das die Range-Qualität bewertet. Schrumpfendes Volumen über die Range deutet auf Akkumulation (bullish), steigendes auf Distribution (atypisch). Drei Stufen: bestätigt, neutral, atypisch.
- **Spring-Marker (Bonus)**: kurze Penetration unter Support am Tag mit dem höchsten Volumen — Wyckoff-treues Signal für das Aussetzen schwacher Hände vor dem Markup. Im UI als Sub-Tag mit Datum und Volumen-Ratio sichtbar.
- Bei Distributions-Verdacht (Wyckoff-Score atypisch) wird das gesamte Heartbeat-Panel rot umrandet, damit die Warnung im Listing nicht übersehen wird.

> Merke: Kein einzelner Indikator reicht für eine Entscheidung. Das [Scoring-System](#wie-funktioniert-scoring) kombiniert bewusst mehrere Indikatoren, um die Trefferquote zu erhöhen.
