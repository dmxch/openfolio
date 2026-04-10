/**
 * Central glossary of financial terms used across OpenFolio.
 * Keys are the display terms (used for lookup), values contain explanations.
 */

export const GLOSSARY = {
  // --- Indicators & Technical Analysis ---
  "Technischer Indikator": {
    short: "Mathematisch berechnetes Signal basierend auf Marktdaten — keine Kaufempfehlung.",
    long: "OpenFolio nutzt technische Indikatoren (Moving Averages, MRS, Donchian Channel, Scoring) um Marktbedingungen zu analysieren. Diese Indikatoren sind Werkzeuge zur Unterstützung der eigenen Analyse, keine Handlungsanweisungen.",
    category: "general"
  },
  "MRS": {
    short: "Mansfield Relative Stärke — misst wie stark eine Aktie im Vergleich zum S&P 500 performt.",
    long: "Ein Wert über 0 bedeutet: die Aktie schlägt den Markt. Über 0.5 = stark, über 1.0 = Sektor-Leader. Berechnung: EMA(13) auf wöchentliche relative Performance vs. S&P 500.",
    category: "indicator"
  },
  "Mansfield RS": {
    short: "Mansfield Relative Stärke — vergleicht die Performance einer Aktie mit dem Gesamtmarkt (S&P 500).",
    long: "Positiv = Aktie performt besser als der Markt. Negativ = schlechter. Hilft, die stärksten Aktien in einem Aufwärtstrend zu finden.",
    category: "indicator"
  },
  "SMA": {
    short: "Simple Moving Average — Durchschnittskurs über eine bestimmte Anzahl Tage.",
    long: "Glättet Kursschwankungen und zeigt den Trend. SMA(50) = Durchschnitt der letzten 50 Tage. Kurs über SMA = Aufwärtstrend, darunter = Abwärtstrend.",
    category: "indicator"
  },
  "MA50": {
    short: "50-Tage gleitender Durchschnitt — kurzfristiger Trendindikator.",
    long: "Zeigt den Durchschnittskurs der letzten 50 Handelstage. Kurs über MA50 = kurzfristiger Aufwärtstrend. Wird auch 'Trader Line' genannt.",
    category: "indicator"
  },
  "MA150": {
    short: "150-Tage gleitender Durchschnitt — die 'Investor Line'.",
    long: "Wichtigster Trendindikator im System. Kurs unter MA150 = Schwur 1 verletzt → Verkaufskriterien erreicht. Kurs darüber = grundlegender Aufwärtstrend intakt.",
    category: "indicator"
  },
  "MA200": {
    short: "200-Tage gleitender Durchschnitt — langfristiger Trendindikator.",
    long: "Der bekannteste langfristige Trendindikator. Kurs über MA200 = langfristiger Aufwärtstrend. Wird von institutionellen Investoren weltweit beachtet.",
    category: "indicator"
  },
  "150-DMA": {
    short: "150-Day Moving Average — die 'Investor Line', wichtigster Trendindikator.",
    long: "Kurs unter der 150-DMA = Schwur 1 verletzt. Bedeutet: Der mittelfristige Aufwärtstrend ist gebrochen und ein Verkauf sollte geprüft werden.",
    category: "indicator"
  },
  "200-DMA": {
    short: "200-Day Moving Average — langfristiger Trendindikator.",
    long: "Gilt als Grenze zwischen Bullen- und Bärenmarkt. Wenn der S&P 500 unter der 200-DMA handelt, ist Vorsicht geboten.",
    category: "indicator"
  },
  "EMA": {
    short: "Exponential Moving Average — gewichteter Durchschnitt, der neuere Kurse stärker berücksichtigt.",
    long: "Reagiert schneller auf Kursänderungen als der einfache Durchschnitt (SMA). Wird z.B. für die MRS-Berechnung verwendet (EMA 13 auf Wochenbasis).",
    category: "indicator"
  },
  "3-Punkt-Umkehr": {
    short: "Drei tiefere Tiefs gefolgt von einem höheren Tief — mögliche Trendwende von Abwärts zu Aufwärts.",
    long: "Das Muster identifiziert potenzielle Bodenbildungen: Drei aufeinanderfolgende tiefere Tiefs (Lower Lows) zeigen einen Abwärtstrend. Wenn dann ein höheres Tief (Higher Low) folgt, deutet das auf nachlassenden Verkaufsdruck hin. Nur relevant für Aktien unter der 150-DMA — bei Aktien im Aufwärtstrend hat das Muster keine Aussagekraft. Kein technisches Signal, sondern ein Hinweis für weitere Analyse.",
    category: "indicator"
  },
  "Donchian Channel": {
    short: "Preiskanal basierend auf dem höchsten Hoch und tiefsten Tief der letzten 20 Tage.",
    long: "Wenn der Kurs über den oberen Kanal ausbricht (= neues 20-Tage-Hoch), ist das ein Breakout-Signal. Erfunden von Richard Donchian, dem 'Vater des Trendfolgens'.",
    category: "indicator"
  },
  "Donchian Breakout": {
    short: "Ausbruch über das höchste Hoch der letzten 20 Handelstage.",
    long: "Ein Donchian Breakout signalisiert, dass der Kurs ein neues kurzfristiges Hoch erreicht hat. Wird mit Volumen-Bestätigung (≥ 1.5× Durchschnitt) kombiniert für stärkere Signale.",
    category: "indicator"
  },
  "Bollinger Bänder": {
    short: "Preiskanal um den 20-Tage-Durchschnitt, basierend auf der Standardabweichung.",
    long: "Enge Bänder = geringe Volatilität (Ausbruch wahrscheinlich). Weite Bänder = hohe Volatilität. Kurs am oberen Band = überkauft, am unteren = überverkauft.",
    category: "indicator"
  },
  "BB": {
    short: "Bollinger Bands — Volatilitätsbänder um den 20-Tage-Durchschnitt.",
    long: "Zeigt ob eine Aktie im Vergleich zu ihrer eigenen Volatilität teuer (oberes Band) oder günstig (unteres Band) ist.",
    category: "indicator"
  },
  "RSI": {
    short: "Relative Strength Index — misst ob eine Aktie überkauft (>70) oder überverkauft (<30) ist.",
    long: "Oszillator zwischen 0 und 100. Über 70 = überkauft (Korrektur wahrscheinlich). Unter 30 = überverkauft (Erholung möglich). Standard-Periode: 14 Tage.",
    category: "indicator"
  },
  "VIX": {
    short: "Volatilitätsindex — das 'Angstbarometer' der Börse.",
    long: "Misst die erwartete Schwankungsbreite des S&P 500 für die nächsten 30 Tage. Unter 15 = ruhiger Markt (Risk-On). Über 25 = erhöhte Angst. Über 30 = Panik (Risk-Off).",
    category: "indicator"
  },
  "Support": {
    short: "Unterstützung — Kursniveau bei dem viele Käufer einsteigen und den Kurs stützen.",
    long: "An einem Support-Level gibt es genug Nachfrage, um den Kursfall zu stoppen. Wird der Support gebrochen, fällt der Kurs oft zum nächsten Support-Level.",
    category: "indicator"
  },
  "Widerstand": {
    short: "Resistance — Kursniveau bei dem viele Verkäufer auftreten und den Kursanstieg bremsen.",
    long: "An einem Widerstand gibt es genug Angebot, um den Kursanstieg zu stoppen. Wird der Widerstand durchbrochen, ist das ein Breakout-Signal.",
    category: "indicator"
  },
  "Resistance": {
    short: "Widerstand — Kursniveau das den Kursanstieg bremst.",
    long: "Wenn eine Aktie wiederholt an einem bestimmten Preis abprallt, bildet sich dort ein Widerstand. Ein Durchbruch (Breakout) deutet auf mögliche Stärke hin.",
    category: "indicator"
  },
  "Breakout": {
    short: "Ausbruch über ein wichtiges Kursniveau (z.B. Widerstand, 20-Tage-Hoch).",
    long: "Ein Breakout mit überdurchschnittlichem Volumen gilt als zuverlässiger technischer Indikator. Ohne Volumen-Bestätigung ist der Breakout weniger vertrauenswürdig.",
    category: "indicator"
  },
  "52W-Hoch": {
    short: "Höchster Kurs der letzten 52 Wochen (1 Jahr).",
    long: "Eine Aktie nahe am 52-Wochen-Hoch zeigt relative Stärke. Aktien die neue Hochs machen, tendieren dazu, weiter zu steigen (Momentum-Effekt).",
    category: "indicator"
  },
  "52W-Tief": {
    short: "Tiefster Kurs der letzten 52 Wochen (1 Jahr).",
    long: "Eine Aktie nahe am 52-Wochen-Tief kann ein Warnsignal sein oder eine Kaufgelegenheit — kommt auf den Kontext an (Gesamtmarkt, Fundamentaldaten).",
    category: "indicator"
  },
  "S/R": {
    short: "Support & Resistance — wichtige Kursniveaus die als Unterstützung oder Widerstand dienen.",
    long: "Support = Niveau wo Käufer einsteigen. Resistance = Niveau wo Verkäufer auftreten. Diese Niveaus helfen bei der Bestimmung von Einstiegs- und Ausstiegspunkten.",
    category: "indicator"
  },

  // --- Fundamental Metrics ---
  "PE Ratio": {
    short: "Kurs-Gewinn-Verhältnis — wie viele Jahre Gewinn man für den aktuellen Kurs bezahlt.",
    long: "PE = Aktienkurs / Gewinn pro Aktie. Ein PE von 20 bedeutet: man bezahlt das 20-fache des Jahresgewinns. Niedrig = günstig bewertet, hoch = teuer. Immer im Branchenvergleich betrachten.",
    category: "metric"
  },
  "KGV": {
    short: "Kurs-Gewinn-Verhältnis — deutscher Begriff für PE Ratio.",
    long: "Zeigt wie teuer eine Aktie im Verhältnis zu ihrem Gewinn ist. KGV von 15 = fair bewertet für viele Branchen. Tech-Aktien haben oft KGV über 30.",
    category: "metric"
  },
  "PEG Ratio": {
    short: "Verhältnis von KGV zu Gewinnwachstum — setzt die Bewertung ins Verhältnis zum Wachstum.",
    long: "PEG = PE Ratio / Earnings Growth Rate. Unter 1.0 = potenziell unterbewertet, über 2.0 = potenziell überbewertet. Peter Lynch's Weiterentwicklung der klassischen P/E-Analyse. Nur bei positivem Gewinnwachstum aussagekräftig.",
    category: "metric"
  },
  "Forward PE": {
    short: "Erwartetes PE basierend auf den prognostizierten Gewinnen der nächsten 12 Monate.",
    long: "Wenn Forward PE deutlich tiefer als Trailing PE ist, erwarten Analysten steigende Gewinne. Umgekehrt = Gewinnrückgang erwartet.",
    category: "metric"
  },
  "D/E": {
    short: "Debt-to-Equity — Verschuldungsgrad: Verhältnis von Schulden zu Eigenkapital.",
    long: "D/E von 0.5 = für jeden Franken Eigenkapital gibt es 50 Rappen Schulden. Unter 1.0 gilt als gesund. Aber: kapitalintensive Branchen (Versorger, Immobilien) haben naturgemäss höhere D/E-Werte.",
    category: "metric"
  },
  "Debt/Equity": {
    short: "Verschuldungsgrad — wie stark ein Unternehmen im Verhältnis zum Eigenkapital verschuldet ist.",
    long: "Wichtig im Branchenvergleich: Ein D/E von 2.5 ist für eine Müllentsorgungsfirma normal, für ein Tech-Unternehmen wäre es besorgniserregend.",
    category: "metric"
  },
  "ROE": {
    short: "Return on Equity — Eigenkapitalrendite: wie profitabel ein Unternehmen sein Eigenkapital einsetzt.",
    long: "ROE von 15% bedeutet: für jeden Franken Eigenkapital erwirtschaftet das Unternehmen 15 Rappen Gewinn. Über 15% gilt als gut, über 20% als ausgezeichnet.",
    category: "metric"
  },
  "FCF": {
    short: "Free Cash Flow — der Bargeld-Überschuss nach allen Ausgaben und Investitionen.",
    long: "FCF = Operativer Cashflow minus Investitionsausgaben. Zeigt wie viel Geld tatsächlich übrig bleibt für Dividenden, Aktienrückkäufe oder Schuldenabbau. Positiver FCF = gesundes Unternehmen.",
    category: "metric"
  },
  "Free Cash Flow": {
    short: "Freier Cashflow — das Geld das nach allen Ausgaben und Investitionen übrig bleibt.",
    long: "Der ehrlichste Indikator für die finanzielle Gesundheit. Kann im Gegensatz zum Gewinn nicht so leicht durch Buchhaltungstricks geschönt werden.",
    category: "metric"
  },
  "EPS": {
    short: "Earnings per Share — Gewinn pro Aktie.",
    long: "Der Nettogewinn eines Unternehmens geteilt durch die Anzahl ausstehender Aktien. Steigender EPS = Unternehmen verdient mehr pro Aktie. Basis für die PE-Berechnung (Kurs / EPS = PE).",
    category: "metric"
  },
  "EPS Growth": {
    short: "Gewinnwachstum pro Aktie im Jahresvergleich (YoY).",
    long: "Zeigt ob ein Unternehmen seinen Gewinn pro Aktie steigert. Positives Wachstum ist ein Qualitätsmerkmal. Berechnet aus dem Vergleich des aktuellen TTM-EPS mit dem Vorjahreswert.",
    category: "metric"
  },
  "ROIC": {
    short: "Return on Invested Capital — Kapitalrendite auf das investierte Kapital.",
    long: "Misst wie effizient ein Unternehmen sein gesamtes eingesetztes Kapital (Eigenkapital + Fremdkapital) in Gewinn umwandelt. Über 12% gilt als stark, 8–12% als durchschnittlich, unter 8% als schwach.",
    category: "metric"
  },
  "Revenue": {
    short: "Umsatz — der Gesamtbetrag den ein Unternehmen mit seinen Produkten/Dienstleistungen einnimmt.",
    long: "Auch 'Top Line' genannt (oberste Zeile der Erfolgsrechnung). Steigender Umsatz = wachsendes Geschäft. Umsatz allein sagt aber nichts über die Profitabilität.",
    category: "metric"
  },
  "Gross Margin": {
    short: "Bruttomarge — wie viel Prozent vom Umsatz nach Abzug der Herstellungskosten übrig bleibt.",
    long: "Gross Margin = (Umsatz - Herstellungskosten) / Umsatz. Hohe Marge = Preismacht und/oder effiziente Produktion. Software-Firmen: 70-80%, Detailhandel: 20-30%.",
    category: "metric"
  },
  "Net Margin": {
    short: "Nettomarge — wie viel Prozent vom Umsatz als Reingewinn übrig bleibt.",
    long: "Net Margin = Reingewinn / Umsatz. Berücksichtigt ALLE Kosten (Produktion, Verwaltung, Steuern, Zinsen). 10% = solide, 20% = sehr gut. Branchenvergleich wichtig.",
    category: "metric"
  },
  "Market Cap": {
    short: "Marktkapitalisierung — der Gesamtwert aller Aktien eines Unternehmens.",
    long: "Market Cap = Aktienkurs × Anzahl Aktien. Large Cap (>10 Mrd) = stabiler. Mid Cap (2-10 Mrd) = Wachstumspotential. Small Cap (<2 Mrd) = höheres Risiko.",
    category: "metric"
  },
  "Dividende": {
    short: "Regelmässige Gewinnausschüttung an Aktionäre — wie Miete für dein investiertes Kapital.",
    long: "Nicht alle Unternehmen zahlen Dividenden — Wachstumsunternehmen reinvestieren oft den gesamten Gewinn. Dividendenrendite = jährliche Dividende / Aktienkurs.",
    category: "metric"
  },
  "Yield": {
    short: "Rendite — bei Dividenden: die jährliche Ausschüttung in Prozent des Aktienkurses.",
    long: "Dividendenrendite von 3% bedeutet: bei einer Investition von CHF 10'000 erhältst du CHF 300 pro Jahr als Dividende.",
    category: "metric"
  },
  "Branche Ø": {
    short: "Branchendurchschnitt — der typische Wert für diese Kennzahl in der gleichen Industrie.",
    long: "Vergleicht man eine Aktie nur mit sich selbst, fehlt der Kontext. Der Branchenvergleich zeigt ob ein Wert (z.B. D/E, Marge, PE) für diese spezifische Branche gut oder schlecht ist.",
    category: "metric"
  },

  // --- Scoring & Strategy ---
  "Makro-Gate": {
    short: "7-Punkte-Check des Gesamtmarkts — informativer Indikator auf der Markt & Sektoren Seite.",
    long: "Prüft: S&P 500 Trend, VIX-Level, Shiller PE, Buffett Indicator, Zinsstruktur und mehr. Dient als Marktumfeld-Einschätzung, beeinflusst aber nicht die Einzelaktien-Signale.",
    category: "strategy"
  },
  "Setup-Score": {
    short: "18-Punkte-Checkliste für einzelne Aktien — bewertet technische Qualität.",
    long: "Prüft Moving Averages, Donchian Breakout, relative Stärke, Volumen und Trendwende. Ab 70% = STARK (Kaufkandidat). Unter 45% = SCHWACH. Fundamentaldaten separat auf StockAnalysis prüfen.",
    category: "strategy"
  },
  "KAUFSIGNAL": {
    short: "Alle Kaufkriterien erfüllt — starkes Setup + bestätigter Breakout.",
    long: "Alle technischen Bedingungen erfüllt: Setup-Score ≥70%, Donchian Breakout mit Volumen. Dies ist ein technischer Indikator, keine Kaufempfehlung.",
    category: "strategy"
  },
  "WATCHLIST": {
    short: "Starkes Setup, aber Breakout noch nicht erfolgt — beobachten und auf Ausbruch warten.",
    long: "Die Aktie erfüllt die technischen Kriterien, hat aber den Widerstand noch nicht durchbrochen. Auf die Watchlist setzen und bei Breakout handeln.",
    category: "strategy"
  },
  "BEOBACHTEN": {
    short: "Moderates Setup — einige Kriterien fehlen noch. Weiter beobachten.",
    long: "Die Aktie zeigt Potential, ist aber noch nicht stark genug für einen Kauf. Regelmässig prüfen ob sich das Setup verbessert.",
    category: "strategy"
  },
  "ETF_KAUFSIGNAL": {
    short: "Kaufkriterien für breite Index-ETFs erfüllt — der ETF handelt unter der 200-DMA.",
    long: "Erweiterter Schwur 1: Breite Index-ETFs (VOO, QQQ, SPY, etc.) unter der 200-DMA. Technischer Indikator, keine Kaufempfehlung.",
    category: "strategy"
  },
  "Core": {
    short: "Langfristige Kernposition — Quality-Aktien mit strukturellem Stop (15-25%).",
    long: "Core-Positionen werden quartalsweise überprüft und nur bei fundamentaler Verschlechterung verkauft. Ziel: 70% des Aktienportfolios. Beispiele: JNJ, PEP, WM.",
    category: "strategy"
  },
  "Satellite": {
    short: "Taktische Position — Breakout-Trades mit engem Stop (5-12%).",
    long: "Satellite-Positionen werden wöchentlich überprüft und schneller verkauft. Ziel: 30% des Aktienportfolios. Höheres Risiko, höhere potentielle Rendite.",
    category: "strategy"
  },
  "Stop-Loss": {
    short: "Verkaufslimit das den Verlust begrenzt. Pflicht für Satellite, optional für Core.",
    long: "Bei Satellite ist ein technischer Stop unter dem letzten Higher Low Pflicht (5-12%). Core hat keinen technischen Stop — Verkauf nur bei fundamentalem Bruch (These gebrochen, Moat zerstört).",
    category: "risk"
  },
  "Fundamentaler Verkaufstrigger": {
    short: "Der einzige gültige Verkaufsgrund für Core-Positionen — nicht Kurs, sondern Geschäftsmodell.",
    long: "Moat intakt? Pricing Power vorhanden? FCF wächst? Wenn ja → halten. Wenn nein → verkaufen.",
    category: "risk"
  },
  "Trailing Stop": {
    short: "Stop-Loss der automatisch nach oben mitgezogen wird wenn der Kurs steigt.",
    long: "Schützt Gewinne: Wenn eine Aktie von 100 auf 130 steigt, zieht der Trailing Stop z.B. auf 117 mit (10% unter dem Hoch). Bei Kursrückgang wird automatisch verkauft.",
    category: "risk"
  },

  // --- Market Indicators ---
  "Shiller PE": {
    short: "Zyklisch bereinigtes KGV — nutzt den Durchschnittsgewinn der letzten 10 Jahre statt nur 1 Jahr.",
    long: "Auch CAPE (Cyclically Adjusted PE) genannt. Glättet Konjunkturzyklen. Historischer Durchschnitt: ~17. Über 30 = Markt ist teuer. Aktuell oft über 30 (seit 2020).",
    category: "indicator"
  },
  "CAPE": {
    short: "Cyclically Adjusted PE — siehe Shiller PE. Langfristiges Bewertungsmass für den Gesamtmarkt.",
    long: "Entwickelt von Nobelpreisträger Robert Shiller. Hoher CAPE-Wert bedeutet nicht zwingend einen Crash, aber niedrigere erwartete Renditen über die nächsten 10 Jahre.",
    category: "indicator"
  },
  "Shiller PE (CAPE)": {
    short: "Zyklisch bereinigtes KGV — nutzt den Durchschnittsgewinn der letzten 10 Jahre statt nur 1 Jahr.",
    long: "Auch CAPE (Cyclically Adjusted PE) genannt. Glättet Konjunkturzyklen. Historischer Durchschnitt: ~17. Über 30 = Markt ist teuer.",
    category: "indicator"
  },
  "Buffett Indicator": {
    short: "Gesamte Marktkapitalisierung geteilt durch das Bruttoinlandsprodukt eines Landes.",
    long: "Warren Buffetts bevorzugter Indikator für die Gesamtmarkt-Bewertung. Über 100% = Markt ist teurer als die Wirtschaftsleistung. Über 150% = stark überbewertet.",
    category: "indicator"
  },
  "Zinsstrukturkurve": {
    short: "Vergleich von kurzfristigen und langfristigen Zinsen — invertiert = Rezessionswarnung.",
    long: "Normal: Langfristige Zinsen höher als kurzfristige. Invertiert (kurzfristig > langfristig) = der Markt erwartet eine Rezession. Hat historisch jede US-Rezession vorhergesagt.",
    category: "indicator"
  },
  "Yield Curve": {
    short: "Zinsstrukturkurve — siehe oben. Invertierung = klassisches Rezessionssignal.",
    long: "Die Differenz zwischen 10-Jahres und 2-Jahres US-Staatsanleihen. Negativ = invertiert = Warnsignal. Positiv = normal.",
    category: "indicator"
  },
  "Zinsstruktur (10Y-2Y)": {
    short: "Differenz zwischen 10-Jahres und 2-Jahres US-Staatsanleihen — invertiert = Rezessionswarnung.",
    long: "Normal: 10Y > 2Y (positive Steigung). Invertiert: 2Y > 10Y — historisch einer der zuverlässigsten Rezessionsindikatoren.",
    category: "indicator"
  },
  "SARON": {
    short: "Swiss Average Rate Overnight — der Schweizer Referenzzinssatz für variabel verzinste Hypotheken.",
    long: "SARON ersetzt seit 2022 den LIBOR. Er wird täglich von der SIX berechnet und basiert auf tatsächlichen Transaktionen am Schweizer Geldmarkt. SARON-Hypotheken haben einen variablen Zins (SARON + Bankmarge).",
    category: "general"
  },
  "S&P 500": {
    short: "Index der 500 grössten US-Unternehmen — DER Benchmark für den Aktienmarkt.",
    long: "Enthält Apple, Microsoft, Amazon, etc. Wenn 'der Markt' steigt oder fällt, ist meist der S&P 500 gemeint. Basis für viele Indikatoren (VIX, MRS, Makro-Gate).",
    category: "general"
  },
  "Sektor-Rotation": {
    short: "Kapitalflüsse zwischen Branchen — zeigt welche Sektoren gerade bevorzugt werden.",
    long: "In verschiedenen Marktphasen performen unterschiedliche Sektoren besser: Technologie in Aufschwung, Versorger/Gesundheit in Abschwung, Rohstoffe bei Inflation.",
    category: "strategy"
  },
  "Risk-On": {
    short: "Marktumfeld in dem Anleger risikofreudig sind — Aktien, Krypto und Wachstumswerte steigen.",
    long: "Typisch bei niedrigem VIX, steigendem S&P 500, und positiver Wirtschaftsstimmung. Satellite-Positionen und Breakout-Trades funktionieren am besten.",
    category: "strategy"
  },
  "Risk-Off": {
    short: "Marktumfeld in dem Anleger Risiko meiden — Flucht in sichere Häfen (Gold, Anleihen, Cash).",
    long: "Typisch bei hohem VIX, fallendem S&P 500, und Rezessionsangst. In diesem Umfeld: nur Core-Positionen halten, keine Neukäufe, Cash aufbauen.",
    category: "strategy"
  },

  // --- General ---
  "TTWROR": {
    short: "True Time-Weighted Rate of Return — zeitgewichtete Rendite die Ein-/Auszahlungen herausrechnet.",
    long: "Die fairste Art, Portfolio-Performance zu messen. Eliminiert den Effekt von Geldzu-/-abflüssen. So werden deine Anlageentscheide bewertet, nicht dein Timing bei Ein-/Auszahlungen.",
    category: "general"
  },
  "YTD": {
    short: "Year to Date — Performance seit Jahresbeginn (1. Januar).",
    long: "Zeigt wie sich dein Portfolio oder eine Aktie seit dem 1. Januar dieses Jahres entwickelt hat. Standard-Vergleichszeitraum in der Finanzwelt.",
    category: "general"
  },
  "ISIN": {
    short: "International Securities Identification Number — weltweit eindeutige Wertpapierkennung.",
    long: "12-stelliger Code der jedes Wertpapier eindeutig identifiziert. Beispiel: CH0012032048 = Roche. Wird beim Import von Transaktionen für das Ticker-Mapping verwendet.",
    category: "general"
  },
  "Ticker": {
    short: "Börsenkürzel einer Aktie — z.B. WM für Waste Management, NOVN.SW für Novartis.",
    long: "Jede Aktie hat einen kurzen Code (Ticker) der sie an der Börse identifiziert. Das Suffix zeigt die Börse: .SW = Schweiz (SIX), .TO = Kanada (TSX), kein Suffix = USA.",
    category: "general"
  },
  "Volumen": {
    short: "Anzahl gehandelter Aktien in einem Zeitraum — zeigt wie aktiv eine Aktie gehandelt wird.",
    long: "Hohes Volumen bei einem Breakout = viele Marktteilnehmer bestätigen die Bewegung. Niedriges Volumen = die Bewegung ist weniger vertrauenswürdig.",
    category: "general"
  },
  "Allokation": {
    short: "Verteilung des Portfolios auf verschiedene Anlageklassen, Sektoren oder Positionen.",
    long: "Beispiel: 70% Core-Aktien, 30% Satellite. Oder: 40% Tech, 20% Gesundheit, 15% Finanzen, etc. Gute Allokation = Diversifikation = weniger Risiko.",
    category: "general"
  },
  "ETF": {
    short: "Exchange Traded Fund — Fonds der an der Börse gehandelt wird und einen Index nachbildet.",
    long: "Beispiel: SPY bildet den S&P 500 nach. Ein ETF-Kauf = du kaufst alle 500 Unternehmen auf einmal. Günstig, diversifiziert, ideal für Einsteiger.",
    category: "general"
  },
  "DCA": {
    short: "Dollar Cost Averaging — regelmässig den gleichen Betrag investieren, egal ob der Markt hoch oder tief steht.",
    long: "Beispiel: Jeden Monat CHF 500 in einen ETF. Bei hohen Kursen kaufst du weniger Anteile, bei tiefen mehr. Über Zeit ergibt sich ein guter Durchschnittspreis.",
    category: "strategy"
  },
  "FX": {
    short: "Foreign Exchange — Wechselkurse zwischen Währungen (z.B. USD/CHF).",
    long: "Wichtig für Schweizer Anleger: US-Aktien werden in Dollar gehandelt. Steigt der Dollar, steigt auch der CHF-Wert deiner US-Aktien (und umgekehrt).",
    category: "general"
  },
  "Spot-Preis": {
    short: "Aktueller Marktpreis für sofortige Lieferung — z.B. bei Gold oder Silber.",
    long: "Der Preis zu dem ein Rohstoff oder Edelmetall JETZT gehandelt wird (im Gegensatz zu Futures-Preisen für zukünftige Lieferung).",
    category: "general"
  },
  "Rebalancing": {
    short: "Neugewichtung des Portfolios — Positionen zurück auf die Zielallokation bringen.",
    long: "Wenn eine Aktie stark gestiegen ist und nun 15% statt 10% des Portfolios ausmacht, wird sie teilverkauft um die Balance wiederherzustellen.",
    category: "strategy"
  },
  "Schwur 1": {
    short: "Kernregel: Kein Kauf wenn der Kurs unter der 150-DMA (Investor Line) liegt.",
    long: "Die wichtigste Regel im System. Schützt davor, in einem Abwärtstrend zu kaufen. Wird der Schwur verletzt (Kurs fällt unter 150-DMA), Verkaufskriterien prüfen. Ausnahme: Breite Index-ETFs — unter 200-DMA sind Kaufkriterien erfüllt.",
    category: "strategy"
  },
  "YoY": {
    short: "Year over Year — Vergleich mit dem gleichen Zeitraum im Vorjahr.",
    long: "Zeigt ob ein Wert (z.B. Umsatz, Gewinn) im Vergleich zum Vorjahr gewachsen oder geschrumpft ist. Beispiel: Revenue Growth YoY +18% = Umsatz ist 18% höher als vor einem Jahr.",
    category: "general"
  },
  "HH/HL": {
    short: "Higher High / Higher Low — aufsteigende Hochs und Tiefs, Zeichen eines Aufwärtstrends.",
    long: "In einem Aufwärtstrend macht der Kurs immer höhere Hochs (HH) und höhere Tiefs (HL). Wenn dieses Muster bricht, ist der Trend möglicherweise zu Ende.",
    category: "indicator"
  },
  "MCap": {
    short: "Market Capitalization — Börsenwert eines Unternehmens (Aktienkurs × Anzahl Aktien).",
    long: "Large Cap (>10 Mrd) = stabil, geringes Risiko. Mid Cap (2-10 Mrd) = Wachstumspotential. Small Cap (<2 Mrd) = höheres Risiko, höhere Chancen.",
    category: "metric"
  },
  "Sektor-Leader": {
    short: "Aktie mit Mansfield RS über 1.0 — performt deutlich besser als der Gesamtmarkt.",
    long: "Sektor-Leader sind die stärksten Aktien innerhalb ihrer Branche. Sie steigen in Aufwärtsmärkten am stärksten und fallen in Abwärtsmärkten oft weniger.",
    category: "indicator"
  },
  "starkes Setup": {
    short: "Setup-Score ≥ 70% — hohe technische Qualität, Kaufkandidat.",
    long: "Mindestens 13 von 18 Kriterien erfüllt. Die Aktie zeigt starken Trend und relative Stärke. Bei Breakout → Kaufkriterien erfüllt.",
    category: "strategy"
  },
  "moderates Setup": {
    short: "Setup-Score 45-69% — einige Kriterien fehlen noch, beobachten.",
    long: "Die Aktie zeigt Potential, aber nicht genug für einen Kauf. Regelmässig prüfen ob sich die fehlenden Kriterien verbessern.",
    category: "strategy"
  },
  "schwaches Setup": {
    short: "Setup-Score unter 45% — zu viele Kriterien nicht erfüllt, kein Kauf.",
    long: "Weniger als die Hälfte der technischen Kriterien ist erfüllt. Die Aktie ist aktuell kein Kaufkandidat.",
    category: "strategy"
  },
  "Moving Averages": {
    short: "Gleitende Durchschnitte — glätten den Kursverlauf und zeigen den Trend.",
    long: "MA50 (kurzfristig), MA150 (mittelfristig, 'Investor Line'), MA200 (langfristig). Kurs über den MAs = Aufwärtstrend. Wenn kürzere MAs über längeren liegen = besonders stark.",
    category: "indicator"
  },
  "Fundamentals": {
    short: "Fundamentaldaten — finanzielle Kennzahlen eines Unternehmens (Umsatz, Gewinn, Verschuldung).",
    long: "Zeigen die wirtschaftliche Gesundheit: Wächst der Umsatz? Ist das Unternehmen profitabel? Wie hoch ist die Verschuldung? Gute Fundamentaldaten = solide Basis für den Aktienkurs.",
    category: "metric"
  },
  "Liquidität": {
    short: "Wie einfach eine Aktie ge- oder verkauft werden kann ohne den Kurs zu beeinflussen.",
    long: "Hohes Volumen und hohe Marktkapitalisierung = gute Liquidität. Illiquide Aktien (Small Caps, wenig gehandelt) können grosse Spreads und schwierige Verkäufe bedeuten.",
    category: "general"
  },
  "Avg Volume": {
    short: "Durchschnittliches tägliches Handelsvolumen — wie viele Aktien pro Tag gehandelt werden.",
    long: "Über 200'000 Aktien/Tag gilt als ausreichend liquid für Privatanleger. Niedriges Volumen = schwieriger zu kaufen/verkaufen zu fairen Preisen.",
    category: "metric"
  },

  // --- Real Estate ---
  "LTV": {
    short: "Loan-to-Value — Belehnung: Verhältnis von Hypothek zu Marktwert der Immobilie.",
    long: "LTV 80% bedeutet: 80% des Immobilienwerts ist fremdfinanziert. In der Schweiz: bis 66.7% = 1. Hypothek (keine Amortisation), darüber = 2. Hypothek (Amortisation innert 15 Jahren). Max: 80%.",
    category: "metric"
  },
  "Eigenkapital": {
    short: "Der Anteil am Immobilienwert, der nicht durch Hypotheken finanziert ist.",
    long: "Eigenkapital = Marktwert minus Hypothekarschuld. In der Schweiz müssen mindestens 20% Eigenkapital eingebracht werden, davon mindestens 10% nicht aus der Pensionskasse.",
    category: "general"
  },
  "Hypothek": {
    short: "Kredit zur Finanzierung einer Immobilie, besichert durch das Grundpfandrecht.",
    long: "Typen in der Schweiz: Festhypothek (fixer Zins, 2-15 Jahre), SARON-Hypothek (variabler Zins) und variable Hypothek (jederzeit kündbar, höherer Zins).",
    category: "general"
  },
  "Marktwert": {
    short: "Aktueller Wert einer Position oder Immobilie zu heutigen Marktpreisen.",
    long: "Bei Aktien: Anzahl × Kurs × Wechselkurs. Bei Immobilien: geschätzter Verkehrswert. Bei Edelmetallen: Gewicht × Spot-Preis.",
    category: "metric"
  },

  // --- Precious Metals ---
  "COMEX": {
    short: "Commodity Exchange — die weltweit grösste Terminbörse für Gold und Silber (CME Group, New York).",
    long: "COMEX-Preise gelten als globaler Referenzpreis für Edelmetalle. Gold COMEX und Silber COMEX zeigen den aktuellen Spot-Preis an dieser Börse.",
    category: "general"
  },
  "Gold/Silber Ratio": {
    short: "Wie viele Unzen Silber man für eine Unze Gold bekommt. Historischer Durchschnitt: ~60-70.",
    long: "Hoher Wert (>80) = Silber relativ günstig. Niedriger Wert (<50) = Silber relativ teuer. Wird als Umschichtungs-Signal zwischen Gold und Silber verwendet.",
    category: "metric"
  },
  "Einstand": {
    short: "Kaufpreis — der ursprüngliche Anschaffungswert inklusive Gebühren.",
    long: "Bei Edelmetallen: Kaufpreis pro Stück inklusive Premium und Transaktionskosten. Basis für die Berechnung von Gewinn oder Verlust.",
    category: "general"
  },
  "CHF/oz": {
    short: "Preis in Schweizer Franken pro Feinunze (31.1 Gramm).",
    long: "Die Feinunze (Troy Ounce) ist die Standard-Gewichtseinheit für Edelmetalle. 1 oz = 31.1035 Gramm.",
    category: "metric"
  },

  // --- Crypto ---
  "BTC Dominance": {
    short: "Anteil von Bitcoin an der gesamten Krypto-Marktkapitalisierung.",
    long: "Hohe Dominance (>60%) = Bitcoin dominiert (typisch in Bärenmärkten). Sinkende Dominance kann auf eine 'Altcoin Season' hindeuten.",
    category: "metric"
  },
  "Fear & Greed": {
    short: "Crypto Fear & Greed Index — Marktstimmung von 0 (extreme Angst) bis 100 (extreme Gier).",
    long: "Basiert auf Volatilität, Volumen, Social Media und BTC-Dominanz. Angst (<20) = mögliche Kaufgelegenheit. Gier (>80) = Warnung vor Überhitzung.",
    category: "indicator"
  },
  "Halving": {
    short: "Bitcoin Halving — die Block-Belohnung für Miner wird alle ~4 Jahre halbiert.",
    long: "Reduziert die Bitcoin-Inflation. Historisch folgten auf Halvings (2012, 2016, 2020, 2024) signifikante Kursanstiege in den 12-18 Monaten danach.",
    category: "general"
  },
  "DXY": {
    short: "US Dollar Index — misst den Dollar gegenüber 6 Hauptwährungen (EUR, JPY, GBP, CAD, SEK, CHF).",
    long: "Steigender DXY = stärkerer Dollar, tendenziell negativ für Bitcoin, Gold und Risiko-Assets. Fallender DXY = oft bullish für Krypto und Edelmetalle.",
    category: "indicator"
  },
  "ATH": {
    short: "All-Time High — der höchste jemals erreichte Kurs.",
    long: "BTC vs ATH zeigt wie weit der aktuelle Kurs vom historischen Höchstwert entfernt ist. -44% = Kurs liegt 44% unter dem Allzeithoch.",
    category: "metric"
  },
  "24h %": {
    short: "Kursveränderung in den letzten 24 Stunden, in Prozent.",
    long: "Bei Kryptowährungen ist der Markt 24/7 geöffnet, daher 24h statt Tagesveränderung.",
    category: "metric"
  },
  "MWR": {
    short: "Geldgewichtete Rendite (Money-Weighted Return) — misst die tatsächliche Rendite unter Berücksichtigung von Zeitpunkt und Höhe aller Ein-/Auszahlungen.",
    long: "MWR/XIRR zeigt was du wirklich verdient hast: Wenn du am Tiefpunkt viel Geld investiert hast, ist deine MWR besser als die zeitgewichtete Rendite. Wird für Jahres- und YTD-Totals verwendet.",
    category: "metric"
  },
  "XIRR": {
    short: "Extended Internal Rate of Return — annualisierte geldgewichtete Rendite (= MWR).",
    long: "XIRR berechnet die Rendite, bei der der Barwert aller Cashflows (Ein-/Auszahlungen + aktueller Portfoliowert) gleich null ist. Standard in der Finanzbranche für Portfolio-Performance.",
    category: "metric"
  },
  "Modified Dietz": {
    short: "Zeitgewichtete Renditeberechnung für einzelne Monate — berücksichtigt Cashflow-Zeitpunkte.",
    long: "Formel: R = (V_end - V_start - Summe CF) / (V_start + Summe(w_i * CF_i)). Gewichtet Cashflows nach ihrem Zeitpunkt im Monat. Wird in OpenFolio für die Monatsrenditen in der Heatmap verwendet.",
    category: "metric"
  },
  "Perf %": {
    short: "Performance in Prozent — Gewinn oder Verlust relativ zum Einstandspreis.",
    long: "Berechnung: ((aktueller Wert / Einstandswert) - 1) × 100. Positiv = Gewinn, Negativ = Verlust.",
    category: "metric"
  },
  "Marktklima": {
    short: "Gesamteinschätzung des Marktzustands basierend auf technischen und makroökonomischen Indikatoren.",
    long: "Kombiniert S&P 500 Trend, VIX-Regime und Makro-Gate zu einer Ampel: Risk-On (grün) oder Risk-Off (rot). Bestimmt ob neue Käufe erlaubt sind.",
    category: "strategy"
  },
  "50-DMA": {
    short: "50-Tage gleitender Durchschnitt — kurzfristiger Trendindikator.",
    long: "Zeigt den Trend der letzten ~2.5 Monate. Kurs über 50-DMA = kurzfristig positiv.",
    category: "indicator"
  },
  "DMA": {
    short: "Daily Moving Average — gleitender Durchschnitt über eine bestimmte Anzahl Handelstage.",
    long: "Der 50-DMA zeigt den kurzfristigen, der 150-DMA den mittelfristigen und der 200-DMA den langfristigen Trend. Kurs über dem DMA = Aufwärtstrend.",
    category: "indicator"
  },
  "Core/Satellite": {
    short: "Portfolio-Strategie: 70% langfristige Kernpositionen (Core) + 30% taktische Chancen (Satellite).",
    long: "Core-Positionen sind Qualitätsaktien mit strukturellem Stop (15-25%), quartalsweise überprüft. Satellite sind Breakout-Trades mit engem Stop (5-12%), wöchentlich überprüft.",
    category: "strategy"
  },
  "D/E Ratio": {
    short: "Debt-to-Equity Ratio — Verhältnis von Fremdkapital zu Eigenkapital.",
    long: "Unter 1.0 bedeutet mehr Eigenkapital als Schulden. Branchenvergleich wichtig: kapitalintensive Branchen haben naturgemäss höhere D/E-Werte.",
    category: "metric"
  },
  "Arbeitslosenquote": {
    short: "Anteil der erwerbsfähigen Bevölkerung ohne Arbeit — ein nachlaufender Konjunkturindikator.",
    long: "Steigende Arbeitslosigkeit signalisiert Abschwächung. Daten von FRED (Federal Reserve Economic Data).",
    category: "metric"
  },
  "WTI": {
    short: "West Texas Intermediate — der US-amerikanische Rohöl-Benchmark-Preis.",
    long: "Steigender Ölpreis kann Inflation antreiben. Stark fallender Ölpreis kann auf Rezession hindeuten.",
    category: "metric"
  },
  "Öl (Brent)": {
    short: "Brent Crude — der globale Rohöl-Benchmark-Preis (Nordsee).",
    long: "Brent ist der wichtigste internationale Ölpreis-Benchmark. Er liegt typischerweise $2-5 über WTI (Transportkosten). Starke Abweichungen deuten auf geopolitische Spannungen oder regionale Angebotsverschiebungen hin.",
    category: "metric"
  },
  "WTI-Brent Spread": {
    short: "Preisdifferenz zwischen Brent und WTI Rohöl — ein Indikator für geopolitische Risiken.",
    long: "Normal: $2-5 (Transportkosten). Wachsender Spread (>$5): Geopolitische Spannungen oder globale Angebotsknappheit. Negativer Spread (WTI > Brent): Sehr selten, deutet auf US-spezifische Engpässe. Schnelle Veränderungen sind ein Frühwarnzeichen.",
    category: "metric"
  },
  "Fed Funds Rate": {
    short: "Der Leitzins der US-Notenbank — bestimmt die Kosten für kurzfristige Kredite.",
    long: "Die Fed erhöht den Zins gegen Inflation und senkt ihn zur Ankurbelung. Höhere Zinsen machen Aktien relativ unattraktiver.",
    category: "metric"
  },
  "Gew.": {
    short: "Gewichtung — wie stark dieser Indikator im Makro-Gate Score zählt.",
    long: "S&P 500 über 150-DMA und VIX unter 20 zählen doppelt (Gewichtung 2) weil sie die wichtigsten Signale sind.",
    category: "general"
  },
  "Schwelle": {
    short: "Mindestpunktzahl damit das Makro-Gate als bestanden gilt (aktuell 6 von 9).",
    long: "Wenn der Score unter der Schwelle liegt, zeigt das Makro-Gate an, dass Kaufkriterien nicht erfüllt sind.",
    category: "strategy"
  },
  "Credit Spread (High Yield)": {
    short: "Renditedifferenz zwischen Hochzins-Unternehmensanleihen und US-Staatsanleihen.",
    long: "Steigende Spreads = Anleger verlangen mehr Risikoprämie = Vorsicht. Unter 3%: entspannt. 3-5%: normal. 5-7%: erhöhte Risikoaversion. Über 7%: historisch oft vor/während Rezessionen.",
    category: "metric"
  },
  "Marktbreite (A/D Ratio)": {
    short: "Verhältnis der steigenden zu fallenden Aktien an der NYSE.",
    long: "Zeigt ob ein Trend von vielen oder nur wenigen Aktien getragen wird. Über 1.5: breite Beteiligung, gesund. Unter 0.7: Marktbreite kollabiert. Divergenz (Index steigt, A/D fällt) = klassisches Warnsignal.",
    category: "metric"
  },
  // --- Smart Money / Screening ---
  "Smart Money Score": {
    short: "Aggregierter Score (0–10) basierend auf institutioneller Aktivität rund um eine Aktie.",
    long: "Kombiniert Signale aus Insider-Käufen, Superinvestor-Positionen, Aktienrückkäufen, Congressional Trading, Short-Trends und weiteren Quellen. Ein höherer Score bedeutet, dass mehrere unabhängige Quellen institutionelles Interesse zeigen. Dies ist kein Kauf-/Verkaufssignal, sondern ein Kontextindikator.",
    category: "indicator"
  },
  "Insider-Cluster": {
    short: "Zwei oder mehr Insider (CEO, CFO, Directors) kaufen innerhalb von 60 Tagen Aktien desselben Unternehmens.",
    long: "Einer der stärksten Smart-Money-Indikatoren. Wenn mehrere Insider gleichzeitig mit eigenem Geld kaufen, deutet das auf Überzeugung des Managements hin, dass die Aktie unterbewertet ist. Gewichtung im Score: 3 Punkte. Quelle: OpenInsider (SEC Form 4).",
    category: "indicator"
  },
  "Grosser Insider-Kauf": {
    short: "Ein einzelner Insider kauft Aktien im Wert von über $500'000.",
    long: "Grosse Insider-Käufe zeigen starkes persönliches Commitment. Der Insider riskiert erhebliches eigenes Kapital, was als positives Signal gewertet wird. Gewichtung im Score: 1 Punkt. Wird nicht gezählt, wenn bereits ein Insider-Cluster vorliegt. Quelle: OpenInsider (SEC Form 4).",
    category: "indicator"
  },
  "Superinvestor": {
    short: "Bekannte Value-Investoren wie Buffett, Icahn oder Ackman halten eine Position in dieser Aktie.",
    long: "Basiert auf 13F-Filings und Dataroma's Tracking von 82 Superinvestoren. Wenn 3 oder mehr Superinvestoren dieselbe Aktie halten, wird dies als Konsenssignal gewertet. Gewichtung im Score: 2 Punkte. Daten sind quartalweise (13F) mit 45 Tagen Verzögerung.",
    category: "indicator"
  },
  "Aktivist (13D/13G)": {
    short: "Ein aktivistischer Investor hat eine Beteiligung von 5% oder mehr an diesem Unternehmen gemeldet.",
    long: "SEC Schedule 13D wird eingereicht, wenn ein Investor 5%+ einer Firma besitzt und aktiv Einfluss nehmen will (z.B. Icahn, Elliott, Starboard). 13G ist die passive Variante. Beide signalisieren erhebliches institutionelles Interesse. Gewichtung: 2 Punkte. Quelle: SEC EDGAR Submissions API.",
    category: "indicator"
  },
  "Aktienrückkauf": {
    short: "Das Unternehmen hat ein Aktienrückkaufprogramm (Share Buyback) angekündigt.",
    long: "Wenn eine Firma eigene Aktien zurückkauft, signalisiert das Management, dass es die Aktie für unterbewertet hält. Rückkäufe reduzieren die Anzahl ausstehender Aktien und erhöhen den Gewinn pro Aktie. Wird aus SEC 8-K Filings mit den Stichworten 'share repurchase' oder 'stock buyback' erkannt. Gewichtung: 2 Punkte.",
    category: "indicator"
  },
  "Kongresskauf": {
    short: "Ein Mitglied des US-Kongresses hat diese Aktie in den letzten 90 Tagen gekauft.",
    long: "Unter dem STOCK Act müssen US-Kongressmitglieder Aktientransaktionen offenlegen. Historisch haben Kongressportfolios den Markt geschlagen, möglicherweise aufgrund politischer Informationsvorsprünge. Achtung: Reporting-Delay von bis zu 45 Tagen. Gewichtung: 1 Punkt. Quelle: Capitol Trades.",
    category: "indicator"
  },
  "Short-Trend": {
    short: "Die Short-Quote dieser Aktie ist in den letzten 14 Tagen um mindestens 20% gestiegen — ein kontextabhängiges Signal.",
    long: "Bearish-Lesart: Mehr Institutionen wetten gegen die Aktie — sie sehen möglicherweise etwas Negatives, das der breite Markt noch nicht eingepreist hat. Bullish-Lesart (Kontrarian): Hoher Short-Anteil erzeugt Squeeze-Potenzial — wenn der Kurs trotzdem steigt, müssen Shorter zurückkaufen, was den Kurs weiter treibt. Im Smart Money Tracker wird der Short-Trend als Verstärker-Signal genutzt (1 Punkt), nicht als eigenständiges Kaufargument. Er feuert nur für Aktien, die bereits ein anderes Signal haben (z.B. Insider-Käufe + Short-Druck ist aussagekräftiger als Short-Druck allein). Quelle: FINRA Short Volume (tägliche Daten, 14-Tage-Trend).",
    category: "indicator"
  },
  "Fails-to-Deliver": {
    short: "Hohe Anzahl an Aktien, die nach einer Transaktion nicht innerhalb der Frist geliefert wurden (SEC FTD).",
    long: "Fails-to-Deliver entstehen, wenn Verkäufer Aktien nicht rechtzeitig liefern können. Hohe FTD-Zahlen können auf Naked Shorting hindeuten und erhöhen das Short-Squeeze-Potenzial. Die SEC veröffentlicht FTD-Daten halbjährlich. Dies ist ein Warnindikator ohne Score-Punkte.",
    category: "indicator"
  },
  "Unusual Volume": {
    short: "Das Handelsvolumen dieser Aktie liegt über dem 3-fachen des 20-Tage-Durchschnitts.",
    long: "Ungewöhnlich hohes Volumen deutet darauf hin, dass grosse Marktteilnehmer (Institutionen, Fonds) aktiv handeln. In Kombination mit anderen Smart-Money-Signalen verstärkt es die Aussagekraft. Gewichtung: +1 Bonuspunkt. Quelle: yfinance Volumendaten.",
    category: "indicator"
  },

  // --- Macro / Positionierung ---
  "CFTC": {
    short: "Commodity Futures Trading Commission — US-Aufsichtsbehörde für Futures- und Optionsmärkte.",
    long: "Die CFTC reguliert den Handel mit Futures und Optionen in den USA und veröffentlicht wöchentlich den Commitments of Traders (COT) Report, der die Positionierung verschiedener Marktteilnehmer offenlegt.",
    category: "general"
  },
  "Managed Money": {
    short: "Professionelle Vermögensverwalter und Hedge Funds in CFTC-Positionierungsdaten (COT-Report).",
    long: "Die Kategorie 'Managed Money' im COT-Report umfasst Commodity Trading Advisors (CTAs), Hedge Funds und andere professionelle Vermögensverwalter. Ihre Positionierung gilt als spekulativ und kann Hinweise auf institutionelle Markterwartungen geben.",
    category: "general"
  },
  "Commercial": {
    short: "Hedger/Produzenten die Futures zur Absicherung ihres physischen Geschäfts nutzen (COT-Report).",
    long: "Commercials sind Unternehmen, die Futures-Märkte nutzen, um ihre physischen Geschäftsrisiken abzusichern (z.B. Ölproduzenten, Landwirte, Minengesellschaften). Ihre Positionierung gilt als 'Smart Money', da sie den zugrunde liegenden Markt am besten kennen.",
    category: "general"
  },
  "Open Interest": {
    short: "Gesamtzahl offener Futures-Kontrakte — misst die Marktaktivität und Liquidität.",
    long: "Open Interest zeigt, wie viele Futures-Kontrakte aktuell offen (nicht glattgestellt) sind. Steigendes Open Interest bei steigenden Preisen bestätigt einen Trend. Fallendes Open Interest kann auf nachlassendes Interesse hindeuten.",
    category: "general"
  },
  "SNB": {
    short: "Schweizerische Nationalbank — zuständig für die Geldpolitik und den Leitzins in der Schweiz.",
    long: "Die SNB legt den Leitzins fest, steuert die Geldmenge und interveniert bei Bedarf am Devisenmarkt, um den Franken zu stabilisieren. Ihre geldpolitischen Entscheide beeinflussen Hypothekarzinsen, Inflation und die allgemeine Wirtschaftslage in der Schweiz.",
    category: "general"
  },
  "HICP": {
    short: "Harmonisierter Verbraucherpreisindex — EU-weit standardisiertes Inflationsmass (Eurostat).",
    long: "Der HICP misst die Preisentwicklung eines repräsentativen Warenkorbs nach einheitlicher EU-Methodik. Er ermöglicht den Vergleich der Inflationsraten zwischen verschiedenen Ländern. Die Schweiz publiziert den HICP zusätzlich zum nationalen Landesindex der Konsumentenpreise (LIK).",
    category: "metric"
  },
  "Heatmap": {
    short: "Visuelle Darstellung der Marktperformance nach Farbe (grün/rot) und Fläche (Marktkapitalisierung).",
    long: "Die Heatmap zeigt auf einen Blick, welche Aktien oder Sektoren steigen (grün) oder fallen (rot). Die Grösse der Flächen entspricht der Marktkapitalisierung, sodass grosse Unternehmen mehr Platz einnehmen. Nützlich für einen schnellen Überblick über die Marktstimmung.",
    category: "general"
  },
}

/**
 * Lookup a glossary entry by term (case-insensitive).
 */
export function lookupGlossary(term) {
  if (!term) return null
  // Exact match first
  if (GLOSSARY[term]) return { key: term, ...GLOSSARY[term] }
  // Case-insensitive
  const lower = term.toLowerCase()
  const match = Object.entries(GLOSSARY).find(([k]) => k.toLowerCase() === lower)
  if (match) return { key: match[0], ...match[1] }
  return null
}

/**
 * Get all glossary entries sorted alphabetically.
 */
export function getAllGlossaryEntries() {
  return Object.entries(GLOSSARY)
    .map(([key, val]) => ({ key, ...val }))
    .sort((a, b) => a.key.localeCompare(b.key, 'de'))
}

export const CATEGORY_LABELS = {
  indicator: 'Indikatoren',
  metric: 'Kennzahlen',
  strategy: 'Strategie',
  risk: 'Risikomanagement',
  general: 'Allgemein',
}
