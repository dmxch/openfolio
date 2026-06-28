import { useApi } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import { PieChart } from 'lucide-react'

const CLASS_BADGES = {
  low:      { label: 'Gut diversifiziert',   text: 'text-success', chip: 'bg-success/10 border-success/30 text-success' },
  moderate: { label: 'Moderat konzentriert', text: 'text-warning', chip: 'bg-warning/10 border-warning/30 text-warning' },
  high:     { label: 'Stark konzentriert',   text: 'text-danger',  chip: 'bg-danger/10 border-danger/30 text-danger' },
}

const LABEL = 'font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label'

export default function HhiCard({ bucketId = null }) {
  const url = bucketId
    ? `/portfolio/correlation-matrix?period=90d&bucket_id=${bucketId}`
    : '/portfolio/correlation-matrix?period=90d'
  const { data, loading, error } = useApi(url)

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card p-[18px] animate-pulse">
        <div className="h-4 bg-hover rounded w-32 mb-4" />
        <div className="grid grid-cols-3 gap-6">
          <div className="h-12 bg-hover rounded" />
          <div className="h-12 bg-hover rounded" />
          <div className="h-12 bg-hover rounded" />
        </div>
      </div>
    )
  }
  if (error || !data?.concentration) return null

  const c = data.concentration
  const badge = CLASS_BADGES[c.classification] || CLASS_BADGES.moderate

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <PieChart size={16} className="text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">Diversifikation</h3>
        </div>
        <span className={`text-[11px] font-medium px-2.5 py-1 rounded-md border ${badge.chip}`}>
          {badge.label}
        </span>
      </div>

      <div className="p-[18px] grid grid-cols-3 gap-4">
        <div>
          <p className={`${LABEL} mb-1.5`}>HHI</p>
          <p className={`text-xl font-mono font-semibold tabular-nums ${badge.text}`}>{formatNumber(c.hhi, 3)}</p>
          <p className="text-[11px] text-text-muted mt-0.5">Herfindahl-Index</p>
        </div>
        <div>
          <p className={`${LABEL} mb-1.5`}>Effektive Positionen</p>
          <p className="text-xl font-mono font-semibold text-text-primary tabular-nums">{formatNumber(c.effective_n, 2)}</p>
          <p className="text-[11px] text-text-muted mt-0.5">von {c.nominal_count ?? data.tickers?.length ?? '?'} nominal</p>
        </div>
        <div className="min-w-0">
          <p className={`${LABEL} mb-1.5`}>Grösste Position</p>
          <p className="text-base font-semibold text-text-primary truncate" title={c.max_weight_name || c.max_weight_ticker}>
            {c.max_weight_name || c.max_weight_ticker}
          </p>
          <p className="text-[11px] text-text-muted mt-0.5">{formatNumber(c.max_weight_pct, 2)}% des invest. Kapitals</p>
        </div>
      </div>
    </div>
  )
}
