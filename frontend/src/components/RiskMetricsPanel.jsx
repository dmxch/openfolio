import { useApi } from '../hooks/useApi'
import { formatNumber, formatPct, pnlColor } from '../lib/format'
import G from './GlossarTooltip'

// Verhältniszahl (Sharpe/Sortino/Calmar/Beta) mit 2 Nachkommastellen, "–" bei null.
function ratio(v) {
  if (v == null) return '–'
  return formatNumber(v, 2)
}

// Prozent als Betrag, immer positiv dargestellt (z.B. Volatilität, Tracking Error).
function pctMag(v) {
  if (v == null) return '–'
  return `${formatNumber(v, 2)}%`
}

function Shell({ children }) {
  return (
    <div className="bg-card border border-border rounded-card p-[18px]">
      <h3 className="text-sm font-semibold text-text-primary mb-3.5">Risiko-Kennzahlen</h3>
      {children}
    </div>
  )
}

export default function RiskMetricsPanel() {
  const { data: risk, loading: riskLoading, error: riskError } = useApi('/portfolio/risk-metrics')
  const { data: factor, loading: factorLoading } = useApi('/analysis/factor-decomposition')

  const loading = riskLoading || factorLoading

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card p-[18px] animate-pulse">
        <div className="h-4 bg-hover rounded w-40 mb-4" />
        <div className="flex flex-col gap-2.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-5 bg-hover rounded" />
          ))}
        </div>
      </div>
    )
  }

  // Zu wenig Historie → Backend antwortet mit HTTP 422, mit error-Feld
  // 'insufficient_history' oder schlicht ohne die Kern-Kennzahlen.
  const insufficient =
    (riskError && /\b422\b/.test(riskError)) ||
    risk?.error === 'insufficient_history' ||
    !risk ||
    (risk.sharpe_ratio == null && risk.volatility_pct == null && risk.max_drawdown_pct == null)

  if (insufficient) {
    return (
      <Shell>
        <p className="text-xs text-text-muted">Zu wenig Historie für Risiko-Kennzahlen.</p>
      </Shell>
    )
  }

  const alphaPct = factor?.alpha?.annualized_pct
  const betaSpy = factor?.factors?.SPY?.beta

  const rows = [
    {
      term: 'Alpha',
      label: 'Alpha',
      value: alphaPct == null ? '–' : formatPct(alphaPct),
      color: pnlColor(alphaPct),
    },
    {
      term: 'Beta',
      label: 'Beta',
      value: ratio(betaSpy),
      color: 'text-text-bright',
    },
    {
      term: 'Sharpe-Ratio',
      label: 'Sharpe',
      value: ratio(risk.sharpe_ratio),
      color: 'text-text-bright',
    },
    {
      term: 'Sortino-Ratio',
      label: 'Sortino',
      value: ratio(risk.sortino_ratio),
      color: 'text-text-bright',
    },
    {
      term: 'Calmar-Ratio',
      label: 'Calmar',
      value: ratio(risk.calmar_ratio),
      color: 'text-text-bright',
    },
    {
      term: 'Volatilität (p.a.)',
      label: 'Volatilität',
      value: pctMag(risk.volatility_pct),
      color: 'text-text-bright',
    },
    {
      term: 'Max Drawdown',
      label: 'Max Drawdown',
      value: risk.max_drawdown_pct == null ? '–' : `-${formatNumber(risk.max_drawdown_pct, 2)}%`,
      color: 'text-danger',
    },
    {
      term: 'Tracking Error',
      label: 'Tracking Error',
      value: pctMag(risk.tracking_error_pct),
      color: 'text-text-bright',
    },
  ]

  return (
    <Shell>
      <div className="flex flex-col">
        {rows.map((r, i) => (
          <div
            key={r.label}
            className={`flex items-center justify-between py-[9px] ${
              i < rows.length - 1 ? 'border-b border-border-row2' : ''
            }`}
          >
            <span className="text-[12.5px] text-text-secondary">
              <G term={r.term}>{r.label}</G>
            </span>
            <span className={`font-mono text-[13px] font-medium tabular-nums ${r.color}`}>
              {r.value}
            </span>
          </div>
        ))}
      </div>
    </Shell>
  )
}
