import { useEffect } from 'react'
import { useLocation } from 'react-router'
import G from '../components/GlossarTooltip'
import PageHeader from '../components/ui/PageHeader'
import { useLegalLinks } from '../lib/legalLinks'

const GITHUB_URL = 'https://github.com/dmxch/openfolio'

export default function Legal() {
  const { hash } = useLocation()
  const links = useLegalLinks()

  useEffect(() => {
    if (hash) {
      const el = document.getElementById(hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else {
      window.scrollTo(0, 0)
    }
  }, [hash])

  return (
    <div className="pb-10">
      <PageHeader title="Rechtliches" subtitle="Hinweise, Datenschutz, Nutzungsbedingungen, Impressum" showBell={false} />
      <div className="max-w-[760px] flex flex-col gap-10">
        {/* Quick nav */}
        <div className="flex flex-wrap gap-2 text-xs">
          <a href="#disclaimer" className="px-3 py-1.5 rounded-lg bg-surface border border-border text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors">Rechtlicher Hinweis</a>
          <a href="#datenschutz" className="px-3 py-1.5 rounded-lg bg-surface border border-border text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors">Datenschutz</a>
          <a href="#nutzungsbedingungen" className="px-3 py-1.5 rounded-lg bg-surface border border-border text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors">Nutzungsbedingungen</a>
          <a href="#impressum" className="px-3 py-1.5 rounded-lg bg-surface border border-border text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors">Impressum</a>
        </div>

      {/* ── Disclaimer ── */}
      <section id="disclaimer" className="scroll-mt-6 space-y-4">
        <h2 className="text-base font-semibold text-text-primary border-b border-border-2 pb-2">Rechtlicher Hinweis</h2>
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
        <h2 className="text-base font-semibold text-text-primary border-b border-border-2 pb-2">Datenschutz</h2>
        {links.privacy ? (
          <Card title="Datenschutzerklärung des Betreibers">
            <p>Für diese Instanz gilt die Datenschutzerklärung ihres Betreibers.</p>
            <ExternalLink href={links.privacy}>Datenschutzerklärung lesen →</ExternalLink>
          </Card>
        ) : (
        <>
        <p className="text-sm text-text-secondary">Dieser Abschnitt beschreibt, wie die Software OpenFolio (Free and Open Source, MIT-Lizenz) Daten speichert und verarbeitet. Verantwortlich für diese Instanz ist ihr Betreiber.</p>

        <Card title="Betrieb und Verantwortung">
          <ul className="space-y-1.5">
            <Li><strong className="text-text-primary">Datenhaltung</strong>: Deine Daten liegen in der Datenbank der Instanz, auf der du dich angemeldet hast.</Li>
            <Li><strong className="text-text-primary">Zugriff</strong>: Wer Zugriff auf Datenbank und Verschlüsselungsschlüssel hat, bestimmt der Betreiber der Instanz.</Li>
            <Li><strong className="text-text-primary">Keine Telemetrie</strong>: Die Software sendet keine Nutzungsdaten, Statistiken oder Diagnose-Informationen an die Entwickler oder an Dritte.</Li>
            <Li><strong className="text-text-primary">Externer Datenverkehr</strong>: Die einzigen ausgehenden Verbindungen sind Kursabfragen an Yahoo Finance, CoinGecko, FRED und FMP. Diese enthalten ausschliesslich <G term="Ticker">Ticker</G>-Symbole — keine persönlichen Daten.</Li>
          </ul>
          <p className="text-xs text-text-secondary mt-3">Backups, Updates und Sicherheit der Instanz liegen beim Betreiber.</p>
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
          <p className="text-text-secondary text-xs mt-2">Keine dieser APIs erhält persönliche Daten, Kontostände oder Portfolio-Informationen. Die server-seitigen Abfragen (Yahoo Finance, CoinGecko, FRED, FMP, SNB, Gold.org, multpl.com) enthalten ausschliesslich Ticker-Symbole oder Indikator-IDs.</p>
          <p className="text-text-secondary text-xs mt-2"><strong className="text-text-secondary">Hinweis zu TradingView:</strong> Das TradingView-Chart-Widget wird direkt im Browser geladen. Dabei wird Ihre IP-Adresse an TradingView Inc. (USA) übermittelt. TradingView kann eigene Cookies setzen. Weitere Informationen finden Sie in der <a href="https://www.tradingview.com/privacy-policy/" target="_blank" rel="noopener noreferrer" className="text-link hover:underline">Datenschutzerklärung von TradingView</a>. Die Einbindung erfolgt auf Grundlage unseres berechtigten Interesses an einer ansprechenden Darstellung von Kursdaten (Art. 6 Abs. 1 lit. f DSGVO).</p>
          <p className="text-text-secondary text-xs mt-2"><strong className="text-text-secondary">Hinweis zu Yahoo Finance:</strong> Die Kursdaten werden über die Open-Source-Bibliothek yfinance bezogen. Die Verfügbarkeit und Genauigkeit der Daten kann nicht garantiert werden.</p>
        </Card>

        <Card title="Deine Rechte">
          <ul className="space-y-1.5">
            <Li><strong className="text-text-primary">Einsicht</strong>: Jederzeit voller Zugriff auf alle deine Daten über die App.</Li>
            <Li><strong className="text-text-primary">Export</strong>: Transaktionen und Positionen exportierbar.</Li>
            <Li><strong className="text-text-primary">Löschung</strong>: Konto jederzeit löschbar — alle Daten werden unwiderruflich entfernt.</Li>
            <Li><strong className="text-text-primary">Portabilität</strong>: Du kannst deine Daten exportieren und auf eine andere Instanz umziehen.</Li>
          </ul>
        </Card>

        <Card title="Aufbewahrung und Löschung">
          <ul className="space-y-1.5">
            <Li><strong className="text-text-primary">Aufbewahrungsdauer</strong>: Daten werden gespeichert, solange dein Konto aktiv ist.</Li>
            <Li><strong className="text-text-primary">Kontolöschung</strong>: Bei Kontolöschung werden alle Daten unwiderruflich entfernt (CASCADE DELETE).</Li>
          </ul>
        </Card>

        <Card title="Rechtsgrundlagen">
          <ul className="space-y-1.5">
            <Li><strong className="text-text-primary">Login, Portfolio-Daten, Transaktionen</strong>: Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO / Art. 31 DSG).</Li>
            <Li><strong className="text-text-primary">Kursdaten-Abruf</strong> (Yahoo Finance, CoinGecko, FRED, FMP, Gold.org, SNB, multpl.com): Vertragserfüllung — nötig für die Kernfunktionalität (Art. 6 Abs. 1 lit. b DSGVO).</Li>
            <Li><strong className="text-text-primary">TradingView-Widget</strong>: Berechtigtes Interesse an ansprechender Chart-Darstellung (Art. 6 Abs. 1 lit. f DSGVO).</Li>
            <Li><strong className="text-text-primary">E-Mail-Benachrichtigungen</strong>: Einwilligung — der Nutzer aktiviert Alerts explizit (Art. 6 Abs. 1 lit. a DSGVO).</Li>
            <Li><strong className="text-text-primary">Sicherheitslogs</strong> (Rate Limiting, Audit Log): Berechtigtes Interesse an der Sicherheit des Dienstes (Art. 6 Abs. 1 lit. f DSGVO).</Li>
          </ul>
        </Card>

        <Card title="Kontakt für Datenschutzanfragen">
          <p>Für Datenschutzanfragen (Auskunft, Berichtigung, Löschung) wende dich an den Betreiber dieser Instanz.</p>
        </Card>

        <Card title="Open Source">
          <p>OpenFolio ist und bleibt Free and Open Source Software unter der MIT-Lizenz.</p>
          <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer"
             className="text-link hover:underline text-sm mt-2 inline-block">github.com/dmxch/openfolio</a>
        </Card>
        </>
        )}
      </section>

      {/* ── Nutzungsbedingungen ── */}
      <section id="nutzungsbedingungen" className="scroll-mt-6 space-y-4">
        <h2 className="text-base font-semibold text-text-primary border-b border-border-2 pb-2">Nutzungsbedingungen</h2>
        {links.terms ? (
          <Card title="AGB des Betreibers">
            <p>Für diese Instanz gelten die Allgemeinen Geschäftsbedingungen ihres Betreibers.</p>
            <ExternalLink href={links.terms}>AGB lesen →</ExternalLink>
          </Card>
        ) : (
          <Card title="Keine Nutzungsbedingungen hinterlegt">
            <p>Der Betreiber dieser Instanz hat keine Nutzungsbedingungen hinterlegt. Für die Software OpenFolio gilt die MIT-Lizenz.</p>
            <ExternalLink href={GITHUB_URL}>github.com/dmxch/openfolio</ExternalLink>
          </Card>
        )}
      </section>

      {/* ── Impressum ── */}
      <section id="impressum" className="scroll-mt-6 space-y-4">
        <h2 className="text-base font-semibold text-text-primary border-b border-border-2 pb-2">Impressum</h2>
        {links.imprint ? (
          <Card title="Impressum des Betreibers">
            <p>Die Angaben zum Betreiber dieser Instanz stehen im Impressum des Betreibers.</p>
            <ExternalLink href={links.imprint}>Impressum lesen →</ExternalLink>
          </Card>
        ) : (
          <>
            <Card title="Betreiber dieser Instanz">
              <p>Diese Instanz von OpenFolio wird von ihrem Betreiber betrieben. Der Betreiber hinterlegt sein Impressum über die Einstellung LEGAL_IMPRINT_URL.</p>
            </Card>
            <Card title="Open Source">
              <p>OpenFolio ist Free and Open Source Software unter der MIT-Lizenz.</p>
              <ExternalLink href={GITHUB_URL}>github.com/dmxch/openfolio</ExternalLink>
            </Card>
          </>
        )}
      </section>
      </div>
    </div>
  )
}

function Card({ title, children }) {
  return (
    <div className="rounded-card border border-border bg-card p-[18px]">
      <h3 className="text-sm font-semibold text-text-primary mb-2">{title}</h3>
      <div className="text-sm text-text-secondary leading-relaxed">{children}</div>
    </div>
  )
}

function ExternalLink({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-block mt-3 text-link hover:underline text-sm font-medium">
      {children}
    </a>
  )
}

function Li({ children }) {
  return <li className="flex gap-2 text-sm text-text-secondary"><span className="text-text-muted shrink-0">•</span><span>{children}</span></li>
}

function DataTable({ headers, rows }) {
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
