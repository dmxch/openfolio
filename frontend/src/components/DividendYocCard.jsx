import { useApi } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { Coins, Loader2 } from 'lucide-react'

const THEAD = 'bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint'

export default function DividendYocCard() {
  const { data, loading } = useApi('/analysis/dividend-yoc')

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card">
        <div className="text-center py-10"><Loader2 size={18} className="animate-spin text-text-muted mx-auto" /></div>
      </div>
    )
  }
  // Keine Dividenden-Zahler im liquiden Sleeve -> nichts anzeigen.
  if (!data || !data.has_data) return null

  const positions = data.positions || []

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <Coins size={16} className="text-primary" />
        <h3 className="text-sm font-semibold text-text-primary">Dividenden Yield-on-Cost (12M)</h3>
      </div>

      <div className="px-[18px] pt-3">
        <p className="text-[11px] text-text-muted">
          Portfolio <span className="text-text-primary font-mono font-medium">{data.portfolio_yoc_pct?.toFixed(2)} %</span>
          {' '}· {formatCHF(data.trailing_dividends_chf)} erhalten auf {formatCHF(data.eligible_cost_basis_chf)} Kostenbasis (letzte 12 Monate).
        </p>
      </div>

      <div className="overflow-x-auto mt-3">
        <table className="w-full text-xs">
          <thead>
            <tr className={THEAD}>
              <th className="text-left pl-[18px] pr-3 py-2.5 font-medium">Position</th>
              <th className="text-right px-3 py-2.5 font-medium">Div 12M</th>
              <th className="text-right px-3 py-2.5 font-medium">Kostenbasis</th>
              <th className="text-right px-3 py-2.5 font-medium pr-[18px]">YoC</th>
            </tr>
          </thead>
          <tbody>
            {positions.slice(0, 15).map((p) => (
              <tr key={p.ticker} className="border-b border-border-row hover:bg-hover transition-colors">
                <td className="pl-[18px] pr-3 py-2.5 text-text-primary">{p.ticker}</td>
                <td className="px-3 py-2.5 text-right font-mono text-text-secondary tabular-nums">{formatCHF(p.dividends_12m_chf)}</td>
                <td className="px-3 py-2.5 text-right font-mono text-text-secondary tabular-nums">{formatCHF(p.cost_basis_chf)}</td>
                <td className="px-3 py-2.5 text-right pr-[18px] font-mono text-success tabular-nums">{p.yoc_pct.toFixed(2)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-text-muted px-[18px] py-3 border-t border-border-2">Rückwärts (effektiv erhalten, netto) — keine Prognose.</p>
    </div>
  )
}
