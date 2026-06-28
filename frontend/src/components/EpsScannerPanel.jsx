import { Link } from 'react-router-dom'
import { TrendingUp, ArrowUpRight, AlertTriangle } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { formatQuarterLabel, formatYoyPct } from '../lib/epsFormat'

/**
 * EPS-Scanner-Kontext-Widget fuer die Aktiendetailseite — analog SmartMoneyPanel.
 * Zeigt die letzten Quartals-EPS als Heatzellen (Q / EPS / YoY) und verlinkt
 * (eine Richtung) zum EPS-Scanner, vorgefiltert auf diesen Ticker. Versteckt,
 * wenn der Ticker nicht im S&P-500-Universum ist (404 -> kein data).
 */
function heatBg(yoy) {
  if (yoy == null) return undefined
  const intensity = Math.min(Math.abs(yoy) / 60, 1)
  const a = 0.10 + intensity * 0.32
  return yoy >= 0 ? `rgba(69,192,138,${a})` : `rgba(232,98,90,${a})`
}

export default function EpsScannerPanel({ ticker }) {
  const { data } = useApi(`/eps-scanner/ticker/${ticker}`)
  if (!data) return null

  const quarters = data.quarters || []

  // Per-Quartal-YoY aus dem 8-Quartals-Fenster ableiten (eps[i] vs. eps[i-4]).
  const withYoy = quarters.map((q, i) => {
    let yoy = null
    if (i >= 4) {
      const prev = quarters[i - 4]?.eps
      if (prev != null && prev !== 0) yoy = ((q.eps - prev) / Math.abs(prev)) * 100
    }
    return { ...q, yoy }
  })
  const cells = withYoy.slice(-4)

  return (
    <Link
      to={`/eps-scanner?search=${encodeURIComponent(ticker)}`}
      className="block bg-card border border-border rounded-card overflow-hidden hover:border-border-hover transition-colors group"
    >
      {/* Header */}
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <TrendingUp size={16} className="text-primary shrink-0" />
          <h3 className="text-sm font-semibold text-text-primary">EPS-Verlauf</h3>
          <div className="flex gap-1">
            {data.super_quarter && (
              <span className="px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-primary/15 text-primary" title="Super-Quartal-Kriterien erfüllt (Schwellen noch nicht backtest-validiert)">SQ</span>
            )}
            {data.record_quarter && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-success/15 text-success" title="Record-Quartal — neues 8-Quartals-EPS-Hoch">
                RQ{data.record_quarter_outlier && <AlertTriangle size={10} className="text-warning" />}
              </span>
            )}
            {data.turnaround && (
              <span className="px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-violet-500/15 text-violet-300" title="Turnaround: Verlust → Gewinn">TA</span>
            )}
          </div>
        </div>
        <ArrowUpRight size={16} className="text-text-muted group-hover:text-primary transition-colors shrink-0" />
      </div>

      {/* Quartals-Heatzellen */}
      <div className="p-[18px]">
        {cells.length > 0 ? (
          <div className="grid grid-cols-4 gap-2">
            {cells.map((c, i) => (
              <div
                key={i}
                className="rounded-lg border border-border-2 p-2.5 text-center"
                style={{ background: heatBg(c.yoy) }}
              >
                <div className="font-mono text-[10px] tracking-[0.04em] uppercase text-text-label">{formatQuarterLabel(c.period_end)}</div>
                <div className="font-mono text-[15px] font-semibold text-text-primary tabular-nums mt-1.5 leading-none">{c.eps != null ? c.eps.toFixed(2) : '—'}</div>
                <div className={`font-mono text-[10.5px] mt-1.5 ${c.yoy == null ? 'text-text-faint' : c.yoy >= 0 ? 'text-success' : 'text-danger'}`}>
                  {c.yoy == null ? '—' : formatYoyPct(c.yoy)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[12.5px] text-text-muted">Keine Quartalsdaten verfügbar.</p>
        )}
        <div className="mt-3 flex items-center justify-between text-[11px]">
          <span className="text-text-muted">Streak (Q mit +YoY): <span className="font-mono text-text-secondary">{data.streak_count ?? '—'}</span></span>
          <span className="text-link group-hover:underline">Im EPS-Scanner ansehen →</span>
        </div>
      </div>
    </Link>
  )
}
