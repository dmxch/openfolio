import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { CalendarClock, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"
const MAX_ROWS = 12

/**
 * Dividenden-Forecast — projiziertes Einkommen der naechsten 12 Monate als
 * Run-Rate (Trailing-12M je aktueller Position). Read-only, worker-gecacht.
 * Quelle: GET /api/analysis/dividend-forecast.
 */
export default function DividendForecastCard() {
  const { data, loading } = useApi('/analysis/dividend-forecast')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data) return null

  const comps = data.by_holding || []
  const shown = comps.slice(0, MAX_ROWS)

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-1">
        <CalendarClock size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Dividenden-Forecast (12M)</h3>
      </div>

      {!data.has_data ? (
        <p className="text-xs text-text-muted py-3">
          Wird beim nächsten Dividenden-Lauf (täglich 09:30) berechnet und erscheint dann hier.
        </p>
      ) : data.forecast_12m_chf <= 0 ? (
        <p className="text-xs text-text-muted py-3">Keine dividendenzahlenden Positionen erkannt.</p>
      ) : (
        <>
          <div className="mb-3">
            <div className="text-2xl font-bold text-text-primary tabular-nums">{formatCHF(data.forecast_12m_chf)}</div>
            <div className="text-[11px] text-text-muted">
              projiziert aus {data.payer_count} Zahler{data.payer_count === 1 ? '' : 'n'} · Run-Rate (Trailing-12M je aktueller Position, keine Wachstumsannahme)
            </div>
          </div>
          <div className="space-y-1">
            {shown.map((h) => (
              <div key={h.ticker} className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate">
                  <span className="font-medium text-text-primary">{h.ticker}</span>
                  <span className="text-text-muted"> · {h.name}</span>
                </span>
                <span className="shrink-0 tabular-nums text-text-secondary">{formatCHF(h.forecast_chf)}</span>
              </div>
            ))}
            {comps.length > MAX_ROWS && (
              <p className="text-[11px] text-text-muted pt-1">+{comps.length - MAX_ROWS} weitere</p>
            )}
          </div>
          {data.as_of && <p className="text-[11px] text-text-muted mt-2">Stand {data.as_of}</p>}
        </>
      )}
    </div>
  )
}
