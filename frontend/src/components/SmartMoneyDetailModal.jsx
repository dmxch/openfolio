import { useEffect, useState, useRef } from 'react'
import { X } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { SIGNAL_CONFIG } from '../lib/screeningConfig'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import TradingViewChart from './TradingViewChart'
import TickerLogo from './TickerLogo'

// Hinweis: Plan-Drift mit Begruendung — Plan sah MiniChartTooltip vor, das ist
// aber ein Hover-Popup. TradingViewChart ist die passende Embed-Komponente.

export default function SmartMoneyDetailModal({ ticker, onClose }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const dialogRef = useRef(null)

  useEscClose(onClose)
  useFocusTrap(true)

  useEffect(() => {
    if (!ticker) return
    let active = true
    setLoading(true)
    setError(null)
    authFetch(`/api/screening/ticker/${ticker}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((json) => { if (active) { setDetail(json); setLoading(false) } })
      .catch((e) => { if (active) { setError(e.message); setLoading(false) } })
    return () => { active = false }
  }, [ticker])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className="bg-card border border-border rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between p-4 border-b border-border sticky top-0 bg-card">
          <div className="flex items-center gap-3">
            <TickerLogo ticker={ticker} size={28} />
            <div>
              <div className="font-mono text-lg font-semibold">{ticker}</div>
              {detail?.name && <div className="text-sm text-text-muted">{detail.name}</div>}
            </div>
          </div>
          <button onClick={onClose} aria-label="Schliessen" className="p-1 rounded hover:bg-card-hover">
            <X size={20} />
          </button>
        </div>

        <div className="p-4 space-y-6">
          {loading && <div className="text-text-muted">Lade Detail-Daten…</div>}
          {error && <div className="text-danger">Fehler: {error}</div>}

          {detail && (
            <>
              <section>
                <div className="flex items-baseline gap-3 mb-2">
                  <h3 className="text-sm uppercase text-text-muted">Score-Breakdown</h3>
                  <span className="font-mono text-2xl font-semibold text-primary">{detail.score_display}</span>
                  <span className="text-sm text-text-muted">/100 (raw {detail.score})</span>
                </div>
                <ul className="space-y-2">
                  {Object.entries(detail.signals || {}).map(([key, val]) => {
                    const cfg = SIGNAL_CONFIG[key]
                    if (!cfg) return (
                      <li key={key} className="text-sm border border-border rounded p-2">
                        <div className="font-medium">{key}</div>
                        <pre className="text-xs text-text-muted mt-1 overflow-x-auto">{JSON.stringify(val, null, 2)}</pre>
                      </li>
                    )
                    return (
                      <li key={key} className="text-sm border border-border rounded p-2">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium">{cfg.label}</span>
                          <span className={`text-xs font-mono ${cfg.weight < 0 ? 'text-warning' : cfg.weight > 0 ? 'text-success' : 'text-text-muted'}`}>
                            {cfg.weight > 0 ? `+${cfg.weight}` : cfg.weight}
                          </span>
                        </div>
                        <div className="text-xs text-text-muted">{cfg.description}</div>
                        <pre className="text-xs text-text-muted mt-1 overflow-x-auto">{JSON.stringify(val, null, 2)}</pre>
                      </li>
                    )
                  })}
                </ul>
              </section>

              <section>
                <h3 className="text-sm uppercase text-text-muted mb-2">Chart</h3>
                <TradingViewChart ticker={ticker} height={300} />
              </section>

              <section>
                <button
                  disabled
                  title="Kommt in Iteration 5 mit AI-Skill-Trigger"
                  className="w-full py-2 px-4 rounded bg-primary/30 text-text-muted cursor-not-allowed"
                >
                  Trade-Plan generieren (Iteration 5)
                </button>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
