import { useMemo } from 'react'
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { TrendingDown, Loader2 } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { CHART_COLORS, AXIS_TICK_SM } from '../lib/chartColors'

const MS_PER_YEAR = 365 * 24 * 60 * 60 * 1000

/** Compact x-axis label: mm.yyyy (über mehrjährige Range gut lesbar). */
function fmtAxisDate(s) {
  if (!s) return ''
  const [y, m] = s.split('-')
  return `${m}.${y}`
}

/** Volles Datum für den Tooltip: dd.mm.yyyy (wie PerformanceChart). */
function fmtFullDate(s) {
  if (!s) return ''
  const [y, m, d] = s.split('-')
  return `${d}.${m}.${y}`
}

function fmtPct(v) {
  if (v == null || !Number.isFinite(v)) return '–'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

function fmtPctAxis(v) {
  return `${Math.round(v)}%`
}

/**
 * Leitet aus der cash-flow-adjustierten portfolio_indexed-Reihe zwei Reihen ab:
 *  - drawdown: Underwater-Drawdown ggü. laufendem Hochpunkt (immer <= 0).
 *  - rolling:  rollierende 12-Monats-Rendite (Anker ~1 Jahr zurück).
 */
function computeSeries(rawData) {
  const data = (rawData || [])
    .filter((d) => d && d.date != null && Number.isFinite(d.portfolio_indexed))
    .map((d) => ({ date: d.date, t: Date.parse(d.date), v: d.portfolio_indexed }))
    .filter((d) => Number.isFinite(d.t))
    .sort((a, b) => a.t - b.t)

  // 1) Underwater-Drawdown ggü. laufendem Peak
  let peak = -Infinity
  const drawdown = data.map((d) => {
    if (d.v > peak) peak = d.v
    const dd = peak > 0 ? (d.v / peak - 1) * 100 : 0
    return { date: d.date, drawdown_pct: dd }
  })

  // 2) Rollierende 12-Monats-Rendite. Anker = jüngster Punkt, der noch >= 365
  //    Tage vor D liegt (höchstes t <= cutoff). Bei <5-Tage-Downsampling liegt
  //    der Anker max. einen Gap-Schritt vor exakt 1 Jahr — präzise genug.
  const rolling = []
  let j = 0
  for (let i = 0; i < data.length; i++) {
    const cutoff = data[i].t - MS_PER_YEAR
    while (j + 1 < data.length && data[j + 1].t <= cutoff) j++
    if (data[j].t <= cutoff) {
      const back = data[j].v
      if (Number.isFinite(back) && back !== 0) {
        rolling.push({ date: data[i].date, rolling_pct: (data[i].v / back - 1) * 100 })
      }
    }
  }

  return { drawdown, rolling, points: data.length }
}

function PctTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const p = payload[0]
  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-text-muted mb-1">{fmtFullDate(label)}</div>
      <div className="flex items-center gap-2">
        <span className="text-text-secondary">{p.name}:</span>
        <span className="font-medium tabular-nums" style={{ color: p.color }}>
          {fmtPct(p.value)}
        </span>
      </div>
    </div>
  )
}

function CardShell({ children }) {
  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="p-4 border-b border-border flex items-center gap-2">
        <TrendingDown size={16} className="text-primary" />
        <h3 className="text-sm font-medium text-text-secondary">Rendite-Verlauf & Drawdown</h3>
      </div>
      {children}
    </div>
  )
}

export default function RollingDrawdownCard({ bucketId = null }) {
  const endpoint = useMemo(() => {
    const now = new Date()
    const endDate = now.toISOString().split('T')[0]
    const startObj = new Date(now)
    startObj.setFullYear(startObj.getFullYear() - 5)
    const startDate = startObj.toISOString().split('T')[0]
    // liquid=true: gleiche Reihe (Rendite-Risikobuch) wie die Risiko-Kennzahlen,
    // damit der Underwater-Drawdown-Tiefpunkt zur Max-Drawdown-Zahl passt.
    let url = `/portfolio/history?benchmark=${encodeURIComponent('^GSPC')}&start=${startDate}&end=${endDate}&liquid=true`
    if (bucketId) url += `&bucket_id=${bucketId}`
    return url
  }, [bucketId])

  const { data, loading, error } = useApi(endpoint)

  const { drawdown, rolling, points } = useMemo(
    () => computeSeries(data?.data),
    [data]
  )

  if (loading) {
    return (
      <CardShell>
        <div className="p-6 flex items-center justify-center h-48">
          <Loader2 size={20} className="animate-spin text-text-muted" />
        </div>
      </CardShell>
    )
  }

  if (error || points < 2) {
    return (
      <CardShell>
        <div className="p-6 text-sm text-text-muted">
          {error ? 'Verlaufsdaten momentan nicht abrufbar.' : 'Zu wenig Historie für Rolling-Kennzahlen.'}
        </div>
      </CardShell>
    )
  }

  return (
    <CardShell>
      <div className="p-4 space-y-6">
        {/* Underwater-Drawdown */}
        <div>
          <p className="text-[11px] font-medium text-text-muted mb-2">Underwater-Drawdown</p>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={drawdown} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="rddDrawdownFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={CHART_COLORS.danger} stopOpacity={0.05} />
                  <stop offset="100%" stopColor={CHART_COLORS.danger} stopOpacity={0.45} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={CHART_COLORS.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tick={AXIS_TICK_SM}
                axisLine={{ stroke: CHART_COLORS.grid }}
                tickLine={false}
                tickFormatter={fmtAxisDate}
                interval="preserveStartEnd"
                minTickGap={48}
              />
              <YAxis
                tick={AXIS_TICK_SM}
                axisLine={false}
                tickLine={false}
                domain={['auto', 0]}
                tickFormatter={fmtPctAxis}
                width={44}
              />
              <Tooltip content={<PctTooltip />} />
              <ReferenceLine y={0} stroke={CHART_COLORS.grid} />
              <Area
                type="monotone"
                dataKey="drawdown_pct"
                name="Drawdown"
                stroke={CHART_COLORS.danger}
                strokeWidth={1.5}
                fill="url(#rddDrawdownFill)"
                baseValue={0}
                dot={false}
                activeDot={{ r: 3 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Rollierende 12-Monats-Rendite */}
        <div>
          <p className="text-[11px] font-medium text-text-muted mb-2">Rollierende 12-Monats-Rendite</p>
          {rolling.length < 2 ? (
            <div className="h-[200px] flex items-center justify-center text-sm text-text-muted">
              Noch keine vollen 12 Monate Historie.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={rolling} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={CHART_COLORS.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={AXIS_TICK_SM}
                  axisLine={{ stroke: CHART_COLORS.grid }}
                  tickLine={false}
                  tickFormatter={fmtAxisDate}
                  interval="preserveStartEnd"
                  minTickGap={48}
                />
                <YAxis
                  tick={AXIS_TICK_SM}
                  axisLine={false}
                  tickLine={false}
                  domain={['auto', 'auto']}
                  tickFormatter={fmtPctAxis}
                  width={44}
                />
                <Tooltip content={<PctTooltip />} />
                <ReferenceLine y={0} stroke={CHART_COLORS.grid} />
                <Line
                  type="monotone"
                  dataKey="rolling_pct"
                  name="12M-Rendite"
                  stroke={CHART_COLORS.primary}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </CardShell>
  )
}
