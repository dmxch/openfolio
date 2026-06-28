import { useState } from 'react'
import { useApi, apiPost } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { CalendarClock, Loader2, RefreshCw } from 'lucide-react'

const MAX_ROWS = 12

/**
 * Dividenden-Forecast — projiziertes Einkommen der naechsten 12 Monate als
 * Run-Rate (Trailing-12M je aktueller Position). Worker-gecacht, plus
 * On-demand-Neuberechnung (gedrosselt via Cache + Semaphore im Backend).
 * Quelle: GET /api/analysis/dividend-forecast, POST .../refresh.
 */
export default function DividendForecastCard() {
  const { data, loading, refetch } = useApi('/analysis/dividend-forecast')
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = async () => {
    if (refreshing) return
    setRefreshing(true)
    try {
      await apiPost('/analysis/dividend-forecast/refresh')
      await refetch()
    } catch {
      // Fehler bewusst geschluckt — die Card bleibt auf dem letzten Stand.
    } finally {
      setRefreshing(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card">
        <div className="text-center py-10"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data) return null

  const comps = data.by_holding || []
  const shown = comps.slice(0, MAX_ROWS)

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <CalendarClock size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Dividenden-Forecast (12M)</h3>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          title="Jetzt neu berechnen"
          className="ml-auto text-text-muted hover:text-text-primary disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="p-[18px]">
        {!data.has_data ? (
          <p className="text-xs text-text-muted py-3">
            Wird beim nächsten Dividenden-Lauf (täglich 09:30) berechnet — oder jetzt per ↻ oben.
          </p>
        ) : data.forecast_12m_chf <= 0 ? (
          <p className="text-xs text-text-muted py-3">Keine dividendenzahlenden Positionen erkannt.</p>
        ) : (
          <>
            <div className="mb-4">
              <div className="text-[22px] font-mono font-semibold text-text-primary tabular-nums leading-none">{formatCHF(data.forecast_12m_chf)}</div>
              <div className="text-[11px] text-text-muted mt-1.5">
                projiziert aus {data.payer_count} Zahler{data.payer_count === 1 ? '' : 'n'} · Run-Rate (Trailing-12M je aktueller Position, keine Wachstumsannahme)
              </div>
            </div>
            <div className="space-y-1.5">
              {shown.map((h) => (
                <div key={h.ticker} className="flex items-center justify-between gap-3 text-xs">
                  <span className="min-w-0 truncate">
                    <span className="font-medium text-text-primary">{h.ticker}</span>
                    <span className="text-text-muted"> · {h.name}</span>
                  </span>
                  <span className="shrink-0 font-mono tabular-nums text-text-secondary">{formatCHF(h.forecast_chf)}</span>
                </div>
              ))}
              {comps.length > MAX_ROWS && (
                <p className="text-[11px] text-text-muted pt-2">+{comps.length - MAX_ROWS} weitere</p>
              )}
            </div>
            {data.as_of && <p className="text-[11px] text-text-muted mt-3">Stand {data.as_of}</p>}
          </>
        )}
      </div>
    </div>
  )
}
