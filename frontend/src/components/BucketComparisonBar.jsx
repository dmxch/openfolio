import { LayoutGrid } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { formatCHF, formatPct, pnlColor } from '../lib/format'

// "Performance je Bucket" — Vergleichs-Tabelle: Total + jeder USER-Bucket als
// Zeile mit Ist-Gewicht (Inline-Balken), Wert, YTD, Benchmark-Delta und
// Drawdown vs. Peak. Klick auf eine Bucket-Zeile scrollt zum Detail-Abschnitt.
//
// Props:
//   onSelectBucket?: (bucketId: string) => void  // optional (vor Aufruf guarden)
//
// Datenquellen (analog BucketPerformanceCard):
//   /portfolio/buckets                                  → Bucket-Liste
//   /portfolio/buckets/allocations                      → Live-Werte/Gewicht je Bucket
//   /portfolio/buckets/{id}/benchmark-comparison?period=ytd
//   /portfolio/buckets/{id}/summary
//   /portfolio/summary + /portfolio/total-return        → Total-Zeile
//
// Sichtbar nur, wenn der User mind. 1 user-Bucket hat (sonst return null).

const NEUTRAL_DOT = '#64748b'

// Gemeinsames Spalten-Raster fuer Kopf-/Total-/Bucket-Zeilen — identische
// Template, damit die Spalten exakt fluchten. Auf schmalen Screens scrollt der
// Container horizontal (min-w).
const ROW = 'grid grid-cols-[1.4fr_1.7fr_1fr_0.85fr_1fr_0.85fr] items-center gap-3'
const MICRO = 'font-mono text-[10px] uppercase tracking-[0.06em] text-text-label'

function WeightBar({ pct, color, fillClass, track = 'bg-card-2' }) {
  const w = Math.max(0, Math.min(100, pct ?? 0))
  return (
    <div className="flex items-center gap-2.5">
      <div className={`flex-1 h-1.5 rounded-full overflow-hidden ${track}`}>
        <div
          className={`h-full rounded-full ${fillClass || ''}`}
          style={{ width: `${w}%`, ...(fillClass ? {} : { background: color }) }}
        />
      </div>
      <span className="font-mono text-[11.5px] text-text-bright tabular-nums w-10 text-right shrink-0">
        {pct != null ? `${pct.toFixed(1)}%` : '–'}
      </span>
    </div>
  )
}

function BucketRow({ bucket, alloc, onSelect }) {
  const { data: comp } = useApi(`/portfolio/buckets/${bucket.id}/benchmark-comparison?period=ytd`)
  const { data: summary } = useApi(`/portfolio/buckets/${bucket.id}/summary`)

  const value = alloc?.value_chf ?? summary?.total_value_chf ?? null
  const weight = alloc?.pct ?? null
  const ytd = comp?.bucket_return_pct ?? null
  const delta = comp?.delta_pct ?? null
  const bench = comp?.benchmark_return_pct ?? null
  const benchName = comp?.benchmark_name
  const peak = summary?.drawdown_vs_peak_pct ?? null
  const clamped = comp?.clamped

  return (
    <button
      type="button"
      onClick={() => onSelect?.(bucket.id)}
      className={`${ROW} w-full text-left px-3 py-2.5 rounded-lg hover:bg-hover transition-colors`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: bucket.color || NEUTRAL_DOT }} />
        <span className="text-[13px] font-medium text-text-primary truncate" title={bucket.name}>{bucket.name}</span>
      </div>
      <WeightBar pct={weight} color={bucket.color || NEUTRAL_DOT} />
      <span className="font-mono text-[12.5px] text-text-bright tabular-nums text-right">{formatCHF(value)}</span>
      <span
        className={`font-mono text-[12.5px] font-semibold tabular-nums text-right ${pnlColor(ytd)}`}
        title={clamped ? 'Vergleich ab Bucket-Erstellung — frühere Werte aus proportionalem Backfill.' : undefined}
      >
        {ytd != null ? formatPct(ytd) : '–'}{clamped ? '*' : ''}
      </span>
      <span
        className={`font-mono text-[12.5px] tabular-nums text-right ${pnlColor(delta)}`}
        title={benchName && bench != null ? `${benchName}: ${formatPct(bench)}` : undefined}
      >
        {delta != null ? formatPct(delta) : '–'}
      </span>
      <span className="font-mono text-[12.5px] text-text-muted tabular-nums text-right">
        {peak != null ? formatPct(peak) : '–'}
      </span>
    </button>
  )
}

