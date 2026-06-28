import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Scissors, AlertTriangle, Loader2 } from 'lucide-react'

const LABEL = 'font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label'

/**
 * Per-Position-Rebalancing (lean) — bricht den Bucket-Ueberhang auf Trim-
 * Kandidaten herunter (groesste Position zuerst) + Konzentrations-Flags.
 * Read-only, neutrale Sprache. Quelle: GET /api/analysis/position-rebalancing.
 */
export default function PositionRebalancingCard() {
  const { data, loading } = useApi('/analysis/position-rebalancing')

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card">
        <div className="text-center py-10"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  if (!data || !data.has_data) return null

  const trims = data.trim_candidates || []
  const flags = data.concentration_flags || []

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <Scissors size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Positions-Trim & Konzentration</h3>
      </div>

      <div className="p-[18px]">
        <p className="text-[11px] text-text-muted mb-4">
          Bucket-Überhang auf Einzelpositionen heruntergebrochen (grösste zuerst). Keine Anweisung — Kandidaten zur Prüfung.
        </p>

        {trims.length > 0 && (
          <div className="mb-4">
            <div className={`${LABEL} mb-2`}>Trim-Kandidaten (übergewichtete Buckets)</div>
            <div className="space-y-1.5">
              {trims.map((t, i) => (
                <div key={`${t.ticker}-${i}`} className="flex items-center justify-between gap-3 text-xs">
                  <span className="min-w-0 truncate">
                    <span className="font-medium text-text-primary">{t.ticker}</span>
                    <span className="text-text-muted"> · {t.bucket_name}</span>
                    <span className="text-text-muted"> · hält {formatCHF(t.current_chf)}</span>
                  </span>
                  <span className="shrink-0 font-mono tabular-nums text-danger">reduzieren ~{formatCHF(t.trim_chf)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {flags.length > 0 && (
          <div>
            <div className={`flex items-center gap-1 ${LABEL} mb-2`}>
              <AlertTriangle size={11} /> Klumpenrisiko (&ge; {data.concentration_threshold_pct}% des liquiden Werts)
            </div>
            <div className="space-y-1.5">
              {flags.map((f) => (
                <div key={f.ticker} className="flex items-center justify-between gap-3 text-xs">
                  <span className="min-w-0 truncate">
                    <span className="font-medium text-text-primary">{f.ticker}</span>
                    <span className="text-text-muted"> · {formatCHF(f.value_chf)}</span>
                  </span>
                  <span className="shrink-0 font-mono tabular-nums text-text-secondary">{(f.weight_pct ?? 0).toFixed(1)} %</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
