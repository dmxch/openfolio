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

// Detail-Cluster: ein Tab auf einmal statt ~10 Karten gestapelt — das aufgeklappte
// Bucket-Detail wirkt damit aufgeraeumt statt ueberwaeltigend. Pro Tab wird nur der
// jeweilige Widget-Satz gemountet (lazy) → noch weniger Parallel-Fetches (H-7).
const SUB_TABS = [
  { key: 'rendite', label: 'Rendite' },
  { key: 'risiko', label: 'Risiko' },
  { key: 'positionen', label: 'Positionen & Cashflow' },
]

/**
 * Akkordeon-Sektion fuer EINEN Bucket. Der volle Widget-Satz wird erst beim
 * Aufklappen gemountet (lazy) — so feuern die vielen per-Bucket-Fetches nur,
 * wenn der User die Sektion tatsaechlich oeffnet (H-7: keine Parallel-Last).
 */
export default function BucketSection({ bucket, positions = [], weightPct = null }) {
  const [open, setOpen] = useState(false)
  const [subTab, setSubTab] = useState('rendite')
  const bucketPositions = positions.filter((p) => p.bucket_id === bucket.id)

  // Kopf-Kennzahlen (immer geladen, auch eingeklappt): YTD + Benchmark-Delta.
  const { data: comp } = useApi(`/portfolio/buckets/${bucket.id}/benchmark-comparison?period=ytd`)
  const ytd = comp?.bucket_return_pct ?? null
  const delta = comp?.delta_pct ?? null
  const bench = comp?.benchmark_return_pct ?? null
  const benchName = comp?.benchmark_name
  const clamped = comp?.clamped

  // Detail-Daten nur laden, wenn aufgeklappt
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
        className="w-full px-[18px] py-3.5 flex items-center gap-3 hover:bg-hover transition-colors text-left"
        aria-expanded={open}
      >
        {/* Name */}
        <div className="flex items-center gap-2.5 w-[150px] shrink-0 min-w-0">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: bucket.color || '#888' }} />
          <h3 className="text-sm font-semibold text-text-primary truncate" title={bucket.name}>{bucket.name}</h3>
        </div>

        {/* Ist-Gewicht */}
        <div className="flex-1 flex items-center gap-2.5 min-w-0">
          <div className="flex-1 h-1.5 rounded-full bg-card-2 overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max(0, Math.min(100, weightPct ?? 0))}%`, background: bucket.color || '#888' }}
            />
          </div>
          <span className="font-mono text-[11.5px] text-text-bright tabular-nums w-11 text-right shrink-0">
            {weightPct != null ? `${weightPct.toFixed(1)}%` : '–'}
          </span>
        </div>

        {/* YTD */}
        <div className="hidden sm:flex items-baseline gap-1 w-[86px] justify-end shrink-0">
          <span className="font-mono text-[9px] uppercase tracking-wide text-text-label">YTD</span>
          <span className={`font-mono text-[12.5px] font-semibold tabular-nums ${pnlColor(ytd)}`}>
            {ytd != null ? `${formatPct(ytd)}${clamped ? '*' : ''}` : '–'}
          </span>
        </div>

        {/* Δ Benchmark */}
        <div
          className="hidden md:flex items-baseline gap-1 w-[92px] justify-end shrink-0"
          title={benchName && bench != null ? `${benchName}: ${formatPct(bench)}` : undefined}
        >
          <span className="font-mono text-[9px] uppercase tracking-wide text-text-label">Δ</span>
          <span className={`font-mono text-[12.5px] tabular-nums ${pnlColor(delta)}`}>
            {delta != null ? formatPct(delta) : '–'}
          </span>
        </div>

        <ChevronDown size={18} className={`text-text-muted transition-transform shrink-0 ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="border-t border-border-2 p-[18px]">
          {/* Sub-Navigation: ein Cluster auf einmal statt 10 Karten gestapelt */}
          <div className="flex gap-1 mb-[18px] p-1 bg-surface rounded-lg w-fit border border-border-2">
            {SUB_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setSubTab(t.key)}
                className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                  subTab === t.key ? 'bg-active-tint text-text-bright' : 'text-text-muted hover:text-text-primary'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Rendite: Summary, Total-Return-Breakdown, Equity-Curve, Monatsrenditen */}
          {subTab === 'rendite' && (
            <div className="space-y-[18px]">
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

              {/* Equity-Curve — Default-Benchmark = Bucket-Benchmark */}
              <PerformanceChart bucketId={bucket.id} benchmark={bucket.benchmark} />

              {/* Monatsrenditen */}
              <MonthlyHeatmap data={monthly} loading={monthlyLoading} bucketMode={true} scope={bucket.name} />
            </div>
          )}

          {/* Risiko: Kennzahlen, Faktor-Exposition, Drawdown */}
          {subTab === 'risiko' && (
            <div className="space-y-[18px]">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
                <RiskMetricsCard bucketId={bucket.id} />
                <FactorExposureCard bucketId={bucket.id} />
              </div>
              <RollingDrawdownCard bucketId={bucket.id} />
            </div>
          )}

          {/* Positionen & Cashflow: Top-Mover, Diversifikation, Realisiert, Gebühren */}
          {subTab === 'positionen' && (
            <div className="space-y-[18px]">
              <TopMovers positions={bucketPositions} />
              <HhiCard bucketId={bucket.id} />
              <RealizedGainsTable bucketId={bucket.id} />
              <FeeSummary bucketId={bucket.id} />
            </div>
          )}
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
