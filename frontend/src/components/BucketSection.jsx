import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { formatCHF, formatPct, pnlColor } from '../lib/format'
import { ChevronDown } from 'lucide-react'
import BucketPerformanceCard from './BucketPerformanceCard'
import PerformanceChart from './PerformanceChart'
import RiskMetricsCard from './RiskMetricsCard'
import FactorExposureCard from './FactorExposureCard'
import RollingDrawdownCard from './RollingDrawdownCard'
import MonthlyHeatmap from './MonthlyHeatmap'
import TopMovers from './TopMovers'
import RealizedGainsTable from './RealizedGainsTable'
import FeeSummary from './FeeSummary'
import HhiCard from './HhiCard'

/**
 * Akkordeon-Sektion fuer EINEN Bucket. Der volle Widget-Satz wird erst beim
 * Aufklappen gemountet (lazy) — so feuern die vielen per-Bucket-Fetches nur,
 * wenn der User die Sektion tatsaechlich oeffnet (H-7: keine Parallel-Last).
 */
export default function BucketSection({ bucket, positions = [] }) {
  const [open, setOpen] = useState(false)
  const bucketPositions = positions.filter((p) => p.bucket_id === bucket.id)

  // Daten nur laden, wenn aufgeklappt
  const { data: monthly, loading: monthlyLoading } = useApi(
    open ? `/portfolio/buckets/${bucket.id}/monthly-returns` : null,
    { skip: !open },
  )
  const { data: tr } = useApi(
    open ? `/portfolio/buckets/${bucket.id}/total-return` : null,
    { skip: !open },
  )

  return (
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-[18px] py-4 flex items-center justify-between hover:bg-hover transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2.5">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: bucket.color || '#888' }} />
          <h3 className="text-sm font-semibold text-text-primary">{bucket.name}</h3>
          {bucket.benchmark && <span className="text-xs text-text-muted">vs {bucket.benchmark}</span>}
        </div>
        <ChevronDown size={18} className={`text-text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="border-t border-border-2 p-[18px] space-y-[18px]">
          {/* Summary + YTD vs Benchmark */}
          <BucketPerformanceCard bucketId={bucket.id} />

          {/* Total-Return-Breakdown (Geld-auf-Geld) */}
          {tr && (
            <div className="rounded-card border border-border-2 bg-card-2 p-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-semibold text-text-primary">Total-Return-Breakdown</h4>
                <span className={`text-sm font-mono font-semibold tabular-nums ${pnlColor(tr.total_return_chf)}`}>
                  {formatCHF(tr.total_return_chf)}{' '}
                  <span className="text-xs">({formatPct(tr.total_return_pct)})</span>
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
                <Stat label="Unrealisiert" value={tr.unrealized_pnl_chf} />
                <Stat label="Realisiert" value={tr.realized_pnl_chf} />
                <Stat label="Dividenden (netto)" value={tr.dividends_net_chf} />
                <Stat label="Zinsen" value={tr.interest_chf} />
                <Stat label="Kapitalgewinne" value={tr.capital_gains_dist_chf} />
                <Stat label="Gebühren" value={-(tr.total_fees_chf || 0)} />
              </div>
              <p className="text-[11px] text-text-muted mt-3">
                Geld-auf-Geld auf investiertem Kapital ({formatCHF(tr.total_invested_chf)}) — kein XIRR.
                Die zeitgewichtete Rendite vs Benchmark steht in der Karte oben.
              </p>
            </div>
          )}

          {/* Risiko & Faktoren */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
            <RiskMetricsCard bucketId={bucket.id} />
            <FactorExposureCard bucketId={bucket.id} />
          </div>

          {/* Equity-Curve + Rolling/Drawdown — Default-Benchmark = Bucket-Benchmark */}
          <PerformanceChart bucketId={bucket.id} benchmark={bucket.benchmark} />
          <RollingDrawdownCard bucketId={bucket.id} />

          {/* Monatsrenditen */}
          <MonthlyHeatmap data={monthly} loading={monthlyLoading} bucketMode={true} />

          {/* Top-Mover (client-seitig auf Bucket gefiltert) */}
          <TopMovers positions={bucketPositions} />

          {/* Diversifikation */}
          <HhiCard bucketId={bucket.id} />

          {/* Realisiert + Gebühren */}
          <RealizedGainsTable bucketId={bucket.id} />
          <FeeSummary bucketId={bucket.id} />
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div>
      <p className="text-text-muted">{label}</p>
      <p className={`font-mono tabular-nums font-medium ${pnlColor(value)}`}>{formatCHF(value)}</p>
    </div>
  )
}
