import { useApi } from '../hooks/useApi'
import { ExternalLink, Check, X, Minus } from 'lucide-react'
import G from './GlossarTooltip'

function formatLargeNumber(val) {
  if (val == null) return '–'
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(1)}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(0)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}K`
  return `${sign}$${abs.toFixed(0)}`
}

function formatPct(val) {
  if (val == null) return '–'
  const pct = val * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
}

function formatPctRaw(val) {
  if (val == null) return '–'
  return `${val.toFixed(1)}%`
}

function StatusIcon({ passed }) {
  if (passed === true) return <Check size={12} className="text-success" />
  if (passed === false) return <X size={12} className="text-danger" />
  return <Minus size={12} className="text-text-muted" />
}

function MetricCard({ label, value, sub, passed, passLabel, peerAvg, peerBetter }) {
  return (
    <div className="bg-card-alt/50 rounded-lg p-3">
      <div className="text-[11px] text-text-muted mb-1">{label}</div>
      <div className="text-lg font-mono font-bold text-text-primary">{value}</div>
      {sub && (
        <div className={`text-[11px] font-mono mt-0.5 ${sub.color || 'text-text-muted'}`}>
          {sub.text}
        </div>
      )}
      {peerAvg != null && (
        <div className="text-[10px] text-text-muted mt-1">Branche Ø: {peerAvg}</div>
      )}
      {passLabel && (
        <div className="flex items-center gap-1 mt-1">
          <StatusIcon passed={peerBetter != null ? peerBetter : passed} />
          <span className="text-[10px] text-text-muted">{passLabel}</span>
        </div>
      )}
    </div>
  )
}

function isUsTicker(ticker) {
  return !ticker.includes('.')
}

function getBaseTicker(ticker) {
  const dot = ticker.indexOf('.')
  return dot > 0 ? ticker.substring(0, dot) : ticker
}

const STOCKANALYSIS_LINKS = [
  { label: 'Revenue', path: '/revenue/' },
  { label: 'Financials', path: '/financials/' },
  { label: 'Balance Sheet', path: '/financials/balance-sheet/' },
  { label: 'Dividends', path: '/dividend/' },
]

const YAHOO_LINKS = [
  { label: 'Financials', path: '/financials/' },
  { label: 'Balance Sheet', path: '/balance-sheet/' },
]

export default function FundamentalCharts({ ticker }) {
  // key-metrics from yfinance (with industry averages)
  const { data: metrics, loading: metricsLoading } = useApi(`/stock/${ticker}/key-metrics`)
  // score endpoint (always loaded on this page, has criteria checks)
  const { data: scoreData } = useApi(`/analysis/score/${ticker}`)

  if (metricsLoading) return null

  // Use metrics if available, otherwise fall back to scoreData for basic fields
  const m = metrics && !metrics.error ? metrics : null
  const name = m?.name || scoreData?.name
  const industry = m?.industry || scoreData?.industry
  const avg = m?.industry_avg || null

  const de = m?.debt_to_equity
  const gm = m?.gross_margins
  const nm = m?.profit_margins
  const marketCap = m?.market_cap || scoreData?.market_cap
  const pe = m?.trailing_pe
  const fcf = m?.free_cashflow
  const divYield = m?.dividend_yield
  const revenue = m?.revenue
  const revenueGrowth = m?.revenue_growth
  const eps = m?.trailing_eps
  const epsGrowth = m?.earnings_growth
  const roic = m?.roic
  const roicIsRoe = m?.roic_is_roe
  const forwardPe = m?.forward_pe
  const metricCurrency = m?.currency || 'USD'
  const ccySymbol = metricCurrency === 'USD' ? '$' : metricCurrency + ' '

  // Score criteria for check icons
  const criteria = scoreData?.criteria || []
  const getCriteria = (id) => criteria.find(c => c.id === id)

  if (!m && !scoreData) {
    return (
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-2">Fundamentaldaten</h3>
          <p className="text-sm text-text-muted">Fundamentaldaten für {ticker} nicht verfügbar.</p>
        </div>
      </div>
    )
  }

  const useTicker = isUsTicker(ticker)
  const baseTicker = getBaseTicker(ticker).toLowerCase()

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-text-primary">Fundamentaldaten</h3>
            {industry && <span className="text-[10px] text-text-muted">{industry}</span>}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard
              label={<G term="Revenue">Revenue</G>}
              value={formatLargeNumber(revenue)}
              sub={revenueGrowth != null ? {
                text: `YoY: ${formatPct(revenueGrowth)}`,
                color: revenueGrowth >= 0 ? 'text-success' : 'text-danger',
              } : null}
              passed={getCriteria(15)?.passed}
              passLabel="Umsatz wächst"
            />
            <MetricCard
              label={<G term="Gross Margin">Gross Margin</G>}
              value={gm != null ? formatPctRaw(gm * 100) : '–'}
              peerAvg={avg?.gross_margin != null ? formatPctRaw(avg.gross_margin * 100) : null}
              peerBetter={gm != null && avg?.gross_margin != null ? gm >= avg.gross_margin : null}
              passLabel={gm != null && avg?.gross_margin != null ? (gm >= avg.gross_margin ? 'über Branche Ø' : 'unter Branche Ø') : 'Marge stabil'}
              passed={getCriteria(16)?.passed}
            />
            <MetricCard
              label={<G term="D/E">Debt/Equity</G>}
              value={de != null ? de.toFixed(2) : '–'}
              peerAvg={avg?.de_ratio != null ? avg.de_ratio.toFixed(2) : null}
              peerBetter={de != null && avg?.de_ratio != null ? de <= avg.de_ratio * 1.2 : null}
              passLabel={de != null && avg?.de_ratio != null ? (de <= avg.de_ratio ? 'unter Branche Ø' : 'über Branche Ø') : 'D/E < 1.0'}
              passed={getCriteria(17)?.passed}
            />
            <MetricCard
              label={<G term="Dividende">Dividende</G>}
              value={divYield != null ? formatPctRaw(divYield * 100) : '–'}
              sub={divYield != null ? { text: 'Yield', color: 'text-text-muted' } : null}
            />
            <MetricCard
              label={<G term="Net Margin">Net Margin</G>}
              value={nm != null ? formatPctRaw(nm * 100) : '–'}
              peerAvg={avg?.net_margin != null ? formatPctRaw(avg.net_margin * 100) : null}
              peerBetter={nm != null && avg?.net_margin != null ? nm >= avg.net_margin : null}
              passLabel={nm != null && avg?.net_margin != null ? (nm >= avg.net_margin ? 'über Branche Ø' : 'unter Branche Ø') : null}
            />
            <MetricCard
              label={<G term="FCF">Free Cash Flow</G>}
              value={formatLargeNumber(fcf)}
              passed={fcf != null ? fcf > 0 : null}
              passLabel="FCF positiv"
            />
            <MetricCard
              label={<G term="PE Ratio">PE Ratio</G>}
              value={pe != null ? pe.toFixed(1) : '–'}
              peerAvg={avg?.pe != null ? avg.pe.toFixed(0) : null}
              peerBetter={pe != null && avg?.pe != null ? pe <= avg.pe : null}
              passLabel={pe != null && avg?.pe != null ? (pe <= avg.pe ? 'unter Branche Ø' : 'über Branche Ø') : null}
              sub={forwardPe != null ? { text: `Forward: ${forwardPe.toFixed(1)}`, color: 'text-text-muted' } : null}
            />
            <MetricCard
              label={<G term="Market Cap">Market Cap</G>}
              value={formatLargeNumber(marketCap)}
            />
            <MetricCard
              label={roicIsRoe ? <G term="ROE">ROE</G> : <G term="ROIC">ROIC</G>}
              value={roic != null ? formatPctRaw(roic * 100) : '–'}
              passed={roic != null ? roic >= 0.12 : null}
              passLabel={roic != null ? (roic >= 0.12 ? '> 12%' : roic >= 0.08 ? '8–12%' : '< 8%') : null}
            />
            <MetricCard
              label={<G term="EPS">EPS (TTM)</G>}
              value={eps != null ? `${ccySymbol}${eps.toFixed(2)}` : '–'}
              passed={eps != null ? eps > 0 : null}
              passLabel={eps != null ? (eps > 0 ? 'Gewinn' : 'Verlust') : null}
            />
            <MetricCard
              label={<G term="EPS Growth">EPS Growth</G>}
              value={epsGrowth != null ? formatPct(epsGrowth) : '–'}
              passed={epsGrowth != null ? epsGrowth > 0 : null}
              passLabel={epsGrowth != null ? (epsGrowth > 0 ? 'wachsend' : epsGrowth >= -0.1 ? 'leicht rückläufig' : 'rückläufig') : null}
            />
          </div>
        </div>
      </div>

      {/* External links: Stockanalysis (US) or Yahoo Finance (non-US) */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="p-4">
          <div className="flex items-center gap-2 mb-3">
            <ExternalLink size={14} className="text-text-muted" />
            <span className="text-xs font-medium text-text-secondary">
              {useTicker ? 'Detail-Charts auf Stockanalysis' : 'Detail-Charts auf Yahoo Finance'}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {useTicker ? (
              <>
                {STOCKANALYSIS_LINKS.map(link => (
                  <a
                    key={link.path}
                    href={`https://stockanalysis.com/stocks/${baseTicker}${link.path}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 text-xs bg-card-alt text-text-secondary hover:text-text-primary rounded-md transition-colors"
                  >
                    {link.label}
                  </a>
                ))}
                <a
                  href={`https://stockanalysis.com/stocks/${baseTicker}/financials/ratios/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-3 py-1.5 text-xs bg-card-alt text-primary hover:text-primary/80 rounded-md transition-colors flex items-center gap-1"
                >
                  Alle Kennzahlen
                  <ExternalLink size={10} />
                </a>
              </>
            ) : (
              <>
                {YAHOO_LINKS.map(link => (
                  <a
                    key={link.path}
                    href={`https://finance.yahoo.com/quote/${ticker}${link.path}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 text-xs bg-card-alt text-text-secondary hover:text-text-primary rounded-md transition-colors"
                  >
                    {link.label}
                  </a>
                ))}
                <a
                  href={`https://finance.yahoo.com/quote/${ticker}/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-3 py-1.5 text-xs bg-card-alt text-primary hover:text-primary/80 rounded-md transition-colors flex items-center gap-1"
                >
                  Übersicht
                  <ExternalLink size={10} />
                </a>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
