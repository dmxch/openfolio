import { useApi } from '../hooks/useApi'
import { formatCHF, formatPct } from '../lib/format'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer, ReferenceLine } from 'recharts'
import { Loader2, TrendingUp } from 'lucide-react'
import { CHART_COLORS, AXIS_TICK_SM } from '../lib/chartColors'

const COLORS = {
  deposits: CHART_COLORS.benchmark,
  capital_gains: CHART_COLORS.successLight,
  realized_gains: CHART_COLORS.successLight,
  dividends: CHART_COLORS.primary,
  fees: CHART_COLORS.danger,
  taxes: CHART_COLORS.danger,
  withdrawals: CHART_COLORS.danger,
  final_value: '#8b5cf6',
}

const LABELS = {
  deposits: 'Einzahlungen',
  capital_gains: 'Kursgewinne',
  realized_gains: 'Realisiert',
  dividends: 'Dividenden',
  fees: 'Gebühren',
  taxes: 'Steuern',
  withdrawals: 'Auszahlungen',
  final_value: 'Portfoliowert',
}

function buildWaterfallData(perf) {
  if (!perf) return []

  const items = [
    { key: 'deposits', value: perf.deposits },
    { key: 'capital_gains', value: perf.capital_gains },
    { key: 'realized_gains', value: perf.realized_gains },
    { key: 'dividends', value: perf.dividends },
    { key: 'fees', value: perf.fees },
    { key: 'taxes', value: perf.taxes },
    { key: 'withdrawals', value: perf.withdrawals },
  ].filter((d) => d.value !== 0)

  // Build waterfall with running total
  let running = 0
  const data = []

  for (const item of items) {
    const start = running
    running += item.value
    data.push({
      name: LABELS[item.key],
      key: item.key,
      value: item.value,
      start: Math.min(start, running),
      bar: Math.abs(item.value),
    })
  }

  // Final value bar
  data.push({
    name: LABELS.final_value,
    key: 'final_value',
    value: perf.final_value,
    start: 0,
    bar: perf.final_value,
  })

  return data
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-text-primary font-medium">{d.name}</div>
      <div className={`tabular-nums ${d.value >= 0 ? 'text-success' : 'text-danger'}`}>
        {formatCHF(d.value)}
      </div>
    </div>
  )
}

export default function PerformanceWaterfall() {
  const { data: perf, loading } = useApi('/portfolio/performance?from=2024-01-01')

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 flex items-center justify-center h-72">
        <Loader2 size={20} className="animate-spin text-text-muted" />
      </div>
    )
  }

  if (!perf) return null

  const chartData = buildWaterfallData(perf)

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">Performance Waterfall</h3>
        </div>
        <div className="flex items-center gap-4 text-xs text-text-secondary">
          <span>TWR: <span className={perf.twr_pct >= 0 ? 'text-success' : 'text-danger'}>{formatPct(perf.twr_pct)}</span></span>
          <span>IRR: <span className={perf.irr_pct >= 0 ? 'text-success' : 'text-danger'}>{formatPct(perf.irr_pct)}</span></span>
        </div>
      </div>
      <div className="p-4">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chartData} barCategoryGap="20%">
            <XAxis
              dataKey="name"
              tick={AXIS_TICK_SM}
              axisLine={{ stroke: CHART_COLORS.grid }}
              tickLine={false}
              interval={0}
              angle={-25}
              textAnchor="end"
              height={60}
            />
            <YAxis
              tick={AXIS_TICK_SM}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
            />
            <Tooltip content={<CustomTooltip />} cursor={false} />
            <ReferenceLine y={0} stroke={CHART_COLORS.grid} />
            {/* Invisible bar for the "start" offset */}
            <Bar dataKey="start" stackId="waterfall" fill="transparent" />
            {/* Visible bar */}
            <Bar dataKey="bar" stackId="waterfall" radius={[3, 3, 0, 0]}>
              {chartData.map((entry) => (
                <Cell key={entry.key} fill={COLORS[entry.key] || '#6b7280'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
