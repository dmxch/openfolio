import { useRef } from 'react'
import { X, ExternalLink, AlertTriangle } from 'lucide-react'
import {
  BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import TradingViewMiniChart from './TradingViewMiniChart'
import TickerLogo from './TickerLogo'
import EpsYoyBadge from './EpsYoyBadge'
import { toTradingViewSymbol } from '../lib/tradingview'
import { CHART_COLORS, AXIS_TICK_SM } from '../lib/chartColors'
import { formatQuarterLabel, formatYoyPct } from '../lib/epsFormat'

const YOY_LAG = 4 // gleiche Quartalsdefinition wie Backend (4 Perioden zurueck)

// Per-Quartal-YoY clientseitig (nur pos->pos, sonst null) — gespiegelt zur
// Backend-Logik, rein fuer die Detail-Tabelle.
function quartersWithYoy(quarters) {
  return quarters.map((q, i) => {
    let yoy = null
    if (i >= YOY_LAG) {
      const base = quarters[i - YOY_LAG].eps
      if (base > 0 && q.eps > 0) yoy = ((q.eps - base) / Math.abs(base)) * 100
    }
    return { ...q, yoy }
  })
}

function ChartTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null
  const p = payload[0].payload
  return (
    <div className="bg-card border border-border rounded px-2 py-1 text-xs">
      <div className="font-mono text-text-primary">{p.label}</div>
      <div className="text-text-secondary">EPS: {p.eps.toFixed(2)}</div>
      {p.yoy != null && <div className="text-text-muted">YoY: {formatYoyPct(p.yoy)}</div>}
    </div>
  )
}

