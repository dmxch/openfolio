import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Coins, Loader2 } from 'lucide-react'

const CARD = "rounded-lg border border-white/[0.06] bg-card p-4 shadow-[0_1px_3px_rgba(0,0,0,0.3)]"

export default function DividendYocCard() {
  const { data, loading } = useApi('/analysis/dividend-yoc')

  if (loading) {
    return (
      <div className={CARD}>
        <div className="text-center py-6"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  // Keine Dividenden-Zahler im liquiden Sleeve -> nichts anzeigen.
  if (!data || !data.has_data) return null

  const positions = data.positions || []

  return (
    <div className={CARD}>
      <div className="flex items-center gap-2 mb-1">
        <Coins size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Dividenden Yield-on-Cost (12M, effektiv erhalten)</h3>
      </div>
      <p className="text-[11px] text-text-muted mb-3">
        Portfolio <span className="text-text-primary font-medium">{data.portfolio_yoc_pct?.toFixed(2)} %</span>
        {' '}· {formatCHF(data.trailing_dividends_chf)} erhalten auf {formatCHF(data.eligible_cost_basis_chf)} Kostenbasis (letzte 12 Monate).
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-text-muted">
              <th className="text-left p-2 font-medium">Position</th>
              <th className="text-right p-2 font-medium">Div 12M</th>
              <th className="text-right p-2 font-medium">Kostenbasis</th>
              <th className="text-right p-2 font-medium">YoC</th>
            </tr>
          </thead>
          <tbody>
            {positions.slice(0, 15).map((p) => (
              <tr key={p.ticker} className="border-b border-border/50 hover:bg-card-alt/50">
                <td className="p-2 text-text-primary">{p.ticker}</td>
                <td className="p-2 text-right text-text-secondary tabular-nums">{formatCHF(p.dividends_12m_chf)}</td>
                <td className="p-2 text-right text-text-secondary tabular-nums">{formatCHF(p.cost_basis_chf)}</td>
                <td className="p-2 text-right text-success tabular-nums">{p.yoc_pct.toFixed(2)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-text-muted mt-2">Rückwärts (effektiv erhalten, netto) — keine Prognose.</p>
    </div>
  )
}
