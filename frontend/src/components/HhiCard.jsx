import { useApi } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import Skeleton from './Skeleton'

const CLASS_BADGES = {
  low:      { label: 'Gut diversifiziert',  color: 'bg-success/15 text-success border-success/30' },
  moderate: { label: 'Moderat konzentriert', color: 'bg-warning/15 text-warning border-warning/30' },
  high:     { label: 'Stark konzentriert',   color: 'bg-danger/15 text-danger border-danger/30' },
}

export default function HhiCard() {
  const { data, loading, error } = useApi('/portfolio/correlation-matrix?period=90d')

  if (loading) return <Skeleton className="h-32" />
  if (error || !data?.concentration) return null

  const c = data.concentration
  const badge = CLASS_BADGES[c.classification] || CLASS_BADGES.moderate

  return (
    <div className="bg-card border border-border rounded-2xl p-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wide">Diversifikation</h3>
        <span className={`text-xs px-2 py-1 rounded-md border ${badge.color}`}>{badge.label}</span>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <div className="text-xs text-text-muted">HHI</div>
          <div className="text-2xl font-semibold text-text-primary">{formatNumber(c.hhi, 3)}</div>
        </div>
        <div>
          <div className="text-xs text-text-muted">Effektive Positionen</div>
          <div className="text-2xl font-semibold text-text-primary">{formatNumber(c.effective_n, 2)}</div>
          <div className="text-xs text-text-muted">von {data.tickers?.length ?? '?'} nominal</div>
        </div>
        <div>
          <div className="text-xs text-text-muted">Groesste Position</div>
          <div className="text-base font-semibold text-text-primary">{c.max_weight_ticker}</div>
          <div className="text-xs text-text-muted">{formatNumber(c.max_weight_pct, 2)}%</div>
        </div>
      </div>
    </div>
  )
}
