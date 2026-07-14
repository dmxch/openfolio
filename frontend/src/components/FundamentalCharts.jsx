import { ExternalLink, BarChart3 } from 'lucide-react'
import { useApi } from '../hooks/useApi'

function isUsTicker(ticker) {
  return !ticker.includes('.')
}

function getBaseTicker(ticker) {
  const dot = ticker.indexOf('.')
  return dot > 0 ? ticker.substring(0, dot) : ticker
}

function formatMCap(v) {
  if (!v) return '–'
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return `${v}`
}

function MetricTile({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-border-2 bg-card-2 p-[13px]">
      <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-1.5">{label}</div>
      <div className="text-[17px] font-mono font-semibold text-text-primary tabular-nums leading-none">{value}</div>
      {sub && <div className="text-[10.5px] text-text-muted mt-1">{sub}</div>}
    </div>
  )
}

export default function FundamentalCharts({ ticker }) {
  const { data: profile } = useApi(`/stock/${ticker}/profile`)
  const { data: summary } = useApi('/portfolio/summary')

  const position = summary?.positions?.find((p) => p.ticker === ticker)
  // Anleihen laufen im Fonds-Pfad: KGV/Margen/Umsatz gibt es für einen Bond-ETF nicht.
  const isEtf = profile?.quoteType === 'ETF' || position?.type === 'etf' || position?.type === 'bond'

  const useTicker = isUsTicker(ticker)
  const baseTicker = getBaseTicker(ticker).toLowerCase()

  if (isEtf) {
    return (
      <div className="bg-card border border-border rounded-card overflow-hidden">
        <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
          <BarChart3 size={16} className="text-etf" />
          <h3 className="text-sm font-semibold text-text-primary">ETF Holdings & Zusammensetzung</h3>
        </div>
        <div className="p-[18px]">
          <p className="text-[12.5px] text-text-muted mb-4">
            Siehe die vollständige Zusammensetzung dieses ETFs.
          </p>
          <a
            href={`https://finance.yahoo.com/quote/${ticker}/holdings/`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 text-[12.5px] font-medium bg-surface border border-border text-text-secondary hover:border-border-hover rounded-lg transition-colors"
          >
            Holdings auf Yahoo Finance
            <ExternalLink size={14} />
          </a>
        </div>
      </div>
    )
  }

  const mainUrl = useTicker
    ? `https://stockanalysis.com/stocks/${baseTicker}/financials/`
    : `https://finance.yahoo.com/quote/${ticker}/financials/`
  const sourceName = useTicker ? 'StockAnalysis' : 'Yahoo Finance'

  // Verfuegbare Kennzahlen aus dem Profil-Endpoint. PEG / ROE / Debt-Equity
  // liefert das Profil nicht — daher hier nicht dargestellt.
  const metrics = []
  if (profile?.trailingPE != null) metrics.push({ label: 'KGV', value: profile.trailingPE.toFixed(1) })
  if (profile?.forwardPE != null) metrics.push({ label: 'Fwd-KGV', value: profile.forwardPE.toFixed(1) })
  if (profile?.dividendYield != null) metrics.push({ label: 'Div-Rendite', value: `${(profile.dividendYield * 100).toFixed(2)}%` })
  if (profile?.beta != null) metrics.push({ label: 'Beta', value: profile.beta.toFixed(2) })
  if (profile?.marketCap != null) metrics.push({ label: 'Marktkap.', value: formatMCap(profile.marketCap) })

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <BarChart3 size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Fundamentaldaten</h3>
      </div>
      <div className="p-[18px]">
        {metrics.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 mb-4">
            {metrics.map((m) => <MetricTile key={m.label} {...m} />)}
          </div>
        ) : (
          <p className="text-[12.5px] text-text-muted mb-4">
            Keine Kennzahlen verfügbar. Für zuverlässige Fundamentaldaten empfehlen wir {sourceName}.
          </p>
        )}

        <a
          href={mainUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 text-[12.5px] font-medium bg-surface border border-border text-text-secondary hover:border-border-hover rounded-lg transition-colors"
        >
          Fundamentaldaten auf {sourceName}
          <ExternalLink size={14} />
        </a>
      </div>
    </div>
  )
}