function TotalRow({ summary, totalReturn }) {
  const value = summary?.total_market_value_chf ?? null
  const ytd = totalReturn?.ytd_pct ?? null
  const total = totalReturn?.total_return_pct ?? null

  return (
    <div className={`${ROW} px-3 py-2.5 rounded-lg bg-primary/5 border border-primary/20`}>
      <div className="flex items-center gap-2 min-w-0">
        <span className="w-2.5 h-2.5 rounded-full shrink-0 bg-primary" />
        <span className="text-[13px] font-semibold text-text-primary">Total</span>
      </div>
      <WeightBar pct={100} fillClass="bg-primary" track="bg-primary/20" />
      <span className="font-mono text-[12.5px] font-semibold text-text-primary tabular-nums text-right">{formatCHF(value)}</span>
      <span className={`font-mono text-[12.5px] font-semibold tabular-nums text-right ${pnlColor(ytd)}`}>
        {ytd != null ? formatPct(ytd) : '–'}
      </span>
      <span
        className={`font-mono text-[12.5px] tabular-nums text-right ${pnlColor(total)}`}
        title="Gesamtrendite seit Inception (MWR)"
      >
        {total != null ? `Ges. ${formatPct(total)}` : '–'}
      </span>
      <span className="font-mono text-[12.5px] text-text-muted tabular-nums text-right">–</span>
    </div>
  )
}

export default function BucketComparisonBar({ onSelectBucket }) {
  const { data: bucketsData, loading } = useApi('/portfolio/buckets')
  const { data: allocData } = useApi('/portfolio/buckets/allocations')
  const { data: totalSummary } = useApi('/portfolio/summary')
  const { data: totalReturn } = useApi('/portfolio/total-return')

  if (loading) {
    return (
      <div className="rounded-card border border-border bg-card p-[18px] animate-pulse">
        <div className="h-4 bg-hover rounded w-44 mb-4" />
        <div className="flex flex-col gap-2">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-9 bg-hover rounded-lg" />)}
        </div>
      </div>
    )
  }

  // Nur USER-Buckets (nicht-geloescht) — System-Rollen werden hier nicht verglichen.
  const userBuckets = (bucketsData?.buckets || []).filter((b) => b.kind === 'user' && !b.deleted_at)
  if (userBuckets.length === 0) return null

  const allocMap = {}
  for (const item of allocData?.items || []) allocMap[item.bucket_id] = item

  return (
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <LayoutGrid size={16} className="text-primary" />
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Performance je Bucket</h3>
          <p className="text-[11px] text-text-muted mt-0.5">
            Ist-Gewicht, YTD-Rendite, Δ zum Benchmark und Drawdown je Bucket · Klick öffnet das Detail
          </p>
        </div>
      </div>

      <div className="p-[18px] overflow-x-auto">
        <div className="min-w-[700px] flex flex-col gap-1">
          {/* Spalten-Kopf */}
          <div className={`${ROW} px-3 pb-1`}>
            <span className={MICRO}>Bucket</span>
            <span className={MICRO}>Ist-Gewicht</span>
            <span className={`${MICRO} text-right`}>Wert</span>
            <span className={`${MICRO} text-right`}>YTD</span>
            <span className={`${MICRO} text-right`}>Δ Benchmark</span>
            <span className={`${MICRO} text-right`}>vs. Peak</span>
          </div>

          <TotalRow summary={totalSummary} totalReturn={totalReturn} />
          {userBuckets.map((b) => (
            <BucketRow key={b.id} bucket={b} alloc={allocMap[b.id]} onSelect={onSelectBucket} />
          ))}
        </div>
      </div>
    </div>
  )
}
