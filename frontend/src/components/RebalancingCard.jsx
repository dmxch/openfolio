import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Scale, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"

export default function RebalancingCard() {
  const { data, loading } = useApi('/analysis/rebalancing')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  // Keine Bucket-Ziele gesetzt -> nichts anzeigen (kein Laerm).
  if (!data || !data.has_targets) return null

  const buckets = data.buckets || []
  const cov = data.cash_covers_underweight_pct

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-1">
        <Scale size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Rebalancing — Soll/Ist je Bucket</h3>
      </div>
      <p className="text-[11px] text-text-muted mb-3">
        Abweichung von deinen Bucket-Zielen (Ist == Allokations-Diagramm).
        {data.total_underweight_chf > 0 && (
          <> Untergewicht total {formatCHF(data.total_underweight_chf)} · verfuegbares Cash {formatCHF(data.available_cash_chf)}
          {cov != null && <> (deckt {cov.toFixed(0)} %)</>}.</>
        )}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-text-muted">
              <th className="text-left p-2 font-medium">Bucket</th>
              <th className="text-right p-2 font-medium">Soll</th>
              <th className="text-right p-2 font-medium">Ist</th>
              <th className="text-right p-2 font-medium">Δ</th>
              <th className="text-left p-2 font-medium">Hinweis</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => {
              const onTarget = Math.abs(b.delta_pp) < 1
              const under = b.delta_chf > 0
              const deltaColor = onTarget ? 'text-text-muted' : under ? 'text-primary' : 'text-danger'
              return (
                <tr key={b.bucket_id} className="border-b border-border/50 hover:bg-card-alt/50">
                  <td className="p-2 text-text-primary">
                    <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: b.color || '#666' }} />
                    {b.name}
                  </td>
                  <td className="p-2 text-right text-text-secondary tabular-nums">{b.target_pct.toFixed(1)} %</td>
                  <td className="p-2 text-right text-text-secondary tabular-nums">{b.actual_pct.toFixed(1)} %</td>
                  <td className={`p-2 text-right tabular-nums ${deltaColor}`}>
                    {b.delta_pp > 0 ? '+' : ''}{b.delta_pp.toFixed(1)} pp
                  </td>
                  <td className="p-2">
                    {onTarget ? <span className="text-success">im Ziel</span>
                      : under ? <span className="text-primary">aufstocken ~{formatCHF(b.delta_chf)}</span>
                      : <span className="text-danger">reduzieren ~{formatCHF(-b.delta_chf)}</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-text-muted mt-2">Orientierung auf Bucket-Ebene — keine Anlageempfehlung.</p>
    </div>
  )
}
