import { Link } from 'react-router-dom'
import G from '../components/GlossarTooltip'

export default function Disclaimer() {
  return (
    <div className="min-h-screen bg-body">
      <div className="max-w-3xl mx-auto px-4 py-12 space-y-6">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Rechtlicher Hinweis</h1>
          <p className="text-sm text-text-secondary mt-2">
            OpenFolio ist ein Software-Tool zur Verwaltung und Analyse von Wertpapierportfolios.
            OpenFolio ist <strong className="text-text-primary">kein Anlageberater</strong> und gibt <strong className="text-text-primary">keine Anlageempfehlungen</strong>.
          </p>
        </div>

        <Section title="Keine Anlageberatung">
          <p>
            Scoring-Ergebnisse, Signale und Analysen sind <G term="Technischer Indikator">technische Indikatoren</G> auf Basis
            öffentlich verfügbarer Marktdaten. Sie stellen keine Aufforderung zum Kauf oder
            Verkauf von Wertpapieren dar. Der Nutzer ist allein für seine Anlageentscheidungen
            verantwortlich.
          </p>
        </Section>

        <Section title="Keine Gewähr auf Datengenauigkeit">
          <p>
            Kurse und Finanzdaten stammen von Drittanbietern (Yahoo Finance, CoinGecko, FRED)
            und können verzögert, unvollständig oder fehlerhaft sein. Für die Richtigkeit und
            Aktualität wird keine Gewähr übernommen.
          </p>
        </Section>

        <Section title="Performance-Berechnungen">
          <p>
            Performance-Berechnungen (<G term="XIRR">XIRR</G>, <G term="Modified Dietz">Modified Dietz</G>) sind mathematische Annäherungen
            und können von tatsächlichen Werten abweichen.
          </p>
        </Section>

        <Section title="Keine steuerliche Grundlage">
          <p>
            Berechnungen zu realisierten Gewinnen, Dividenden und Performance sind nicht für
            steuerliche Zwecke geeignet. Für steuerliche Fragen konsultiere bitte einen
            qualifizierten Steuerberater.
          </p>
        </Section>

        <Section title="Alerts und Benachrichtigungen">
          <p>
            Alerts werden nach bestem Bemühen ausgelöst. Eine Garantie auf vollständige und
            rechtzeitige Zustellung besteht nicht.
          </p>
        </Section>

        <Section title="Vergangene Wertentwicklungen">
          <p>
            Vergangene Wertentwicklungen sind kein verlässlicher Indikator für zukünftige
            Ergebnisse.
          </p>
        </Section>

        <Section title="Haftungsausschluss">
          <p>
            Der Betreiber haftet nicht für finanzielle Verluste, die durch die Nutzung von
            OpenFolio entstehen. Die Nutzung erfolgt auf eigenes Risiko.
          </p>
        </Section>

        <div className="text-xs text-text-secondary pt-4 border-t border-border space-x-4">
          <Link to="/datenschutz" className="hover:text-text-secondary transition-colors">Datenschutz</Link>
          <Link to="/nutzungsbedingungen" className="hover:text-text-secondary transition-colors">Nutzungsbedingungen</Link>
          <Link to="/impressum" className="hover:text-text-secondary transition-colors">Impressum</Link>
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
