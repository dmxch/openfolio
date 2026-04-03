import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { authFetch } from '../hooks/useApi'
import { CheckCircle2, Circle, X, ChevronRight } from 'lucide-react'

const CHECKLIST_ITEMS = [
  {
    key: 'import',
    label: 'Transaktionen importieren',
    description: 'Importiere deine Trades per CSV für lückenlose Auswertungen.',
    route: '/transactions',
  },
  {
    key: 'first_position',
    label: 'Erste Position erfassen',
    description: 'Füge eine Aktie oder einen ETF zu deinem Portfolio hinzu.',
    route: '/portfolio',
  },
  {
    key: 'cash_account',
    label: 'Kassenkonto anlegen',
    description: 'Erfasse dein Bargeld/Kontoguthaben als Cash-Position.',
    route: '/portfolio?action=add-cash',
  },
  {
    key: 'stop_loss',
    label: 'Stop-Loss setzen',
    description: 'Hinterlege Stop-Loss-Kurse für deine Positionen.',
    route: '/portfolio',
  },
  {
    key: 'watchlist',
    label: 'Watchlist pflegen',
    description: 'Füge Aktien zur Watchlist hinzu und beobachte den Setup-Score.',
    route: '/analysis',
  },
  {
    key: 'market',
    label: 'Marktüberblick ansehen',
    description: 'Prüfe Makro-Gate, VIX und Sektor-Rotation.',
    route: '/',
  },
  {
    key: 'diversify',
    label: 'Diversifizieren',
    description: 'Ergänze Crypto, Rohstoffe oder Vorsorge.',
    route: '/portfolio',
  },
  {
    key: 'profile',
    label: '2FA aktivieren',
    description: 'Schütze dein Konto mit Zwei-Faktor-Authentifizierung.',
    route: '/settings',
  },
]

export default function OnboardingChecklist() {
  const [status, setStatus] = useState(null)
  const [hidden, setHidden] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    async function fetchStatus() {
      try {
        const res = await authFetch('/api/settings/onboarding/status')
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled) {
          if (data.checklist_hidden) {
            setHidden(true)
          }
          setStatus(data)
        }
      } catch (e) {
        // ignore
      }
    }
    fetchStatus()
    return () => { cancelled = true }
  }, [])

  if (hidden || !status || status.checklist_hidden) return null

  const steps = status.steps || {}
  const doneCount = CHECKLIST_ITEMS.filter(item => steps[item.key]).length
  const totalCount = CHECKLIST_ITEMS.length
  const allDone = doneCount === totalCount
  const progressPct = Math.round((doneCount / totalCount) * 100)

  const hideChecklist = async () => {
    setHidden(true)
    try {
      await authFetch('/api/settings/onboarding/hide-checklist', { method: 'POST' })
    } catch (e) {
      // ignore
    }
  }

  return (
    <div className="bg-card border border-border rounded-xl p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">
            {allDone ? 'Einrichtung abgeschlossen!' : 'Erste Schritte'}
          </h3>
          <p className="text-sm text-text-muted mt-0.5">
            {doneCount} von {totalCount} erledigt
          </p>
        </div>
        <button
          onClick={hideChecklist}
          className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors"
          title="Checkliste ausblenden"
        >
          <X size={16} />
        </button>
      </div>

      {/* Progress bar */}
      <div className="w-full h-2 bg-border rounded-full mb-5 overflow-hidden">
        <div
          className="h-full bg-primary rounded-full transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Timeline */}
      <div className="space-y-1">
        {CHECKLIST_ITEMS.map((item, idx) => {
          const done = steps[item.key]
          return (
            <button
              key={item.key}
              onClick={() => { if (!done) navigate(item.route) }}
              disabled={done}
              className={`w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                done
                  ? 'opacity-60 cursor-default'
                  : 'hover:bg-card-alt cursor-pointer'
              }`}
            >
              <div className="mt-0.5 flex-shrink-0">
                {done ? (
                  <CheckCircle2 size={18} className="text-primary" />
                ) : (
                  <Circle size={18} className="text-text-muted" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <span className={`text-sm font-medium ${done ? 'text-text-muted line-through' : 'text-text-primary'}`}>
                  {item.label}
                </span>
                {!done && (
                  <p className="text-xs text-text-secondary mt-0.5">{item.description}</p>
                )}
              </div>
              {!done && (
                <ChevronRight size={14} className="text-text-muted mt-1 flex-shrink-0" />
              )}
            </button>
          )
        })}
      </div>

      {allDone && (
        <div className="mt-4 pt-3 border-t border-border">
          <button
            onClick={hideChecklist}
            className="w-full text-center text-sm text-primary hover:text-primary/80 transition-colors font-medium"
          >
            Checkliste ausblenden
          </button>
        </div>
      )}
    </div>
  )
}
