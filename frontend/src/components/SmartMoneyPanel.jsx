import { useState } from 'react'
import { Users, Building2, TrendingDown, AlertTriangle, BarChart3, ChevronDown, ChevronUp, Radar } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import G from './GlossarTooltip'

const SIGNAL_CONFIG = {
  insider_cluster: { label: 'Insider-Cluster', glossar: 'Insider-Cluster', short: 'I', icon: Users, type: 'positive' },
  large_buy: { label: 'Grosser Insider-Kauf', glossar: 'Grosser Insider-Kauf', short: 'I', icon: Users, type: 'positive' },
  superinvestor: { label: 'Superinvestor', glossar: 'Superinvestor', short: 'A', icon: Users, type: 'positive' },
  activist: { label: 'Aktivist (13D/13G)', glossar: 'Aktivist (13D/13G)', short: 'A', icon: Users, type: 'positive' },
  buyback: { label: 'Aktienrückkauf', glossar: 'Aktienrückkauf', short: 'B', icon: Building2, type: 'positive' },
  congressional: { label: 'Kongresskauf', glossar: 'Kongresskauf', short: 'C', icon: Building2, type: 'positive' },
  short_trend: { label: 'Short-Trend', glossar: 'Short-Trend', short: 'S', icon: TrendingDown, type: 'warning' },
  ftd: { label: 'Fails-to-Deliver', glossar: 'Fails-to-Deliver', short: 'F', icon: AlertTriangle, type: 'warning' },
  unusual_volume: { label: 'Unusual Volume', glossar: 'Unusual Volume', short: 'V', icon: BarChart3, type: 'flag' },
}

function SignalRow({ signalKey, data }) {
  const cfg = SIGNAL_CONFIG[signalKey]
  if (!cfg) return null
  const Icon = cfg.icon

  let detail = ''
  if (signalKey === 'insider_cluster') {
    detail = `${data.insider_count || '?'} Insider kaufen gleichzeitig`
    if (data.total_value) detail += ` — $${Number(data.total_value).toLocaleString('en-US')}`
    if (data.trade_date) detail += ` (${data.trade_date})`
  } else if (signalKey === 'large_buy') {
    detail = `Einzelkauf $${Number(data.value || 0).toLocaleString('en-US')}`
    if (data.trade_date) detail += ` (${data.trade_date})`
  } else if (signalKey === 'superinvestor') {
    detail = data.source === 'dataroma_portfolio'
      ? `${data.num_investors} Superinvestoren halten Position`
      : `${data.investor || 'Superinvestor'} kauft`
  } else if (signalKey === 'activist') {
    detail = `${data.investor || 'Aktivist'} — ${data.form || '13D/13G'}`
    if (data.filing_date) detail += ` (${data.filing_date})`
  } else if (signalKey === 'buyback') {
    detail = `Rückkaufprogramm angekündigt`
    if (data.filing_date) detail += ` (8-K vom ${data.filing_date})`
  } else if (signalKey === 'congressional') {
    detail = 'US-Kongressmitglied hat gekauft (90 Tage)'
  } else if (signalKey === 'short_trend') {
    const start = data.ratio_start ? `${(data.ratio_start * 100).toFixed(1)}%` : '?'
    const end = data.ratio_end ? `${(data.ratio_end * 100).toFixed(1)}%` : '?'
    detail = `Short-Ratio: ${start} → ${end}`
    if (data.change_pct != null) detail += ` (${data.change_pct > 0 ? '+' : ''}${data.change_pct}%)`
  } else if (signalKey === 'ftd') {
    detail = `${Number(data.total_shares || 0).toLocaleString('de-CH')} Aktien nicht geliefert`
  } else if (signalKey === 'unusual_volume') {
    detail = `${data.ratio || '?'}× des 20-Tage-Durchschnitts`
    if (data.latest_volume) detail += ` (${Number(data.latest_volume).toLocaleString('de-CH')} Vol.)`
  }

  return (
    <div className="flex items-start gap-3 py-1.5">
      <span className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold shrink-0 ${
        cfg.type === 'warning' ? 'bg-warning/15 text-warning' : cfg.type === 'flag' ? 'bg-text-muted/15 text-text-muted' : 'bg-primary/15 text-primary'
      }`}>
        {cfg.short}
      </span>
      <div className="min-w-0">
        <span className="text-sm font-medium text-text-primary"><G term={cfg.glossar}>{cfg.label}</G></span>
        <span className="text-sm text-text-muted ml-2">{detail}</span>
      </div>
    </div>
  )
}

function ScoreBar({ score, max = 10 }) {
  const segments = []
  for (let i = 0; i < max; i++) {
    segments.push(
      <div key={i} className={`h-3 flex-1 rounded-sm ${i < score ? 'bg-primary' : 'bg-border'}`} />
    )
  }
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5 w-28" aria-label={`Smart Money Score: ${score} von ${max}`}>
        {segments}
      </div>
      <span className="text-lg font-bold font-mono text-text-primary">{score}</span>
      <span className="text-sm text-text-muted">/ {max}</span>
    </div>
  )
}

export default function SmartMoneyPanel({ ticker }) {
  const [collapsed, setCollapsed] = useState(false)

  const { data: match, error } = useApi(`/screening/ticker/${ticker}`)
  const scannedAt = match?.scanned_at

  // Don't render if still loading or no data (404 = no scan or ticker not found)
  if (!match) return null

  const signals = match.signals || {}
  const signalKeys = Object.keys(signals)

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-card-alt/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <Radar size={18} className="text-primary" />
          <span className="text-sm font-semibold text-text-primary"><G term="Smart Money Score">Smart Money Kontext</G></span>
          <div className="flex gap-1 ml-2">
            {signalKeys.map(key => {
              const cfg = SIGNAL_CONFIG[key]
              return cfg ? (
                <span key={key} className={`inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold ${
                  cfg.type === 'warning' ? 'bg-warning/15 text-warning' : cfg.type === 'flag' ? 'bg-text-muted/15 text-text-muted' : 'bg-primary/15 text-primary'
                }`}>
                  {cfg.short}
                </span>
              ) : null
            })}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <ScoreBar score={match.score} />
          {collapsed ? <ChevronDown size={16} className="text-text-muted" /> : <ChevronUp size={16} className="text-text-muted" />}
        </div>
      </button>

      {/* Body */}
      {!collapsed && (
        <div className="px-5 pb-4 pt-1 border-t border-border space-y-1">
          {signalKeys.map(key => (
            <SignalRow key={key} signalKey={key} data={signals[key]} />
          ))}
          {scannedAt && (
            <p className="text-xs text-text-muted pt-2">
              Stand: {new Date(scannedAt).toLocaleString('de-CH')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
