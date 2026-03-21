import { useState, useEffect } from 'react'
import { Menu, X, WifiOff } from 'lucide-react'
import Sidebar from './Sidebar'
import CommandPalette from './CommandPalette'
import OnboardingTour from './OnboardingTour'
import useOnlineStatus from '../hooks/useOnlineStatus'
import { authFetch } from '../hooks/useApi'

export default function Layout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const online = useOnlineStatus()
  const [showTour, setShowTour] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function checkOnboarding() {
      try {
        const res = await authFetch('/api/settings/onboarding/status')
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled && !data.tour_completed) {
          setShowTour(true)
        }
      } catch (e) {
        // ignore
      }
    }
    checkOnboarding()
    return () => { cancelled = true }
  }, [])

  return (
    <div className="min-h-screen bg-body">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-[60] focus:top-2 focus:left-2 focus:bg-primary focus:text-white focus:px-4 focus:py-2 focus:rounded-lg">
        Zum Inhalt springen
      </a>
      {/* Mobile Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={`
        fixed inset-y-0 left-0 z-50
        transform ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0
        transition-transform duration-200 ease-in-out
      `}>
        <Sidebar onNavigate={() => setSidebarOpen(false)} />
      </div>

      {/* Main */}
      <div className="md:ml-60">
        {/* Mobile Header */}
        <div className="md:hidden flex items-center gap-3 p-4 border-b border-border bg-card">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 rounded-lg hover:bg-card-alt transition-colors"
            aria-label="Menu öffnen"
          >
            <Menu size={20} className="text-text-primary" />
          </button>
          <span className="font-bold text-text-primary">OpenFolio</span>
        </div>

        {!online && (
          <div className="bg-warning/10 border-b border-warning/30 px-4 py-2 flex items-center gap-2 text-warning text-sm">
            <WifiOff size={14} />
            <span>Keine Internetverbindung — Daten könnten veraltet sein.</span>
          </div>
        )}

        <main id="main-content" className="p-4 md:p-6">
          {children}
        </main>
      </div>

      <CommandPalette />
      {showTour && <OnboardingTour onComplete={() => setShowTour(false)} />}
    </div>
  )
}
