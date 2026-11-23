---
id: "makro-gate"
title: "Makro-Gate (7 Checks)"
summary: "Sieben gewichtete Prüfungen bestimmen, ob das Marktumfeld Käufe erlaubt."
section: "scoring-system"
order: 20
---

Das Makro-Gate besteht aus sieben gewichteten Checks, die zusammen maximal 9 Punkte ergeben. Das Gate ist bestanden, wenn die Schwelle erreicht wird — standardmässig **6 von 9 Punkten** (die Schwelle ist dynamisch, siehe unten).

## Die 7 Checks

**S&P 500 über 150-DMA** (2 Punkte): Der S&P 500 muss über seinem 150-Tage-Durchschnitt notieren. Das ist der wichtigste Einzelcheck — er zeigt, ob der Markt in einem Aufwärtstrend ist.

**S&P 500 Higher Highs / Higher Lows** (1 Punkt): Der Markt bildet höhere Hochs und höhere Tiefs — ein klassisches Trendmerkmal. (Technische Näherung: approximiert durch S&P über 50-DMA UND 50-DMA über 150-DMA.)

**VIX unter 20** (2 Punkte): Der Volatilitätsindex VIX misst die erwartete Schwankungsbreite. Unter 20 herrscht relative Ruhe; darüber steigt das Risiko.

**Sektor stark** (1 Punkt): Der jeweils betrachtete Sektor hat im letzten Monat eine positive Rendite (> 0%) erzielt. Ist kein Sektor angegeben, gilt dieser Check automatisch als erfüllt.

**Shiller PE unter 30** (1 Punkt): Das zyklisch adjustierte KGV liegt unter 30 — der Markt ist nicht extrem überbewertet.

**Buffett Indicator unter 150%** (1 Punkt): Das Verhältnis von Marktkapitalisierung zum BIP liegt unter 150%.

**Zinsstruktur nicht invertiert** (1 Punkt): Die Zinsstrukturkurve ist nicht invertiert — ein invertierter Verlauf gilt als Rezessionssignal.

> Merke: Die Checks mit 2 Punkten (S&P über 150-DMA, VIX) haben doppelte Gewichtung, weil sie besonders aussagekräftig sind.

## FRED-Abhängigkeit und dynamische Schwelle

Drei Checks (Buffett Indicator, Shiller PE, Zinsstruktur) benötigen externe Makro-Daten. Fehlen sie — etwa ohne hinterlegten [FRED API Key](#einstellungen) — werden sie als «nicht verfügbar» markiert (grau) und fliessen nicht in die Wertung ein. Die Schwelle ist deshalb dynamisch: Sie liegt bei zwei Dritteln der verfügbaren Punkte (aufgerundet). Standard sind 6 von 9 Punkten; fehlen die FRED-Checks, sinkt die maximale Punktzahl auf 6 und die Schwelle auf 4 von 6.
