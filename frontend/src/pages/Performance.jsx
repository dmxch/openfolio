import { useEffect, useState, useCallback } from 'react'
import { useApi } from '../hooks/useApi'
import { usePortfolioData } from '../contexts/DataContext'
import { formatCHF, formatPct, formatNumber, formatTime, pnlColor } from '../lib/format'
import Skeleton from '../components/Skeleton'
import RecalculateButton from '../components/RecalculateButton'
import PageHeader from '../components/ui/PageHeader'
import StatTile from '../components/ui/StatTile'
import G from '../components/GlossarTooltip'
import PerformanceCard from '../components/PerformanceCard'
import PerformanceChart, { PERIODS, BASE_BENCHMARKS } from '../components/PerformanceChart'
import FactorExposureCard from '../components/FactorExposureCard'
import RiskMetricsPanel from '../components/RiskMetricsPanel'
import AlphaValue from '../components/AlphaValue'
import AllocationDonutCard from '../components/AllocationDonutCard'
import TopConcentrationCard from '../components/TopConcentrationCard'
import ReturnContributionCard from '../components/ReturnContributionCard'
import RollingDrawdownCard from '../components/RollingDrawdownCard'
import AllocationCharts from '../components/AllocationCharts'
import HhiCard from '../components/HhiCard'
import EtfCountryLookthroughCard from '../components/EtfCountryLookthroughCard'
import RebalancingCard from '../components/RebalancingCard'
import PositionRebalancingCard from '../components/PositionRebalancingCard'
import TradeJournalCard from '../components/TradeJournalCard'
import DividendYocCard from '../components/DividendYocCard'
import DividendForecastCard from '../components/DividendForecastCard'
import NetWorthCard from '../components/NetWorthCard'
import FireProjectionCard from '../components/FireProjectionCard'
import MonthlyHeatmap from '../components/MonthlyHeatmap'
import TopMovers from '../components/TopMovers'
import RealizedGainsTable from '../components/RealizedGainsTable'
import FeeSummary from '../components/FeeSummary'
import BucketComparisonBar from '../components/BucketComparisonBar'
import BucketSection from '../components/BucketSection'
import BucketCorrelationCard from '../components/BucketCorrelationCard'

/**
 * Performance-Seite — buendelt alle Renditen-/Risiko-Auswertungen in fuenf
 * Sub-Tabs (Uebersicht / Rendite / Risiko / Allokation / Cashflow). Pro Tab wird
 * nur der jeweilige Widget-Satz gemountet (lazy). Datenanbindung der Karten
 * bleibt unveraendert — die Seite verteilt sie nur neu und steuert die
 * Equity-Kurve via gemeinsamer Period-/Benchmark-Wahl (Sub-Tab-Leiste + Header).
 */

const TABS = [
  { key: 'uebersicht', label: 'Übersicht' },
  { key: 'rendite', label: 'Rendite' },
  { key: 'risiko', label: 'Risiko' },
  { key: 'allokation', label: 'Allokation' },
  { key: 'cashflow', label: 'Cashflow' },
]

// Verhältniszahl (Sharpe/Sortino/…) mit 2 Nachkommastellen.
function ratio(v) {
  return v == null ? '–' : formatNumber(v, 2)
}