export default function EpsDetailModal({ row, onClose }) {
  const dialogRef = useRef(null)
  useEscClose(onClose)
  useFocusTrap(true)

  if (!row) return null

  const quarters = quartersWithYoy(row.quarters || [])
  const latest = quarters.length ? quarters[quarters.length - 1] : null
  const chartData = quarters.map((q) => ({
    label: formatQuarterLabel(q.period_end),
    eps: q.eps,
    yoy: q.yoy,
    period: q.period_end,
  }))
  const source = latest?.source
  const ageDays = row.data_age_days

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`EPS-Detail ${row.ticker}`}
        onClick={(e) => e.stopPropagation()}
        className="bg-card border border-border rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto"
      >
        {/* Kopf */}
        <div className="flex items-center justify-between p-4 border-b border-border sticky top-0 bg-card z-10">
          <div className="flex items-center gap-3 min-w-0">
            <TickerLogo ticker={row.ticker} size={28} />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-lg font-semibold">{row.ticker}</span>
                {row.super_quarter && (
                  <span className="px-1.5 py-0.5 rounded text-xs bg-primary/15 text-primary" title="Super-Quartal-Kriterien erfüllt (Schwellen noch nicht backtest-validiert)">SQ</span>
                )}
                {row.record_quarter && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-success/15 text-success" title="Record-Quartal — neues 8-Quartals-EPS-Hoch">
                    RQ{row.record_quarter_outlier && <AlertTriangle size={11} className="text-warning" aria-label="möglicher Einmaleffekt" />}
                  </span>
                )}
                {row.turnaround && (
                  <span className="px-1.5 py-0.5 rounded text-xs bg-violet-500/15 text-violet-300" title="Turnaround: Verlust → Gewinn (im 8-Q-Fenster verlustig, jüngstes Quartal wieder profitabel)">TA</span>
                )}
              </div>
              <div className="text-sm text-text-muted truncate">
                {row.name}{row.sector ? ` · ${row.sector}` : ''}
              </div>
            </div>
          </div>
          <button onClick={onClose} aria-label="Schliessen" className="p-1 rounded hover:bg-card-hover">
            <X size={20} />
          </button>
        </div>

        <div className="p-4 space-y-5">
          {/* Kennzahlen */}
          <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div>
              <div className="text-xs uppercase tracking-wide text-text-muted">Jüngstes EPS</div>
              <div className="font-mono text-lg text-text-primary">{latest ? latest.eps.toFixed(2) : '—'}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-text-muted">YoY (jüngstes Q)</div>
              <div className="mt-0.5"><EpsYoyBadge yoyGrowthPct={row.yoy_growth_pct} yoyFlag={row.yoy_flag} /></div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-text-muted">Streak (Q mit +YoY)</div>
              <div className="font-mono text-lg text-text-primary">{row.streak_count ?? '—'}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-text-muted">Quelle / Stand</div>
              <div className="text-sm text-text-secondary">
                {source || '—'}{ageDays != null && <span className="text-text-muted"> · {ageDays === 0 ? 'heute' : `${ageDays}d`}</span>}
              </div>
            </div>
          </section>

          {/* Quartals-EPS Balkendiagramm */}
          <section>
            <h3 className="text-xs uppercase tracking-wide text-text-muted mb-2">Quartals-EPS</h3>
            {chartData.length > 0 ? (
              <div style={{ height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                    <XAxis dataKey="label" tick={AXIS_TICK_SM} axisLine={{ stroke: CHART_COLORS.grid }} tickLine={false} />
                    <YAxis tick={AXIS_TICK_SM} axisLine={false} tickLine={false} width={40} />
                    <Tooltip content={<ChartTooltip />} cursor={{ fill: CHART_COLORS.cardAlt }} />
                    <Bar dataKey="eps" radius={[2, 2, 0, 0]}>
                      {chartData.map((d, i) => {
                        const isLatest = i === chartData.length - 1
                        let fill = d.eps >= 0 ? CHART_COLORS.success : CHART_COLORS.danger
                        if (isLatest && row.record_quarter && d.eps >= 0) fill = CHART_COLORS.successLight
                        if (isLatest && row.super_quarter) fill = CHART_COLORS.primary
                        return <Cell key={d.period} fill={fill} />
                      })}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="text-text-muted text-sm">Keine Quartalsdaten.</div>
            )}
          </section>

          {/* Quartals-Tabelle */}
          <section>
            <h3 className="text-xs uppercase tracking-wide text-text-muted mb-2">Quartale (Reported EPS)</h3>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="text-text-muted text-xs">
                  <tr>
                    <th scope="col" className="text-left font-medium py-1 pr-3">Periode</th>
                    <th scope="col" className="text-right font-medium py-1 pr-3">EPS</th>
                    <th scope="col" className="text-right font-medium py-1">YoY</th>
                  </tr>
                </thead>
                <tbody>
                  {[...quarters].reverse().map((q, idx) => {
                    const isLatest = idx === 0
                    return (
                      <tr key={q.period_end} className={`border-t border-border/50 ${isLatest ? 'bg-card-alt/40' : ''}`}>
                        <td className="py-1 pr-3 font-mono text-text-secondary">
                          {formatQuarterLabel(q.period_end)} <span className="text-text-muted">({q.period_end})</span>
                        </td>
                        <td className={`py-1 pr-3 text-right font-mono ${q.eps < 0 ? 'text-danger' : 'text-text-primary'}`}>{q.eps.toFixed(2)}</td>
                        <td className="py-1 text-right font-mono text-text-secondary">{q.yoy == null ? '—' : formatYoyPct(q.yoy)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* TradingView-Chart (gross) */}
          <section>
            <div className="flex items-baseline justify-between mb-2">
              <h3 className="text-xs uppercase tracking-wide text-text-muted">Chart</h3>
              <a
                href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(toTradingViewSymbol(row.ticker))}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 underline"
              >
                Auf TradingView öffnen
                <ExternalLink size={12} />
              </a>
            </div>
            <TradingViewMiniChart ticker={row.ticker} height={360} dateRange="12M" />
          </section>
        </div>
      </div>
    </div>
  )
}
