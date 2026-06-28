import { useApi } from '../hooks/useApi'
import { formatNumber, formatDateShort } from '../lib/format'
import { Activity } from 'lucide-react'

// Reihenfolge + deutsche Labels für die Faktor-Betas.
const FACTOR_LABELS = [
  ['SPY', 'Markt'],
  ['MTUM', 'Momentum'],
  ['VLUE', 'Value'],
  ['QUAL', 'Quality'],
  ['IWM', 'Small-Cap'],
  ['GLD', 'Gold'],
  ['BTCUSD', 'Krypto'],
  ['USDCHF', 'CHF-FX'],
]

const TITLE = 'Faktor-Exposure (Alpha / Beta)'
const LABEL = 'font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label'

function Shell({ children }) {
  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">{TITLE}</h3>
        <Activity size={16} className="text-text-muted" />
      </div>
      <div className="p-[18px]">{children}</div>
    </div>
  )
}

export default function FactorExposureCard({ bucketId = null }) {
  const url = bucketId
    ? `/analysis/factor-decomposition?bucket_id=${bucketId}`
    : '/analysis/factor-decomposition'
  const { data, loading, error } = useApi(url)

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card p-[18px] animate-pulse">
        <div className="h-4 bg-hover rounded w-48 mb-4" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-5">
          <div className="h-12 bg-hover rounded" />
          <div className="h-12 bg-hover rounded" />
          <div className="h-12 bg-hover rounded" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-12 bg-hover rounded" />)}
        </div>
      </div>
    )
  }

  // 422 = insufficient_history; 503 = Faktor-Kursdaten nicht abrufbar.
  if (error || !data?.factors) {
    const insufficient = !error || /\b422\b/.test(String(error))
    return (
      <Shell>
        <p className="text-xs text-text-muted">
          {insufficient
            ? 'Zu wenig Historie für eine Faktor-Regression (min. 30 Handelstage).'
            : 'Faktordaten momentan nicht abrufbar.'}
        </p>
      </Shell>
    )
  }

  const alpha = data.alpha || {}
  const missing = new Set(data.missing_factors || [])
  const alphaPct = alpha.annualized_pct
  const alphaColor = alphaPct > 0 ? 'text-success' : alphaPct < 0 ? 'text-danger' : 'text-text-primary'
  const rSquared = data.r_squared

  return (
    <Shell>
      <div className="grid grid-cols-3 gap-4 mb-5">
        <div>
          <p className={`${LABEL} mb-1.5`}>Alpha (annualisiert)</p>
          <p className={`text-xl font-mono font-semibold tabular-nums ${alphaColor}`}>
            {alphaPct != null ? `${alphaPct > 0 ? '+' : ''}${formatNumber(alphaPct, 2)}%` : '–'}
          </p>
          <p className="text-[11px] text-text-muted mt-0.5">faktor-bereinigte Überrendite</p>
        </div>
        <div>
          <p className={`${LABEL} mb-1.5`}>R²</p>
          <p className="text-xl font-mono font-semibold text-text-primary tabular-nums">
            {rSquared != null ? `${(rSquared * 100).toFixed(0)}%` : '–'}
          </p>
          <p className="text-[11px] text-text-muted mt-0.5">durch Faktoren erklärt</p>
        </div>
        <div className="min-w-0">
          <p className={`${LABEL} mb-1.5`}>Stichprobe</p>
          <p className="text-base font-mono font-semibold text-text-primary tabular-nums">n={data.n_obs ?? '?'}</p>
          {data.window?.start && data.window?.end && (
            <p className="text-[11px] text-text-muted mt-0.5">
              {formatDateShort(data.window.start)} – {formatDateShort(data.window.end)}
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-[11px]">
        {FACTOR_LABELS.map(([key, label]) => {
          const f = data.factors[key]
          if (!f || missing.has(key) || f.beta == null) return null
          const beta = f.beta
          const neg = beta < 0
          // Balkenbreite: |beta| auf 1.0 gecappt (kein Überlauf), relativ zur halben Track-Breite.
          const frac = Math.min(Math.abs(beta), 1)
          const t = f.t_stat
          const significant = t != null && Math.abs(t) >= 2
          return (
            <div
              key={key}
              className="flex items-center gap-2.5"
              title={t != null ? `t = ${formatNumber(t, 2)}` : undefined}
            >
              <span className="text-xs text-text-secondary w-[78px] flex-none truncate">{label}</span>
              <div className="flex-1 h-2 bg-border-row rounded relative flex">
                <div className="absolute left-1/2 -top-[3px] -bottom-[3px] w-px bg-border-hover" />
                <div className="w-1/2 flex justify-end">
                  {neg && (
                    <div className="h-2 bg-danger rounded-l" style={{ width: `${frac * 100}%` }} />
                  )}
                </div>
                <div className="w-1/2">
                  {!neg && (
                    <div className="h-2 bg-primary rounded-r" style={{ width: `${frac * 100}%` }} />
                  )}
                </div>
              </div>
              <span
                className={`font-mono text-[11.5px] tabular-nums w-[46px] text-right flex-none ${significant ? 'text-text-bright font-medium' : 'text-text-muted'}`}
              >
                {beta >= 0 ? '+' : ''}{formatNumber(beta, 2)}
              </span>
            </div>
          )
        })}
      </div>

      <p className="text-[11px] text-text-muted mt-4">
        OLS, tägliche Returns, NYSE-aligned. t-Wert ≥ 2 = signifikant.
      </p>
    </Shell>
  )
}
