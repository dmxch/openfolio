import { Link } from 'react-router'

export default function Imprint() {
  return (
    <div className="min-h-screen bg-body">
      <div className="max-w-[760px] mx-auto px-4 py-14 space-y-6">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-text-primary">Impressum</h1>
        </div>

        <Section title="Betreiber dieser Instanz">
          <p>Diese Instanz von OpenFolio wird von ihrem Betreiber betrieben. Der Betreiber hinterlegt sein Impressum über die Einstellung LEGAL_IMPRINT_URL.</p>
        </Section>

        <Section title="Open Source">
          <p>OpenFolio ist Free and Open Source Software unter der MIT-Lizenz.</p>
          <p className="mt-1">
            Quellcode:{' '}
            <a href="https://github.com/dmxch/openfolio" target="_blank" rel="noopener noreferrer" className="text-link hover:underline">
              github.com/dmxch/openfolio
            </a>
          </p>
        </Section>

        <Section title="Haftungsausschluss">
          <p>
            Die rechtlichen Hinweise zur Software sind unter{' '}
            <Link to="/disclaimer" className="text-link hover:underline">Disclaimer</Link> einsehbar.
          </p>
        </Section>

        <Section title="Urheberrecht">
          <p>Die Inhalte dieser Software sind — soweit nicht anders gekennzeichnet — unter der MIT-Lizenz veröffentlicht. Drittanbieter-Daten (Kurse, Marktdaten) unterliegen den jeweiligen Lizenzbedingungen der Anbieter (Yahoo Finance, CoinGecko, FRED, TradingView).</p>
        </Section>

        <div className="text-xs pt-4 border-t border-border-2 space-x-4">
          <Link to="/datenschutz" className="text-text-muted hover:text-text-primary transition-colors inline-block max-md:py-3 max-md:-my-3">Datenschutz</Link>
          <Link to="/disclaimer" className="text-text-muted hover:text-text-primary transition-colors inline-block max-md:py-3 max-md:-my-3">Disclaimer</Link>
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="rounded-card border border-border bg-card p-[18px]">
      <h3 className="text-sm font-semibold text-text-primary mb-2">{title}</h3>
      <div className="text-sm text-text-secondary leading-relaxed">{children}</div>
    </div>
  )
}
