import { useEffect, useState } from 'react'
import { LayoutGrid } from 'lucide-react'
import { authFetch } from '../hooks/useApi'

// Toggle "Aggregiert / Pro Bucket" + Tab-Bar mit Buckets.
//
// Props:
//   value: { mode: 'aggregated' | 'bucket', bucketId: string | null }
//   onChange: (newValue) => void
//
// Sichtbarkeit: nur wenn der User mind. 1 user-bucket hat. System-only-User
// (kein Onboarding genutzt) sehen die Komponente nicht.
//
// State-Persistenz: localStorage ('openfolio.bucketView')
export default function BucketTabBar({ value, onChange }) {
  const [buckets, setBuckets] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await authFetch('/api/portfolio/buckets')
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        // Anzeige-Reihenfolge: liquid_default zuerst, dann user-buckets nach sort_order
        const eligible = (data.buckets || []).filter(
          (b) =>
            !b.deleted_at &&
            (b.kind === 'user' || b.system_role === 'liquid_default'),
        )
        setBuckets(eligible)
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return null

  const userBuckets = buckets.filter((b) => b.kind === 'user')
  if (userBuckets.length === 0) return null

  const isAggregated = value.mode === 'aggregated'
  const activeId = value.bucketId

  function setMode(mode, bucketId = null) {
    const next = { mode, bucketId }
    onChange(next)
    try {
      localStorage.setItem('openfolio.bucketView', JSON.stringify(next))
    } catch {
      // ignore
    }
  }

  const tooManyTabs = buckets.length > 6

  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-3">
      <div className="flex items-center gap-2">
        <LayoutGrid size={14} className="text-text-muted" />
        <span className="text-xs text-text-secondary">Ansicht</span>
        <div className="ml-auto flex gap-1 p-1 bg-card-alt/50 rounded-md border border-border">
          <button
            onClick={() => setMode('aggregated')}
            className={`px-3 py-1 text-xs rounded transition-colors ${
              isAggregated
                ? 'bg-primary text-white'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            Aggregiert
          </button>
          <button
            onClick={() =>
              setMode(
                'bucket',
                value.bucketId || userBuckets[0]?.id || buckets[0]?.id,
              )
            }
            className={`px-3 py-1 text-xs rounded transition-colors ${
              !isAggregated
                ? 'bg-primary text-white'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            Pro Bucket
          </button>
        </div>
      </div>

      {!isAggregated && (
        <div
          className={`flex gap-1.5 ${tooManyTabs ? 'overflow-x-auto pb-1' : 'flex-wrap'}`}
        >
          {buckets.map((b) => {
            const isActive = b.id === activeId
            return (
              <button
                key={b.id}
                onClick={() => setMode('bucket', b.id)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border transition-colors whitespace-nowrap ${
                  isActive
                    ? 'border-primary bg-primary/10 text-text-primary'
                    : 'border-border text-text-muted hover:text-text-primary'
                }`}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: b.color || '#64748b' }}
                />
                {b.name}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// Helper: lese persistierten State (oder Default)
export function loadBucketView() {
  try {
    const raw = localStorage.getItem('openfolio.bucketView')
    if (!raw) return { mode: 'aggregated', bucketId: null }
    const parsed = JSON.parse(raw)
    if (parsed && (parsed.mode === 'aggregated' || parsed.mode === 'bucket')) {
      return parsed
    }
  } catch {
    // ignore
  }
  return { mode: 'aggregated', bucketId: null }
}
