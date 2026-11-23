---
id: "alerts"
title: "Alerts & Benachrichtigungen"
summary: "Automatische Warnungen per E-Mail bei wichtigen Ereignissen."
section: "risikomanagement"
order: 30
---

OpenFolio kann dich automatisch per E-Mail benachrichtigen, wenn wichtige Ereignisse eintreten. So verpasst du keine Stop-Loss-Auslösung und kein Breakout-Signal.

## Alert-Typen

**Portfolio-Alerts**: Warnungen, wenn eine Position ihren Stop-Loss-Bereich erreicht oder der Portfoliowert einen bestimmten Schwellenwert unterschreitet.

**Kurs-Alerts**: Benachrichtigung, wenn eine Aktie einen bestimmten Kurs über- oder unterschreitet. Nützlich für Watchlist-Aktien, bei denen du auf einen Breakout wartest.

**Breakout-Alerts**: Meldung, wenn eine Aktie ihr Widerstandsniveau mit Volumen durchbricht.

**Drawdown-Bremse pro Bucket**: Status-Mail, wenn ein [Bucket](#buckets) seine Drawdown-Schwelle (Peak-to-Trough) erreicht.

**Bucket-Drift**: Hinweis, wenn ein Bucket seinen maximalen Anteil am liquiden Portfolio überschreitet.

**Dividenden-Alerts**: Erinnerung an erkannte, noch nicht erfasste Dividenden (siehe [Dividenden automatisch erfassen](#dividenden)).

**ETF 200-DMA-Alerts**: Meldung, wenn ein breiter Index-ETF unter seine 200-DMA fällt (erfüllte Kaufkriterien).

**Regel-Alerts**: Eigene, frei definierte Bedingungen auf Kennzahlen oder Kursen.

Jede Kategorie lässt sich unter **Einstellungen → Alerts** einzeln auf E-Mail aktivieren oder stummschalten.

## Alerts einrichten

Navigiere zu einer Position oder Aktie und klicke auf «Alert erstellen». Definiere die Bedingung (z.B. Kurs unter CHF 150) und den Alert-Typ. Bei Auslösung erhältst du eine E-Mail mit allen relevanten Details.

> Voraussetzung: Für E-Mail-Alerts muss ein SMTP-Server in den [Einstellungen](#einstellungen) konfiguriert sein. Ohne SMTP-Konfiguration werden Alerts zwar ausgelöst, aber nicht per E-Mail versendet.

## Best Practices

Richte für jede Position einen **Stop-Loss-Alert** ein. Setze den Alert leicht über dem tatsächlichen Stop-Loss — z.B. bei -10%, wenn dein Stop bei -12% liegt. So hast du Zeit zu reagieren, bevor der Stop erreicht wird. Für Watchlist-Aktien empfiehlt sich ein Alert knapp unter dem Widerstandsniveau.