export default function Performance() {
  const { refetch: refetchGlobal } = usePortfolioData()
  const { data: summary, loading, error, refetch: refetchSummary } = useApi('/portfolio/summary')
  const { data: reData } = useApi('/properties')
  // Abhaengige Endpoints erst nach summary laden (H-7: keine Parallel-Last)
  const { data: dailyChange, refetch: refetchDaily } = useApi('/portfolio/daily-change', { skip: !summary })
  const { data: totalReturn, refetch: refetchTotalReturn } = useApi('/portfolio/total-return', { skip: !summary })
  const { data: monthlyReturns, loading: monthlyLoading, refetch: refetchMonthly } = useApi('/portfolio/monthly-returns', { skip: !summary })
  const { data: bucketList } = useApi('/portfolio/buckets', { skip: !summary })
  const { data: bucketAlloc } = useApi('/portfolio/buckets/allocations', { skip: !summary })
  // Hero-Kacheln (Uebersicht) — gleiche Endpoints wie die jeweiligen Karten.
  const { data: netWorth } = useApi('/analysis/net-worth', { skip: !summary })
  const { data: riskHero } = useApi('/portfolio/risk-metrics', { skip: !summary })
  const { data: factorHero } = useApi('/analysis/factor-decomposition', { skip: !summary })

  const [tab, setTab] = useState('uebersicht')
  // Gemeinsame Steuerung der Equity-Kurve (Sub-Tab-Leiste = Zeitraum, Header = Benchmark)
  const [period, setPeriod] = useState(PERIODS[4]) // 1Y default
  const [benchmark, setBenchmark] = useState('^GSPC')

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
  // (Allokations-Alert). Auf den passenden Tab springen und scrollen.
  useEffect(() => {
    if (loading) return
    const hash = window.location.hash
    if (!hash) return
    if (hash === '#allocation-charts') setTab('allokation')
    const t = setTimeout(() => {
      document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 250)
    return () => clearTimeout(t)
  }, [loading])

  const subtitle = dailyChange?.timestamp
    ? `Stand ${formatTime(dailyChange.timestamp)}`
    : 'Rendite-, Risiko- & Allokations-Cockpit'

  const showChartControls = tab === 'uebersicht' || tab === 'rendite'

  const headerActions = (
    <>
      <RecalculateButton onRecalculate={handleRecalculated} />
      {showChartControls && (
        <select
          value={benchmark}
          onChange={(e) => setBenchmark(e.target.value)}
          aria-label="Benchmark"
          className="bg-surface border border-border rounded-lg px-3 py-[7px] text-[12.5px] text-text-secondary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
        >
          {BASE_BENCHMARKS.map((b) => (
            <option key={b.value} value={b.value}>{b.label || 'Kein Benchmark'}</option>
          ))}
        </select>
      )}
    </>
  )

  if (loading) {
    return (
      <div className="pb-10">
        <PageHeader title="Performance" subtitle="Rendite-, Risiko- & Allokations-Cockpit" />
        <div className="flex flex-col gap-[18px]">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-[14px]">
            {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-[92px] rounded-card" />)}
          </div>
          <Skeleton className="h-96 rounded-card" />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
            <Skeleton className="h-64 rounded-card" />
            <Skeleton className="h-64 rounded-card" />
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="pb-10">
        <PageHeader title="Performance" subtitle="Rendite-, Risiko- & Allokations-Cockpit" />
        <div className="rounded-card border border-danger/30 bg-danger/10 p-6 text-danger text-sm">
          Fehler beim Laden: {error}
        </div>
      </div>
    )
  }

  const realEstateEquity = reData?.total_equity_chf || 0
  const positions = summary?.positions || []
  const allBuckets = bucketList?.buckets || (Array.isArray(bucketList) ? bucketList : [])
  const userBuckets = allBuckets.filter((b) => b?.kind === 'user' && !b.deleted_at)
  const bucketAllocMap = {}
  for (const item of bucketAlloc?.items || []) bucketAllocMap[item.bucket_id] = item

  // ---- Hero-Kacheln (Uebersicht) ----
  const netWorthValue = netWorth?.net_worth_chf ?? (summary.total_market_value_chf + realEstateEquity)
  const twr = riskHero?.annualized_return_pct
  const alphaPct = factorHero?.alpha?.annualized_pct
  const sharpe = riskHero?.sharpe_ratio
  const maxDd = riskHero?.max_drawdown_pct
  const benchPa = riskHero?.benchmark_annualized_return_pct

  const heroTiles = [
    {
      label: 'Netto-Vermögen',
      value: formatCHF(netWorthValue),
      tone: 'default',
      sub: realEstateEquity > 0 ? 'inkl. Vorsorge & Immobilien' : null,
    },
    {
      label: <G term="TWR">Rendite p.a. (TWR)</G>,
      value: twr == null ? '–' : formatPct(twr),
      tone: twr == null ? 'default' : twr >= 0 ? 'success' : 'danger',
      sub: 'zeitgewichtet',
    },
    {
      label: <G term="Alpha">vs. Benchmark (Alpha p.a.)</G>,
      value: <AlphaValue alpha={factorHero?.alpha} />,
      tone: 'default',
      sub: benchPa != null ? `Benchmark ${formatPct(benchPa)} p.a.` : 'faktor-bereinigt',
    },
    {
      label: <G term="Sharpe Ratio">Sharpe Ratio</G>,
      value: ratio(sharpe),
      tone: 'primary',
      sub: riskHero?.risk_free_rate_pct != null ? `risk-free ${riskHero.risk_free_rate_pct}%` : null,
    },
    {
      label: <G term="Max Drawdown">Max Drawdown</G>,
      value: maxDd == null ? '–' : `-${formatNumber(maxDd, 2)}%`,
      tone: maxDd == null ? 'default' : 'danger',
      sub: 'groesster Rueckgang',
    },
  ]

  // Risiko-Tab StatTiles (8, analog Mockup): Alpha/Beta aus der Faktor-Regression,
  // Rest aus risk-metrics (inkl. neu exponiertem Tracking Error).
  const riskTiles = [
    {
      label: <G term="Alpha">Alpha p.a.</G>,
      value: <AlphaValue alpha={factorHero?.alpha} />,
      tone: 'default',
    },
    { label: <G term="Beta">Beta (Markt)</G>, value: ratio(factorHero?.factors?.SPY?.beta), tone: 'default' },
    { label: <G term="Sharpe Ratio">Sharpe</G>, value: ratio(riskHero?.sharpe_ratio), tone: 'primary' },
    { label: <G term="Sortino Ratio">Sortino</G>, value: ratio(riskHero?.sortino_ratio), tone: 'primary' },
    { label: <G term="Calmar Ratio">Calmar</G>, value: ratio(riskHero?.calmar_ratio), tone: 'primary' },
    { label: 'Volatilität p.a.', value: riskHero?.volatility_pct == null ? '–' : `${formatNumber(riskHero.volatility_pct, 2)}%`, tone: 'bright' },
    {
      label: <G term="Max Drawdown">Max Drawdown</G>,
      value: riskHero?.max_drawdown_pct == null ? '–' : `-${formatNumber(riskHero.max_drawdown_pct, 2)}%`,
      tone: riskHero?.max_drawdown_pct == null ? 'default' : 'danger',
    },
    { label: <G term="Tracking Error">Tracking Error</G>, value: riskHero?.tracking_error_pct == null ? '–' : `${formatNumber(riskHero.tracking_error_pct, 2)}%`, tone: 'bright' },
  ]

  // Mobile-Kennzahlen-Raster (2 Spalten) — dieselben realen Felder wie Desktop.
  // Beta = Markt-Beta aus der Faktor-Regression (factors.SPY); kein separater
  // Portfolio-Beta-Wert im Backend.
  const betaMarket = factorHero?.factors?.SPY?.beta
  const mobileMetrics = [
    {
      label: <G term="Alpha">Alpha p.a.</G>,
      value: <AlphaValue alpha={factorHero?.alpha} />,
      tone: 'default',
    },
    { label: <G term="Sharpe Ratio">Sharpe</G>, value: ratio(sharpe), tone: 'primary' },
    {
      label: 'Volatilität p.a.',
      value: riskHero?.volatility_pct == null ? '–' : `${formatNumber(riskHero.volatility_pct, 2)}%`,
      tone: 'bright',
    },
    {
      label: <G term="Max Drawdown">Max Drawdown</G>,
      value: maxDd == null ? '–' : `-${formatNumber(maxDd, 2)}%`,
      tone: maxDd == null ? 'default' : 'danger',
    },
    { label: 'Beta (Markt)', value: betaMarket == null ? '–' : formatNumber(betaMarket, 2), tone: 'default' },
    { label: 'Calmar', value: ratio(riskHero?.calmar_ratio), tone: 'primary' },
  ]

  return (
    <div className="pb-10">
      <PageHeader title="Performance" subtitle={subtitle} actions={headerActions} />

      {/* ============ DESKTOP (>=md): unveraenderte 5-Tab-Ansicht ============ */}
      <div className="hidden md:block">

      {/* Sticky Sub-Tab-Leiste */}
      <div className="sticky top-[64px] z-20 -mt-1 mb-[18px] flex items-center justify-between gap-4 border-b border-border-soft bg-body/[0.86] backdrop-blur-md">
        <div className="flex items-center gap-5">
          {TABS.map((t) => {
            const on = t.key === tab
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`relative pt-1 pb-2.5 text-[13px] font-medium transition-colors ${
                  on ? 'text-text-primary' : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                {t.label}
                {on && <span className="absolute left-0 right-0 -bottom-px h-0.5 rounded-full bg-primary" />}
              </button>
            )
          })}
        </div>
        {showChartControls && (
          <div className="flex rounded-lg border border-border-2 bg-surface overflow-hidden mb-1.5">
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
        )}
      </div>

      {/* ---------------- ÜBERSICHT ---------------- */}
      {tab === 'uebersicht' && (
        <div className="flex flex-col gap-[18px]">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-[14px]">
            {heroTiles.map((t, i) => <StatTile key={i} {...t} />)}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[2fr_1fr] gap-[18px]">
            <PerformanceChart
              height={260}
              hideControls
              period={period}
              onPeriodChange={setPeriod}
              benchmarkValue={benchmark}
              onBenchmarkChange={setBenchmark}
            />
            <RiskMetricsPanel />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-[18px]">
            <AllocationDonutCard />
            <FactorExposureCard />
            <TopConcentrationCard variant="compact" />
          </div>

          {userBuckets.length > 0 && (
            <div className="flex flex-col gap-[18px] pt-1">
              <BucketComparisonBar
                onSelectBucket={(id) =>
                  document.getElementById(`bucket-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }
              />
              <div className="flex flex-col gap-3">
                {userBuckets.map((b) => (
                  <div key={b.id} id={`bucket-${b.id}`}>
                    <BucketSection bucket={b} positions={positions} weightPct={bucketAllocMap[b.id]?.pct} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ---------------- RENDITE ---------------- */}
      {tab === 'rendite' && (
        <div className="flex flex-col gap-[18px]">
          <PerformanceCard
            summary={summary}
            realEstateEquity={realEstateEquity}
            dailyChange={dailyChange}
            totalReturn={totalReturn}
          />
          <PerformanceChart
            height={360}
            hideControls
            period={period}
            onPeriodChange={setPeriod}
            benchmarkValue={benchmark}
            onBenchmarkChange={setBenchmark}
          />
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.4fr] gap-[18px]">
            <ReturnContributionCard />
            <MonthlyHeatmap data={monthlyReturns} loading={monthlyLoading} bucketMode={false} scope="Gesamtportfolio" />
          </div>
          <TopMovers positions={positions} />
          <RealizedGainsTable />
        </div>
      )}

      {/* ---------------- RISIKO ---------------- */}
      {tab === 'risiko' && (
        <div className="flex flex-col gap-[18px]">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-[14px]">
            {riskTiles.map((t, i) => <StatTile key={i} {...t} />)}
          </div>
          <RollingDrawdownCard />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
            <FactorExposureCard />
            <TopConcentrationCard variant="wide" />
          </div>
          <BucketCorrelationCard />
        </div>
      )}

      {/* ---------------- ALLOKATION ---------------- */}
      {tab === 'allokation' && (
        <div className="flex flex-col gap-[18px]">
          <div id="allocation-charts">
            <AllocationCharts allocations={summary?.allocations} realEstateEquity={realEstateEquity} positions={positions} />
          </div>
          <EtfCountryLookthroughCard />
          <NetWorthCard />
        </div>
      )}

      {/* ---------------- CASHFLOW ---------------- */}
      {tab === 'cashflow' && (
        <div className="flex flex-col gap-[18px]">
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
            <DividendForecastCard />
            <DividendYocCard />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-[18px]">
            <FireProjectionCard />
            <RebalancingCard />
          </div>
          <PositionRebalancingCard />
          <TradeJournalCard />
          <FeeSummary />
        </div>
      )}

      </div>{/* /Desktop */}

      {/* ============ MOBILE (<md): kompakte Single-Scroll-Ansicht ============ */}
      <div className="md:hidden flex flex-col gap-[14px]">
        {/* 1) Rendite-Hero — TWR-Headline + Benchmark + Perioden-Control */}
        <div className="bg-card border border-border rounded-card p-[18px]">
          <p className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label">
            Rendite p.a. (TWR)
          </p>
          <p
            className={`text-[34px] leading-none font-mono font-semibold tabular-nums mt-2 ${
              twr == null ? 'text-text-primary' : pnlColor(twr)
            }`}
          >
            {twr == null ? '–' : formatPct(twr)}
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {benchPa != null && (
              <span className="text-text-muted">
                vs. {riskHero?.benchmark || 'Benchmark'}:{' '}
                <span className="font-mono tabular-nums text-text-secondary">{formatPct(benchPa)}</span> p.a.
              </span>
            )}
            {alphaPct != null && (
              <span className="font-mono tabular-nums font-medium text-text-muted">
                Alpha <AlphaValue alpha={factorHero?.alpha} />
              </span>
            )}
          </div>
          {/* Perioden-Segment-Control (steuert die Equity-Kurve darunter) */}
          <div className="mt-3.5 grid grid-cols-6 gap-1">
            {PERIODS.map((p) => {
              const on = period.label === p.label
              return (
                <button
                  key={p.label}
                  onClick={() => setPeriod(p)}
                  className={`py-1.5 rounded-lg border font-mono text-[11px] tracking-[0.03em] transition-colors ${
                    on
                      ? 'bg-active-tint text-text-bright border-border-active'
                      : 'bg-surface text-text-muted border-border-2 hover:text-text-primary'
                  }`}
                >
                  {p.label}
                </button>
              )
            })}
          </div>
        </div>

        {/* Equity-Kurve (klein) — Zeitraum via Hero-Control, Benchmark via Header */}
        <PerformanceChart
          height={190}
          hideControls
          period={period}
          onPeriodChange={setPeriod}
          benchmarkValue={benchmark}
          onBenchmarkChange={setBenchmark}
        />

        {/* 2) Kennzahlen-Raster (Alpha/Sharpe/Volatilität/Max-DD/Beta/Calmar) */}
        <div className="grid grid-cols-2 gap-[14px]">
          {mobileMetrics.map((t, i) => <StatTile key={i} {...t} />)}
        </div>

        {/* 3) Buckets — reale YTD-/Wert-Daten je Bucket (Mobile: Karten-Stapel) */}
        {userBuckets.length > 0 && <BucketComparisonBar layout="cards" />}
      </div>
    </div>
  )
}
