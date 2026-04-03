import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Loader2, TrendingUp } from 'lucide-react'
import { CHART_COLORS, AXIS_TICK_SM } from '../lib/chartColors'

const PERIODS = [
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: 'YTD', days: null },
  { label: '1Y', days: 365 },
  { label: 'MAX', days: 3650 },
]

const BENCHMARKS = [
  { label: 'S&P 500', value: '^GSPC' },
  { label: 'SMI', value: '^SSMI' },
  { label: 'Keiner', value: '' },
]

function getStartDate(period) {
  const now = new Date()
  if (period.label === 'YTD') {
    return `${now.getFullYear()}-01-01`
  }
  const d = new Date(now)
  d.setDate(d.getDate() - period.days)
  return d.toISOString().split('T')[0]
}

function formatDate(dateStr) {
  const [y, m, d] = dateStr.split('-')
  return `${d}.${m}.${y}`
}

function formatPctSigned(val) {
  if (val == null) return '—'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-text-muted mb-1">{formatDate(label)}</div>
      {payload.map((p) => {
        const pct = p.value - 100
        return (
          <div key={p.dataKey} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: p.color }} />
            <span className="text-text-secondary">{p.name}:</span>
            <span className={`font-medium tabular-nums ${pct >= 0 ? 'text-success' : 'text-danger'}`}>
              {formatPctSigned(pct)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function PerformanceChart() {
  const [period, setPeriod] = useState(PERIODS[4]) // 1Y default
  const [benchmark, setBenchmark] = useState(BENCHMARKS[0])

  const startDate = useMemo(() => getStartDate(period), [period])
  const endDate = useMemo(() => new Date().toISOString().split('T')[0], [])
  const endpoint = `/portfolio/history?start=${startDate}&end=${endDate}${benchmark.value ? `&benchmark=${encodeURIComponent(benchmark.value)}` : ''}`

  const { data, loading } = useApi(endpoint)

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 flex items-center justify-center h-72">
        <Loader2 size={20} className="animate-spin text-text-muted" />
      </div>
    )
  }

  if (!data?.data?.length) return null

  const chartData = data.data
  const summary = data.summary || {}
  const hasBenchmark = benchmark.value && chartData[0]?.benchmark_indexed != null

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="p-4 border-b border-border flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">Performance-Verlauf</h3>
          {summary.return_pct != null && (
            <span className={`text-xs font-medium ${summary.return_pct >= 0 ? 'text-success' : 'text-danger'}`}>
              {formatPctSigned(summary.return_pct)}
            </span>
          )}
          {hasBenchmark && summary.benchmark_return_pct != null && (
            <span className="text-xs text-text-secondary">
              vs. {benchmark.label}: <span className={summary.benchmark_return_pct >= 0 ? 'text-success' : 'text-danger'}>
                {formatPctSigned(summary.benchmark_return_pct)}
              </span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Period buttons */}
          <div className="flex rounded-md border border-border overflow-hidden">
            {PERIODS.map((p) => (
              <button
                key={p.label}
                onClick={() => setPeriod(p)}
                className={`px-2 py-1 text-xs font-medium transition-colors ${
                  period.label === p.label
                    ? 'bg-primary text-white'
                    : 'text-text-muted hover:text-text-primary hover:bg-card-alt'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {/* Benchmark dropdown */}
          <select
            value={benchmark.value}
            onChange={(e) => setBenchmark(BENCHMARKS.find(b => b.value === e.target.value) || BENCHMARKS[2])}
            className="bg-card border border-border rounded px-2 py-1 text-xs text-text-secondary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
          >
            {BENCHMARKS.map((b) => (
              <option key={b.value} value={b.value}>{b.label}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="p-4">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <XAxis
              dataKey="date"
              tick={AXIS_TICK_SM}
              axisLine={{ stroke: CHART_COLORS.grid }}
              tickLine={false}
              tickFormatter={formatDate}
              interval="preserveStartEnd"
              minTickGap={60}
            />
            <YAxis
              tick={AXIS_TICK_SM}
              axisLine={false}
              tickLine={false}
              domain={['auto', 'auto']}
              tickFormatter={(v) => `${(v - 100).toFixed(0)}%`}
            />
            <Tooltip content={<CustomTooltip />} />
            <Line
              type="monotone"
              dataKey="portfolio_indexed"
              name="Portfolio"
              stroke={CHART_COLORS.primary}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
            {hasBenchmark && (
              <Line
                type="monotone"
                dataKey="benchmark_indexed"
                name={benchmark.label}
                stroke={CHART_COLORS.benchmark}
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={false}
                activeDot={{ r: 3 }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
