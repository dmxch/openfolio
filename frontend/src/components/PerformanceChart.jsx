import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { localDateStr } from '../lib/format'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Loader2, TrendingUp } from 'lucide-react'
import { CHART_COLORS, AXIS_TICK_SM } from '../lib/chartColors'

export const PERIODS = [
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: 'YTD', days: null },
  { label: '1Y', days: 365 },
  { label: 'MAX', days: 3650 },
]

export const BASE_BENCHMARKS = [
  { label: 'S&P 500', value: '^GSPC' },
  { label: 'SMI', value: '^SSMI' },
  { label: 'Keiner', value: '' },
]

// Freundliche Labels fuer bekannte Benchmark-Ticker (u.a. Bucket-Benchmarks).
const BENCHMARK_LABELS = {
  '^GSPC': 'S&P 500',
  '^SSMI': 'SMI',
  '^IXIC': 'Nasdaq',
  '^STOXX50E': 'Euro Stoxx 50',
  'URTH': 'MSCI World',
  'MTUM': 'Momentum (MTUM)',
  'GLD': 'Gold',
  'BTC-USD': 'Bitcoin',
}

// Optionsliste — ergaenzt um den eigenen Benchmark eines Buckets (z.B. MTUM
// fuer Satellite), falls noch nicht in der Basisliste enthalten.
function buildBenchmarks(bucketBenchmark) {
  if (!bucketBenchmark || BASE_BENCHMARKS.some((b) => b.value === bucketBenchmark)) {
    return BASE_BENCHMARKS
  }
  const label = BENCHMARK_LABELS[bucketBenchmark] || bucketBenchmark
  return [{ label, value: bucketBenchmark }, ...BASE_BENCHMARKS]
}

function getStartDate(period) {
  const now = new Date()
  if (period.label === 'YTD') {
    return `${now.getFullYear()}-01-01`
  }
  const d = new Date(now)
  d.setDate(d.getDate() - period.days)
  return localDateStr(d)
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
    <div className="bg-modal border border-border-hover rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="font-mono text-text-muted mb-1">{formatDate(label)}</div>
      {payload.map((p) => {
        const pct = p.value - 100
        return (
          <div key={p.dataKey} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: p.color }} />
            <span className="text-text-secondary">{p.name}:</span>
            <span className={`font-mono font-medium tabular-nums ${pct >= 0 ? 'text-success' : 'text-danger'}`}>
              {formatPctSigned(pct)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/**
 * Equity-Kurve Portfolio vs Benchmark. Kann uncontrolled (eigene Period-/
 * Benchmark-Selektoren, z.B. im Bucket-Akkordeon) oder controlled betrieben
 * werden (Period/Benchmark kommen von der Performance-Seite — Sub-Tab-Leiste +
 * Header). hideControls blendet die internen Selektoren aus, wenn die Seite sie
 * stellt. Datenanbindung/Endpoint-Konstruktion unveraendert.
 */
export default function PerformanceChart({
  bucketId = null,
  benchmark: bucketBenchmark = null,
  height = 300,
  period: controlledPeriod = null,
  onPeriodChange = null,
  benchmarkValue: controlledBenchmarkValue = null,
  onBenchmarkChange = null,
  hideControls = false,
}) {
  const benchmarks = useMemo(() => buildBenchmarks(bucketBenchmark), [bucketBenchmark])
  const [periodInternal, setPeriodInternal] = useState(PERIODS[4]) // 1Y default
  // Default-Benchmark: der eigene Benchmark des Buckets (falls gesetzt), sonst S&P 500.
  const [benchmarkInternal, setBenchmarkInternal] = useState(() => benchmarks[0])

  const period = controlledPeriod || periodInternal
  const benchmark = controlledBenchmarkValue != null
    ? (benchmarks.find((b) => b.value === controlledBenchmarkValue)
        || benchmarks.find((b) => b.value === '')
        || benchmarks[0])
    : benchmarkInternal

  const setPeriod = (p) => { onPeriodChange ? onPeriodChange(p) : setPeriodInternal(p) }
  const setBenchmark = (val) => {
    const b = benchmarks.find((x) => x.value === val) || benchmarks.find((x) => x.value === '')
    if (onBenchmarkChange) onBenchmarkChange(val)
    else setBenchmarkInternal(b)
  }

  const startDate = useMemo(() => getStartDate(period), [period])
  const endDate = useMemo(() => localDateStr(), [])
  const endpoint = `/portfolio/history?start=${startDate}&end=${endDate}${benchmark.value ? `&benchmark=${encodeURIComponent(benchmark.value)}` : ''}${bucketId ? `&bucket_id=${bucketId}` : ''}`

  const { data, loading } = useApi(endpoint)

  if (loading) {
    return (
      <div className="rounded-card border border-border bg-card p-6 flex items-center justify-center" style={{ minHeight: height + 80 }}>
        <Loader2 size={20} className="animate-spin text-text-muted" />
      </div>
    )
  }

  if (!data?.data?.length) return null

  const chartData = data.data
  const summary = data.summary || {}
  const hasBenchmark = benchmark.value && chartData[0]?.benchmark_indexed != null

  return (
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2.5">
          <TrendingUp size={16} className="text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">Performance-Verlauf</h3>
          {summary.return_pct != null && (
            <span className={`font-mono text-xs font-medium tabular-nums ${summary.return_pct >= 0 ? 'text-success' : 'text-danger'}`}>
              {formatPctSigned(summary.return_pct)}
            </span>
          )}
          {hasBenchmark && summary.benchmark_return_pct != null && (
            <span className="text-xs text-text-muted">
              vs. {benchmark.label}:{' '}
              <span className={`font-mono tabular-nums ${summary.benchmark_return_pct >= 0 ? 'text-success' : 'text-danger'}`}>
                {formatPctSigned(summary.benchmark_return_pct)}
              </span>
            </span>
          )}
        </div>
        {!hideControls && (
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-border-2 bg-surface overflow-hidden">
              {PERIODS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => setPeriod(p)}
                  className={`px-2.5 py-1 font-mono text-[11px] tracking-[0.04em] transition-colors ${
                    period.label === p.label
                      ? 'bg-active-tint text-text-bright'
                      : 'text-text-muted hover:text-text-primary hover:bg-hover'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <select
              value={benchmark.value}
              onChange={(e) => setBenchmark(e.target.value)}
              className="bg-surface border border-border-2 rounded-lg px-2 py-1 text-xs text-text-secondary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            >
              {benchmarks.map((b) => (
                <option key={b.value} value={b.value}>{b.label}</option>
              ))}
            </select>
          </div>
        )}
      </div>
      <div className="p-[18px]">
        <ResponsiveContainer width="100%" height={height}>
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
