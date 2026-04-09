import { useApi } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import { PieChart } from 'lucide-react'

const CLASS_BADGES = {
  low:      { label: 'Gut diversifiziert',   bg: 'bg-success/5 border-success/20', text: 'text-success' },
  moderate: { label: 'Moderat konzentriert', bg: 'bg-warning/5 border-warning/20', text: 'text-warning' },
  high:     { label: 'Stark konzentriert',   bg: 'bg-danger/5 border-danger/20',   text: 'text-danger' },
}

export default function HhiCard() {
  const { data, loading, error } = useApi('/portfolio/correlation-matrix?period=90d')

  if (loading) {
    return (
      <div className="rounded-lg border border-border p-5 animate-pulse">
        <div className="h-4 bg-card-alt rounded w-32 mb-4"></div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="h-12 bg-card-alt rounded"></div>
          <div className="h-12 bg-card-alt rounded"></div>
          <div className="h-12 bg-card-alt rounded"></div>
        </div>
      </div>
    )
  }
  if (error || !data?.concentration) return null

  const c = data.concentration
  const badge = CLASS_BADGES[c.classification] || CLASS_BADGES.moderate

  return (
    <div className={`rounded-lg border p-5 ${badge.bg}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-text-secondary">Diversifikation</h3>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-bold px-2.5 py-1 rounded ${badge.text} ${badge.bg} border`}>
            {badge.label}
          </span>
          <PieChart size={18} className="text-text-muted" />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div>
          <p className="text-[11px] text-text-muted mb-1">HHI</p>
          <p className={`text-2xl font-bold ${badge.text}`}>{formatNumber(c.hhi, 3)}</p>
          <p className="text-xs text-text-muted mt-0.5">Herfindahl-Index</p>
        </div>
        <div>
          <p className="text-[11px] text-text-muted mb-1">Effektive Positionen</p>
          <p className="text-2xl font-bold text-text-primary">{formatNumber(c.effective_n, 2)}</p>
          <p className="text-xs text-text-muted mt-0.5">von {data.tickers?.length ?? '?'} nominal</p>
        </div>
        <div>
          <p className="text-[11px] text-text-muted mb-1">Grösste Position</p>
          <p className="text-2xl font-bold text-text-primary">{c.max_weight_ticker}</p>
          <p className="text-xs text-text-muted mt-0.5">{formatNumber(c.max_weight_pct, 2)}% Gewicht</p>
        </div>
      </div>
    </div>
  )
}
