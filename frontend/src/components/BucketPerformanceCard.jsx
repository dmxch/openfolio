import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, FolderTree } from 'lucide-react'
import { formatCHF, formatPct, pnlColor } from '../lib/format'
import { authFetch } from '../hooks/useApi'

// Performance-Karte fuer den Pro-Bucket-Modus.
// Zeigt Bucket-spezifische Werte aus /buckets/{id}/summary +
// /buckets/{id}/benchmark-comparison?period=ytd, statt der globalen
// PerformanceCard.
export default function BucketPerformanceCard({ bucketId }) {
  const [summary, setSummary] = useState(null)
  const [benchmark, setBenchmark] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!bucketId) {
      setSummary(null)
      setBenchmark(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    Promise.all([
      authFetch(`/api/portfolio/buckets/${bucketId}/summary`).then((r) =>
        r.ok ? r.json() : null,
      ),
      authFetch(
        `/api/portfolio/buckets/${bucketId}/benchmark-comparison?period=ytd`,
      ).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([s, b]) => {
        if (cancelled) return
        setSummary(s)
        setBenchmark(b)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [bucketId])

  if (loading) {
    return (
      <div className="rounded-lg border border-border/50 p-5 animate-pulse">
        <div className="h-4 bg-card-alt rounded w-32 mb-3" />
        <div className="h-8 bg-card-alt rounded w-40" />
      </div>
    )
  }
  if (!summary) return null

  const value = summary.total_value_chf || 0
  const cost = summary.cost_basis_chf || 0
  const pnl = summary.unrealized_pnl_chf || 0
  const pnlPct = summary.unrealized_pnl_pct || 0
  const ytdReturn = benchmark?.bucket_return_pct
  const ytdBench = benchmark?.benchmark_return_pct
  const ytdDelta = benchmark?.delta_pct
  // Wenn das Vergleichsfenster auf das Bucket-Erstellungsdatum geklemmt wurde
  // (Backfill-Historie davor ist nicht bucket-spezifisch), ehrlich labeln statt
  // "YTD" — sonst zeigt die Kachel einen Wert ueber ein anderes Fenster an.
  const clamped = benchmark?.clamped
  const effStart = benchmark?.effective_start
  const fmtDate = (iso) => {
    if (!iso) return ''
    return new Date(`${iso}T00:00:00`).toLocaleDateString('de-CH', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
    })
  }
  const perfLabel = clamped ? `Perf. seit ${fmtDate(effStart)}` : 'YTD Performance'
  const perfHint = clamped
    ? 'Vergleich ab Bucket-Erstellung — frühere Werte stammen aus proportionalem Backfill und sind nicht bucket-spezifisch.'
    : undefined
  const Icon = pnl >= 0 ? TrendingUp : TrendingDown
  const accent =
    pnl >= 0 ? 'bg-success/5 border-success/20' : 'bg-danger/5 border-danger/20'
  // Wealth-Index-basierter Drawdown vom Backend (cashflow-bereinigt).
  // Nominal-Berechnung (value - peak_chf) / peak_chf wuerde nach Sells
  // einen kuenstlichen Drawdown anzeigen — der Outflow ist kein Wertverlust.
  const peakDraw = summary.drawdown_vs_peak_pct ?? null

  return (
    <div className={`rounded-lg border p-5 ${accent}`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-text-secondary flex items-center gap-2">
          <FolderTree size={14} className="text-primary" />
          Bucket: <span className="font-semibold text-text-primary">{summary.name}</span>
        </h3>
        <Icon size={18} className="text-text-muted" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <p className="text-[11px] text-text-muted mb-1">Marktwert</p>
          <p className="text-xl font-bold text-text-primary">{formatCHF(value)}</p>
          <p className="text-[11px] text-text-muted mt-0.5">
            {summary.position_count || 0} Positionen
          </p>
        </div>
        <div>
          <p className="text-[11px] text-text-muted mb-1">Unrealisiert</p>
          <p className={`text-xl font-bold ${pnlColor(pnl)}`}>{formatCHF(pnl)}</p>
          <p className={`text-[11px] mt-0.5 ${pnlColor(pnlPct)}`}>
            {formatPct(pnlPct)} vs. {formatCHF(cost)} Cost
          </p>
        </div>
        <div>
          <p className="text-[11px] text-text-muted mb-1" title={perfHint}>
            {perfLabel}
            {clamped && <span className="ml-1 text-text-muted/70">*</span>}
          </p>
          {ytdReturn != null ? (
            <>
              <p className={`text-xl font-bold ${pnlColor(ytdReturn)}`}>
                {formatPct(ytdReturn)}
              </p>
              {ytdBench != null && (
                <p className="text-[11px] mt-0.5 text-text-muted">
                  vs. {benchmark.benchmark_name || benchmark.benchmark_ticker}{' '}
                  {formatPct(ytdBench)}
                  {ytdDelta != null && (
                    <span className={`ml-1 ${pnlColor(ytdDelta)}`}>
                      (Δ {formatPct(ytdDelta)})
                    </span>
                  )}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-text-muted italic">Keine Bucket-Historie</p>
          )}
        </div>
        <div>
          <p className="text-[11px] text-text-muted mb-1">vs. Peak</p>
          {peakDraw != null ? (
            <p className={`text-xl font-bold ${pnlColor(peakDraw)}`}>
              {formatPct(peakDraw)}
            </p>
          ) : (
            <p className="text-sm text-text-muted italic">–</p>
          )}
          <p className="text-[11px] mt-0.5 text-text-muted">
            Peak: {summary.running_peak_chf ? formatCHF(summary.running_peak_chf) : '–'}
          </p>
        </div>
      </div>
    </div>
  )
}
