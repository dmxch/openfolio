import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Scissors, AlertTriangle, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"

/**
 * Per-Position-Rebalancing (lean) — bricht den Bucket-Ueberhang auf Trim-
 * Kandidaten herunter (groesste Position zuerst) + Konzentrations-Flags.
 * Read-only, neutrale Sprache. Quelle: GET /api/analysis/position-rebalancing.
 */
export default function PositionRebalancingCard() {
  const { data, loading } = useApi('/analysis/position-rebalancing')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data || !data.has_data) return null

  const trims = data.trim_candidates || []
  const flags = data.concentration_flags || []

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-1">
        <Scissors size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Positions-Trim & Konzentration</h3>
      </div>
      <p className="text-[11px] text-text-muted mb-3">
        Bucket-Überhang auf Einzelpositionen heruntergebrochen (grösste zuerst). Keine Anweisung — Kandidaten zur Prüfung.
      </p>

      {trims.length > 0 && (
        <div className="mb-3">
          <div className="text-[11px] uppercase tracking-wide text-text-muted mb-1">Trim-Kandidaten (übergewichtete Buckets)</div>
          <div className="space-y-1">
            {trims.map((t, i) => (
              <div key={`${t.ticker}-${i}`} className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate">
                  <span className="font-medium text-text-primary">{t.ticker}</span>
                  <span className="text-text-muted"> · {t.bucket_name}</span>
                  <span className="text-text-muted"> · hält {formatCHF(t.current_chf)}</span>
                </span>
                <span className="shrink-0 tabular-nums text-danger">reduzieren ~{formatCHF(t.trim_chf)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {flags.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-text-muted mb-1">
            <AlertTriangle size={11} /> Klumpenrisiko (&ge; {data.concentration_threshold_pct}% des liquiden Werts)
          </div>
          <div className="space-y-1">
            {flags.map((f) => (
              <div key={f.ticker} className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate">
                  <span className="font-medium text-text-primary">{f.ticker}</span>
                  <span className="text-text-muted"> · {formatCHF(f.value_chf)}</span>
                </span>
                <span className="shrink-0 tabular-nums text-text-secondary">{(f.weight_pct ?? 0).toFixed(1)} %</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
