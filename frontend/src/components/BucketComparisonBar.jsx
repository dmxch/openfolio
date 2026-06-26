import { useCallback, useEffect, useState } from 'react'
import { LayoutGrid } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { useApi } from '../hooks/useApi'
import { formatCHF, formatPct, pnlColor } from '../lib/format'
import { CHART_COLORS, AXIS_TICK_SM } from '../lib/chartColors'

// Vergleichs-Leiste fuer die Performance-Seite: Total + jeder USER-Bucket
// nebeneinander, plus ein Balkendiagramm YTD-Rendite vs Benchmark je Bucket.
//
// Props:
//   onSelectBucket?: (bucketId: string) => void  // optional, Klick auf eine
//     Bucket-Kachel; vor Aufruf guarden (kann undefined sein).
//
// Datenquellen (analog BucketTabBar / BucketPerformanceCard):
//   /portfolio/buckets                                  → Bucket-Liste
//   /portfolio/buckets/allocations                      → Live-Werte je Bucket
//   /portfolio/buckets/{id}/benchmark-comparison?period=ytd
//   /portfolio/buckets/{id}/summary
//   /portfolio/summary + /portfolio/total-return        → Total-Spalte
//
// Sichtbar nur, wenn der User mind. 1 user-Bucket hat (sonst return null).

const NEUTRAL_DOT = '#64748b'

// Einzelne Bucket-Kachel. Holt benchmark-comparison + summary selbst (eigene
// useApi-Hooks, sauber pro Bucket) und meldet die Rohdaten via onData nach oben,
// damit das Diagramm daraus aufgebaut werden kann. Jede fehlende Quelle zeigt
// "–" statt zu crashen.
function BucketComparisonCell({ bucket, alloc, onSelectBucket, onData }) {
  const { data: comp } = useApi(
    `/portfolio/buckets/${bucket.id}/benchmark-comparison?period=ytd`,
  )
  const { data: summary } = useApi(`/portfolio/buckets/${bucket.id}/summary`)

  // Rohdaten fuer das Diagramm nach oben reichen. comp/summary aendern ihre
  // Identitaet nur beim Fetch-Abschluss → kein Render-Loop (onData ist stabil).
  useEffect(() => {
    onData?.(bucket.id, { comp, summary })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bucket.id, comp, summary])

  const value = alloc?.value_chf ?? summary?.total_value_chf ?? null
  const ytd = comp?.bucket_return_pct ?? null
  const bench = comp?.benchmark_return_pct ?? null
  const delta = comp?.delta_pct ?? null
  const benchName = comp?.benchmark_name
  const peakDraw = summary?.drawdown_vs_peak_pct ?? null
  const clamped = comp?.clamped

  return (
    <button
      type="button"
      onClick={() => onSelectBucket?.(bucket.id)}
      className="w-44 shrink-0 text-left rounded-lg border border-border bg-card-alt/40 hover:border-primary/50 transition-colors p-3"
    >
      <div className="flex items-center gap-1.5 mb-2">
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ background: bucket.color || NEUTRAL_DOT }}
        />
        <span className="text-xs font-medium text-text-primary truncate" title={bucket.name}>
          {bucket.name}
        </span>
      </div>

      <p className="text-[11px] text-text-muted">Wert</p>
      <p className="text-base font-bold text-text-primary mb-1.5">{formatCHF(value)}</p>

      <p
        className="text-[11px] text-text-muted"
        title={
          clamped
            ? 'Vergleich ab Bucket-Erstellung — frühere Werte stammen aus proportionalem Backfill.'
            : undefined
        }
      >
        YTD{clamped && <span className="ml-0.5 text-text-muted/70">*</span>}
      </p>
      <p className={`text-sm font-semibold ${pnlColor(ytd)}`}>
        {ytd != null ? formatPct(ytd) : '–'}
      </p>

      <p className="text-[11px] text-text-muted mt-1.5">Δ Benchmark</p>
      <p className={`text-sm font-semibold ${pnlColor(delta)}`}>
        {delta != null ? formatPct(delta) : '–'}
      </p>
      {benchName && bench != null && (
        <p className="text-[10px] text-text-muted truncate" title={benchName}>
          {benchName} {formatPct(bench)}
        </p>
      )}

      <p className="text-[11px] text-text-muted mt-1.5">vs. Peak</p>
      <p className="text-sm font-semibold text-text-muted">
        {peakDraw != null ? formatPct(peakDraw) : '–'}
      </p>
    </button>
  )
}

