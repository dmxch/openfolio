# OpenFolio — Architektur-Dokumentation

> Dieses Dokument erklärt, wie OpenFolio aufgebaut ist und funktioniert — ohne Programmierkenntnisse vorauszusetzen. Alle Fachbegriffe werden beim ersten Auftreten erklärt.

---

## Inhaltsverzeichnis

1. [Was ist OpenFolio?](#1-was-ist-openfolio)
2. [Die Bausteine](#2-die-bausteine)
3. [Wie kommen die Daten rein?](#3-wie-kommen-die-daten-rein)
4. [Wie werden Kurse aktualisiert?](#4-wie-werden-kurse-aktualisiert)
5. [Wie wird der Portfolio-Wert berechnet?](#5-wie-wird-der-portfolio-wert-berechnet)
6. [Wie funktioniert die Renditeberechnung?](#6-wie-funktioniert-die-renditeberechnung)
7. [Das Scoring-System](#7-das-scoring-system)
8. [Sicherheit](#8-sicherheit)
9. [Frontend — was der User sieht](#9-frontend--was-der-user-sieht)
10. [Wie hängt alles zusammen?](#10-wie-hängt-alles-zusammen)
11. [Qualitätssicherung](#11-qualitätssicherung)
12. [Glossar](#12-glossar)

---

## 1. Was ist OpenFolio?

OpenFolio ist ein selbst gehostetes Portfolio-Management-Tool für systematisches Investieren. Es hilft dir, den Überblick über deine Aktien, ETFs, Kryptowährungen, Edelmetalle, Immobilien und Private Equity zu behalten.

Das Besondere: OpenFolio verlässt sich nicht auf Bauchgefühl, sondern auf **regelbasierte Marktanalyse**. Ein Scoring-System mit 18 Kriterien bewertet automatisch, ob eine Aktie ein starkes technisches Setup hat. Dazu kommen automatische Warnungen bei Stop-Loss-Verletzungen, Earnings-Terminen und Marktklima-Veränderungen.

Alle Daten bleiben auf deinem eigenen Server — kein Cloud-Dienst, keine Abhängigkeit von Drittanbietern für die Datenspeicherung.

---

## 2. Die Bausteine

### Was ist ein Container?

Stell dir einen Container vor wie eine **eigenständige Maschine in einer Fabrik**. Jede Maschine hat genau eine Aufgabe, enthält alles was sie dafür braucht, und kann unabhängig von den anderen gestartet oder gestoppt werden. Ein Container ist eine isolierte Umgebung, die ein Programm und alle seine Abhängigkeiten enthält.

### Docker Compose — der Orchesterdirigent

**Docker Compose** (ein Werkzeug, das mehrere Container gemeinsam verwaltet) ist wie ein Orchesterdirigent: Es sorgt dafür, dass alle Instrumente zur richtigen Zeit einsetzen, aufeinander hören und zusammenspielen. Mit einem einzigen Befehl startet es alle sechs Container von OpenFolio in der richtigen Reihenfolge.

### Die sechs Container

#### 1. Datenbank (PostgreSQL)

**Was es ist:** Die Datenbank ist das **Archiv** von OpenFolio — wie ein grosser Aktenschrank, in dem alles dauerhaft gespeichert wird: Positionen, Transaktionen, Benutzer, Kursdaten, Snapshots.

**Technologie:** PostgreSQL 16, eine bewährte Open-Source-Datenbank, die auch von grossen Unternehmen eingesetzt wird.

**Besonderheiten:**
- Bekommt 4 GB Arbeitsspeicher und optimierte Einstellungen für schnelle Abfragen
- Speichert die Daten auf einem permanenten Speicherbereich (Volume), der auch Container-Neustarts überlebt
- Wird alle 10 Sekunden geprüft, ob sie noch erreichbar ist (Healthcheck)

#### 2. Redis — der Zwischenspeicher

**Was es ist:** Redis ist wie ein **Notizzettel neben dem Aktenschrank**. Statt jedes Mal den ganzen Schrank zu öffnen, schaut man zuerst auf den Zettel, ob die Antwort schon dort steht. Das macht alles viel schneller.

**Technologie:** Redis 7, ein extrem schneller In-Memory-Speicher (hält Daten im Arbeitsspeicher statt auf der Festplatte).

**Was wird zwischengespeichert:**
- Aktienkurse (damit nicht bei jedem Seitenaufruf die Börse abgefragt wird)
- FX-Kurse (Wechselkurse zwischen Währungen)
- Portfolio-Berechnungen
- Scoring-Ergebnisse

**Besonderheit:** Wenn der Speicher voll ist (max. 512 MB), werden die ältesten Einträge automatisch gelöscht (LRU-Strategie — Least Recently Used, also „am längsten nicht benutzt").

#### 3. Backend — das Gehirn

**Was es ist:** Das Backend ist die **Küche des Restaurants**. Der Gast (das Frontend) bestellt etwas, und die Küche bereitet es zu: Daten laden, berechnen, zusammenstellen, zurückliefern.

**Technologie:** Python mit FastAPI (ein Framework, also ein Baukasten, für schnelle Webschnittstellen).

**Aufgaben:**
- Nimmt Anfragen vom Frontend entgegen (über eine API — eine Schnittstelle, über die Programme miteinander kommunizieren)
- Berechnet Portfolio-Werte, Renditen, Scores
- Verwaltet Benutzer und deren Zugriffsrechte
- Kommuniziert mit der Datenbank und dem Cache

**Aufbau:** Das Backend ist in verschiedene Bereiche aufgeteilt:
- **API-Router** (20 Dateien): Nehmen die Bestellungen entgegen — je ein Router für Portfolios, Positionen, Transaktionen, Importe, Analyse, usw.
- **Services** (49 Dateien): Die eigentliche Geschäftslogik — hier passiert die Arbeit
- **Models** (24 Dateien): Beschreiben die Datenstrukturen (wie sieht eine Position aus? Was hat eine Transaktion für Felder?)

#### 4. Worker — der Nachtarbeiter

**Was es ist:** Der Worker ist wie ein **fleissiger Hausmeister**, der im Hintergrund aufräumt und Daten aktualisiert, ohne dass der Benutzer davon etwas merkt.

**Technologie:** Dasselbe Python-Programm wie das Backend, aber mit einem speziellen Startbefehl, der den Scheduler (Aufgabenplaner) aktiviert.

**Geplante Aufgaben:**

| Aufgabe | Zeitplan | Beschreibung |
|---|---|---|
| Kurs-Refresh | Alle 60 Sekunden (Mo-Fr, 8-23 Uhr) | Aktuelle Kurse von yfinance, CoinGecko, Gold.org holen |
| Tages-Refresh | Täglich 7:00 Uhr | Vollständiger Refresh inkl. Makro-Indikatoren, Earnings-Termine, Snapshots |
| Token-Aufräumung | Täglich 3:00 Uhr | Abgelaufene Login-Tokens löschen |
| Breakout-Alarm | Täglich 22:30 Uhr | Watchlist auf Donchian-Breakouts prüfen |
| ETF 200-DMA Alarm | Täglich 22:35 Uhr | Breit-ETFs auf 200-Tage-Durchschnitt prüfen |

**Sicherheitsmechanismus:** Der Worker nutzt einen sogenannten Advisory Lock (Datenbanksperre). Das verhindert, dass zwei Worker gleichzeitig dieselbe Arbeit machen — wie ein Schild „Besetzt" an der Tür.

#### 5. Frontend (Nginx)

**Was es ist:** Das Frontend ist die **Theke des Restaurants** — die schöne Oberfläche, die der Gast sieht. Dahinter steht Nginx (ausgesprochen „Engine-X"), ein Webserver, der die Webseite ausliefert.

**Doppelrolle von Nginx:**
1. **Webseiten-Auslieferer:** Gibt die HTML-, CSS- und JavaScript-Dateien an den Browser aus
2. **Reverse Proxy** (Vermittler): Leitet API-Anfragen an das Backend weiter, wie ein Kellner, der Bestellungen in die Küche bringt

**Sicherheitsfeatures:**
- Rate Limiting: Maximal 60 API-Anfragen pro Minute pro Benutzer (Schutz vor Überlastung)
- Security Headers: Schutzmechanismen gegen verschiedene Angriffsarten (Clickjacking, Cross-Site-Scripting, usw.)
- Kompression: Dateien werden beim Ausliefern komprimiert, damit die Seite schneller lädt
- Statische Dateien (Bilder, Schriften) werden für ein Jahr im Browser zwischengespeichert

#### 6. Uptime Kuma — der Wächter

**Was es ist:** Uptime Kuma ist ein **Überwachungstool**, wie eine Sicherheitskamera für die Infrastruktur. Es prüft regelmässig, ob alle Dienste laufen und schlägt Alarm, wenn etwas nicht erreichbar ist.

### Netzwerke

Die Container sind in zwei Netzwerke aufgeteilt:
- **Backend-Netzwerk:** Datenbank, Redis, Backend, Worker (die interne Infrastruktur)
- **Frontend-Netzwerk:** Frontend, Backend (nur das Backend ist in beiden Netzen, weil es die Brücke zwischen Frontend und Daten bildet)

Das ist wie eine Firma, in der die Werkstatt (Backend-Netzwerk) vom Empfangsbereich (Frontend-Netzwerk) getrennt ist. Nur der Projektleiter (Backend) hat Zutritt zu beiden.

---

## 3. Wie kommen die Daten rein?

### Der Import-Ablauf

Stell dir vor, du bringst einen Stapel Kontoauszüge zum Buchhalter. Der Import funktioniert in fünf Schritten:

#### Schritt 1: Datei hochladen
Du lädst eine CSV-Datei (eine Tabellendatei, ähnlich wie Excel, aber als reiner Text) hoch. Das System akzeptiert nur CSV-Dateien bis maximal 10 MB.

#### Schritt 2: Erkennung (Parse)
Das System erkennt automatisch, von welchem Broker die Datei stammt — unterstützt werden Swissquote, Interactive Brokers und Pocket. Es liest die Spalten aus und ordnet sie den richtigen Feldern zu (Ticker, Datum, Anzahl, Preis, Gebühren).

#### Schritt 3: Vorschau (Preview)
Du bekommst eine Übersicht aller erkannten Transaktionen. Hier kannst du prüfen, ob alles korrekt zugeordnet wurde. Falls das System eine Spalte nicht richtig erkannt hat, kannst du die Zuordnung manuell anpassen (Remapping).

#### Schritt 4: Bestätigung (Confirm)
Erst wenn du bestätigst, werden die Daten tatsächlich in die Datenbank geschrieben. Für jeden Ticker wird entweder eine bestehende Position aktualisiert oder eine neue erstellt.

#### Schritt 5: Neuberechnung
Nach dem Import wird automatisch:
- Alle Positionen neu durchgerechnet (Einstandspreis, aktuelle Bewertung)
- Der Portfolio-Cache ungültig gemacht, damit beim nächsten Aufruf frische Zahlen erscheinen
- Ein neuer Snapshot (Momentaufnahme des Portfolio-Werts) erstellt

### Was bei einem Import passiert

Für jede importierte Transaktion erstellt das System:
1. Eine **Transaktion** (Kauf, Verkauf, Dividende) mit allen Details
2. Aktualisiert die **Position** (addiert Shares bei Kauf, reduziert bei Verkauf)
3. Berechnet den neuen **Einstandswert in CHF** (inkl. Gebühren und damaligem Wechselkurs)

---

## 4. Wie werden Kurse aktualisiert?

### Der 60-Sekunden-Takt

Während der erweiterten Handelszeiten (Montag bis Freitag, 8:00 bis 23:00 Uhr Schweizer Zeit) holt der Worker alle 60 Sekunden die neuesten Kurse.

### Datenquellen

| Quelle | Liefert | Für |
|---|---|---|
| **yfinance** (Yahoo Finance) | Aktienkurse, ETF-Kurse, Indizes, Wechselkurse | Aktien, ETFs, VIX |
| **CoinGecko** | Kryptowährungs-Preise in CHF | Bitcoin, Ethereum, usw. |
| **Gold.org** | Goldpreis in CHF pro Unze | Physisches Gold |
| **FRED** (Federal Reserve) | Makro-Indikatoren (US-Wirtschaftsdaten) | Marktklima-Analyse |
| **FMP** (Financial Modeling Prep) | Ergänzende Fundamentaldaten | Scoring, Earnings |

### Der Caching-Mechanismus (Zwischenspeicher)

Kurse werden in drei Ebenen gespeichert — wie ein dreistufiges Regal:

1. **Redis-Cache** (schnellster Zugriff): Aktienkurse bleiben hier ca. 60 Sekunden. Jede Anfrage schaut zuerst hier.
2. **Datenbank-Cache**: Kurse werden auch in die Datenbank geschrieben. Falls Redis leer ist, wird hier gesucht (heutiger Tag).
3. **Fallback** (Notlösung): Wenn weder Redis noch die Tages-Daten verfügbar sind, werden bis zu 5 Tage alte Kurse aus der Datenbank genommen. Das verhindert, dass eine Position plötzlich mit 0 bewertet wird.

### Stale-Erkennung

Wenn gar kein Kurs gefunden werden kann, markiert das System die Position als „stale" (veraltet) und zeigt stattdessen den Einstandswert an. Die Oberfläche kennzeichnet solche Positionen, damit du weisst, dass der angezeigte Wert nicht aktuell ist.

### Wechselkurse (FX-Rates)

Da OpenFolio alles in Schweizer Franken (CHF) anzeigt, werden Wechselkurse für alle im Portfolio vorkommenden Währungen geladen (USD, EUR, GBP, usw.). Diese kommen ebenfalls von Yahoo Finance und werden gesammelt in einem einzigen Abruf geholt (Batch-Verfahren), um die Geschwindigkeit zu erhöhen.

---

## 5. Wie wird der Portfolio-Wert berechnet?

### Die heilige Formel

In OpenFolio gibt es Berechnungen, die als **„heilig" gelten**. Das bedeutet: Sie dürfen nur mit ausdrücklicher Genehmigung des Maintainers geändert werden. Der Grund: Schon eine kleine Änderung an diesen Formeln würde alle Portfolio-Werte, Renditen und historischen Daten verfälschen. Es ist wie das Rezept eines Sternekochs — eine Zutat ändern, und das ganze Gericht schmeckt anders.

### Die drei Grundwerte

Für jede Position werden drei Werte berechnet:

#### 1. Einstandswert (cost_basis_chf)
**Was ist investiert worden — in CHF zum damaligen Kurs?**

Der Einstandswert ist der historische CHF-Wert zum Kaufzeitpunkt. Er berücksichtigt:
- Den Kaufpreis in der Originalwährung
- Den Wechselkurs am Kauftag
- Alle Gebühren (Courtagen, Stempel, Wechselgebühren)

Beispiel: Du kaufst 10 Apple-Aktien für je 150 USD bei einem Kurs von 0.90 CHF/USD mit 15 CHF Gebühren:
Einstandswert = (10 × 150 × 0.90) + 15 = 1'365 CHF

#### 2. Marktwert (value_chf)
**Was ist die Position heute wert — in CHF?**

Die Formel: **Anzahl Aktien × aktueller Kurs × aktueller Wechselkurs**

Beispiel: 10 Apple-Aktien × 175 USD × 0.88 CHF/USD = 1'540 CHF

#### 3. Performance in Prozent (perf_pct)
**Wie viel habe ich gewonnen oder verloren?**

Die Formel: **((Marktwert / Einstandswert) - 1) × 100**

Beispiel: ((1'540 / 1'365) - 1) × 100 = +12.82%

### Spezialfälle

| Typ | Bewertung |
|---|---|
| **Aktien & ETFs** | Kurs von Yahoo Finance × FX-Rate |
| **Krypto** | Preis in CHF direkt von CoinGecko |
| **Gold** | Preis pro Unze in CHF von Gold.org |
| **Cash & Vorsorge** | Einstandswert = Marktwert (keine Kursschwankung) |
| **Immobilien** | Werden NICHT in die liquide Performance eingerechnet |
| **Private Equity** | Wird KOMPLETT aus der Performance-Berechnung ausgeschlossen |
| **Manuelle Preise** | Einige Positionen können manuell bepreist werden (z.B. illiquide Anlagen) |

### Allokationen (Aufteilungen)

Das System berechnet automatisch, wie dein Portfolio aufgeteilt ist:
- **Nach Typ:** Aktien, ETFs, Krypto, Cash, usw.
- **Nach Stil:** Core (Kernpositionen) vs. Satellite (taktische Positionen)
- **Nach Sektor:** Technologie, Gesundheit, Finanzen, usw.
- **Nach Währung:** CHF, USD, EUR, usw.

Bei Multi-Sektor-ETFs (ETFs, die mehrere Branchen abdecken) werden die Sektoren anteilig aufgeteilt, basierend auf gespeicherten Gewichtungen.

---

## 6. Wie funktioniert die Renditeberechnung?

Die Renditeberechnung ist ebenfalls „heilig" — sie darf nur mit Freigabe geändert werden.

### Das Problem

Rendite berechnen klingt einfach: „Am Anfang hatte ich X, jetzt habe ich Y." Aber was, wenn du zwischendurch Geld einzahlst oder abhebst? Dann ist ein einfacher Vergleich verfälscht, weil der Zuwachs teilweise von deiner Einzahlung stammt und nicht von der Marktentwicklung.

### Lösung 1: Modified Dietz (für Monatsrenditen)

**Analogie:** Stell dir vor, du hast ein Sparkonto. Am 1. des Monats sind 10'000 CHF drauf. Am 15. zahlst du 5'000 CHF ein. Am Monatsende sind 15'800 CHF auf dem Konto. Wie viel hat das Konto „verdient"?

Die **Modified-Dietz-Methode** berücksichtigt, dass die 5'000 CHF nur die Hälfte des Monats investiert waren. Sie gewichtet jeden Geldfluss danach, wie lange er im Monat investiert war.

Die Formel in Worten:
> Rendite = (Endwert - Startwert - Einzahlungen) / (Startwert + gewichtete Einzahlungen)

Die Gewichtung funktioniert so: Eine Einzahlung am 1. des Monats zählt voll (100%), eine am 15. nur halb (50%), eine am 30. fast gar nicht (3%).

Diese Methode wird für **jeden einzelnen Monat** angewendet.

### Lösung 2: XIRR (für Jahres- und Gesamtrendite)

**Analogie:** XIRR (Extended Internal Rate of Return — erweiterte interne Rendite) ist wie ein Gutachter, der rückblickend sagt: „Wenn du das Geld stattdessen auf ein Sparkonto mit festem Zinssatz gelegt hättest — welcher Zinssatz hätte dasselbe Ergebnis geliefert?"

XIRR berücksichtigt:
- Den Startwert des Portfolios
- Alle Ein- und Auszahlungen mit ihrem genauen Datum
- Den Endwert des Portfolios

Es berechnet dann eine **annualisierte Rendite** (auf ein Jahr hochgerechnet), egal ob der Zeitraum 3 Monate oder 5 Jahre ist.

**Für das laufende Jahr** wird die XIRR-Rendite wieder auf den tatsächlichen Zeitraum heruntergerechnet (de-annualisiert), damit die Zahl realistisch bleibt.

### Warum zwei Methoden?

| Methode | Verwendet für | Stärke |
|---|---|---|
| Modified Dietz | Einzelne Monate | Schnell, genau genug für kurze Perioden |
| XIRR | Jahrestal, YTD, Gesamtrendite | Präzise über lange Zeiträume mit vielen Transaktionen |

---

## 7. Das Scoring-System

### Überblick

Das Scoring-System bewertet Aktien anhand von **18 technischen Kriterien** (eine Art Checkliste). Jedes Kriterium kann bestanden (grün), nicht bestanden (rot) oder nicht verfügbar (grau) sein. Zusammen ergeben sie einen Prozentsatz, der die „Setup-Qualität" einer Aktie beschreibt.

### Die 18 Kriterien im Detail

#### Gruppe 1: Moving Averages (Gleitende Durchschnitte, 7 Kriterien)

Ein Moving Average (MA) ist der Durchschnittskurs der letzten X Tage. Er glättet tägliche Schwankungen und zeigt den übergeordneten Trend.

1. **Preis über MA200** — Der aktuelle Kurs liegt über dem 200-Tage-Durchschnitt (langfristiger Aufwärtstrend)
2. **Preis über MA150** — Kurs über dem 150-Tage-Durchschnitt
3. **Preis über MA50** — Kurs über dem 50-Tage-Durchschnitt (kurzfristiger Aufwärtstrend)
4. **MA50 über MA150** — Der kurzfristige Trend ist stärker als der mittelfristige
5. **MA50 über MA200** — Der kurzfristige Trend ist stärker als der langfristige
6. **MA150 über MA200** — Der mittelfristige Trend ist stärker als der langfristige
7. **MA200 steigend** — Der 200-Tage-Durchschnitt steigt seit einem Monat (der langfristige Trend dreht nach oben)

**Warum das wichtig ist:** Wenn alle gleitenden Durchschnitte richtig „gestapelt" sind (kurze über langen), ist die Aktie in einem gesunden Aufwärtstrend — wie ein Flugzeug im stabilen Steigflug.

#### Gruppe 2: Breakout (Ausbruch, 6 Kriterien)

8. **Donchian 20d Breakout** — Der Kurs hat das 20-Tage-Hoch überschritten (ein Donchian Channel ist ein Preiskanal basierend auf dem höchsten Hoch und tiefsten Tief der letzten 20 Tage)
9. **Volumen >= 1.5× Durchschnitt** — Der Ausbruch passiert mit überdurchschnittlich hohem Handelsvolumen (Bestätigung, dass viele Marktteilnehmer mitmachen)
10. **Über 150-DMA (Schwur 1)** — Preis liegt über dem 150-Tage-Durchschnitt
11. **Max 25% unter 52-Wochen-Hoch** — Die Aktie hat nicht zu viel verloren
12. **>= 30% über 52-Wochen-Tief** — Die Aktie hat sich deutlich vom Tief erholt

#### Gruppe 3: Relative Stärke (3 Kriterien)

Die **Mansfield Relative Stärke (MRS)** vergleicht die Kursentwicklung einer Aktie mit dem S&P 500 (dem wichtigsten US-Aktienindex). Berechnet wird sie als EMA(13) auf Wochendaten — ein exponentiell gewichteter 13-Wochen-Durchschnitt der relativen Stärke.

13. **MRS > 0** — Die Aktie entwickelt sich besser als der Gesamtmarkt
14. **MRS > 0.5** — Die Aktie ist deutlich stärker als der Markt
15. **MRS > 1.0** — Die Aktie ist ein Sektor-Leader (Branchenführer in Sachen Performance)

#### Gruppe 4: Volumen & Liquidität (2 Kriterien)

16. **Marktkapitalisierung > 2 Mrd.** — Die Firma ist gross genug, um nicht zu leicht manipuliert zu werden
17. **Durchschnittliches Volumen > 200'000** — Genug Handelsaktivität, um jederzeit kaufen/verkaufen zu können

#### Gruppe 5: Trendwende (1 Kriterium)

18. **3-Punkt-Umkehr erkannt** — Ein spezielles Chartmuster, das auf eine mögliche Trendwende hindeutet (nur relevant, wenn die Aktie unter dem 150-Tage-Durchschnitt liegt)

### Bewertung und Signale

Aus dem Score ergibt sich ein **Signal** — aber bewusst neutral formuliert (keine Kauf- oder Verkaufsbefehle):

| Score | Qualität | Signal | Bedeutung |
|---|---|---|---|
| >= 70% | STARK | **Kaufkriterien erfüllt** (bei Breakout) | Starkes Setup mit bestätigtem Ausbruch |
| >= 70% | STARK | **Warten auf Breakout** (ohne Breakout) | Setup ist gut, aber der Ausbruch fehlt noch |
| 45-69% | MODERAT | **Setup noch nicht stark genug** | Einige Kriterien erfüllt, aber nicht überzeugend |
| < 45% | SCHWACH | **Kriterien nicht erfüllt** | Die Aktie zeigt kein technisch starkes Bild |

#### Sonderfall: ETF 200-DMA Kaufsignal

Für breit diversifizierte ETFs (wie den S&P 500 oder den MSCI World) gibt es ein invertiertes Signal: Wenn der ETF **unter** seinem 200-Tage-Durchschnitt fällt, wird das als „Kaufkriterien erfüllt" angezeigt — basierend auf der Idee, dass breit diversifizierte Indizes sich langfristig immer erholen.

### MA-Status pro Position

Jede Position im Portfolio bekommt ausserdem einen Gesundheitsstatus basierend auf den gleitenden Durchschnitten:
- **GESUND** (grün): Kurs über allen relevanten MAs
- **WARNUNG** (gelb): Kurs über einigen, aber nicht allen MAs
- **KRITISCH** (rot): Kurs unter den meisten MAs

---

## 8. Sicherheit

### Login und Authentifizierung

#### JWT (JSON Web Token)

Ein JWT ist wie ein **digitaler Eintrittsstempel** im Club. Nach dem Login bekommst du einen Token (eine Art verschlüsselte Eintrittskarte), den dein Browser bei jeder Anfrage mitschickt. Das Backend prüft diesen Stempel und weiss: „Ah, das ist User X, der darf das."

**So funktioniert der Login-Ablauf:**

1. Du gibst E-Mail und Passwort ein
2. Das Backend prüft die Daten und erstellt zwei Tokens:
   - **Access Token** (kurzlebig): Wird für jede Anfrage verwendet
   - **Refresh Token** (langlebig): Wird benutzt, um einen neuen Access Token zu holen, wenn der alte abläuft
3. Der Access Token wird nur im Arbeitsspeicher gehalten (nicht im Browser-Speicher — sicherer gegen Diebstahl)
4. Der Refresh Token wird im localStorage (lokaler Browserspeicher) abgelegt, damit du nach dem Schliessen des Tabs eingeloggt bleibst

#### MFA (Multi-Faktor-Authentifizierung)

OpenFolio unterstützt TOTP-basierte Zwei-Faktor-Authentifizierung (wie Google Authenticator). Nach der Passwort-Eingabe muss ein zusätzlicher 6-stelliger Code eingegeben werden. Backup-Codes sind ebenfalls verfügbar, falls das MFA-Gerät verloren geht.

### Verschlüsselung

- **Passwörter** werden gehasht (in eine nicht umkehrbare Zeichenkette verwandelt) gespeichert — selbst ein Datenbankzugang verrät kein Passwort
- **TOTP-Secrets** (die geheimen Schlüssel für die Zwei-Faktor-Authentifizierung) werden verschlüsselt in der Datenbank abgelegt
- **Sensible Felder** (wie IBAN-Nummern bei Positionen) können verschlüsselt gespeichert werden
- Die Kommunikation zwischen Browser und Server ist über HTTPS verschlüsselt (HSTS-Header erzwingen dies)

### Rate Limiting — Schutz vor Überlastung

**Analogie:** Stell dir eine Postfiliale vor, die pro Minute nur 60 Pakete annimmt. Wer mehr schickt, muss warten. Das schützt vor:

- **Brute-Force-Attacken:** Jemand probiert tausende Passwörter durch → wird nach wenigen Versuchen gebremst
- **Überlastung:** Ein fehlerhaftes Script schickt endlos Anfragen → wird gedrosselt

Rate Limiting findet auf zwei Ebenen statt:
1. **Nginx:** 60 Anfragen pro Minute pro IP-Adresse
2. **Backend:** Zusätzliche, strengere Limits für sensible Endpunkte (Login: begrenzt, Import: 10 pro Minute)

### IDOR-Schutz

**IDOR** (Insecure Direct Object Reference — unsicherer direkter Objektzugriff) ist eine Angriffsart, bei der jemand versucht, auf fremde Daten zuzugreifen, indem er die ID in der Adresse ändert.

Beispiel: Dein Portfolio hat die ID `abc-123`. Was passiert, wenn du die URL änderst auf `xyz-789` (das Portfolio eines anderen Users)?

**Schutz in OpenFolio:** Bei jeder Datenbankabfrage wird geprüft, ob die angeforderten Daten auch wirklich zum eingeloggten Benutzer gehören. Jede Position, jede Transaktion, jeder Snapshot ist mit einer User-ID verknüpft. Die Abfragen filtern immer nach `user_id = aktueller Benutzer`.

### Weitere Sicherheitsmassnahmen

- **Container-Isolation:** Kein Container kann mehr Rechte erlangen als er hat (no-new-privileges, alle unnötigen Linux-Capabilities entfernt)
- **Request-Grössenlimit:** Maximale Upload-Grösse von 10 MB
- **Admin-Credentials werden nach dem Start gelöscht:** Das Admin-Passwort wird nach dem Erstellen des Admin-Users aus dem Speicher entfernt
- **Security Headers:** Schutz gegen Clickjacking (X-Frame-Options), MIME-Sniffing (X-Content-Type-Options) und Cross-Site-Scripting (CSP)

---

## 9. Frontend — was der User sieht

### Technologie

Das Frontend ist mit **React** gebaut — einer JavaScript-Bibliothek, die Webseiten aus wiederverwendbaren Bausteinen (Komponenten) zusammensetzt. Stell dir Lego vor: Jeder Baustein (Button, Tabelle, Chart) ist ein eigenständiges Teil, das zusammengesetzt die Seite ergibt.

**Styling:** Tailwind CSS sorgt für das Erscheinungsbild. OpenFolio nutzt ein dunkles Theme (Dark Mode), das den Augen bei langer Nutzung schont.

**Icons:** Lucide Icons — eine einheitliche Icon-Bibliothek.

**Charts:** Recharts für die Diagramme (Portfolio-Verlauf, Allokationen, Monatsrenditen).

### Lazy Loading — Seiten auf Abruf

Nicht alle Seiten werden beim ersten Besuch geladen. Stell dir vor, du betrittst eine Bibliothek: Du holst nicht sofort alle Bücher vom Regal, sondern nur das, das du gerade lesen willst.

**Lazy Loading** bedeutet, dass eine Seite erst geladen wird, wenn du sie tatsächlich aufrufst. Das macht den ersten Seitenaufbau deutlich schneller.

### Wie Daten geholt werden

#### AuthContext — der Türsteher

Der AuthContext (Authentifizierungs-Kontext) verwaltet den Login-Zustand:
- Ist der Benutzer eingeloggt?
- Wie heisst er?
- Tokens für API-Aufrufe
- Automatisches Session-Erneuern (Refresh)

#### DataContext — der Datenbote

Der DataContext holt und verwaltet die Portfolio- und Watchlist-Daten:
- Beim Login werden Portfolio-Daten und Watchlist sofort geladen
- Alle 65 Sekunden wird automatisch im Hintergrund aktualisiert (etwas länger als die 60 Sekunden des Workers, um Race Conditions — Wettlaufsituationen — zu vermeiden)
- Daten werden zwischengespeichert: Wenn du zwischen Seiten wechselst, wird nicht jedes Mal neu geladen
- Doppelte Anfragen werden verhindert: Wenn bereits ein Abruf läuft, wird kein zweiter gestartet

#### useApi — der Briefträger

Jede Anfrage an das Backend geht über einen speziellen Hook (Hilfsfunktion) namens `authFetch`. Dieser fügt automatisch den Login-Token hinzu und stellt sicher, dass nur authentifizierte Anfragen gesendet werden.

---

## 10. Wie hängt alles zusammen?

### Beispiel: „User klickt auf Portfolio"

Hier ist der komplette Weg einer Anfrage — von deinem Klick bis zur Zahl auf dem Bildschirm:

```
1. 🖱️ DU klickst auf „Portfolio"

2. 📱 BROWSER (React/DataContext)
   → Prüft: Sind frische Daten im Cache? (< 65 Sekunden alt)
   → Falls ja: Zeigt sofort die gecachten Daten an. Fertig.
   → Falls nein: Sendet Anfrage an /api/portfolio/summary

3. 🌐 NGINX (Reverse Proxy)
   → Empfängt die Anfrage
   → Prüft Rate Limit (nicht mehr als 60/min?)
   → Leitet weiter an Backend-Container

4. 🔐 BACKEND (Auth-Middleware)
   → Liest den JWT-Token aus dem Header
   → Prüft: Ist der Token gültig? Ist der User aktiv?
   → Falls ungültig: Sendet Fehler 401 „Nicht authentifiziert"

5. 📊 BACKEND (Portfolio-Service)
   → Lädt alle aktiven Positionen des Users aus der Datenbank
   → Für jede Position:
     a) Holt aktuellen Kurs (Redis → DB → yfinance-Fallback)
     b) Holt Wechselkurs für die Währung
     c) Berechnet: Marktwert = Aktien × Kurs × FX-Rate
     d) Berechnet: Performance = (Marktwert / Einstandswert - 1) × 100
     e) Berechnet: MA-Status und Mansfield RS
   → Berechnet Allokationen (Typ, Sektor, Währung, Stil)
   → Fasst alles in eine Antwort zusammen

6. ↩️ ANTWORT reist zurück
   Backend → Nginx → Browser

7. 📱 BROWSER (React)
   → Empfängt die Daten
   → Speichert sie im DataContext-Cache (65s gültig)
   → Rendert die Seite: Tabelle, Charts, Allokationen
   → Du siehst dein Portfolio!
```

### Hinter den Kulissen: Der Worker

Unabhängig von deinen Klicks arbeitet der Worker im Hintergrund:
- Alle 60 Sekunden: Neue Kurse holen und in Redis + Datenbank speichern
- Morgens um 7: Voller Refresh mit Makro-Daten, Earnings-Termine, Snapshots
- Abends um 22:30: Breakout-Alerts prüfen und per E-Mail benachrichtigen

Das bedeutet: Wenn du die Seite öffnest, sind die Kurse meistens schon aktuell, weil der Worker sie bereits im Hintergrund aktualisiert hat.

---

## 11. Qualitätssicherung

### Tests

OpenFolio hat eine **pytest-Suite** (eine Sammlung automatisierter Tests), die prüft, ob die wichtigsten Funktionen korrekt arbeiten. Tests können mit einem Befehl ausgeführt werden und geben sofort Feedback, ob etwas kaputt ist.

### Der Audit-Agent

Vor jedem Merge (Zusammenführen von Code-Änderungen) läuft ein automatisierter **Audit-Agent** (`@openfolio-audit`). Dieser prüft:
- Sicherheitsaspekte (keine Geheimnisse im Code?)
- Code-Qualität (konsistente Patterns, keine offensichtlichen Fehler?)
- Barrierefreiheit (Accessibility)
- Performance-Probleme (z.B. N+1 Queries — wenn die Datenbank unnötig oft abgefragt wird)
- Nginx-Konfiguration (Sicherheitsheader korrekt?)

**Kein Code wird zusammengeführt, ohne dass der Audit grün ist.**

### Die vier Agenten

OpenFolio nutzt spezialisierte KI-Agenten für verschiedene Aufgaben:

| Agent | Aufgabe |
|---|---|
| **Audit** | Prüft Code-Änderungen auf Qualität und Sicherheit |
| **Fixer** | Behebt gefundene Probleme automatisch |
| **Release** | Erstellt neue Versionen mit Changelog |
| **Design** | Prüft UI-Konsistenz und Barrierefreiheit |

### Diagnose-Reports

Grössere Analysen werden als separate Markdown-Dateien im Projektordner abgelegt, damit sie nachvollziehbar und versioniert sind.

---

## 12. Glossar

| Begriff | Erklärung |
|---|---|
| **API** | Application Programming Interface — eine Schnittstelle, über die Programme miteinander kommunizieren. Wie ein Kellner, der Bestellungen zwischen Gast und Küche vermittelt. |
| **Async / Asynchron** | Eine Arbeitsweise, bei der das Programm nicht wartet, bis eine Aufgabe fertig ist, sondern in der Zwischenzeit andere Dinge erledigt. Wie ein Koch, der Wasser aufsetzt und während des Wartens schon Gemüse schneidet. |
| **Cache** | Ein Zwischenspeicher für häufig benötigte Daten, damit sie nicht jedes Mal neu berechnet oder geladen werden müssen. |
| **Container** | Eine isolierte Umgebung, die ein Programm mit allen Abhängigkeiten enthält. Wie ein Koffer, der alles enthält, was man für eine Reise braucht. |
| **CORS** | Cross-Origin Resource Sharing — eine Sicherheitsregel, die bestimmt, von welchen Adressen aus das Backend Anfragen akzeptiert. |
| **CSV** | Comma-Separated Values — eine Textdatei, in der Daten durch Kommas getrennt sind (ähnlich einer einfachen Excel-Tabelle). |
| **Docker Compose** | Ein Werkzeug, das mehrere Container gemeinsam verwaltet und orchestriert. |
| **Donchian Channel** | Ein Preiskanal, der aus dem höchsten Hoch und tiefsten Tief der letzten 20 Tage besteht. Ein Ausbruch über das Hoch gilt als Kaufsignal. |
| **EMA** | Exponential Moving Average — ein gleitender Durchschnitt, der neuere Kurse stärker gewichtet als ältere. |
| **Endpoint** | Ein spezifischer Zugangspunkt einer API, z.B. `/api/portfolio/summary`. Wie eine bestimmte Theke in einem Amt. |
| **FX-Rate** | Foreign Exchange Rate — ein Wechselkurs zwischen zwei Währungen (z.B. USD zu CHF). |
| **Healthcheck** | Eine automatische Prüfung, ob ein Dienst noch funktioniert. Wie ein regelmässiger Puls-Check. |
| **JWT** | JSON Web Token — ein verschlüsselter Ausweis, der bei jeder Anfrage mitgeschickt wird, um den Benutzer zu identifizieren. |
| **Lazy Loading** | Daten oder Seiten werden erst geladen, wenn sie tatsächlich gebraucht werden, statt alles auf einmal. |
| **MA / Moving Average** | Gleitender Durchschnitt — der Mittelwert der Schlusskurse über eine bestimmte Anzahl Tage (z.B. MA200 = letzten 200 Tage). |
| **MFA** | Multi-Faktor-Authentifizierung — Login mit Passwort plus einem zusätzlichen Faktor (z.B. Code auf dem Handy). |
| **Modified Dietz** | Eine Methode zur Renditeberechnung, die Geldflüsse (Ein-/Auszahlungen) zeitgewichtet berücksichtigt. |
| **MRS / Mansfield RS** | Mansfield Relative Stärke — vergleicht die Performance einer Aktie mit dem S&P 500. Positiv = besser als der Markt. |
| **Nginx** | Ein schneller Webserver, der auch als Reverse Proxy (Vermittler) eingesetzt wird. |
| **PostgreSQL** | Ein leistungsfähiges Open-Source-Datenbanksystem für strukturierte Daten. |
| **Pydantic** | Eine Python-Bibliothek, die sicherstellt, dass eingehende Daten das richtige Format haben (Validierung). Wie ein Zollbeamter, der prüft, ob alle Papiere korrekt sind. |
| **Rate Limiting** | Begrenzung der Anzahl Anfragen pro Zeiteinheit, um Missbrauch und Überlastung zu verhindern. |
| **Redis** | Ein extrem schneller Zwischenspeicher, der Daten im Arbeitsspeicher hält. |
| **Reverse Proxy** | Ein Vermittler, der Anfragen entgegennimmt und an den richtigen Server weiterleitet. Der Benutzer kommuniziert nie direkt mit dem Backend. |
| **Router** | In einer API: Ein Modul, das Anfragen für einen bestimmten Bereich verarbeitet (z.B. alles rund um Portfolios). |
| **Scheduler** | Ein Aufgabenplaner, der Aktionen zu bestimmten Zeiten oder in bestimmten Intervallen ausführt. |
| **Snapshot** | Eine Momentaufnahme des Portfolio-Werts zu einem bestimmten Zeitpunkt. Wird täglich gespeichert und für die Renditeberechnung verwendet. |
| **SQLAlchemy** | Eine Python-Bibliothek, die als Übersetzer zwischen Python-Code und der Datenbank dient. Statt SQL (die Sprache der Datenbank) direkt zu schreiben, arbeitet man mit Python-Objekten. |
| **TOTP** | Time-Based One-Time Password — ein zeitbasierter Einmalcode (wie bei Google Authenticator). |
| **VIX** | Volatility Index — der „Angstindex" der Börse. Hohe Werte = viel Unsicherheit am Markt. |
| **Volume** | Ein dauerhafter Speicherbereich für Docker-Container, der Container-Neustarts überlebt. |
| **XIRR** | Extended Internal Rate of Return — eine Methode zur Berechnung der annualisierten Rendite unter Berücksichtigung aller Geldflüsse. |
| **yfinance** | Eine Python-Bibliothek, die Börsen- und Finanzdaten von Yahoo Finance abruft. |
