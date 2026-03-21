import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import G from '../components/GlossarTooltip'

export default function Legal() {
  const { hash } = useLocation()

  useEffect(() => {
    if (hash) {
      const el = document.getElementById(hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else {
      window.scrollTo(0, 0)
    }
  }, [hash])

  return (
    <div className="max-w-3xl mx-auto space-y-10">
      {/* Quick nav */}
      <div>
        <h1 className="text-xl font-bold text-text-primary mb-3">Rechtliches</h1>
        <div className="flex flex-wrap gap-2 text-xs">
          <a href="#disclaimer" className="px-3 py-1.5 rounded-lg bg-card border border-border text-text-secondary hover:text-text-primary hover:border-primary/50 transition-colors">Rechtlicher Hinweis</a>
          <a href="#datenschutz" className="px-3 py-1.5 rounded-lg bg-card border border-border text-text-secondary hover:text-text-primary hover:border-primary/50 transition-colors">Datenschutz</a>
          <a href="#nutzungsbedingungen" className="px-3 py-1.5 rounded-lg bg-card border border-border text-text-secondary hover:text-text-primary hover:border-primary/50 transition-colors">Nutzungsbedingungen</a>
          <a href="#impressum" className="px-3 py-1.5 rounded-lg bg-card border border-border text-text-secondary hover:text-text-primary hover:border-primary/50 transition-colors">Impressum</a>
        </div>
      </div>

      {/* ── Disclaimer ── */}
      <section id="disclaimer" className="scroll-mt-6 space-y-4">
        <h2 className="text-lg font-semibold text-text-primary border-b border-border pb-2">Rechtlicher Hinweis</h2>
        <p className="text-sm text-text-secondary">
          OpenFolio ist ein Software-Tool zur Verwaltung und Analyse von Wertpapierportfolios.
          OpenFolio ist <strong className="text-text-primary">kein Anlageberater</strong> und gibt <strong className="text-text-primary">keine Anlageempfehlungen</strong>.
        </p>

        <Card title="Keine Anlageberatung">
          Scoring-Ergebnisse, Signale und Analysen sind <G term="Technischer Indikator">technische Indikatoren</G> auf Basis
          öffentlich verfügbarer Marktdaten. Sie stellen keine Aufforderung zum Kauf oder
          Verkauf von Wertpapieren dar. Der Nutzer ist allein für seine Anlageentscheidungen verantwortlich.
        </Card>
        <Card title="Keine Gewähr auf Datengenauigkeit">
          Kurse und Finanzdaten stammen von Drittanbietern (Yahoo Finance, CoinGecko, FRED)
          und können verzögert, unvollständig oder fehlerhaft sein. Für die Richtigkeit und
          Aktualität wird keine Gewähr übernommen.
        </Card>
        <Card title="Performance-Berechnungen">
          Performance-Berechnungen (<G term="XIRR">XIRR</G>, <G term="Modified Dietz">Modified Dietz</G>) sind mathematische Annäherungen
          und können von tatsächlichen Werten abweichen.
        </Card>
        <Card title="Keine steuerliche Grundlage">
          Berechnungen zu realisierten Gewinnen, Dividenden und Performance sind nicht für
          steuerliche Zwecke geeignet. Für steuerliche Fragen konsultiere bitte einen qualifizierten Steuerberater.
        </Card>
        <Card title="Alerts und Benachrichtigungen">
          Alerts werden nach bestem Bemühen ausgelöst. Eine Garantie auf vollständige und rechtzeitige Zustellung besteht nicht.
        </Card>
        <Card title="Vergangene Wertentwicklungen">
          Vergangene Wertentwicklungen sind kein verlässlicher Indikator für zukünftige Ergebnisse.
        </Card>
        <Card title="Haftungsausschluss">
          Der Betreiber haftet nicht für finanzielle Verluste, die durch die Nutzung von OpenFolio entstehen. Die Nutzung erfolgt auf eigenes Risiko.
        </Card>
      </section>

      {/* ── Datenschutz ── */}
      <section id="datenschutz" className="scroll-mt-6 space-y-4">
        <h2 className="text-lg font-semibold text-text-primary border-b border-border pb-2">Datenschutz</h2>
        <p className="text-sm text-text-secondary">OpenFolio ist Free and Open Source Software (MIT-Lizenz). Du hast zwei Möglichkeiten, OpenFolio zu nutzen:</p>

        <Card title="Self-Hosted (Du hostest selbst)">
          <ul className="space-y-1.5">
            <Li><strong className="text-text-primary">Volle Kontrolle</strong>: Deine Daten liegen ausschliesslich auf deiner eigenen Infrastruktur.</Li>
            <Li><strong className="text-text-primary">Kein Dritter hat Zugang</strong>: Niemand ausser dir hat Zugriff auf die Datenbank oder die Verschlüsselungsschlüssel.</Li>
            <Li><strong className="text-text-primary">Keine Telemetrie</strong>: OpenFolio sendet keine Nutzungsdaten, Statistiken oder Diagnose-Informationen an uns oder Dritte.</Li>
            <Li><strong className="text-text-primary">Externer Datenverkehr</strong>: Die einzigen ausgehenden Verbindungen sind Kursabfragen an Yahoo Finance, CoinGecko, FRED und FMP. Diese enthalten ausschliesslich <G term="Ticker">Ticker</G>-Symbole — keine persönlichen Daten.</Li>
          </ul>
          <p className="text-xs text-text-muted mt-3">Du bist für Backups, Updates und Sicherheit selbst verantwortlich.</p>
        </Card>

        <Card title="Managed Hosting (Wir hosten für dich)">
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
        </Card>

        <Card title="Welche Daten werden gespeichert?">
          <h4 className="text-sm font-semibold text-text-primary mb-2">Kontodaten</h4>
          <DataTable
            headers={['Daten', 'Speicherung', 'Zugriff']}
            rows={[
              ['E-Mail-Adresse', 'Klartext', 'Login, Benachrichtigungen'],
              ['Passwort', 'Einweg-Hash (bcrypt)', 'Niemand kann es lesen'],
              ['MFA-Secret', 'Verschlüsselt (AES-256)', 'Nur zur TOTP-Validierung'],
            ]}
          />
          <h4 className="text-sm font-semibold text-text-primary mt-4 mb-2">Finanzdaten</h4>
          <DataTable
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
        </Card>

        <Card title="Externe API-Verbindungen">
          <DataTable
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
        </Card>

        <Card title="Deine Rechte">
          <ul className="space-y-1.5">
            <Li><strong className="text-text-primary">Einsicht</strong>: Jederzeit voller Zugriff auf alle deine Daten über die App.</Li>
            <Li><strong className="text-text-primary">Export</strong>: Transaktionen und Positionen exportierbar.</Li>
            <Li><strong className="text-text-primary">Löschung</strong>: Konto jederzeit löschbar — alle Daten werden unwiderruflich entfernt.</Li>
            <Li><strong className="text-text-primary">Portabilität</strong>: Jederzeit vom Managed Hosting zu Self-Hosted wechselbar.</Li>
          </ul>
        </Card>

        <Card title="Aufbewahrung und Löschung">
          <ul className="space-y-1.5">
            <Li><strong className="text-text-primary">Aufbewahrungsdauer</strong>: Daten werden gespeichert, solange dein Konto aktiv ist.</Li>
            <Li><strong className="text-text-primary">Kontolöschung</strong>: Bei Kontolöschung werden alle Daten unwiderruflich entfernt (CASCADE DELETE).</Li>
            <Li><strong className="text-text-primary">Rechtsgrundlage</strong>: Die Verarbeitung erfolgt auf Grundlage der Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO / Art. 31 DSG).</Li>
          </ul>
        </Card>

        <Card title="Managed Hosting: Auftragsverarbeitung">
          <p>Beim Managed Hosting werden die Daten auf Servern in der Schweiz gespeichert. Der Hosting-Anbieter wird im <a href="#impressum" className="text-primary hover:underline">Impressum</a> benannt.</p>
        </Card>

        <Card title="Open Source">
          <p>OpenFolio ist und bleibt Free and Open Source Software unter der MIT-Lizenz.</p>
          <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer"
             className="text-primary hover:underline text-sm mt-2 inline-block">github.com/dmxch/openfolio</a>
          <p className="mt-2">Die Software ist kostenlos. Der Managed-Hosting-Service ist ein optionaler Komfort-Service.</p>
        </Card>
      </section>

      {/* ── Nutzungsbedingungen (Kurzversion mit Link) ── */}
      <section id="nutzungsbedingungen" className="scroll-mt-6 space-y-4">
        <h2 className="text-lg font-semibold text-text-primary border-b border-border pb-2">Nutzungsbedingungen</h2>
        <Card title="Allgemeine Geschäftsbedingungen (AGB)">
          <p>Die vollständigen Nutzungsbedingungen umfassen 15 Abschnitte und regeln unter anderem:</p>
          <ul className="list-disc list-inside mt-2 space-y-1">
            <li>Leistungsumfang und Beschreibung des Dienstes</li>
            <li>Keine Anlageberatung (§ 3)</li>
            <li>Datengenauigkeit und Haftungsausschluss (§ 4-5)</li>
            <li>Pflichten des Nutzers (§ 6)</li>
            <li>Konto, Verfügbarkeit, Datenschutz (§ 7-9)</li>
            <li>Drittanbieter, Open Source, Preise (§ 10-12)</li>
            <li>Kündigung und Schlussbestimmungen (§ 13-15)</li>
          </ul>
          <a href="/nutzungsbedingungen" className="inline-block mt-3 text-primary hover:underline text-sm font-medium">
            Vollständige AGB lesen →
          </a>
        </Card>
      </section>

      {/* ── Impressum ── */}
      <section id="impressum" className="scroll-mt-6 space-y-4">
        <h2 className="text-lg font-semibold text-text-primary border-b border-border pb-2">Impressum</h2>
        <p className="text-xs text-text-muted">Angaben gemäss Art. 3 UWG (Schweiz) und § 5 TMG (Deutschland)</p>

        <Card title="Betreiber">
          <p>[Vorname Nachname]</p>
          <p>[Strasse und Hausnummer]</p>
          <p>[PLZ Ort]</p>
          <p>Schweiz</p>
          <p className="mt-2">E-Mail: [deine@email.ch]</p>
        </Card>
        <Card title="Verantwortlich für den Inhalt">
          <p>[Vorname Nachname]</p>
        </Card>
        <Card title="Hosting">
          <p>[z.B. «Eigene Server in der Schweiz» oder «Hetzner Cloud, Standort Zürich»]</p>
        </Card>
        <Card title="Open Source">
          <p>OpenFolio ist Free and Open Source Software unter der MIT-Lizenz.</p>
          <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline text-sm mt-1 inline-block">github.com/dmxch/openfolio</a>
        </Card>
        <Card title="Streitbeilegung">
          <p>Der Betreiber ist nicht bereit und nicht verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>
        </Card>
        <p className="text-xs text-text-muted">Stand: März 2026</p>
      </section>
    </div>
  )
}

function Card({ title, children }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-2">{title}</h3>
      <div className="text-sm text-text-secondary leading-relaxed">{children}</div>
    </div>
  )
}

function Li({ children }) {
  return <li className="flex gap-2 text-sm text-text-secondary"><span className="text-text-muted shrink-0">•</span><span>{children}</span></li>
}

function DataTable({ headers, rows }) {
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
