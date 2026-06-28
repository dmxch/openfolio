import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Scale, Loader2 } from 'lucide-react'

const THEAD = 'bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint'

export default function RebalancingCard() {
  const { data, loading } = useApi('/analysis/rebalancing')

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card">
        <div className="text-center py-10"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  // Keine Bucket-Ziele gesetzt -> nichts anzeigen (kein Laerm).
  if (!data || !data.has_targets) return null

  const buckets = data.buckets || []
  const cov = data.cash_covers_underweight_pct

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <Scale size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Rebalancing — Soll/Ist je Bucket</h3>
      </div>

      <div className="px-[18px] pt-3">
        <p className="text-[11px] text-text-muted">
          Abweichung von deinen Bucket-Zielen (Ist == Allokations-Diagramm).
          {data.total_underweight_chf > 0 && (
            <> Untergewicht total {formatCHF(data.total_underweight_chf)} · verfügbares Cash {formatCHF(data.available_cash_chf)}
            {cov != null && <> (deckt {cov.toFixed(0)} %)</>}.</>
          )}
        </p>
      </div>

      <div className="overflow-x-auto mt-3">
        <table className="w-full text-xs">
          <thead>
            <tr className={THEAD}>
              <th className="text-left pl-[18px] pr-3 py-2.5 font-medium">Bucket</th>
              <th className="text-right px-3 py-2.5 font-medium">Soll</th>
              <th className="text-right px-3 py-2.5 font-medium">Ist</th>
              <th className="text-right px-3 py-2.5 font-medium">Δ</th>
              <th className="text-left px-3 py-2.5 font-medium pr-[18px]">Hinweis</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => {
              const onTarget = Math.abs(b.delta_pp) < 1
              const under = b.delta_chf > 0
              const deltaColor = onTarget ? 'text-text-muted' : under ? 'text-primary' : 'text-danger'
              return (
                <tr key={b.bucket_id} className="border-b border-border-row hover:bg-hover transition-colors">
                  <td className="pl-[18px] pr-3 py-2.5 text-text-primary">
                    <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: b.color || '#666' }} />
                    {b.name}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-secondary tabular-nums">{b.target_pct.toFixed(1)} %</td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-secondary tabular-nums">{b.actual_pct.toFixed(1)} %</td>
                  <td className={`px-3 py-2.5 text-right font-mono tabular-nums ${deltaColor}`}>
                    {b.delta_pp > 0 ? '+' : ''}{b.delta_pp.toFixed(1)} pp
                  </td>
                  <td className="px-3 py-2.5 pr-[18px]">
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
      <p className="text-[11px] text-text-muted px-[18px] py-3 border-t border-border-2">Orientierung auf Bucket-Ebene — keine Anlageempfehlung.</p>
    </div>
  )
}
