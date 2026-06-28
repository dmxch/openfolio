import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { WifiOff } from 'lucide-react'
import Sidebar from './Sidebar'
import MobileNav from './MobileNav'
import CommandPalette from './CommandPalette'
import OnboardingTour from './OnboardingTour'
import BucketsOnboardingModal from './BucketsOnboardingModal'
import useOnlineStatus from '../hooks/useOnlineStatus'
import { authFetch } from '../hooks/useApi'

export default function Layout({ children }) {
  const online = useOnlineStatus()
  const [showTour, setShowTour] = useState(false)
  const [bucketsModalData, setBucketsModalData] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    async function checkOnboarding() {
      try {
        const res = await authFetch('/api/settings/onboarding/status')
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled && !data.tour_completed) setShowTour(true)
      } catch (e) {
        // ignore
      }
    }
    async function checkBucketsModal() {
      try {
        const res = await authFetch('/api/portfolio/buckets')
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled && data.show_onboarding_modal) setBucketsModalData(data)
      } catch (e) {
        // ignore
      }
    }
    checkOnboarding()
    checkBucketsModal()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="min-h-screen bg-body">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-[60] focus:top-2 focus:left-2 focus:bg-primary focus:text-white focus:px-4 focus:py-2 focus:rounded-lg">
        Zum Inhalt springen
      </a>

      {/* Sidebar — nur Desktop */}
      <div className="hidden md:block fixed inset-y-0 left-0 z-50">
        <Sidebar />
      </div>

      {/* Main */}
      <div className="md:ml-60">
        {!online && (
          <div className="bg-warning/10 border-b border-warning/30 px-4 py-2 flex items-center gap-2 text-warning text-sm">
            <WifiOff size={14} />
            <span>Keine Internetverbindung — Daten könnten veraltet sein.</span>
          </div>
        )}

        {/* Mobil: unten Platz fuer die Bottom-Tab-Bar (inkl. iOS Safe-Area) */}
        <main id="main-content" className="p-4 md:p-6 pb-[calc(76px+env(safe-area-inset-bottom))] md:pb-6">
          {children}
        </main>
      </div>

      {/* Bottom-Tab-Bar — nur Mobil */}
      <MobileNav />

      <CommandPalette />
      {showTour && <OnboardingTour onComplete={() => setShowTour(false)} />}
      {bucketsModalData && (
        <BucketsOnboardingModal
          data={bucketsModalData}
          onClose={() => setBucketsModalData(null)}
          onNavigate={() => navigate('/settings?tab=buckets')}
        />
      )}
    </div>
  )
}