// Total-Kachel (Aggregat ueber das ganze liquide Portfolio).
function TotalCell({ summary, totalReturn }) {
  const value = summary?.total_market_value_chf ?? null
  const ytd = totalReturn?.ytd_pct ?? null
  const totalPct = totalReturn?.total_return_pct ?? null

  return (
    <div className="w-44 shrink-0 rounded-lg border border-primary/40 bg-primary/5 p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <span className="w-2.5 h-2.5 rounded-full shrink-0 bg-primary" />
        <span className="text-xs font-semibold text-text-primary">Total</span>
      </div>

      <p className="text-[11px] text-text-muted">Wert</p>
      <p className="text-base font-bold text-text-primary mb-1.5">{formatCHF(value)}</p>

      <p className="text-[11px] text-text-muted">YTD</p>
      <p className={`text-sm font-semibold ${pnlColor(ytd)}`}>
        {ytd != null ? formatPct(ytd) : '–'}
      </p>

      <p className="text-[11px] text-text-muted mt-1.5">Gesamt</p>
      <p className={`text-sm font-semibold ${pnlColor(totalPct)}`}>
        {totalPct != null ? formatPct(totalPct) : '–'}
      </p>

      <p className="text-[11px] text-text-muted mt-1.5">vs. Peak</p>
      <p className="text-sm font-semibold text-text-muted">–</p>
    </div>
  )
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null
  const benchName = payload[0]?.payload?.benchName
  const delta = payload[0]?.payload?.delta
  return (
    <div className="bg-card border border-border rounded px-2.5 py-1.5 text-xs">
      <div className="font-medium text-text-primary mb-0.5">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="text-text-secondary">
          <span style={{ color: p.color }}>■</span>{' '}
          {p.dataKey === 'rendite' ? 'Bucket' : benchName || 'Benchmark'}: {formatPct(p.value)}
        </div>
      ))}
      {delta != null && (
        <div className={`mt-0.5 ${pnlColor(delta)}`}>Δ {formatPct(delta)}</div>
      )}
    </div>
  )
}

export default function BucketComparisonBar({ onSelectBucket }) {
  const { data: bucketsData, loading: bucketsLoading } = useApi('/portfolio/buckets')
  const { data: allocData } = useApi('/portfolio/buckets/allocations')
  const { data: totalSummary } = useApi('/portfolio/summary')
  const { data: totalReturn } = useApi('/portfolio/total-return')

  // Rohdaten je Bucket (von den Zellen hochgereicht) fuer das Diagramm.
  const [cellData, setCellData] = useState({})
  const handleCellData = useCallback((id, payload) => {
    setCellData((prev) => ({ ...prev, [id]: payload }))
  }, [])

  if (bucketsLoading) {
    return (
      <div className="rounded-lg border border-border bg-card p-5 animate-pulse">
        <div className="h-4 bg-card-alt rounded w-40 mb-4" />
        <div className="flex gap-3">
          <div className="h-32 bg-card-alt rounded w-44" />
          <div className="h-32 bg-card-alt rounded w-44" />
          <div className="h-32 bg-card-alt rounded w-44" />
        </div>
      </div>
    )
  }

  // Nur USER-Buckets (nicht-geloescht) — System-Rollen (real_estate,
  // private_equity, pension, liquid_default) werden hier nicht verglichen.
  // Spiegelt die kind === 'user'-Filterung aus BucketTabBar.
  const userBuckets = (bucketsData?.buckets || []).filter(
    (b) => b.kind === 'user' && !b.deleted_at,
  )

  // Ohne user-Buckets ist die Vergleichs-Leiste bedeutungslos.
  if (userBuckets.length === 0) return null

  // Allokations-Map: bucket_id → Live-Allokation (value_chf, pct).
  const allocMap = {}
  for (const item of allocData?.items || []) {
    allocMap[item.bucket_id] = item
  }

  // Diagramm-Daten: pro Bucket ein Eintrag mit zwei Balken (Rendite vs
  // Benchmark). Buckets ohne Vergleichsdaten werden uebersprungen.
  const chartData = userBuckets
    .map((b) => {
      const comp = cellData[b.id]?.comp
      if (!comp || comp.bucket_return_pct == null) return null
      return {
        name: b.name,
        rendite: comp.bucket_return_pct,
        benchmark: comp.benchmark_return_pct,
        benchName: comp.benchmark_name,
        delta: comp.delta_pct,
      }
    })
    .filter(Boolean)

  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div className="flex items-center gap-2">
        <LayoutGrid size={16} className="text-primary" />
        <h3 className="text-sm font-medium text-text-secondary">Performance je Bucket</h3>
      </div>

      <div className="flex gap-3 overflow-x-auto pb-1">
        <TotalCell summary={totalSummary} totalReturn={totalReturn} />
        {userBuckets.map((b) => (
          <BucketComparisonCell
            key={b.id}
            bucket={b}
            alloc={allocMap[b.id]}
            onSelectBucket={onSelectBucket}
            onData={handleCellData}
          />
        ))}
      </div>

      {chartData.length > 0 && (
        <div>
          <p className="text-xs text-text-muted mb-2">YTD-Rendite vs Benchmark je Bucket</p>
          <div style={{ width: '100%', height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                <XAxis
                  dataKey="name"
                  tick={AXIS_TICK_SM}
                  axisLine={{ stroke: CHART_COLORS.grid }}
                  tickLine={false}
                  interval={0}
                />
                <YAxis
                  tick={AXIS_TICK_SM}
                  axisLine={false}
                  tickLine={false}
                  width={44}
                  tickFormatter={(v) => `${v}%`}
                />
                <ReferenceLine y={0} stroke={CHART_COLORS.grid} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: CHART_COLORS.cardAlt }} />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: CHART_COLORS.muted }}
                  formatter={(val) => (val === 'rendite' ? 'Bucket' : 'Benchmark')}
                />
                <Bar dataKey="rendite" fill={CHART_COLORS.primary} radius={[2, 2, 0, 0]} />
                <Bar dataKey="benchmark" fill={CHART_COLORS.benchmark} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  )
}
