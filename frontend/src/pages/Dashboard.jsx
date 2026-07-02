import { useEffect } from 'react'
import { useApi, authFetch } from '../hooks/useApi'
import useIsMobile from '../hooks/useIsMobile'
import MarketClimate from '../components/MarketClimate'
import ChMacroCard from '../components/ChMacroCard'
import CotMacroPanel from '../components/CotMacroPanel'
import UpcomingEarningsBanner from '../components/UpcomingEarningsBanner'
import PendingDividendsWidget from '../components/PendingDividendsWidget'
import DisclaimerBanner from '../components/DisclaimerBanner'
import Skeleton from '../components/Skeleton'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { formatNumber, formatDateTime } from '../lib/format'
import { RefreshCw } from 'lucide-react'

// combined_status -> Pill-Styling (green=bullish, yellow=neutral, red=bearish)
const PILL = {
  green: 'bg-success/10 text-success border-success/30',
  yellow: 'bg-warning/10 text-warning border-warning/30',
  red: 'bg-danger/10 text-danger border-danger/30',
}
const PILL_DOT = { green: '#45c08a', yellow: '#e0a64b', red: '#e8625a' }

function ClimatePill({ status, label, hint }) {
  if (!label) return null
  const cls = PILL[status] || PILL.yellow
  return (
    <span
      title={hint || undefined}
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-[7px] text-[12.5px] font-medium ${cls}`}
    >
      <span className="w-2 h-2 rounded-full" style={{ background: PILL_DOT[status] || PILL_DOT.yellow }} />
      {label}
    </span>
  )
}

// Heatmap-Farbe: gruen fuer positiv, rot fuer negativ, Alpha nach Betrag skaliert.
function heatColor(v) {
  if (v == null) return 'transparent'
  const a = Math.min(0.55, (Math.abs(v) / 10) * 0.55)
  return v >= 0 ? `rgba(69,192,138,${a})` : `rgba(232,98,90,${a})`
}

function HeatCell({ value, className = '' }) {
  if (value == null) {
    return <td className={`py-1.5 ${className}`}><div className="text-center text-text-faint text-[11.5px]">–</div></td>
  }
  return (
    <td className={`py-1.5 ${className}`}>
      <div
        className="rounded py-1 text-center font-mono text-[11.5px] tabular-nums text-text-primary"
        style={{ background: heatColor(value) }}
      >
        {value >= 0 ? '+' : ''}{formatNumber(value, 1)}%
      </div>
    </td>
  )
}

function SectorMomentum() {
  const { data, loading, error } = useApi('/market/sectors')
  const sectors = Array.isArray(data) ? data : []

  if (loading) {
    return (
      <Card className="p-[18px] animate-pulse">
        <div className="h-3 bg-card-2 rounded w-32 mb-4" />
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => <div key={i} className="h-7 bg-card-2 rounded" />)}
        </div>
      </Card>
    )
  }
  if (error || !sectors.length) return null

  return (
    <Card className="overflow-hidden flex flex-col">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <span className="w-[9px] h-[9px] rounded-[3px]" style={{ background: '#29c3b1' }} />
        <h3 className="text-sm font-semibold text-text-primary">Sektor-Momentum</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint">
              <th className="text-left pl-[18px] pr-3 py-[10px] font-medium">Sektor</th>
              <th className="text-center px-1.5 py-[10px] font-medium w-[68px]">1W</th>
              <th className="text-center px-1.5 py-[10px] font-medium w-[68px]">1M</th>
              <th className="text-center pl-1.5 pr-[18px] py-[10px] font-medium w-[76px]">3M</th>
            </tr>
          </thead>
          <tbody>
            {sectors.map((s) => (
              <tr key={s.etf} className="border-b border-border-row last:border-0">
                <td className="pl-[18px] pr-3 py-1.5 text-[12px] text-text-secondary truncate max-w-[150px]" title={s.sector}>
                  {s.sector}
                </td>
                <HeatCell value={s.perf_1w} className="px-1.5" />
                <HeatCell value={s.perf_1m} className="px-1.5" />
                <HeatCell value={s.perf_3m} className="pl-1.5 pr-[18px]" />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function Dashboard() {
  const isMobile = useIsMobile()
  const { data: climate, loading, error, refetch } = useApi('/market/climate')

  // Mark market step as visited for onboarding
  useEffect(() => {
    authFetch('/api/settings/onboarding/step-complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: 'market' }),
    }).catch(() => {})
  }, [])

  const updatedAt = climate?.macro?.updated_at
  const subtitle = updatedAt ? `Stand ${formatDateTime(updatedAt)}` : 'Markt-Klima, Earnings, Dividenden'

  const pill = (
    <ClimatePill status={climate?.combined_status} label={climate?.combined_label} hint={climate?.combined_hint} />
  )

  if (loading) {
    return (
      <div className="pb-10">
        <PageHeader title="Marktklima" subtitle="Markt-Klima, Earnings, Dividenden" />
        <div className="flex flex-col gap-[18px]">
          <div className="grid grid-cols-1 xl:grid-cols-[1.7fr_1fr] gap-[18px]">
            <Skeleton className="h-80 rounded-card" />
            <div className="grid grid-cols-2 gap-[14px]">
              {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-[88px] rounded-card" />)}
            </div>
          </div>
          <Skeleton className="h-28 rounded-card" />
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-[18px]">
            {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-72 rounded-card" />)}
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="pb-10">
        <PageHeader title="Marktklima" subtitle="Markt-Klima, Earnings, Dividenden" />
        <div className="rounded-card border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
          <span className="text-danger text-sm">Fehler beim Laden: {error}</span>
          <Button variant="primary" icon={RefreshCw} onClick={refetch}>Erneut laden</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="pb-10">
      <PageHeader title="Marktklima" subtitle={subtitle} actions={pill} />

      <div className="flex flex-col gap-[14px] md:gap-[18px]">
        <MarketClimate data={climate} />

        <UpcomingEarningsBanner />

        {/* Makro-Detail-Panels nur auf Desktop — bedingt gemountet (H11),
            damit sie auf Mobile nicht trotz CSS-hidden fetchen. */}
        {!isMobile && (
          <div className="hidden md:grid grid-cols-1 xl:grid-cols-[1fr_1.2fr_1fr] gap-[18px]">
            <CotMacroPanel />
            <SectorMomentum />
            <ChMacroCard />
          </div>
        )}

        <PendingDividendsWidget />

        <DisclaimerBanner />
      </div>
    </div>
  )
}
