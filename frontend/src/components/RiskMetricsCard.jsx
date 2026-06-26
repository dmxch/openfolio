import { useApi } from '../hooks/useApi'
import { formatNumber, formatPct, pnlColor } from '../lib/format'
import { Gauge } from 'lucide-react'

// Prozent als Betrag (immer positiv dargestellt, z.B. Volatilität).
function pctMag(v) {
  if (v == null) return '–'
  return `${formatNumber(v, 2)}%`
}

// Verhältniszahl (Sharpe/Sortino/…) mit 2 Nachkommastellen, "–" bei null.
function ratio(v) {
  if (v == null) return '–'
  return formatNumber(v, 2)
}

function Tile({ label, value, valueClass = 'text-text-primary', sub }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] text-text-muted mb-1">{label}</p>
      <p className={`text-xl font-bold tabular-nums ${valueClass}`}>{value}</p>
      {sub ? <p className="text-[11px] text-text-muted mt-0.5 truncate">{sub}</p> : null}
    </div>
  )
}

const ROLLING_LABELS = [
  ['1m', '1M'],
  ['3m', '3M'],
  ['6m', '6M'],
  ['1y', '1J'],
]

export default function RiskMetricsCard({ bucketId = null }) {
  const url = bucketId
    ? `/portfolio/risk-metrics?bucket_id=${bucketId}`
    : '/portfolio/risk-metrics'
  const { data, loading, error } = useApi(url)

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-5 animate-pulse">
        <div className="h-4 bg-card-alt rounded w-40 mb-4"></div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-12 bg-card-alt rounded"></div>
          ))}
        </div>
        <div className="h-8 bg-card-alt rounded"></div>
      </div>
    )
  }

  // Zu wenig Historie → Backend antwortet mit HTTP 422. Gedämpfter Leerzustand
  // statt Crash oder leerer Karte.
  if (error && /\b422\b/.test(error)) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-text-secondary">Risiko-Kennzahlen</h3>
          <Gauge size={18} className="text-text-muted" />
        </div>
        <p className="text-xs text-text-muted">Zu wenig Historie für Risiko-Kennzahlen.</p>
      </div>
    )
  }

  if (error || !data) return null

  const rolling = data.rolling_returns || {}

  const tiles = [
    { label: 'Sharpe Ratio', value: ratio(data.sharpe_ratio) },
    { label: 'Sortino Ratio', value: ratio(data.sortino_ratio) },
    { label: 'Calmar Ratio', value: ratio(data.calmar_ratio) },
    { label: 'Volatilität (p.a.)', value: pctMag(data.volatility_pct) },
    {
      label: 'Information Ratio',
      value: ratio(data.information_ratio),
      sub: data.benchmark_annualized_return_pct != null
        ? `Benchmark ${data.benchmark || '–'}: ${formatPct(data.benchmark_annualized_return_pct)} p.a.`
        : null,
    },
    {
      label: 'Max Drawdown',
      value: data.max_drawdown_pct == null ? '–' : `-${formatNumber(data.max_drawdown_pct, 2)}%`,
      valueClass: 'text-danger',
    },
    {
      label: 'Rendite p.a. (TWR)',
      value: data.annualized_return_pct == null ? '–' : formatPct(data.annualized_return_pct),
      valueClass: pnlColor(data.annualized_return_pct),
    },
    { label: 'Downside-Vol (p.a.)', value: pctMag(data.downside_volatility_pct) },
  ]

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-text-secondary">Risiko-Kennzahlen</h3>
        <Gauge size={18} className="text-text-muted" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {tiles.map((t) => (
          <Tile
            key={t.label}
            label={t.label}
            value={t.value}
            valueClass={t.valueClass}
            sub={t.sub}
          />
        ))}
      </div>

      <div className="mt-5 pt-4 border-t border-border">
        <p className="text-[11px] text-text-muted mb-2">Rolling-Returns</p>
        <div className="grid grid-cols-4 gap-3">
          {ROLLING_LABELS.map(([key, label]) => {
            const v = rolling[key]
            return (
              <div key={key} className="text-center">
                <p className="text-[11px] text-text-muted mb-0.5">{label}</p>
                <p className={`text-sm font-semibold tabular-nums ${v == null ? 'text-text-muted' : pnlColor(v)}`}>
                  {v == null ? '–' : formatPct(v)}
                </p>
              </div>
            )
          })}
        </div>
      </div>

      <div className="mt-4 space-y-0.5">
        <p className="text-[11px] text-text-muted">
          risk-free rate = {data.risk_free_rate_pct}% · Benchmark {data.benchmark} · n={data.n_obs} Tage
        </p>
        <p className="text-[11px] text-text-muted">
          Rendite p.a. ist TWR-basiert (nicht die XIRR/MWR der Total-Return-Karte).
        </p>
      </div>
    </div>
  )
}
