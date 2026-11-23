---
id: "donchian-breakout"
title: "Donchian Channel Breakout"
summary: "Wie OpenFolio Ausbrüche über den Donchian Channel erkennt."
section: "scoring-system"
order: 40
---

Der Donchian Channel ist ein wichtiger Indikator für Breakouts. Er bildet den höchsten Hoch- und den tiefsten Tiefpunkt der letzten N Perioden ab.

## Was ist ein Donchian Channel?

Der Donchian Channel besteht aus zwei Linien: dem **oberen Band** (höchstes Hoch der letzten N Tage) und dem **unteren Band** (tiefstes Tief der letzten N Tage). Durchbricht der Kurs das obere Band, liegt ein Breakout vor.

## Breakout-Erkennung

OpenFolio prüft, ob der aktuelle Kurs über dem **Widerstandsniveau** liegt. Dabei gilt strikt: Der Kurs muss den Widerstand überschreiten — ein Gleichstand reicht nicht. Das filtert falsche Signale heraus.

> Wichtig: Die Breakout-Logik verwendet **keine Toleranz**. Der aktuelle Kurs muss strikt über dem Widerstand liegen (current_price > resistance), nicht grösser-gleich.

## Volumenbestätigung

Ein Breakout ist nur dann aussagekräftig, wenn er von **hohem Volumen** begleitet wird. OpenFolio prüft, ob das Breakout-Volumen mindestens 1.5× so hoch ist wie das durchschnittliche Volumen (20-Tage-Schnitt). Ein Breakout ohne Volumen ist oft ein Fehlsignal.

## In der Praxis

Wenn du eine Aktie auf der [Watchlist](#watchlist-nutzen) hast und ein Breakout-Signal erscheint, prüfe den [Setup-Score](#setup-score). Setup STARK und Breakout bestätigt → Kaufkriterien erfüllt.
