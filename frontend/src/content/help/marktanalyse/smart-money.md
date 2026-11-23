---
id: "smart-money"
title: "Smart Money Screening"
summary: "Institutionelle Aktivität rund um eine Aktie als Kontextindikator bündeln."
section: "marktanalyse"
order: 30
---

Das **Smart Money Screening** aggregiert die Aktivität institutioneller und gut informierter Marktteilnehmer rund um eine Aktie zu einem Kontextindikator. Es ist **kein Kauf- oder Verkaufssignal**, sondern zeigt, wo mehrere unabhängige Quellen institutionelles Interesse erkennen lassen.

## Datenquellen

OpenFolio kombiniert unter anderem:
- **Insider-Käufe** (SEC Form 4 / OpenInsider) — einzelne grosse Käufe und Cluster mehrerer Insider.
- **13F-Filings** (SEC) — Positionen und quartalsweise Veränderungen bekannter [Superinvestoren](#glossar-link) (via Dataroma).
- **Aktivisten** (SEC 13D/13G) und **Aktienrückkäufe** (SEC-Filings).
- **Congressional Trading** (Capitol Trades) und **Short-Daten** (FINRA, Fails-to-Deliver).
- **SIX-Management-Transaktionen** für Schweizer Titel und **Analysten-Revisionen**.

## Der Smart Money Score

Aus den gefeuerten Signalen wird ein **Score** gebildet: Käufer-Signale erhöhen ihn (z.B. Insider-Cluster +3, Superinvestor-Konsens +2), Risiko-Signale wie ein anhaltender Short-Trend oder Fails-to-Deliver senken ihn (−1). Ungewöhnliches Volumen ist rein informativ und beeinflusst den Score nicht. Die genauen Gewichte findest du im [Glossar](#glossar-link) bei den einzelnen Begriffen.

## Daten-Aktualität

Die Pipelines laufen täglich (Screening-Scan um 09:30 CET); 13F- und Form-4-Daten werden morgens aktualisiert, COT wöchentlich. Beachte die quellbedingten Verzögerungen: 13F-Filings hinken rund 45 Tage hinterher, Congressional Trades bis zu 45 Tage.

> Wichtig: Smart-Money-Signale sind ein **Kontextindikator**. Kombiniere sie mit dem [Setup-Score](#setup-score) und dem [Marktklima](#marktklima) — sie ersetzen keine eigene Analyse.
