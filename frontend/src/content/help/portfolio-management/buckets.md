---
id: "buckets"
title: "Buckets — Portfolio-Segmentierung"
summary: "Liquides Portfolio in eigenständig getrackte Untermengen aufteilen (Core/Satellite, FIRE/Spielgeld, …)."
section: "portfolio-management"
order: 30
---

Buckets erweitern das Core/Satellite-Konzept zu einem **frei konfigurierbaren System** zur Portfolio-Segmentierung. Du kannst bis zu 15 eigene Buckets anlegen, jedem eine Farbe, einen Benchmark und eine Drawdown-Bremse zuweisen.

## Wofür Buckets?

Typische Anwendungsfälle:
- **Core/Satellite** (Standard-Template): Trennung zwischen Buy-and-Hold-Kernportfolio und taktischen Einzeltiteln (Drawdown-Schwellen 6% / 15%).
- **FIRE/Spielgeld** (Standard-Template): Langfristiger FIRE-Bucket mit konservativer Drawdown-Bremse + risikoreiches Spielgeld (6% / 25%).
- **Zeithorizont** (Standard-Template): kurz / mittel / lang mit Drawdown-Schwellen 3% / 8% / 15%.
- **Risiko-Tiers** (Standard-Template): konservativ / balanced / aggressiv mit Drawdown-Schwellen 5% / 12% / 20%.
- **Strategie-Buckets**: Dividend Growth / Trend Following / Value-Plays getrennt.
- **Account-Mapping**: 1 Bucket je Broker, Übersicht über mehrere Konten.

## System-Buckets vs. User-Buckets

OpenFolio legt für jeden User vier **System-Buckets** automatisch an: *Alle Positionen* (liquid-default), *Immobilien*, *Private Equity*, *Vorsorge*. Sie können nicht gelöscht werden, aber Farbe und Benchmark sind editierbar.

**User-Buckets** legst du selbst an — entweder über ein Template (One-Click-Erstellung von Core+Satellite, FIRE+Spielgeld, Zeithorizont oder Risiko-Tiers) oder als individueller Custom-Bucket.

## Drawdown-Bremse pro Bucket

Jedem Bucket kannst du eine **Drawdown-Schwelle** zuweisen (Standard 6% für Core, 15% für Satellite, 25% für Spielgeld). Wenn der Bucket-Drawdown (Peak-to-Trough) diese Schwelle erreicht, sendet OpenFolio um 07:30 CET eine neutrale Status-Mail. Idempotent: maximal eine Mail pro Bucket und Tag.

> Voraussetzung für Mail-Versand: unter **Einstellungen → Alerts** die Kategorie *Drawdown-Bremse pro Bucket* auf E-Mail aktivieren und einen SMTP-Server konfigurieren.

Junge Buckets (jünger als 7 Tage) lösen keine Alerts aus — damit verhindern wir False-Positives wenn die Snapshot-Historie noch nicht aussagekräftig ist.

## Bucket-Drift-Bremse

Zusätzlich zur Drawdown-Bremse kannst du pro Bucket einen **Max-Total-%-Wert** festlegen (z.B. 25%). Überschreitet der Bucket diesen Anteil am gesamten liquiden Portfolio, sendet OpenFolio um 07:35 CET eine neutrale Status-Mail — so wird kein einzelner Bucket unbemerkt zu dominant. Ebenfalls idempotent (maximal eine Mail pro Bucket und Tag) und unter *Einstellungen → Alerts* aktivierbar.

## Positionen verschieben

Im Portfolio-Tab steht ein Toggle **Aggregiert / Pro Bucket**. Im Pro-Bucket-Modus filtert die Tab-Bar die angezeigten Positionen.

Eine Position in einen anderen Bucket verschiebst du über *Bearbeiten* → *Bucket*-Dropdown. Ein Bestätigungs-Dialog zeigt dir die **Risk-Rules-Diff** (welche Drawdown-Schwelle, welcher Stop-Loss-Vorschlag und welcher Benchmark ändern sich). Der Wechsel ist ein **Re-Labeling**: keine Verkauf+Kauf-Transaktion, keine realisierte P&L, die Cost-Basis wandert mit.

## Backward-Compatibility

Wenn du Buckets nicht aktiv nutzt, bleibt dein Portfolio funktional identisch zur klassischen Ansicht. Der Toggle erscheint erst, wenn du mindestens einen User-Bucket angelegt hast. Frühere *position_type*-Werte (core/satellite) wurden auf die zwei User-Buckets *Core* und *Satellite* gemappt; mit der Bucket-Vollumstellung in Version 0.40 ist die alte Spalte aus der Datenbank entfernt — Klassifikation, Risk-Rules und Alerts laufen jetzt ausschliesslich über die Bucket-Zuordnung.
