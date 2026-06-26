import { useEffect, useCallback } from 'react'
import { useApi } from '../hooks/useApi'
import { usePortfolioData } from '../contexts/DataContext'
import { LineChart } from 'lucide-react'
import Skeleton from '../components/Skeleton'
import RecalculateButton from '../components/RecalculateButton'
import PerformanceCard from '../components/PerformanceCard'
import PerformanceChart from '../components/PerformanceChart'
import FactorExposureCard from '../components/FactorExposureCard'
import RiskMetricsCard from '../components/RiskMetricsCard'
import RollingDrawdownCard from '../components/RollingDrawdownCard'
import AllocationCharts from '../components/AllocationCharts'
import HhiCard from '../components/HhiCard'
import MonthlyHeatmap from '../components/MonthlyHeatmap'
import TopMovers from '../components/TopMovers'
import RealizedGainsTable from '../components/RealizedGainsTable'
import FeeSummary from '../components/FeeSummary'
import BucketComparisonBar from '../components/BucketComparisonBar'
import BucketSection from '../components/BucketSection'

/**
 * Performance-Seite — buendelt alle Renditen-/Risiko-Auswertungen, die frueher
 * auf der Portfolio-Seite lagen, plus neue Kennzahlen (Alpha/Beta, Sharpe/Sortino,
 * Equity-Curve, Rolling/Drawdown). Pro Bucket gibt es eine Vergleichsleiste +
 * Akkordeon mit dem vollen Widget-Satz. Die Portfolio-Seite ist jetzt reine
 * Positionsverwaltung.
 */
export default function Performance() {
  const { refetch: refetchGlobal } = usePortfolioData()
  const { data: summary, loading, error, refetch: refetchSummary } = useApi('/portfolio/summary')
  const { data: reData } = useApi('/properties')
  // Abhaengige Endpoints erst nach summary laden (H-7: keine Parallel-Last)
  const { data: dailyChange, refetch: refetchDaily } = useApi('/portfolio/daily-change', { skip: !summary })
  const { data: totalReturn, refetch: refetchTotalReturn } = useApi('/portfolio/total-return', { skip: !summary })
  const { data: monthlyReturns, loading: monthlyLoading, refetch: refetchMonthly } = useApi('/portfolio/monthly-returns', { skip: !summary })
  const { data: bucketList } = useApi('/portfolio/buckets', { skip: !summary })

  // Nach "Neu berechnen": Cost-Basis ist sofort frisch (Summary/Total-Return);
  // die Snapshot-basierten Charts ziehen nach, sobald die Regen im Hintergrund
  // durch ist (ein Reload zeigt sie vollstaendig).
  const handleRecalculated = useCallback(() => {
    refetchSummary?.()
    refetchDaily?.()
    refetchTotalReturn?.()
    refetchMonthly?.()
    refetchGlobal?.()
  }, [refetchSummary, refetchDaily, refetchTotalReturn, refetchMonthly, refetchGlobal])

  // Hash-Scroll: z.B. von der Portfolio-Seite via /performance#allocation-charts
  // (Allokations-Alert). Nach dem Laden zum Zielelement scrollen.
  useEffect(() => {
    if (loading) return
    const hash = window.location.hash
    if (!hash) return
    const t = setTimeout(() => {
      document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 200)
    return () => clearTimeout(t)
  }, [loading])

  if (loading) {
    return (
      <div className="space-y-6">
        <Header />
        <Skeleton className="h-28" />
        <Skeleton className="h-96" />
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <Header />
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-6 text-danger text-sm">
          Fehler beim Laden: {error}
        </div>
      </div>
    )
  }

  const realEstateEquity = reData?.total_equity_chf || 0
  const positions = summary?.positions || []
  const allBuckets = bucketList?.buckets || (Array.isArray(bucketList) ? bucketList : [])
  const userBuckets = allBuckets.filter((b) => b?.kind === 'user' && !b.deleted_at)

  return (
    <div className="space-y-6">
      <Header onRecalculate={handleRecalculated} />

      {/* Gesamt-Performance (liquid + total, Daily, Total-Return-Breakdown) */}
      <PerformanceCard
        summary={summary}
        realEstateEquity={realEstateEquity}
        dailyChange={dailyChange}
        totalReturn={totalReturn}
      />

      {/* Equity-Curve Portfolio vs Benchmark */}
      <PerformanceChart />

      {/* Risiko & Faktoren */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <RiskMetricsCard />
        <FactorExposureCard />
      </div>
      <RollingDrawdownCard />

      {/* Allokation & Diversifikation */}
      <div id="allocation-charts">
        <AllocationCharts allocations={summary?.allocations} realEstateEquity={realEstateEquity} positions={positions} />
      </div>
      <HhiCard />

      {/* Monatsrenditen */}
      <MonthlyHeatmap data={monthlyReturns} loading={monthlyLoading} bucketMode={false} />

      {/* Top-Gewinner / Top-Verlierer */}
      <TopMovers positions={positions} />

      {/* Realisierte Gewinne + Gebühren/Steuern */}
      <RealizedGainsTable />
      <FeeSummary />

      {/* Pro Bucket: Vergleichsleiste + Akkordeon mit vollem Widget-Satz */}
      {userBuckets.length > 0 && (
        <div className="space-y-4 pt-2">
          <BucketComparisonBar
            onSelectBucket={(id) =>
              document.getElementById(`bucket-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }
          />
          <div className="space-y-3">
            {userBuckets.map((b) => (
              <div key={b.id} id={`bucket-${b.id}`}>
                <BucketSection bucket={b} positions={positions} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Header({ onRecalculate }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <LineChart size={22} className="text-primary" />
        <h2 className="text-xl font-bold text-text-primary">Performance</h2>
      </div>
      {onRecalculate && <RecalculateButton onRecalculate={onRecalculate} />}
    </div>
  )
}
