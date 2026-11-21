import G from '../components/GlossarTooltip'

export default function Datenschutz() {
  return (
    <div className="min-h-screen bg-body">
      <div className="max-w-[760px] mx-auto px-4 py-14 space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-text-primary">Datenschutz bei OpenFolio</h1>
        <p className="text-sm text-text-secondary mt-2 leading-relaxed">Diese Seite beschreibt, wie die Software OpenFolio (Free and Open Source, MIT-Lizenz) Daten speichert und verarbeitet. Verantwortlich für diese Instanz ist ihr Betreiber.</p>
      </div>

      <Section title="Betrieb und Verantwortung">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Datenhaltung</strong>: Deine Daten liegen in der Datenbank der Instanz, auf der du dich angemeldet hast.</Li>
          <Li><strong className="text-text-primary">Zugriff</strong>: Wer Zugriff auf Datenbank und Verschlüsselungsschlüssel hat, bestimmt der Betreiber der Instanz.</Li>
          <Li><strong className="text-text-primary">Keine Telemetrie</strong>: Die Software sendet keine Nutzungsdaten, Statistiken oder Diagnose-Informationen an die Entwickler oder an Dritte.</Li>
          <Li><strong className="text-text-primary">Externer Datenverkehr</strong>: Die einzigen ausgehenden Verbindungen sind Kursabfragen an Yahoo Finance, CoinGecko, FRED und FMP. Diese enthalten ausschliesslich <G term="Ticker">Ticker</G>-Symbole — keine persönlichen Daten.</Li>
        </ul>
        <p className="text-xs text-text-secondary mt-3">Backups, Updates und Sicherheit der Instanz liegen beim Betreiber.</p>
      </Section>

      <Section title="Welche Daten werden gespeichert?">
        <h4 className="text-sm font-semibold text-text-primary mb-2">Kontodaten</h4>
        <Table
          headers={['Daten', 'Speicherung', 'Zugriff']}
          rows={[
            ['E-Mail-Adresse', 'Klartext', 'Login, Benachrichtigungen'],
            ['Passwort', 'Einweg-Hash (bcrypt)', 'Niemand kann es lesen'],
            ['MFA-Secret', 'Verschlüsselt (AES-256)', 'Nur zur TOTP-Validierung'],
          ]}
        />

        <h4 className="text-sm font-semibold text-text-primary mt-4 mb-2">Finanzdaten</h4>
        <Table
          headers={['Daten', 'Speicherung', 'Begründung']}
          rows={[
            ['Positionen, Ticker, Stückzahlen', 'Klartext', 'Kurse abrufen, Performance berechnen'],
            ['Transaktionen, Preise', 'Klartext', 'Renditeberechnung, Snapshots'],
            ['IBAN, Bankname, Kontobezeichnung', 'Verschlüsselt (AES-256)', 'Sensible PII'],
            ['Edelmetall-Seriennummern, Lagerort', 'Verschlüsselt (AES-256)', 'Physische Sicherheit'],
            ['Immobilien-Adressen', 'Verschlüsselt (AES-256)', 'Sensible PII'],
            ['Hypothekenbank, Hypotheken-Notizen', 'Verschlüsselt (AES-256)', 'Sensible PII'],
            ['Mietername (Immobilien-Einnahmen)', 'Verschlüsselt (AES-256)', 'Sensible PII'],
            ['Private Equity (Firmenname, UID, Handelsregister-Nr.)', 'Verschlüsselt (AES-256)', 'Sensible PII'],
            ['Notizen (Portfolio, Watchlist)', 'Verschlüsselt (AES-256)', 'Persönliche Informationen'],
            ['API-Schlüssel (FRED, FMP, SMTP)', 'Verschlüsselt (AES-256)', 'Zugangsdaten'],
          ]}
        />
      </Section>

      <Section title="Externe API-Verbindungen">
        <Table
          headers={['Dienst', 'Gesendet', 'Empfangen']}
          rows={[
            ['Yahoo Finance (via yfinance)', 'Ticker-Symbole', 'Kursdaten, Fundamentaldaten'],
            ['CoinGecko', '"bitcoin"', 'BTC-Kurs in CHF'],
            ['FRED', 'Indikator-IDs', 'Makro-Daten'],
            ['FMP', 'Ticker-Symbole', 'US-Fundamentaldaten'],
            ['SNB', '—', 'SARON-Zinssatz'],
            ['Gold.org', 'Ticker-Symbol', 'Edelmetall-Spotpreise'],
            ['multpl.com', '—', 'Shiller PE (CAPE) Ratio'],
            ['TradingView (Widget)', 'IP-Adresse, Ticker (Client-seitig)', 'Interaktive Charts'],
          ]}
        />
        <p className="text-text-secondary text-xs mt-2">Keine dieser APIs erhält persönliche Daten, Kontostände oder Portfolio-Informationen. Die server-seitigen Abfragen enthalten ausschliesslich Ticker-Symbole oder Indikator-IDs.</p>
        <p className="text-text-secondary text-xs mt-2"><strong className="text-text-secondary">Hinweis zu TradingView:</strong> Das TradingView-Chart-Widget wird direkt im Browser geladen. Dabei wird deine IP-Adresse an TradingView Inc. (USA) übermittelt. TradingView kann eigene Cookies setzen. Weitere Informationen in der <a href="https://www.tradingview.com/privacy-policy/" target="_blank" rel="noopener noreferrer" className="text-link hover:underline">Datenschutzerklärung von TradingView</a>. Die Einbindung erfolgt auf Grundlage unseres berechtigten Interesses an einer ansprechenden Darstellung von Kursdaten (Art. 6 Abs. 1 lit. f DSGVO).</p>
        <p className="text-text-secondary text-xs mt-2"><strong className="text-text-secondary">Hinweis zu Yahoo Finance:</strong> Die Kursdaten werden über die Open-Source-Bibliothek yfinance bezogen. Die Verfügbarkeit und Genauigkeit der Daten kann nicht garantiert werden.</p>
      </Section>

      <Section title="Deine Rechte">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Einsicht</strong>: Jederzeit voller Zugriff auf alle deine Daten über die App.</Li>
          <Li><strong className="text-text-primary">Export</strong>: Transaktionen und Positionen exportierbar.</Li>
          <Li><strong className="text-text-primary">Löschung</strong>: Konto jederzeit löschbar — alle Daten werden unwiderruflich entfernt.</Li>
          <Li><strong className="text-text-primary">Portabilität</strong>: Du kannst deine Daten exportieren und auf eine andere Instanz umziehen.</Li>
        </ul>
      </Section>

      <Section title="Aufbewahrung und Löschung">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Aufbewahrungsdauer</strong>: Daten werden gespeichert, solange dein Konto aktiv ist.</Li>
          <Li><strong className="text-text-primary">Kontolöschung</strong>: Bei Kontolöschung werden alle Daten unwiderruflich entfernt (CASCADE DELETE).</Li>
        </ul>
      </Section>

      <Section title="Rechtsgrundlagen">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Login, Portfolio-Daten, Transaktionen</strong>: Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO / Art. 31 DSG).</Li>
          <Li><strong className="text-text-primary">Kursdaten-Abruf</strong> (Yahoo Finance, CoinGecko, FRED, FMP, Gold.org, SNB, multpl.com): Vertragserfüllung — nötig für die Kernfunktionalität (Art. 6 Abs. 1 lit. b DSGVO).</Li>
          <Li><strong className="text-text-primary">TradingView-Widget</strong>: Berechtigtes Interesse an ansprechender Chart-Darstellung (Art. 6 Abs. 1 lit. f DSGVO).</Li>
          <Li><strong className="text-text-primary">E-Mail-Benachrichtigungen</strong>: Einwilligung — der Nutzer aktiviert Alerts explizit (Art. 6 Abs. 1 lit. a DSGVO).</Li>
          <Li><strong className="text-text-primary">Sicherheitslogs</strong> (Rate Limiting, Audit Log): Berechtigtes Interesse an der Sicherheit des Dienstes (Art. 6 Abs. 1 lit. f DSGVO).</Li>
        </ul>
      </Section>

      <Section title="Kontakt für Datenschutzanfragen">
        <p>Für Datenschutzanfragen (Auskunft, Berichtigung, Löschung) wende dich an den Betreiber dieser Instanz.</p>
      </Section>

      <Section title="Open Source">
        <p>OpenFolio ist und bleibt Free and Open Source Software unter der MIT-Lizenz.</p>
        <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer"
           className="text-link hover:underline text-sm mt-2 inline-block">github.com/dmxch/openfolio</a>
      </Section>

      <div className="text-xs pt-2 space-x-4">
        <a href="/disclaimer" className="text-text-muted hover:text-text-primary transition-colors">Rechtlicher Hinweis</a>
        <a href="/impressum" className="text-text-muted hover:text-text-primary transition-colors">Impressum</a>
      </div>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="rounded-card border border-border bg-card p-[18px]">
      <h3 className="text-sm font-semibold text-text-primary mb-3">{title}</h3>
      <div className="text-sm text-text-secondary leading-relaxed space-y-2">
        {children}
      </div>
    </div>
  )
}

function Li({ children }) {
  return <li className="flex gap-2 text-sm text-text-secondary"><span className="text-text-muted shrink-0">•</span><span>{children}</span></li>
}

function Table({ headers, rows }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border-2 mt-1">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint text-left">
            {headers.map((h, i) => <th key={i} className="px-3 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="text-text-secondary">
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border-row last:border-0 hover:bg-hover transition-colors">
              {row.map((cell, j) => <td key={j} className="px-3 py-2">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
