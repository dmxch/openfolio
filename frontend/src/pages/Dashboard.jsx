import { useEffect } from 'react'
import { useApi, authFetch } from '../hooks/useApi'
import MarketClimate from '../components/MarketClimate'
import StockHeatmap from '../components/StockHeatmap'
import SectorRotation from '../components/SectorRotation'
import DisclaimerBanner from '../components/DisclaimerBanner'
import Skeleton from '../components/Skeleton'
import { RefreshCw } from 'lucide-react'

export default function Dashboard() {
  const { data: climate, loading, error, refetch } = useApi('/market/climate')

  // Mark market step as visited for onboarding
  useEffect(() => {
    authFetch('/api/settings/onboarding/step-complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: 'market' }),
    }).catch(() => {})
  }, [])

  if (loading) {
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-bold text-text-primary">Markt & Sektoren</h2>
        <Skeleton className="h-28" />
        <Skeleton className="h-[500px]" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-bold text-text-primary">Markt & Sektoren</h2>
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
          <span className="text-danger text-sm">Fehler beim Laden: {error}</span>
          <button
            onClick={refetch}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary/90 transition-colors"
          >
            <RefreshCw size={14} />
            Erneut laden
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-text-primary">Markt & Sektoren</h2>

      <MarketClimate data={climate} />

      <StockHeatmap />

      <SectorRotation />

      <DisclaimerBanner />
    </div>
  )
}
