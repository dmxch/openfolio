import { Link } from 'react-router-dom'

export default function Imprint() {
  return (
    <div className="min-h-screen bg-body">
      <div className="max-w-3xl mx-auto px-4 py-12 space-y-6">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Impressum</h1>
          <p className="text-xs text-text-secondary mt-1">Angaben gemäss Art. 3 UWG (Schweiz) und § 5 TMG (Deutschland)</p>
        </div>

        <Section title="Betreiber">
          <p>Harry Fohmann</p>
          <p>Buchholzstrasse 8</p>
          <p>9464 Rüthi SG</p>
          <p>Schweiz</p>
        </Section>

        <Section title="Kontakt">
          <p>E-Mail: openfolio@proton.me</p>
        </Section>

        <Section title="Verantwortlich für den Inhalt">
          <p>Harry Fohmann</p>
        </Section>

        <Section title="Hosting">
          <p>Die Managed-Hosting-Infrastruktur wird auf eigenen Servern in der Schweiz betrieben.</p>
        </Section>

        <Section title="Open Source">
          <p>OpenFolio ist Free and Open Source Software unter der MIT-Lizenz.</p>
          <p className="mt-1">
            Quellcode:{' '}
            <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              github.com/dmxch/openfolio
            </a>
          </p>
        </Section>

        <Section title="Haftungsausschluss">
          <p>
            Die vollständigen Haftungsausschlüsse und rechtlichen Hinweise sind unter{' '}
            <Link to="/disclaimer" className="text-primary hover:underline">Disclaimer</Link> und{' '}
            <Link to="/nutzungsbedingungen" className="text-primary hover:underline">Nutzungsbedingungen</Link> einsehbar.
          </p>
        </Section>

        <Section title="Urheberrecht">
          <p>Die Inhalte dieser Software sind — soweit nicht anders gekennzeichnet — unter der MIT-Lizenz veröffentlicht. Drittanbieter-Daten (Kurse, Marktdaten) unterliegen den jeweiligen Lizenzbedingungen der Anbieter (Yahoo Finance, CoinGecko, FRED, TradingView).</p>
        </Section>

        <Section title="Streitbeilegung">
          <p>Der Betreiber ist nicht bereit und nicht verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>
        </Section>

        <p className="text-xs text-text-secondary">Stand: März 2026</p>

        <div className="text-xs text-text-secondary pt-4 border-t border-border space-x-4">
          <Link to="/datenschutz" className="hover:text-text-secondary transition-colors">Datenschutz</Link>
          <Link to="/disclaimer" className="hover:text-text-secondary transition-colors">Disclaimer</Link>
          <Link to="/nutzungsbedingungen" className="hover:text-text-secondary transition-colors">Nutzungsbedingungen</Link>
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-2">{title}</h3>
      <div className="text-sm text-text-secondary leading-relaxed">{children}</div>
    </div>
  )
}
