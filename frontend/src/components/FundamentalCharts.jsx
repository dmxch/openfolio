import { ExternalLink } from 'lucide-react'
import { useApi } from '../hooks/useApi'

function isUsTicker(ticker) {
  return !ticker.includes('.')
}

function getBaseTicker(ticker) {
  const dot = ticker.indexOf('.')
  return dot > 0 ? ticker.substring(0, dot) : ticker
}

export default function FundamentalCharts({ ticker }) {
  const { data: profile } = useApi(`/stock/${ticker}/profile`)
  const { data: summary } = useApi('/portfolio/summary')

  const position = summary?.positions?.find((p) => p.ticker === ticker)
  const isEtf = profile?.quoteType === 'ETF' || position?.type === 'etf'

  const useTicker = isUsTicker(ticker)
  const baseTicker = getBaseTicker(ticker).toLowerCase()

  if (isEtf) {
    return (
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-text-primary">ETF Holdings & Zusammensetzung</h3>
          </div>

          <p className="text-sm text-text-muted mb-4">
            Siehe die vollständige Zusammensetzung dieses ETFs.
          </p>

          <a
            href={`https://finance.yahoo.com/quote/${ticker}/holdings/`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-primary/10 text-primary hover:bg-primary/20 rounded-lg transition-colors"
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

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-text-primary">Fundamentaldaten</h3>
        </div>

        <p className="text-sm text-text-muted mb-4">
          Für zuverlässige Fundamentalkennzahlen empfehlen wir {sourceName}.
        </p>

        <a
          href={mainUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-primary/10 text-primary hover:bg-primary/20 rounded-lg transition-colors"
        >
          Fundamentaldaten auf {sourceName}
          <ExternalLink size={14} />
        </a>
      </div>
    </div>
  )
}
