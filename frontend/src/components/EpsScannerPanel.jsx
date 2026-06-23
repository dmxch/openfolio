import { Link } from 'react-router-dom'
import { TrendingUp, ArrowUpRight, AlertTriangle } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { formatYoyPct } from '../lib/epsFormat'

/**
 * EPS-Scanner-Kontext-Widget fuer die Aktiendetailseite — analog SmartMoneyPanel.
 * Zeigt die EPS-Momentum-Kennzahlen der Aktie und verlinkt (eine Richtung) zum
 * EPS-Scanner, vorgefiltert auf diesen Ticker. Versteckt, wenn der Ticker nicht
 * im S&P-500-Universum ist (404 -> kein data).
 */
export default function EpsScannerPanel({ ticker }) {
  const { data } = useApi(`/eps-scanner/ticker/${ticker}`)
  if (!data) return null

  const quarters = data.quarters || []
  const latest = quarters.length ? quarters[quarters.length - 1].eps : null

  return (
    <Link
      to={`/eps-scanner?search=${encodeURIComponent(ticker)}`}
      className="block bg-card border border-border rounded-xl overflow-hidden hover:bg-card-alt/30 transition-colors group"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <TrendingUp size={18} className="text-primary" />
          <span className="text-sm font-semibold text-text-primary">EPS-Scanner Kontext</span>
          <div className="flex gap-1 ml-2">
            {data.super_quarter && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-primary/15 text-primary" title="Super-Quartal-Kriterien erfüllt (Schwellen noch nicht backtest-validiert)">SQ</span>
            )}
            {data.record_quarter && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-success/15 text-success" title="Record-Quartal — neues 8-Quartals-EPS-Hoch">
                RQ{data.record_quarter_outlier && <AlertTriangle size={10} className="text-warning" />}
              </span>
            )}
          </div>
        </div>
        <ArrowUpRight size={16} className="text-text-muted group-hover:text-primary transition-colors" />
      </div>

      {/* Kennzahlen */}
      <div className="px-5 pb-4 pt-1 border-t border-border grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-xs text-text-muted">Jüngstes EPS</div>
          <div className="font-mono text-text-primary">{latest != null ? latest.toFixed(2) : '—'}</div>
        </div>
        <div>
          <div className="text-xs text-text-muted">YoY (jüngstes Q)</div>
          <div className="font-mono text-text-primary">{formatYoyPct(data.yoy_growth_pct)}</div>
        </div>
        <div>
          <div className="text-xs text-text-muted">Streak (Q mit +YoY)</div>
          <div className="font-mono text-text-primary">{data.streak_count ?? '—'}</div>
        </div>
      </div>

      <div className="px-5 pb-3 text-xs text-primary group-hover:underline">Im EPS-Scanner ansehen →</div>
    </Link>
  )
}
