import { useEffect, useState } from 'react'
import { GitCompare, Loader2, AlertTriangle } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { formatDate } from '../lib/format'

const PERIOD_OPTIONS = [
  { value: '30d', label: '30 Tage' },
  { value: '90d', label: '90 Tage' },
  { value: '180d', label: '180 Tage' },
  { value: '1y', label: '1 Jahr' },
  { value: 'all', label: 'Gesamt' },
]

function colorFor(r) {
  if (r == null) return 'bg-card-alt text-text-muted'
  if (r >= 0.85) return 'bg-red-500/30 text-red-200'
  if (r >= 0.5) return 'bg-orange-400/25 text-orange-200'
  if (r >= 0.2) return 'bg-yellow-300/20 text-yellow-100'
  if (r > -0.2) return 'bg-card-alt text-text-secondary'
  if (r > -0.5) return 'bg-emerald-400/15 text-emerald-100'
  return 'bg-emerald-500/30 text-emerald-100'
}

export default function BucketCorrelationCard() {
  const [period, setPeriod] = useState('90d')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await authFetch(`/api/portfolio/buckets/correlation-matrix?period=${period}`)
        if (!res.ok) {
          const body = await res.json().catch(() => null)
          throw new Error(body?.detail || 'Korrelationen nicht verfügbar')
        }
        const j = await res.json()
        if (!cancelled) setData(j)
      } catch (e) {
        if (!cancelled) {
          setError(e.message)
          setData(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [period])

  return (
    <section className="bg-card border border-border rounded-card p-[18px] space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <GitCompare size={16} className="text-primary" /> Bucket-Korrelationen
          </h3>
          <p className="text-xs text-text-muted mt-1">
            Tägliche Returns aus bucket_snapshots, cashflow-bereinigt. PE,
            Immobilien und Vorsorge sind ausgeschlossen.
          </p>
        </div>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="bg-surface border border-border-2 rounded-lg px-2 py-1 text-xs text-text-secondary focus:outline-none focus:border-primary"
          aria-label="Zeitraum"
        >
          {PERIOD_OPTIONS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-text-muted text-xs">
          <Loader2 size={12} className="animate-spin" /> Lade Korrelationen...
        </div>
      )}

      {error && !loading && (
        <div className="flex items-start gap-2 text-text-muted text-xs">
          <AlertTriangle size={12} className="text-warning mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && data && (
        <>
          <div className="overflow-x-auto">
            <table className="text-xs border-collapse">
              <thead>
                <tr>
                  <th className="text-left px-2 py-1 text-text-muted font-medium"></th>
                  {data.buckets.map((b) => (
                    <th
                      key={b.id}
                      className="px-2 py-1 text-text-secondary font-medium text-center"
                      style={{ color: b.color || undefined }}
                      title={b.name}
                    >
                      {b.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.buckets.map((b, i) => (
                  <tr key={b.id}>
                    <td
                      className="px-2 py-1 text-text-secondary font-medium whitespace-nowrap"
                      style={{ color: b.color || undefined }}
                    >
                      {b.name}
                    </td>
                    {data.matrix[i].map((v, j) => (
                      <td
                        key={j}
                        className={`px-2 py-1 text-center font-mono tabular-nums ${colorFor(v)}`}
                      >
                        {v == null ? '–' : v.toFixed(2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-[11px] text-text-muted">
            <span>
              {data.observations} gemeinsame Handelstage, Stand{' '}
              {formatDate(data.as_of)}
            </span>
            {data.warnings?.length > 0 && (
              <span className="text-warning">
                {data.warnings.length} Hinweise
              </span>
            )}
          </div>

          {data.high_correlations?.length > 0 && (
            <div className="border-t border-border-2 pt-2 space-y-1">
              <div className="text-xs font-medium text-text-secondary">
                Auffällige Paare (|r| ≥ 0.7)
              </div>
              <ul className="space-y-0.5">
                {data.high_correlations.slice(0, 5).map((p) => (
                  <li
                    key={`${p.bucket_a_id}-${p.bucket_b_id}`}
                    className="text-xs text-text-secondary flex items-center justify-between gap-3"
                  >
                    <span className="truncate">
                      {p.bucket_a_name} ↔ {p.bucket_b_name}
                    </span>
                    <span className="font-mono tabular-nums">
                      r = {p.correlation.toFixed(2)} · {p.interpretation}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  )
}
