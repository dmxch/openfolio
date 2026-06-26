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

export default function FactorExposureCard({ bucketId = null }) {
  const url = bucketId
    ? `/analysis/factor-decomposition?bucket_id=${bucketId}`
    : '/analysis/factor-decomposition'
  const { data, loading, error } = useApi(url)

  if (loading) {
    return (
      <div className="rounded-lg border border-border p-5 animate-pulse">
        <div className="h-4 bg-card-alt rounded w-48 mb-4"></div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-5">
          <div className="h-12 bg-card-alt rounded"></div>
          <div className="h-12 bg-card-alt rounded"></div>
          <div className="h-12 bg-card-alt rounded"></div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="h-12 bg-card-alt rounded"></div>
          <div className="h-12 bg-card-alt rounded"></div>
          <div className="h-12 bg-card-alt rounded"></div>
          <div className="h-12 bg-card-alt rounded"></div>
        </div>
      </div>
    )
  }

  // 422 = insufficient_history (zu wenig Historie); 503 = Faktor-Kursdaten nicht
  // abrufbar. Nur bei 422 (oder fehlenden Daten ohne Fehler) die Historie-Meldung
  // zeigen, sonst einen neutralen Hinweis — kein irrefuehrendes "zu wenig Historie".
  if (error || !data?.factors) {
    const insufficient = !error || /\b422\b/.test(String(error))
    return (
      <div className="rounded-lg border border-border p-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-text-secondary">{TITLE}</h3>
          <Activity size={18} className="text-text-muted" />
        </div>
        <p className="text-xs text-text-muted">
          {insufficient
            ? 'Zu wenig Historie für eine Faktor-Regression (min. 30 Handelstage).'
            : 'Faktordaten momentan nicht abrufbar.'}
        </p>
      </div>
    )
  }

  const alpha = data.alpha || {}
  const missing = new Set(data.missing_factors || [])
  const alphaPct = alpha.annualized_pct
  const alphaColor = alphaPct > 0 ? 'text-success' : alphaPct < 0 ? 'text-danger' : 'text-text-primary'
  const rSquared = data.r_squared

  return (
    <div className="rounded-lg border border-border p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-text-secondary">{TITLE}</h3>
        <Activity size={18} className="text-text-muted" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-5">
        <div>
          <p className="text-[11px] text-text-muted mb-1">Alpha (annualisiert)</p>
          <p className={`text-2xl font-bold ${alphaColor}`}>
            {alphaPct != null ? `${alphaPct > 0 ? '+' : ''}${formatNumber(alphaPct, 2)}%` : '–'}
          </p>
          <p className="text-xs text-text-muted mt-0.5">faktor-bereinigte Überrendite</p>
        </div>
        <div>
          <p className="text-[11px] text-text-muted mb-1">R²</p>
          <p className="text-2xl font-bold text-text-primary">
            {rSquared != null ? `${(rSquared * 100).toFixed(0)}%` : '–'}
          </p>
          <p className="text-xs text-text-muted mt-0.5">durch Faktoren erklärt</p>
        </div>
        <div className="min-w-0">
          <p className="text-[11px] text-text-muted mb-1">Stichprobe</p>
          <p className="text-lg font-bold text-text-primary">n={data.n_obs ?? '?'} Tage</p>
          {data.window?.start && data.window?.end && (
            <p className="text-xs text-text-muted mt-0.5">
              {formatDateShort(data.window.start)} – {formatDateShort(data.window.end)}
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {FACTOR_LABELS.map(([key, label]) => {
          const f = data.factors[key]
          if (!f || missing.has(key)) return null
          const t = f.t_stat
          const significant = t != null && Math.abs(t) >= 2
          return (
            <div key={key} className="rounded border border-border bg-card-alt/40 px-3 py-2">
              <p className="text-[11px] text-text-muted mb-0.5">{label}</p>
              <p className="text-base font-bold text-text-primary tabular-nums">
                {f.beta != null ? formatNumber(f.beta, 3, { minDecimals: 2 }) : '–'}
              </p>
              <p className={`text-[11px] tabular-nums mt-0.5 ${significant ? 'font-bold text-text-secondary' : 'text-text-muted'}`}>
                t={t != null ? formatNumber(t, 2) : '–'}
              </p>
            </div>
          )
        })}
      </div>

      <p className="text-[11px] text-text-muted mt-4">
        OLS, tägliche Returns, NYSE-aligned. t-Wert ≥ 2 = signifikant.
      </p>
    </div>
  )
}
