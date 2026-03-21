import G from '../components/GlossarTooltip'

export default function Datenschutz() {
  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-text-primary">Datenschutz bei OpenFolio</h2>
        <p className="text-sm text-text-secondary mt-2">OpenFolio ist Free and Open Source Software (MIT-Lizenz). Du hast zwei Möglichkeiten, OpenFolio zu nutzen:</p>
      </div>

      <Section title="Self-Hosted (Du hostest selbst)">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Volle Kontrolle</strong>: Deine Daten liegen ausschliesslich auf deiner eigenen Infrastruktur.</Li>
          <Li><strong className="text-text-primary">Kein Dritter hat Zugang</strong>: Niemand ausser dir hat Zugriff auf die Datenbank oder die Verschlüsselungsschlüssel.</Li>
          <Li><strong className="text-text-primary">Keine Telemetrie</strong>: OpenFolio sendet keine Nutzungsdaten, Statistiken oder Diagnose-Informationen an uns oder Dritte.</Li>
          <Li><strong className="text-text-primary">Externer Datenverkehr</strong>: Die einzigen ausgehenden Verbindungen sind Kursabfragen an Yahoo Finance, CoinGecko, FRED und FMP. Diese enthalten ausschliesslich <G term="Ticker">Ticker</G>-Symbole — keine persönlichen Daten.</Li>
        </ul>
        <p className="text-xs text-text-muted mt-3">Du bist für Backups, Updates und Sicherheit selbst verantwortlich.</p>
      </Section>

      <Section title="Managed Hosting (Wir hosten für dich)">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Standort</strong>: Deine Daten werden auf Servern in der Schweiz gespeichert.</Li>
          <Li><strong className="text-text-primary">Verschlüsselung</strong>: Sensible Daten (IBAN, Bankname, Seriennummern, Lagerort, Notizen, Adressen) sind mit AES-256 verschlüsselt.</Li>
          <Li><strong className="text-text-primary">Admin-Zugriff</strong>: Der Betreiber hat administrativen Zugriff auf die Server-Infrastruktur. Über das Admin-Panel sind jedoch <strong className="text-text-primary">keine Portfolio-Daten, Kontostände, Transaktionen oder persönliche Finanzinformationen</strong> einsehbar.</Li>
          <Li><strong className="text-text-primary">Audit-Log</strong>: Alle administrativen Aktionen werden protokolliert.</Li>
          <Li><strong className="text-text-primary">Keine Weitergabe</strong>: Deine Daten werden niemals an Dritte weitergegeben, verkauft oder für Werbung verwendet.</Li>
          <Li><strong className="text-text-primary">Keine Telemetrie</strong>: Keine Nutzungsdaten, keine Tracking-Cookies, keine Analytics.</Li>
          <Li><strong className="text-text-primary">Datenlöschung</strong>: Du kannst dein Konto jederzeit löschen — alle Daten werden unwiderruflich entfernt.</Li>
        </ul>

        <div className="mt-3 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-text-secondary">
          <strong className="text-text-primary">Transparenz:</strong> Der Managed-Hosting-Service nutzt exakt denselben Code wie die Self-Hosted-Version — keine proprietären Erweiterungen, keine versteckten Funktionen.
        </div>
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
            ['Notizen (Portfolio, Watchlist)', 'Verschlüsselt (AES-256)', 'Persönliche Informationen'],
            ['API-Schlüssel (FRED, FMP, SMTP)', 'Verschlüsselt (AES-256)', 'Zugangsdaten'],
          ]}
        />
      </Section>

      <Section title="Externe API-Verbindungen">
        <Table
          headers={['Dienst', 'Gesendet', 'Empfangen']}
          rows={[
            ['Yahoo Finance', 'Ticker-Symbole', 'Kursdaten, Fundamentaldaten'],
            ['CoinGecko', '"bitcoin"', 'BTC-Kurs in CHF'],
            ['FRED', 'Indikator-IDs', 'Makro-Daten'],
            ['FMP', 'Ticker-Symbole', 'US-Fundamentaldaten'],
            ['SNB', '—', 'SARON-Zinssatz'],
          ]}
        />
        <p className="text-text-muted text-xs mt-2">Keine dieser APIs erhält persönliche Daten, Kontostände oder Portfolio-Informationen.</p>
      </Section>

      <Section title="Deine Rechte">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Einsicht</strong>: Jederzeit voller Zugriff auf alle deine Daten über die App.</Li>
          <Li><strong className="text-text-primary">Export</strong>: Transaktionen und Positionen exportierbar.</Li>
          <Li><strong className="text-text-primary">Löschung</strong>: Konto jederzeit löschbar — alle Daten werden unwiderruflich entfernt.</Li>
          <Li><strong className="text-text-primary">Portabilität</strong>: Jederzeit vom Managed Hosting zu Self-Hosted wechselbar.</Li>
        </ul>
      </Section>

      <Section title="Aufbewahrung und Löschung">
        <ul className="space-y-1.5">
          <Li><strong className="text-text-primary">Aufbewahrungsdauer</strong>: Daten werden gespeichert, solange dein Konto aktiv ist.</Li>
          <Li><strong className="text-text-primary">Kontolöschung</strong>: Bei Kontolöschung werden alle Daten unwiderruflich entfernt (CASCADE DELETE).</Li>
          <Li><strong className="text-text-primary">Rechtsgrundlage</strong>: Die Verarbeitung erfolgt auf Grundlage der Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO / Art. 31 DSG).</Li>
        </ul>
      </Section>

      <Section title="Managed Hosting: Auftragsverarbeitung">
        <p>Beim Managed Hosting werden die Daten auf Servern in der Schweiz gespeichert. Der Hosting-Anbieter wird im <a href="/impressum" className="text-primary hover:underline">Impressum</a> benannt.</p>
      </Section>

      <Section title="Open Source">
        <p>OpenFolio ist und bleibt Free and Open Source Software unter der MIT-Lizenz.</p>
        <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer"
           className="text-primary hover:underline text-sm mt-2 inline-block">github.com/dmxch/openfolio</a>
        <p className="mt-2">Die Software ist kostenlos. Der Managed-Hosting-Service ist ein optionaler Komfort-Service.</p>
      </Section>

      <div className="text-xs text-text-muted pt-2 space-x-4">
        <a href="/disclaimer" className="hover:text-text-secondary transition-colors">Rechtlicher Hinweis</a>
        <a href="/nutzungsbedingungen" className="hover:text-text-secondary transition-colors">Nutzungsbedingungen</a>
        <a href="/impressum" className="hover:text-text-secondary transition-colors">Impressum</a>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
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
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-text-muted text-left">
            {headers.map((h, i) => <th key={i} className="py-2 pr-4 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="text-text-secondary">
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border/50">
              {row.map((cell, j) => <td key={j} className="py-2 pr-4">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
