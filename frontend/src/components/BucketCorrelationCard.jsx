import { Fragment, useEffect, useState } from 'react'
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

// Heatmap-Zelle: positive Korrelation -> primary (blau) getoent, negative ->
// success (gruen) getoent, Intensitaet nach |r|; Diagonale neutral. Die RGB-Werte
// spiegeln die Tokens primary (#5b8def) / success (#45c08a) — kontinuierliches
// Alpha braucht inline-rgba (wie Chart-Farben), das ist kein statisches UI-Chrome.
const PRIMARY_RGB = '91,141,239'
const SUCCESS_RGB = '69,192,138'
const CELL = 'h-[34px] rounded-[5px] flex items-center justify-center font-mono text-[11.5px] tabular-nums'

function Cell({ v, diag }) {
  if (v == null) return <div className={`${CELL} bg-card-2 text-text-muted`}>–</div>
  if (diag) return <div className={`${CELL} bg-border-2 text-text-muted`}>{v.toFixed(2)}</div>
  const a = Math.min(Math.abs(v) * 0.55, 1)
  const rgb = v >= 0 ? PRIMARY_RGB : SUCCESS_RGB
  const strong = Math.abs(v) > 0.55
  return (
    <div
      className={`${CELL} ${strong ? 'text-text-primary' : 'text-text-bright'}`}
      style={{ background: `rgba(${rgb},${a.toFixed(2)})` }}
    >
      {(v >= 0 ? '' : '−') + Math.abs(v).toFixed(2)}
    </div>
  )
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

  const n = data?.buckets?.length || 0

  return (
    <section className="bg-card border border-border rounded-card p-[18px]">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <GitCompare size={16} className="text-primary" /> Bucket-Korrelationsmatrix
          </h3>
          <p className="text-xs text-text-muted mt-1">
            Rendite-Korrelation zwischen den Segmenten · tiefer = mehr Diversifikation
          </p>
        </div>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="bg-surface border border-border-2 rounded-lg px-2 py-1 text-xs text-text-secondary focus:outline-none focus:border-primary shrink-0"
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

      {!loading && !error && data && n > 0 && (
        <>
          <div className="overflow-x-auto">
            <div
              className="grid gap-[5px] min-w-[420px] max-w-[560px]"
              style={{ gridTemplateColumns: `80px repeat(${n}, minmax(0, 1fr))` }}
            >
              {/* Kopfzeile: leere Ecke + Spaltenlabels */}
              <span />
              {data.buckets.map((b) => (
                <span
                  key={b.id}
                  className="font-mono text-[10.5px] text-text-muted text-center self-end pb-1 truncate"
                  title={b.name}
                >
                  {b.name}
                </span>
              ))}
              {/* Datenzeilen: Zeilenlabel + Zellen */}
              {data.buckets.map((b, i) => (
                <Fragment key={b.id}>
                  <span
                    className="font-mono text-[11px] text-text-secondary flex items-center truncate"
                    title={b.name}
                  >
                    {b.name}
                  </span>
                  {data.matrix[i].map((v, j) => (
                    <Cell key={j} v={v} diag={i === j} />
                  ))}
                </Fragment>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 text-[11px] text-text-muted mt-3">
            <span className="truncate">
              {data.observations} gemeinsame Handelstage · Stand {formatDate(data.as_of)} · PE/Immobilien/Vorsorge ausgeschlossen
            </span>
            {data.warnings?.length > 0 && (
              <span className="text-warning shrink-0">{data.warnings.length} Hinweise</span>
            )}
          </div>

          {data.high_correlations?.length > 0 && (
            <div className="border-t border-border-2 pt-2.5 mt-2.5 space-y-1">
              <div className="text-xs font-medium text-text-secondary">Auffällige Paare (|r| ≥ 0.7)</div>
              <ul className="space-y-0.5">
                {data.high_correlations.slice(0, 5).map((p) => (
                  <li
                    key={`${p.bucket_a_id}-${p.bucket_b_id}`}
                    className="text-xs text-text-secondary flex items-center justify-between gap-3"
                  >
                    <span className="truncate">
                      {p.bucket_a_name} ↔ {p.bucket_b_name}
                    </span>
                    <span className="font-mono tabular-nums shrink-0">
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
