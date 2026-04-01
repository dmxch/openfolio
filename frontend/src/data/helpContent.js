// Help content for OpenFolio — all text in German
// Formatting markers: ## Heading, **bold**, > Callout, [text](#id)

export const HELP_CATEGORIES = {
  "erste-schritte": "Erste Schritte",
  "portfolio-management": "Portfolio-Management",
  "scoring-system": "Scoring-System",
  "marktanalyse": "Marktanalyse",
  "aktien-analyse": "Aktien-Analyse",
  "risikomanagement": "Risikomanagement",
  "watchlist": "Watchlist",
  "glossar": "Glossar",
};

export const HELP_SECTIONS = [
  {
    id: "erste-schritte",
    title: "Erste Schritte",
    icon: "Rocket",
    articles: [
      {
        id: "wichtiger-hinweis",
        title: "Wichtiger Hinweis",
        summary:
          "OpenFolio ist ein Software-Tool, kein Anlageberater.",
        content: `OpenFolio ist ein Software-Tool, **kein Anlageberater**.

Alle Analysen, Scoring-Ergebnisse und Signale in OpenFolio basieren auf technischen Indikatoren und öffentlich verfügbaren Marktdaten. Sie stellen **keine Aufforderung zum Kauf oder Verkauf** von Wertpapieren dar.

Die in der Hilfe beschriebenen Strategien und Regeln sind ein Analyse-Framework, das du nach eigenem Ermessen anwenden kannst. **Jede Anlageentscheidung liegt in deiner Verantwortung.**

Vergangene Wertentwicklungen sind kein verlässlicher Indikator für zukünftige Ergebnisse. Performance-Berechnungen sind mathematische Annäherungen und nicht für steuerliche Zwecke geeignet.

Für steuerliche und rechtliche Fragen wende dich bitte an einen qualifizierten Berater.`,
      },
      {
        id: "willkommen",
        title: "Willkommen bei OpenFolio",
        summary:
          "Ein Überblick über OpenFolio und was die App für dich tun kann.",
        content: `OpenFolio ist ein Open-Source-Portfoliomanager für systematisches Investieren. Die App hilft dir, dein gesamtes Vermögen an einem Ort zu verwalten — von Aktien und ETFs über Kryptowährungen bis hin zu Immobilien und Vorsorge.

## Was OpenFolio bietet

OpenFolio ist mehr als ein einfacher Portfolio-Tracker. Das integrierte **Scoring-System** analysiert Aktien anhand von 18 technischen Kriterien. Die **Marktanalyse** zeigt dir das aktuelle Marktumfeld.

Alle Berechnungen — von der Performance über die Allokation bis zum Risikomanagement — laufen automatisch. Du siehst auf einen Blick, wie sich dein Vermögen entwickelt und wo Handlungsbedarf besteht.

## Für wen ist OpenFolio?

OpenFolio richtet sich an Anleger, die regelbasiert investieren möchten. Anstatt auf Bauchgefühl zu setzen, nutzt du ein bewährtes System aus technischen Kriterien. Die App unterstützt das **Core/Satellite-Prinzip**: langfristige Kernpositionen kombiniert mit taktischen Chancen.

> Tipp: Starte mit dem [Portfolio einrichten](#portfolio-einrichten), um deine ersten Positionen zu erfassen. Den [CSV-Import](#csv-import) kannst du nutzen, wenn du bereits ein Depot bei Swissquote hast.

## Nächste Schritte

Konfiguriere zuerst deine [Einstellungen](#einstellungen), richte dann dein Portfolio ein und erkunde die Marktanalyse-Tools. OpenFolio lernt mit deinen Daten — je mehr Positionen du erfasst, desto aussagekräftiger werden die Analysen.`,
      },
      {
        id: "portfolio-einrichten",
        title: "Portfolio einrichten",
        summary:
          "So erfasst du deine ersten Positionen und baust dein Portfolio auf.",
        content: `Um dein Portfolio einzurichten, navigiere zum Bereich **Portfolio** und klicke auf «Position hinzufügen». Du kannst verschiedene Asset-Typen erfassen: Aktien, ETFs, Kryptowährungen, Edelmetalle, Cash, Vorsorge und Immobilien.

## Position erfassen

Für jede Position gibst du folgende Informationen ein: den **Ticker** (z.B. AAPL für Apple), die **Anzahl Anteile**, den **Kaufpreis** und das **Kaufdatum**. Bei ausländischen Aktien wird der Wechselkurs automatisch berücksichtigt und in CHF umgerechnet.

## Core oder Satellite?

Jede Position wird als **Core** oder **Satellite** klassifiziert. Core-Positionen sind langfristige Anlagen mit weiterem Stop-Loss (15–25%). Satellite-Positionen sind taktische Trades mit engerem Stop-Loss (5–12%). Das Ziel ist eine Verteilung von ca. 70% Core und 30% Satellite.

> Wichtig: Wähle den Positionstyp bewusst — er bestimmt, wie die Position im Risikomanagement behandelt wird. Mehr dazu unter [Core/Satellite-System](#core-satellite).

## Gebühren und Kosten

Erfasse bei jeder Transaktion auch die **Gebühren**. Diese fliessen in die Kostenbasis ein und sorgen für eine exakte Performance-Berechnung. Die Kostenbasis in CHF wird zum historischen Wechselkurs des Kaufzeitpunkts berechnet.

## Mehrere Käufe

Du kannst denselben Titel mehrfach kaufen. OpenFolio aggregiert alle Käufe zu einer Position und berechnet den durchschnittlichen Einstandspreis automatisch.`,
      },
      {
        id: "csv-import",
        title: "CSV-Import",
        summary:
          "Importiere Transaktionen direkt aus deinem Swissquote-Export.",
        content: `OpenFolio unterstützt den direkten Import von Transaktionen aus **Swissquote**-CSV-Dateien. Das spart dir die manuelle Eingabe und stellt sicher, dass alle Daten korrekt übernommen werden.

## CSV-Datei vorbereiten

Exportiere deine Transaktionshistorie aus Swissquote als CSV-Datei. Die Datei verwendet **Latin-1 Encoding** und **Semikolon als Trennzeichen** — du musst nichts daran ändern. Lade die Datei einfach so hoch, wie du sie von Swissquote erhalten hast.

## Import-Vorschau

Nach dem Upload siehst du eine **Vorschau** aller erkannten Transaktionen. Hier kannst du prüfen, ob Ticker, Stückzahl und Preise korrekt erkannt wurden. Erst wenn du die Vorschau bestätigst, werden die Daten in dein Portfolio übernommen.

## Was wird importiert?

Der Import erkennt automatisch Käufe, Verkäufe und Dividenden. **Teilausführungen** werden intelligent zusammengefasst — wenn eine Order in mehreren Teilen ausgeführt wurde, aggregiert OpenFolio diese zu einer Transaktion. Bonds werden automatisch übersprungen.

> Hinweis: Schweizer Aktien erhalten automatisch das Suffix **.SW**, irische und luxemburgische ETFs das Suffix **.L**. Die Zuordnung erfolgt über die ISIN-Nummer.

## Nach dem Import

Nach einem erfolgreichen Import werden alle Positionen automatisch neu berechnet. Die aktuellen Kurse werden abgerufen und die Performance-Daten aktualisiert. Du findest die importierten Transaktionen unter [Transaktionen](#transaktionen).`,
      },
      {
        id: "einstellungen",
        title: "Einstellungen konfigurieren",
        summary:
          "API-Keys, E-Mail-Benachrichtigungen und persönliche Präferenzen einrichten.",
        content: `Unter **Einstellungen** konfigurierst du OpenFolio nach deinen Bedürfnissen. Hier verwaltest du API-Keys, E-Mail-Versand und Anzeigeoptionen.

## API-Keys

Einige Funktionen benötigen externe API-Keys. Der **FRED API Key** schaltet Makro-Indikatoren wie den Buffett Indicator und die Zinsstrukturkurve frei. Der **FMP API Key** liefert Fundamentaldaten für US-Aktien. Beide Keys sind kostenlos erhältlich und optional — OpenFolio funktioniert auch ohne sie, aber mit eingeschränktem Funktionsumfang.

> Tipp: Alle API-Keys werden mit AES-256 verschlüsselt in der Datenbank gespeichert. Sie sind zu keinem Zeitpunkt im Klartext sichtbar.

## E-Mail-Benachrichtigungen

Konfiguriere einen **SMTP-Server**, um E-Mail-Benachrichtigungen für Alerts zu erhalten. Du brauchst: SMTP-Host, Port, Benutzername und Passwort. Die meisten E-Mail-Anbieter unterstützen SMTP — eine Anleitung findest du bei deinem Provider.

## Zahlenformat

Wähle dein bevorzugtes **Zahlenformat**: Schweiz (1'000.00), Deutschland (1.000,00) oder Englisch (1,000.00). Das Format wird überall in der App angewendet — bei Beträgen, Kursen und Prozentzahlen.

## Sicherheit

Unter Sicherheit kannst du dein Passwort ändern und die **Zwei-Faktor-Authentifizierung (MFA)** aktivieren. MFA schützt deinen Account mit einem zusätzlichen TOTP-Code. Nach der Aktivierung erhältst du Backup-Codes für den Notfall.

## Sitzungen

Du siehst alle aktiven Sitzungen und kannst einzelne Geräte abmelden. Refresh-Tokens sind 30 Tage gültig und rotieren automatisch.`,
      },
    ],
  },
  {
    id: "portfolio-management",
    title: "Portfolio-Management",
    icon: "Briefcase",
    articles: [
      {
        id: "portfolio-uebersicht",
        title: "Portfolio-Übersicht",
        summary:
          "Das Dashboard zeigt dein gesamtes Vermögen und die wichtigsten Kennzahlen.",
        content: `Die Portfolio-Übersicht ist dein zentrales Dashboard. Hier siehst du auf einen Blick, wie sich dein Vermögen zusammensetzt und entwickelt.

## Vermögensübersicht

Ganz oben findest du dein **Gesamtvermögen in CHF**. Darunter ist es aufgeteilt in liquides Vermögen (Aktien, ETFs, Crypto, Cash) und nicht-liquides Vermögen (Immobilien, Vorsorge). Die Performance bezieht sich nur auf das liquide Vermögen.

## Allokation

Die **Asset-Allokation** zeigt dir, wie dein Vermögen auf verschiedene Anlageklassen verteilt ist. Die **Sektor-Allokation** schlüsselt deine Aktien und ETFs nach Branchen auf. ETFs werden dabei anteilig auf ihre enthaltenen Sektoren verteilt.

## Performance-Karte

Die Karte zeigt die **Gesamtrendite** (Total Return) deines liquiden Portfolios, die Rendite seit Jahresbeginn (YTD) sowie die monatliche Entwicklung. Alle Werte werden nach der TTWROR-Methode berechnet.

> Hinweis: Immobilien und Vorsorge-Positionen werden bewusst nicht in die liquide Performance eingerechnet, da sie nicht frei handelbar sind.

## Positionsliste

Darunter findest du alle deine Positionen mit aktuellem Kurs, Tagesveränderung, Gesamtperformance und Gewichtung im Portfolio. Du kannst nach Asset-Typ, Sektor oder Core/Satellite filtern und die Tabelle nach verschiedenen Kriterien sortieren.`,
      },
      {
        id: "core-satellite",
        title: "Core/Satellite-System",
        summary:
          "Langfristige Kernpositionen kombiniert mit taktischen Satelliten.",
        content: `Das Core/Satellite-System ist das Herzstück der Portfolio-Strategie in OpenFolio. Es kombiniert langfristige Stabilität mit taktischer Flexibilität.

## Core-Positionen

**Core-Positionen** bilden das Fundament deines Portfolios (Ziel: ca. 70%). Das sind hochwertige Aktien und ETFs, die du langfristig hältst. Typisch: breit diversifizierte ETFs, Blue-Chip-Aktien mit stabilen Geschäftsmodellen oder Dividendentitel.

Core-Positionen haben einen **weiten Stop-Loss von 15–25%** unter dem Kaufpreis. Sie werden nur quartalsweise überprüft. Ein Verkauf erfolgt nur bei fundamentaler Verschlechterung oder wenn der Stop-Loss ausgelöst wird.

## Satellite-Positionen

**Satellite-Positionen** nutzen taktische Chancen (Ziel: ca. 30%). Das sind Breakout-Trades, Momentum-Plays oder spekulative Positionen. Sie haben einen **engen Stop-Loss von 5–12%** und werden wöchentlich überprüft.

> Wichtig: Der Positionstyp bestimmt die Stop-Loss-Strategie. Wähle ihn beim Anlegen der Position bewusst aus. Mehr dazu unter [Stop-Loss Strategie](#stop-loss).

## Warum dieses System?

Das Core/Satellite-System bietet zwei Vorteile: Die Core-Positionen sorgen für eine **solide Grundrendite** bei geringem Pflegeaufwand. Die Satellite-Positionen ermöglichen **höhere Renditen** in günstigen Marktphasen, ohne das Gesamtportfolio zu gefährden.

## Allokation prüfen

Im Dashboard siehst du die aktuelle Core/Satellite-Verteilung. Weicht sie stark vom Ziel ab, solltest du bei der nächsten Gelegenheit nachbessern — zum Beispiel durch Aufstockung der untergewichteten Seite.`,
      },
      {
        id: "aktien-etfs",
        title: "Aktien & ETFs",
        summary:
          "So verwaltest du Aktien und ETFs in deinem Portfolio.",
        content: `Aktien und ETFs sind die Hauptbausteine deines liquiden Portfolios. OpenFolio unterstützt Titel von allen grossen Börsenplätzen.

## Aktien hinzufügen

Beim Hinzufügen einer Aktie gibst du den **Ticker** ein (z.B. AAPL, NESN.SW, NOVO-B.CO). OpenFolio erkennt den Börsenplatz und lädt automatisch den aktuellen Kurs. Für Schweizer Aktien wird das Suffix .SW verwendet, für britische .L.

> Hinweis: Britische Aktien (.L) werden von yfinance in **Pence** geliefert. OpenFolio rechnet automatisch durch 100, um den Kurs in Pfund darzustellen.

## ETFs und Sektoren

Bei ETFs wird die **Sektorverteilung** automatisch aufgeschlüsselt. Ein S&P-500-ETF wird beispielsweise anteilig auf Technology, Healthcare, Financials usw. verteilt. Das gibt dir ein realistisches Bild deiner tatsächlichen Sektorgewichtung.

## Fremdwährungen

Aktien in Fremdwährung (USD, EUR, GBP usw.) werden automatisch in **CHF umgerechnet**. Der aktuelle Wechselkurs wird laufend aktualisiert. Deine Kostenbasis wird zum historischen Wechselkurs des Kaufdatums berechnet — so ist die Performance-Berechnung exakt.

## Dividenden

Dividendenzahlungen kannst du als Transaktion erfassen oder per [CSV-Import](#csv-import) importieren. Dividenden in Fremdwährung werden automatisch zum Tageskurs in CHF umgerechnet und fliessen in die Gesamtperformance ein.`,
      },
      {
        id: "crypto",
        title: "Kryptowährungen",
        summary:
          "Bitcoin und andere Kryptowährungen im Portfolio verwalten.",
        content: `OpenFolio unterstützt Kryptowährungen als eigene Asset-Klasse. Die Kurse werden über die **CoinGecko API** abgerufen.

## Krypto hinzufügen

Erfasse deine Krypto-Positionen mit der Anzahl Coins, dem Kaufpreis und dem Kaufdatum. Bitcoin wird direkt in CHF bewertet — es ist kein Umweg über USD nötig.

## Besonderheiten

Kryptowährungen werden separat in der Asset-Allokation ausgewiesen. Sie zählen zum **liquiden Vermögen** und fliessen in die Performance-Berechnung ein. Der Kurs wird regelmässig aktualisiert, wobei die Rate Limits der CoinGecko Free API beachtet werden.

> Tipp: Krypto-Positionen eignen sich typischerweise als Satellite-Position mit engem Stop-Loss, da sie eine hohe Volatilität aufweisen.

## Unterstützte Coins

Grundsätzlich werden alle Kryptowährungen unterstützt, die über CoinGecko verfügbar sind. Bitcoin (BTC) ist dabei die am häufigsten genutzte Position. Erfasse den Ticker so, wie er bei CoinGecko gelistet ist.`,
      },
      {
        id: "edelmetalle",
        title: "Physische Edelmetalle",
        summary:
          "Gold, Silber und andere physische Edelmetalle tracken.",
        content: `OpenFolio ermöglicht die Erfassung von physischen Edelmetallen als Teil deines Gesamtvermögens. Gold und Silber bieten eine Absicherung gegen Inflation und Krisen.

## Gold erfassen

Erfasse deine Goldbestände mit der **Menge in Unzen** (oder Gramm, umgerechnet in Unzen) und dem Kaufpreis. Der aktuelle Goldpreis wird automatisch abgerufen und in CHF umgerechnet.

## Rolle im Portfolio

Physische Edelmetalle gelten als **Wertaufbewahrung** und Versicherung. Sie zählen zum liquiden Vermögen und werden in der Asset-Allokation als eigene Kategorie ausgewiesen.

> Tipp: Viele Anleger halten 5–10% ihres Portfolios in physischem Gold als Krisenabsicherung. Edelmetalle sind typischerweise Core-Positionen ohne Stop-Loss.

## Performance

Die Performance wird wie bei anderen Assets berechnet: aktueller Wert in CHF im Verhältnis zur Kostenbasis in CHF. Beachte, dass physische Edelmetalle keine Dividenden oder Zinsen ausschütten — die Rendite kommt ausschliesslich aus der Kursentwicklung.`,
      },
      {
        id: "cash-konti",
        title: "Cash & Konti",
        summary:
          "Bargeldbestände und Kontoguthaben für die Gesamtübersicht erfassen.",
        content: `Cash-Positionen bilden deine liquiden Reserven ab — Bankkonten, Sparkonten oder Bargeld. Sie fliessen in das Gesamtvermögen und die Asset-Allokation ein.

## Warum Cash erfassen?

Cash ist ein wichtiger Teil deiner Gesamtstrategie. Es zeigt dir, wie viel **Kaufkraft** du für neue Investments hast. In der Asset-Allokation siehst du, ob dein Cash-Anteil im gewünschten Bereich liegt.

## Cash-Position anlegen

Erfasse den aktuellen Stand deines Kontos als Position. Du kannst mehrere Konten separat anlegen (z.B. Sparkonto, Tradingkonto). Aktualisiere den Betrag manuell, wenn sich der Kontostand ändert.

> Hinweis: Cash-Positionen haben keine automatische Kursaktualisierung. Der erfasste Betrag bleibt bestehen, bis du ihn manuell anpasst.

## Cash-Quote

Eine gewisse Cash-Quote ist strategisch sinnvoll. In einem ungünstigen Marktumfeld — wenn das [Makro-Gate](#makro-gate) blockiert — ist es besser, Cash zu halten als in fallende Kurse zu kaufen. Typische Cash-Quoten liegen zwischen 5% und 20% des liquiden Vermögens.`,
      },
      {
        id: "vorsorge",
        title: "Vorsorge (3a/PK)",
        summary:
          "Vorsorgegelder tracken — separat vom liquiden Vermögen.",
        content: `Vorsorge-Positionen bilden deine gebundenen Vorsorgegelder ab — Säule 3a, Pensionskasse oder Freizügigkeitskonten. Sie werden separat vom liquiden Vermögen geführt.

## Warum separat?

Vorsorgegelder sind **nicht frei verfügbar**. Du kannst sie nicht kurzfristig für Investitionen nutzen. Deshalb werden sie in OpenFolio bewusst nicht in die liquide Performance eingerechnet. Sie erscheinen aber im Gesamtvermögen.

## Vorsorge erfassen

Erfasse den aktuellen Wert deiner Vorsorgekonten als Position. Aktualisiere den Betrag periodisch, z.B. nach Erhalt des Jahresauszugs.

> Wichtig: Vorsorge-Positionen fliessen **nicht** in die Portfolio-Performance ein. Sie dienen ausschliesslich der Gesamtvermögensübersicht.

## Strategie

Die Säule 3a bietet steuerliche Vorteile — den jährlichen Maximalbetrag einzuzahlen ist für die meisten Anleger sinnvoll. In OpenFolio kannst du mehrere 3a-Konten separat erfassen und so den Überblick behalten.`,
      },
      {
        id: "immobilien",
        title: "Immobilien",
        summary:
          "Immobilienbesitz im Gesamtvermögen abbilden.",
        content: `Immobilien können als Position erfasst werden, um ein vollständiges Bild deines Gesamtvermögens zu erhalten. Sie werden wie Vorsorge separat vom liquiden Vermögen geführt.

## Immobilie erfassen

Erfasse den **aktuellen Marktwert** deiner Immobilie als Position. Ziehe allfällige Hypotheken ab, um den Nettowert (Eigenkapital) darzustellen. Aktualisiere den Wert periodisch, z.B. nach einer Schätzung.

> Wichtig: Immobilien werden **nicht** in die liquide Performance eingerechnet. Sie dienen der Gesamtvermögensübersicht und einer realistischen Asset-Allokation.

## Warum Immobilien tracken?

Auch wenn Immobilien nicht liquid sind, machen sie bei vielen Anlegern einen grossen Teil des Vermögens aus. Ohne sie wäre die Vermögensübersicht unvollständig. Du siehst so auf einen Blick, wie stark du in Immobilien vs. Finanzanlagen gewichtet bist.

## Hypotheken

Erfasse als Wert den **Nettowert** nach Abzug der Hypothek. Wenn deine Immobilie CHF 800'000 wert ist und die Hypothek CHF 500'000 beträgt, erfasst du CHF 300'000 als Positionswert.`,
      },
      {
        id: "performance",
        title: "Performance verstehen",
        summary:
          "Wie OpenFolio die Rendite berechnet: TTWROR, Kostenbasis und Währungseffekte.",
        content: `Die Performance-Berechnung in OpenFolio ist exakt und berücksichtigt Währungseffekte, Gebühren und Cashflows.

## Berechnungsmethode

OpenFolio verwendet die **TTWROR-Methode** (True Time-Weighted Rate of Return). Diese Methode eliminiert den Einfluss von Ein- und Auszahlungen und zeigt die reine Anlagerendite. Das ist der Industriestandard für Portfolio-Performance.

## Kostenbasis

Die **Kostenbasis** ist der Gesamtbetrag, den du für eine Position bezahlt hast — inklusive Gebühren. Bei Aktien in Fremdwährung wird der historische CHF-Wechselkurs zum Kaufzeitpunkt verwendet. Die Formel: Kostenbasis CHF = Anzahl × Kaufpreis × FX-Rate + Gebühren.

## Aktuelle Bewertung

Der **aktuelle Wert** einer Position berechnet sich als: Anzahl × aktueller Kurs × aktueller FX-Rate. Die Performance in Prozent ist dann: ((Wert / Kostenbasis) - 1) × 100.

> Wichtig: Die Performance enthält sowohl die Kursänderung als auch den Währungseffekt. Eine US-Aktie kann im Kurs steigen, aber trotzdem in CHF verlieren, wenn der Dollar fällt.

## Monatsrenditen

OpenFolio erstellt tägliche **Snapshots** deines Portfoliowerts. Daraus werden Monatsrenditen berechnet, die du im Performance-Chart sehen kannst. Die YTD-Rendite (Year-to-Date) zeigt die Entwicklung seit Jahresbeginn.`,
      },
      {
        id: "transaktionen",
        title: "Transaktionen",
        summary:
          "Alle Käufe, Verkäufe und Dividenden auf einen Blick verwalten.",
        content: `Unter **Transaktionen** findest du die vollständige Historie aller Portfoliobewegungen. Du kannst hier Transaktionen manuell erfassen, bearbeiten oder suchen.

## Transaktionstypen

OpenFolio kennt drei Transaktionstypen: **Kauf**, **Verkauf** und **Dividende**. Jede Transaktion enthält Datum, Ticker, Anzahl, Preis, Gebühren und Währung.

## Manuelle Erfassung

Klicke auf «Transaktion hinzufügen», um einen Kauf oder Verkauf manuell zu erfassen. Achte darauf, den korrekten Ticker und das exakte Kaufdatum einzugeben — beides ist wichtig für die Performance-Berechnung.

## Suche und Filter

Du kannst Transaktionen nach **Ticker**, **Typ** (Kauf/Verkauf/Dividende) und **Zeitraum** filtern. Die Suche hilft dir, bestimmte Transaktionen schnell zu finden.

> Tipp: Nutze den [CSV-Import](#csv-import) für Swissquote-Transaktionen, anstatt sie einzeln manuell einzugeben. Das spart Zeit und reduziert Fehler.

## Transaktion bearbeiten

Bestehende Transaktionen können bearbeitet oder gelöscht werden. Nach jeder Änderung werden die betroffenen Positionen automatisch neu berechnet, und die Performance-Daten werden aktualisiert.`,
      },
    ],
  },
  {
    id: "scoring-system",
    title: "Scoring-System",
    icon: "Target",
    articles: [
      {
        id: "wie-funktioniert-scoring",
        title: "Wie funktioniert das Scoring?",
        summary:
          "Das Zwei-Stufen-System aus Makro-Gate und Setup-Score erklärt.",
        content: `Das Scoring-System in OpenFolio bewertet Aktien in zwei Stufen. Zuerst wird das Marktumfeld geprüft (Makro-Gate), dann die einzelne Aktie analysiert (Setup-Score).

## Zwei-Stufen-Prinzip

**Stufe 1 — Makro-Gate**: Ist das allgemeine Marktumfeld für Käufe geeignet? Wenn nicht, zeigt dies, dass das Marktumfeld ungünstig ist. Das Makro-Gate dient als informativer Kontext für die Gesamtmarktlage.

**Stufe 2 — Setup-Score**: Wie gut ist die einzelne Aktie aufgestellt? Der Score bewertet 18 rein technische Kriterien.

## Warum dieses System?

Die meisten Verluste entstehen nicht durch die Auswahl schlechter Aktien, sondern durch Käufe im falschen Marktumfeld. Das Makro-Gate zeigt dies an. Es ist ein **informativer Indikator**, der die Gesamtmarktlage einschätzt.

> Wichtig: Das Makro-Gate wird auf der Seite Markt & Sektoren angezeigt und dient als Kontext. Es beeinflusst die Einzelaktien-Signale nicht direkt.

## Signalarten

Aus dem Setup-Score und der Breakout-Analyse ergeben sich die Signale: **Kaufkriterien erfüllt**, **Watchlist**, **Beobachten** und **Kein Setup**. Die genaue Logik findest du unter [Signal-Logik](#signal-logik).`,
      },
      {
        id: "makro-gate",
        title: "Makro-Gate (7 Checks)",
        summary:
          "Sieben gewichtete Prüfungen bestimmen, ob das Marktumfeld Käufe erlaubt.",
        content: `Das Makro-Gate besteht aus sieben gewichteten Checks, die zusammen maximal 9 Punkte ergeben. Das Gate ist bestanden, wenn mindestens **6 von 9 Punkten** erreicht werden.

## Die 7 Checks

**S&P 500 über 150-DMA** (2 Punkte): Der S&P 500 muss über seinem 150-Tage-Durchschnitt notieren. Das ist der wichtigste Einzelcheck — er zeigt, ob der Markt in einem Aufwärtstrend ist.

**S&P 500 Higher Highs / Higher Lows** (1 Punkt): Der Markt bildet höhere Hochs und höhere Tiefs — ein klassisches Trendmerkmal.

**VIX unter 20** (2 Punkte): Der Volatilitätsindex VIX misst die erwartete Schwankungsbreite. Unter 20 herrscht relative Ruhe; darüber steigt das Risiko.

**Sektor stark** (1 Punkt): Der Sektor der Aktie hat im letzten Monat eine positive Rendite erzielt.

**Shiller PE unter 30** (1 Punkt): Das zyklisch adjustierte KGV liegt unter 30 — der Markt ist nicht extrem überbewertet.

**Buffett Indicator unter 150%** (1 Punkt): Das Verhältnis von Marktkapitalisierung zum BIP liegt unter 150%.

**Zinsstruktur nicht invertiert** (1 Punkt): Die Zinsstrukturkurve ist nicht invertiert — ein invertierter Verlauf gilt als Rezessionssignal.

> Merke: Mindestens 6 von 9 Punkten müssen erreicht werden. Die Checks mit 2 Punkten (S&P über 150-DMA, VIX) haben doppelte Gewichtung, weil sie besonders aussagekräftig sind.`,
      },
      {
        id: "setup-score",
        title: "Setup-Score (18 Punkte)",
        summary:
          "18 rein technische Kriterien bewerten die einzelne Aktie.",
        content: `Der Setup-Score bewertet eine Aktie anhand von 18 rein technischen Kriterien aus fünf Kategorien. Maximal sind 18 Punkte möglich.

## Moving Averages (7 Kriterien)

Preis über MA50, MA150 und MA200. MA50 über MA150 und MA200. MA150 über MA200. MA200 steigend. Das stellt sicher, dass die Aktie in einem intakten Aufwärtstrend ist.

## Breakout (5 Kriterien, Donchian Channel)

20-Tage-Hoch Breakout (2 Punkte), Volumen mindestens 1.5x Durchschnitt, über 150-DMA, maximal 25% unter 52-Wochen-Hoch, mindestens 30% über 52-Wochen-Tief.

## Relative Stärke (3 Kriterien)

Die **Mansfield Relative Stärke** (MRS) muss positiv sein (> 0), stark (> 0.5) und idealerweise Sektor-Leader (> 1.0). Das zeigt, dass die Aktie besser performt als der Gesamtmarkt (S&P 500). Mehr dazu unter [Mansfield RS](#mansfield-rs).

## Volumen & Liquidität (2 Kriterien)

Marktkapitalisierung über 2 Mrd. und durchschnittliches Volumen über 200'000. Das stellt sicher, dass die Aktie institutionell gehandelt wird.

## Trendwende (1 Kriterium)

3-Punkt-Umkehr erkannt — nur relevant für Aktien unter der 150-DMA. Drei tiefere Tiefs gefolgt von einem höheren Tief deuten auf eine mögliche Trendwende hin.

> Bewertung: 70% oder mehr (13+ Punkte) = **STARK**, 45–69% (8–12 Punkte) = **MODERAT**, unter 45% (< 8 Punkte) = **SCHWACH**. Nur starke Setups mit Breakout-Bestätigung erfüllen die Kaufkriterien.`,
      },
      {
        id: "donchian-breakout",
        title: "Donchian Channel Breakout",
        summary:
          "Wie OpenFolio Ausbrüche über den Donchian Channel erkennt.",
        content: `Der Donchian Channel ist ein wichtiger Indikator für Breakouts. Er bildet den höchsten Hoch- und den tiefsten Tiefpunkt der letzten N Perioden ab.

## Was ist ein Donchian Channel?

Der Donchian Channel besteht aus zwei Linien: dem **oberen Band** (höchstes Hoch der letzten N Tage) und dem **unteren Band** (tiefstes Tief der letzten N Tage). Durchbricht der Kurs das obere Band, liegt ein Breakout vor.

## Breakout-Erkennung

OpenFolio prüft, ob der aktuelle Kurs über dem **Widerstandsniveau** liegt. Dabei gilt strikt: Der Kurs muss den Widerstand überschreiten — ein Gleichstand reicht nicht. Das filtert falsche Signale heraus.

> Wichtig: Die Breakout-Logik verwendet **keine Toleranz**. Der aktuelle Kurs muss strikt über dem Widerstand liegen (current_price > resistance), nicht grösser-gleich.

## Volumenbestätigung

Ein Breakout ist nur dann aussagekräftig, wenn er von **hohem Volumen** begleitet wird. OpenFolio prüft, ob das Breakout-Volumen mindestens doppelt so hoch ist wie das durchschnittliche Volumen. Ein Breakout ohne Volumen ist oft ein Fehlsignal.

## In der Praxis

Wenn du eine Aktie auf der [Watchlist](#watchlist-nutzen) hast und ein Breakout-Signal erscheint, prüfe den [Setup-Score](#setup-score). Setup STARK und Breakout bestätigt → Kaufkriterien erfüllt.`,
      },
      {
        id: "branchenvergleich",
        title: "Branchenvergleich",
        summary:
          "Aktien innerhalb ihrer Branche vergleichen und einordnen.",
        content: `Der Branchenvergleich zeigt dir, wie eine Aktie im Vergleich zu anderen Titeln derselben Branche abschneidet. Das hilft dir, die besten Aktien innerhalb eines Sektors zu identifizieren.

## Sektoren und Branchen

OpenFolio verwendet die **FINVIZ-Taxonomie** mit rund 160 Branchen, die in übergeordnete Sektoren gruppiert sind (Technology, Healthcare, Financials usw.). Jede Aktie wird automatisch einer Branche und einem Sektor zugeordnet.

## Vergleichskriterien

Im Branchenvergleich siehst du, wie die Aktie bei verschiedenen Kennzahlen im Vergleich zur Branche steht: **Relative Stärke**, **Scoring**, **Performance** und **Fundamentaldaten**. So erkennst du schnell, ob eine Aktie der Leader oder der Nachzügler ihrer Branche ist.

> Tipp: Investiere bevorzugt in die **stärksten Aktien der stärksten Sektoren**. Die [Sektor-Rotation](#sektor-rotation) zeigt dir, welche Sektoren aktuell stark sind.

## ETF-Sektoren

Bei ETFs wird die Sektorverteilung über die **ETF-Sektor-Gewichtung** aufgeschlüsselt. Ein S&P-500-ETF wird anteilig den enthaltenen Sektoren zugeordnet, sodass du die wahre Sektor-Exposition deines Portfolios siehst.`,
      },
      {
        id: "signal-logik",
        title: "Signal-Logik",
        summary:
          "Wie aus Setup-Score und Breakout das finale Signal entsteht.",
        content: `Die Signal-Logik verknüpft den Setup-Score und den Breakout-Status zu einem klaren Handlungssignal.

## Die vier Signale

**KAUFKRITERIEN ERFÜLLT**: Der Setup-Score ist STARK (≥70%) und ein Breakout mit Volumen-Bestätigung liegt vor.

**WATCHLIST**: Der Setup-Score ist STARK, aber es liegt noch kein Breakout vor. Die Aktie ist bereit — setze sie auf die [Watchlist](#watchlist-nutzen) und warte auf den Breakout.

**BEOBACHTEN**: Der Setup-Score ist MODERAT (45–69%). Die Aktie hat Potenzial, ist aber noch nicht bereit.

**KEIN SETUP**: Der Setup-Score ist SCHWACH (<45%). Die Aktie erfüllt zu wenige Kriterien.

> Das Marktumfeld (Makro-Gate) wird weiterhin auf der Seite **Markt & Sektoren** angezeigt, beeinflusst aber nicht mehr die Einzelaktien-Signale.

## ETF 200-DMA Kaufkriterien

Breite Index-ETFs (VOO, QQQ, VWRL, SWDA etc.) erfüllen automatisch die **Kaufkriterien**, wenn sie unter der 200-DMA handeln — unabhängig von allen anderen Kriterien.

## Signale nutzen

Verwende die Signale als **Entscheidungshilfe**, nicht als automatisches Handelssystem. Prüfe bei erfüllten Kaufkriterien immer noch die [Kauf-Checkliste](#kauf-checklisten), bevor du eine Order aufgibst. Die Signale ersetzen keine eigene Analyse — sie ergänzen sie.`,
      },
    ],
  },
  {
    id: "marktanalyse",
    title: "Marktanalyse",
    icon: "BarChart3",
    articles: [
      {
        id: "marktklima",
        title: "Marktklima & Marktumfeld",
        summary:
          "Das Marktklima-Dashboard zeigt dir, ob der Gesamtmarkt günstig ist.",
        content: `Das Marktklima fasst die wichtigsten Indikatoren zum Zustand des Gesamtmarkts zusammen. Es beantwortet die Frage: Ist jetzt ein guter Zeitpunkt zum Kaufen?

## Marktklima-Ampel

Das Marktklima wird als **Ampel** dargestellt: Grün (günstig für Käufe), Gelb (erhöhte Vorsicht) oder Rot (ungünstig). Die Ampel basiert auf dem [Makro-Gate](#makro-gate) und berücksichtigt alle sieben gewichteten Checks.

## Indikatoren im Detail

Auf dem Dashboard siehst du jeden Check einzeln: S&P 500 vs. 150-DMA, VIX-Level, Shiller PE, Buffett Indicator und Zinsstruktur. Jeder Indikator wird mit seinem aktuellen Wert und dem Status (bestanden/nicht bestanden) angezeigt.

## Historische Perspektive

OpenFolio zeigt nicht nur den aktuellen Stand, sondern auch die **historische Entwicklung** der Indikatoren. So kannst du einordnen, ob sich das Marktumfeld verbessert oder verschlechtert. Ein steigender Trend bei mehreren Indikatoren ist ein gutes Zeichen.

> Tipp: Prüfe das Marktklima regelmässig — mindestens wöchentlich. Wenn das Gate von Grün auf Rot wechselt, solltest du deine Satellite-Positionen und Stop-Losses überprüfen.

## Makro-Daten

Für die vollständige Makro-Analyse benötigst du einen **FRED API Key**. Ohne ihn funktionieren der Buffett Indicator, die Zinsstrukturkurve und die Arbeitsmarktdaten nicht. Den Key kannst du kostenlos unter [fred.stlouisfed.org](https://fred.stlouisfed.org) beantragen und in den [Einstellungen](#einstellungen) hinterlegen.`,
      },
      {
        id: "heatmap",
        title: "Heatmap",
        summary:
          "Visuelle Darstellung der Sektorperformance nach Index.",
        content: `Die Heatmap zeigt dir auf einen Blick, welche Sektoren und Aktien im ausgewählten Index aktuell stark oder schwach sind. Die Grösse der Felder entspricht der Marktkapitalisierung.

## Heatmap lesen

Jedes Feld stellt eine Aktie oder einen Sektor dar. **Grüne Felder** zeigen positive Performance, **rote Felder** negative. Je intensiver die Farbe, desto stärker die Bewegung. Die Grösse der Felder zeigt die relative Marktkapitalisierung.

## Sektorübersicht

Die Heatmap gruppiert Aktien nach Sektoren. So erkennst du schnell, ob ein ganzer Sektor stark oder schwach ist. Ein durchgehend roter Technologie-Sektor deutet z.B. auf eine breite Schwäche hin — nicht nur auf einzelne Verlierer.

> Tipp: Nutze die Heatmap zusammen mit der [Sektor-Rotation](#sektor-rotation), um die stärksten Sektoren zu identifizieren. Investiere bevorzugt in starke Sektoren und meide schwache.

## Zeiträume

Du kannst verschiedene Zeiträume auswählen — Tagesperformance, Wochenperformance oder Monatsperformance. Die Tagesansicht zeigt kurzfristige Bewegungen, die Monatsansicht gibt einen besseren Überblick über den mittelfristigen Trend.`,
      },
      {
        id: "sektor-rotation",
        title: "Sektor-Rotation",
        summary:
          "Welche Sektoren führen und welche hinken hinterher?",
        content: `Die Sektor-Rotation zeigt die relative Stärke der elf S&P-500-Sektoren über verschiedene Zeiträume. Sie hilft dir, in die richtigen Sektoren zu investieren.

## SPDR-Sektor-ETFs

OpenFolio analysiert die Sektoren anhand der **SPDR-Sektor-ETFs** (XLK, XLV, XLF usw.). Für jeden Sektor wird die Performance über 1 Woche, 1 Monat und 3 Monate berechnet und in einer Rangliste dargestellt.

## Rotation erkennen

Die Sektor-Rotation zeigt, welche Sektoren **Momentum aufbauen** und welche an Stärke verlieren. Ein Sektor, der auf allen Zeitebenen im oberen Drittel liegt, ist in einem starken Aufwärtstrend. Ein Sektor, der von oben nach unten fällt, verliert an Momentum.

## Anwendung

Nutze die Sektor-Rotation für zwei Entscheidungen:

1. **Neue Käufe** bevorzugt in Sektoren mit positivem Momentum platzieren.
2. **Bestehende Positionen** in schwachen Sektoren kritischer beobachten — sie könnten zuerst den Stop-Loss erreichen.

> Wichtig: Ein Sektor muss im letzten Monat eine positive Rendite aufweisen, damit der Sektor-Check im [Makro-Gate](#makro-gate) bestanden wird. Ein schwacher Sektor beeinflusst die Makro-Gate Bewertung.`,
      },
      {
        id: "crash-indikatoren",
        title: "Crash-Indikatoren",
        summary:
          "Frühwarnsignale für grössere Markteinbrüche erkennen.",
        content: `Die Crash-Indikatoren sind Frühwarnsignale, die auf erhöhte Risiken im Markt hinweisen. Sie ersetzen keine Prognose, helfen aber bei der Risikoeinschätzung.

## Shiller PE (CAPE Ratio)

Das **zyklisch adjustierte Kurs-Gewinn-Verhältnis** glättet Gewinnschwankungen über 10 Jahre. Werte über 30 deuten auf eine Überbewertung hin. Historisch folgten nach Werten über 30 oft schwächere Marktphasen.

## Buffett Indicator

Der **Buffett Indicator** setzt die gesamte Marktkapitalisierung ins Verhältnis zum Bruttoinlandsprodukt. Werte über 150% gelten als Warnsignal für eine Überbewertung. Benötigt einen FRED API Key.

## Invertierte Zinsstruktur

Wenn kurzfristige Zinsen höher sind als langfristige, spricht man von einer **invertierten Zinsstrukturkurve**. Historisch ging dies oft einer Rezession voraus — mit einer Vorlaufzeit von 6–18 Monaten.

## VIX (Angstindex)

Der **VIX** misst die erwartete Volatilität im S&P 500. Werte unter 15 zeigen extreme Sorglosigkeit, über 20 erhöhte Nervosität, über 30 Panik. Ein stark steigender VIX ist ein Warnsignal.

> Hinweis: Crash-Indikatoren sind **keine Timing-Instrumente**. Ein überbewerteter Markt kann jahrelang weiter steigen. Nutze sie als Kontext für deine Gesamteinschätzung, nicht als Verkaufsindikator.`,
      },
    ],
  },
  {
    id: "aktien-analyse",
    title: "Aktien-Analyse",
    icon: "TrendingUp",
    articles: [
      {
        id: "detailseite",
        title: "Detailseite verstehen",
        summary:
          "Alle Informationen auf der Aktien-Detailseite erklärt.",
        content: `Die Aktien-Detailseite bietet eine umfassende Analyse einer einzelnen Aktie. Hier findest du alle Informationen, die du für eine Kauf- oder Verkaufsentscheidung brauchst.

## Kursübersicht

Oben siehst du den aktuellen **Kurs**, die Tagesveränderung und den Chart mit verschiedenen Zeiträumen (1M, 3M, 6M, 1J, 5J). Der Chart zeigt auch die gleitenden Durchschnitte (50-DMA und 150-DMA) sowie das Widerstandsniveau.

## Scoring-Bereich

Der **Setup-Score** wird mit allen 18 Kriterien angezeigt — jedes einzeln mit Status (bestanden/nicht bestanden). So siehst du genau, welche Kriterien erfüllt sind und wo die Aktie Schwächen hat.

## Fundamentaldaten

Die [Fundamental-Karten](#fundamental-karten) zeigen Umsatz, Gewinn, Margen und Verschuldung. Diese Daten stammen von der FMP API und sind für US-Aktien verfügbar.

## Relative Stärke

Der [Mansfield RS](#mansfield-rs) Chart zeigt die relative Stärke gegenüber dem S&P 500 über die letzten 12 Monate. Ein steigender MRS über null ist bullish.

> Tipp: Nutze die Detailseite, um die [Kauf-Checkliste](#kauf-checklisten) durchzugehen, bevor du eine Position eröffnest.`,
      },
      {
        id: "indikatoren",
        title: "Indikatoren erklärt",
        summary:
          "Die technischen Indikatoren in OpenFolio und ihre Bedeutung.",
        content: `OpenFolio verwendet eine Reihe technischer Indikatoren, um Aktien zu bewerten. Hier sind die wichtigsten erklärt.

## Gleitende Durchschnitte (DMA)

Der **50-DMA** zeigt den kurzfristigen Trend, der **150-DMA** den mittelfristigen. Wenn der Kurs über beiden liegt, ist der Trend intakt. Fällt er darunter, ist Vorsicht geboten. Die 150-DMA-Regel ist ein zentraler Baustein der [Stop-Loss Strategie](#schwur-1).

## Volumen

Das **Volumen** zeigt, wie viele Aktien gehandelt werden. Hohes Volumen bei steigenden Kursen deutet auf institutionelle Käufe hin. Hohes Volumen bei fallenden Kursen zeigt Verkaufsdruck. Das Verhältnis von Aufwärts- zu Abwärtsvolumen ist ein wichtiger Indikator.

## Widerstand (Resistance)

Der **Widerstand** ist das Preisniveau, an dem die Aktie in der Vergangenheit abgeprallt ist. Ein Breakout über den Widerstand — idealerweise mit hohem Volumen — deutet auf mögliche Stärke hin. OpenFolio berechnet das Widerstandsniveau automatisch.

## VIX

Der **Volatilitätsindex** misst die vom Markt erwartete Schwankungsbreite des S&P 500 für die nächsten 30 Tage. Er wird aus Optionspreisen abgeleitet.

> Merke: Kein einzelner Indikator reicht für eine Entscheidung. Das [Scoring-System](#wie-funktioniert-scoring) kombiniert bewusst mehrere Indikatoren, um die Trefferquote zu erhöhen.`,
      },
      {
        id: "fundamental-karten",
        title: "Fundamental-Karten",
        summary:
          "Umsatz, Gewinn, Marge und Verschuldung auf einen Blick.",
        content: `Die Fundamental-Karten zeigen die wichtigsten finanziellen Kennzahlen einer Aktie. Sie helfen dir einzuschätzen, ob das Unternehmen gesund ist.

## Umsatzwachstum

Die Karte zeigt den **Umsatz der letzten Quartale** und ob er wächst. Wachsender Umsatz ist ein Zeichen für ein gesundes Unternehmen. Stagniert oder schrumpft der Umsatz, ist das ein Warnsignal — auch wenn der Kurs steigt.

## Gewinnmarge

Die **Gewinnmarge** zeigt, wie profitabel das Unternehmen arbeitet. Eine stabile oder steigende Marge ist positiv. Eine fallende Marge kann auf Preisdruck, steigende Kosten oder Wettbewerbsprobleme hindeuten.

## Verschuldung (D/E Ratio)

Das **Debt-to-Equity Ratio** setzt die Schulden ins Verhältnis zum Eigenkapital. Ein Wert unter 1.0 bedeutet, dass das Unternehmen mehr Eigenkapital als Schulden hat. Werte über 2.0 sind bei den meisten Branchen ein Warnsignal.

> Hinweis: Fundamentaldaten sind über die **FMP API** verfügbar (Free Tier, 250 Calls/Tag). Ohne FMP API Key werden keine Fundamentaldaten angezeigt. Konfiguriere den Key in den [Einstellungen](#einstellungen).

## Branchenvergleich

Fundamentalkennzahlen sind am aussagekräftigsten im **Branchenvergleich**. Eine D/E Ratio von 1.5 ist für eine Bank normal, für ein Softwareunternehmen aber hoch. OpenFolio zeigt den [Branchenvergleich](#branchenvergleich) für eine bessere Einordnung.`,
      },
      {
        id: "mansfield-rs",
        title: "Mansfield Relative Stärke",
        summary:
          "Wie die Mansfield RS zeigt, ob eine Aktie den Markt schlägt.",
        content: `Die Mansfield Relative Stärke (MRS) ist ein zentraler Indikator in OpenFolio. Sie zeigt, ob eine Aktie besser oder schlechter performt als der Gesamtmarkt.

## Berechnung

Die MRS basiert auf dem **EMA(13) auf Wochendaten** im Vergleich zum S&P 500 (^GSPC). Ein positiver MRS-Wert bedeutet, dass die Aktie den Markt übertrifft. Ein negativer Wert bedeutet, dass sie schlechter läuft als der Index.

## MRS lesen

**MRS > 0 und steigend**: Die Aktie ist ein Leader — sie schlägt den Markt und gewinnt an Stärke. Das ist die ideale Situation für einen Kauf.

**MRS > 0 und fallend**: Die Aktie schlägt noch den Markt, verliert aber an Momentum. Vorsicht — sie könnte bald unter null fallen.

**MRS < 0**: Die Aktie underperformt den Markt. In der Regel solltest du keine neuen Positionen eröffnen, wenn der MRS negativ ist.

> Wichtig: Im Setup-Score werden drei Kriterien zur MRS geprüft: **MRS > 0** (positiv), **MRS > 0.5** (stark) und **MRS > 1.0** (Sektor-Leader). Jedes erfüllte Kriterium gibt einen Punkt.

## Warum Relative Stärke?

Studien zeigen, dass Aktien mit hoher relativer Stärke dazu tendieren, weiterhin gut zu performen — das sogenannte **Momentum-Phänomen**. Die MRS hilft dir, diese Gewinner systematisch zu identifizieren und Verlierer zu meiden.`,
      },
    ],
  },
  {
    id: "risikomanagement",
    title: "Risikomanagement",
    icon: "Shield",
    articles: [
      {
        id: "stop-loss",
        title: "Stop-Loss Strategie",
        summary:
          "Verluste begrenzen mit systematischen Stop-Loss-Levels.",
        content: `Eine konsequente Stop-Loss-Strategie ist der wichtigste Baustein des Risikomanagements. Sie schützt dein Kapital vor grösseren Verlusten.

## Stop-Loss je Positionstyp

Die Stop-Loss-Abstände richten sich nach dem Positionstyp:

**Core-Positionen**: Struktureller Stop bei **15–25%** unter dem Einstiegskurs. Der weitere Abstand gibt langfristigen Positionen Raum zum Atmen, ohne bei normalen Schwankungen ausgestoppt zu werden.

**Satellite-Positionen**: Enger Stop bei **5–12%** unter dem Einstiegskurs. Taktische Trades brauchen einen engen Stop, um das Risiko pro Trade zu begrenzen.

## Trailing Stop

Wenn eine Position im Gewinn ist, kannst du den Stop-Loss **nachziehen** (Trailing Stop). So sicherst du bereits erzielte Gewinne ab. Ziehe den Stop nie zurück — er darf nur nach oben angepasst werden.

> Hinweis: Wenn ein Stop-Loss erreicht wird, sind die Verkaufskriterien erfüllt. Disziplin bei Stop-Losses ist ein zentraler Bestandteil des Risikomanagements.

## Stop-Loss in OpenFolio

OpenFolio berechnet für jede Position das aktuelle Stop-Loss-Level und zeigt den Abstand zum aktuellen Kurs. Wenn der Kurs dem Stop nahe kommt, erhältst du eine Warnung. Richte dazu [Alerts](#alerts) ein.`,
      },
      {
        id: "schwur-1",
        title: "Schwur 1 (150-DMA Regel)",
        summary:
          "Die wichtigste Regel: Kein Kauf unter dem 150-Tage-Durchschnitt.",
        content: `Die 150-DMA-Regel ist eine der fundamentalen Regeln des systematischen Investierens. Sie verhindert Käufe in Abwärtstrends.

## Die Regel

**Das System empfiehlt keine Käufe von Aktien, die unter ihrem 150-Tage-Durchschnitt (150-DMA) notieren.** Der 150-DMA ist ein bewährter Trendfilter. Aktien über dem 150-DMA befinden sich in einem Aufwärtstrend, Aktien darunter in einem Abwärtstrend.

## Warum 150 Tage?

Der 150-DMA (ca. 30 Wochen) glättet kurzfristige Schwankungen und zeigt den mittelfristigen Trend. Er ist nicht so empfindlich wie der 50-DMA und nicht so träge wie der 200-DMA. In der Praxis hat sich der 150-DMA als optimaler Kompromiss bewährt.

## Im Makro-Gate

Der S&P 500 über seinem 150-DMA ist der **wichtigste Check** im [Makro-Gate](#makro-gate) und trägt 2 von 9 möglichen Punkten bei. Wenn der gesamte Markt unter dem 150-DMA notiert, ist das ein starkes Warnsignal.

> Merke: Diese Regel gilt auch für den Gesamtmarkt. Wenn der S&P 500 unter seinem 150-DMA fällt, solltest du keine neuen Positionen eröffnen — unabhängig davon, wie gut einzelne Aktien aussehen.

## Ausnahmen

Die Standardregel sieht keine Ausnahmen vor. Statistisch führen Käufe im Abwärtstrend deutlich häufiger zu Verlusten. Die endgültige Entscheidung liegt beim Anleger.`,
      },
      {
        id: "alerts",
        title: "Alerts & Benachrichtigungen",
        summary:
          "Automatische Warnungen per E-Mail bei wichtigen Ereignissen.",
        content: `OpenFolio kann dich automatisch per E-Mail benachrichtigen, wenn wichtige Ereignisse eintreten. So verpasst du keine Stop-Loss-Auslösung und kein Breakout-Signal.

## Alert-Typen

**Portfolio Alerts**: Warnungen, wenn eine Position ihren Stop-Loss-Bereich erreicht oder der Portfoliowert einen bestimmten Schwellenwert unterschreitet.

**Kurs-Alerts**: Benachrichtigung, wenn eine Aktie einen bestimmten Kurs über- oder unterschreitet. Nützlich für Watchlist-Aktien, bei denen du auf einen Breakout wartest.

## Alerts einrichten

Navigiere zu einer Position oder Aktie und klicke auf «Alert erstellen». Definiere die Bedingung (z.B. Kurs unter CHF 150) und den Alert-Typ. Bei Auslösung erhältst du eine E-Mail mit allen relevanten Details.

> Voraussetzung: Für E-Mail-Alerts muss ein SMTP-Server in den [Einstellungen](#einstellungen) konfiguriert sein. Ohne SMTP-Konfiguration werden Alerts zwar ausgelöst, aber nicht per E-Mail versendet.

## Best Practices

Richte für jede Position einen **Stop-Loss-Alert** ein. Setze den Alert leicht über dem tatsächlichen Stop-Loss — z.B. bei -10%, wenn dein Stop bei -12% liegt. So hast du Zeit zu reagieren, bevor der Stop erreicht wird. Für Watchlist-Aktien empfiehlt sich ein Alert knapp unter dem Widerstandsniveau.`,
      },
      {
        id: "kauf-checklisten",
        title: "Kauf-Checklisten",
        summary:
          "Systematische Checkliste vor jedem Kauf abarbeiten.",
        content: `Eine Kauf-Checkliste stellt sicher, dass du vor jedem Kauf alle wichtigen Punkte überprüfst. Systematisches Vorgehen reduziert emotionale Fehlentscheidungen.

## Vor dem Kauf prüfen

1. **Marktumfeld prüfen?** Prüfe das [Marktklima](#marktklima) auf der Markt & Sektoren-Seite. Das Makro-Gate ist ein informativer Indikator — kein Kaufblocker für Einzelaktien.

2. **Setup-Score STARK?** Die Aktie sollte mindestens 13 von 18 Punkten im [Setup-Score](#setup-score) haben (70% oder mehr).

3. **Breakout bestätigt?** Der Kurs muss über dem Widerstand liegen, idealerweise mit hohem Volumen. Siehe [Donchian Breakout](#donchian-breakout).

4. **MRS positiv und steigend?** Die [Mansfield RS](#mansfield-rs) sollte über null liegen und steigen.

5. **Fundamentals solide?** Umsatzwachstum, stabile Margen, keine übermässige Verschuldung — prüfe bei StockAnalysis oder Yahoo Finance.

## Positionsgrösse bestimmen

Bestimme die **Positionsgrösse** vor dem Kauf. Als Faustregel: Riskiere maximal 1–2% deines Gesamtportfolios pro Position. Bei einem Stop-Loss von 10% und einem maximalen Risiko von 1% wäre die maximale Positionsgrösse 10% des Portfolios.

> Tipp: Dokumentiere bei jedem Kauf kurz, warum du kaufst. Wenn du den Grund nicht in einem Satz formulieren kannst, ist das Setup möglicherweise nicht klar genug.

## Core oder Satellite?

Entscheide vor dem Kauf, ob die Position **Core** oder **Satellite** ist. Das bestimmt den Stop-Loss-Abstand und die Überprüfungsfrequenz. Siehe [Core/Satellite-System](#core-satellite).`,
      },
    ],
  },
  {
    id: "watchlist",
    title: "Watchlist",
    icon: "Eye",
    articles: [
      {
        id: "watchlist-nutzen",
        title: "Watchlist nutzen",
        summary:
          "Aktien beobachten und auf erfüllte Kaufkriterien warten.",
        content: `Die Watchlist ist dein Werkzeug, um vielversprechende Aktien zu sammeln und auf den richtigen Kaufzeitpunkt zu warten. Geduld ist beim systematischen Investieren entscheidend.

## Aktien zur Watchlist hinzufügen

Füge Aktien hinzu, die einen hohen [Setup-Score](#setup-score) haben, aber noch keinen Breakout gezeigt haben — also das Signal «WATCHLIST» erhalten. Du kannst auch Aktien hinzufügen, die du generell interessant findest und beobachten möchtest.

## Watchlist pflegen

Überprüfe deine Watchlist **wöchentlich**. Entferne Aktien, deren Setup-Score unter 8 gefallen ist oder deren Fundamentaldaten sich verschlechtert haben. Eine fokussierte Watchlist mit 10–20 Aktien ist effektiver als eine lange Liste mit 100 Titeln.

## Scoring auf der Watchlist

Für jede Aktie auf der Watchlist siehst du den aktuellen **Setup-Score**, den **MRS-Wert**, den **Abstand zum Widerstand** und das [Makro-Gate](#makro-gate). So erkennst du sofort, welche Aktien am nächsten an den Kaufkriterien sind.

> Tipp: Richte [Kurs-Alerts](#alerts) für Watchlist-Aktien ein, um bei einem Breakout sofort benachrichtigt zu werden. So musst du nicht täglich die Kurse prüfen.

## Von der Watchlist zum Kauf

Wenn eine Watchlist-Aktie die Kaufkriterien erfüllt, gehe die [Kauf-Checkliste](#kauf-checklisten) durch und handle zeitnah. Breakout-Signale sind oft nur kurz aktiv — warte nicht zu lange.`,
      },
      {
        id: "breakout-signale",
        title: "Breakout-Signale erkennen",
        summary:
          "Woran du einen echten Breakout von einem Fehlsignal unterscheidest.",
        content: `Ein Breakout ist der Moment, in dem eine Aktie ihr Widerstandsniveau durchbricht. Nicht jeder Breakout führt zu steigenden Kursen — hier lernst du, echte von falschen Signalen zu unterscheiden.

## Echter Breakout

Ein echter Breakout zeigt typischerweise diese Merkmale: Der Kurs schliesst **deutlich über dem Widerstand** (nicht nur knapp darüber). Das **Volumen ist mindestens doppelt** so hoch wie im Durchschnitt. Der Breakout findet in einem **starken Sektor** statt.

## Fehlsignal (Fakeout)

Ein Fehlsignal erkennst du an: geringem Volumen beim Breakout, schnellem Rückfall unter den Widerstand innerhalb weniger Tage, oder einem Breakout in einem schwachen Marktumfeld (Makro-Gate nicht bestanden).

## Volumen als Schlüssel

Das **Volumen** ist der wichtigste Bestätigungsfaktor. Ein Breakout mit hohem Volumen zeigt, dass institutionelle Anleger kaufen — das gibt dem Ausbruch Nachhaltigkeit. Ein Breakout mit dünnem Volumen hat eine deutlich geringere Erfolgswahrscheinlichkeit.

> Merke: OpenFolio prüft das Breakout-Volumen automatisch im [Setup-Score](#setup-score). Ein Breakout ohne Volumenbestätigung erhält weniger Punkte und damit ein schwächeres Signal.

## Nach dem Breakout

Die Order möglichst am Tag des Breakouts platzieren oder am Folgetag. Je länger du wartest, desto schlechter wird das Chance-Risiko-Verhältnis. Setze den Stop-Loss direkt unter das ehemalige Widerstandsniveau — dieses wird oft zur neuen Unterstützung.`,
      },
      {
        id: "watchlist-zum-kauf",
        title: "Von der Watchlist zum Kauf",
        summary:
          "Der Prozess vom ersten Interesse bis zur Kaufentscheidung.",
        content: `Der Weg von der Watchlist zum Kauf folgt einem klaren Prozess. Jeder Schritt hat seine Kriterien — so triffst du rationale Entscheidungen statt emotionaler.

## Schritt 1: Entdecken

Du findest eine interessante Aktie — durch Screener, Nachrichten, Branchenanalyse oder das Scoring-System. Prüfe den [Setup-Score](#setup-score): Hat die Aktie mindestens 8 Punkte (MODERAT)? Falls ja, setze sie auf die Watchlist.

## Schritt 2: Beobachten

Verfolge die Aktie wöchentlich. Beobachte, ob sich der Setup-Score verbessert. Achte auf den Abstand zum Widerstand — nähert sich der Kurs dem Breakout-Level? Prüfe die [Mansfield RS](#mansfield-rs): Steigt sie und liegt über null?

## Schritt 3: Signal abwarten

Warte auf erfüllte **Kaufkriterien**: Setup-Score STARK (≥70%), Breakout über den Widerstand mit Volumen. Geduld zahlt sich aus — ein zu früher Einstieg birgt höhere Risiken.

## Schritt 4: Kaufen

Wenn das Signal kommt, handle zügig. Arbeite die [Kauf-Checkliste](#kauf-checklisten) durch. Bestimme die Positionsgrösse und den Stop-Loss. Entscheide, ob die Position [Core oder Satellite](#core-satellite) ist. Dann kann die Order platziert werden.

> Wichtig: Nicht jede Watchlist-Aktie wird zum Kauf. Es ist völlig normal, dass Aktien wieder von der Watchlist fallen, weil sich ihr Setup verschlechtert. Qualität vor Quantität.

## Schritt 5: Verwalten

Nach dem Kauf geht die Arbeit weiter. Überwache den Stop-Loss, prüfe regelmässig den Setup-Score und die Fundamentals. Core-Positionen quartalsweise, Satellite-Positionen wöchentlich.`,
      },
    ],
  },
  {
    id: "glossar",
    title: "Glossar",
    icon: "BookOpen",
    articles: [
      {
        id: "glossar-link",
        title: "Glossar der Finanzbegriffe",
        summary:
          "Alle wichtigen Fachbegriffe kurz und verständlich erklärt.",
        content: `Nutze die Suche und die Kategorie-Filter um Begriffe zu finden. Alle unterstrichenen Begriffe in der App zeigen beim Hovern einen Tooltip mit der Erklärung.`,
      },
    ],
  },
];
