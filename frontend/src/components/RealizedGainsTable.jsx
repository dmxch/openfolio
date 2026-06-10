import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { formatCHF, formatDateShort, formatNumber, formatPct, pnlColor } from '../lib/format'
import { TrendingUp, TrendingDown, ArrowRightLeft, ChevronDown } from 'lucide-react'
import MiniChartTooltip from './MiniChartTooltip'

export default function RealizedGainsTable({ bucketId = null }) {
  const endpoint = bucketId
    ? `/portfolio/realized-gains?bucket_id=${encodeURIComponent(bucketId)}`
    : '/portfolio/realized-gains'
  const { data, loading } = useApi(endpoint)
  const [open, setOpen] = useState(false)

  if (loading || !data) return null
  if (!data.positions || data.positions.length === 0) return null

  const total = data.total_realized_pnl_chf
  const Icon = total >= 0 ? TrendingUp : TrendingDown

  return (
    <div className="rounded-lg border border-white/[0.06] bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <button
        onClick={() => setOpen(!open)}
        className="w-full p-4 flex items-center justify-between hover:bg-card-alt/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          <ArrowRightLeft size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">Realisierte Gewinne & Verluste</h3>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Icon size={14} className={pnlColor(total)} />
            <span className={`text-sm font-bold ${pnlColor(total)}`}>{formatCHF(total)}</span>
          </div>
          <ChevronDown size={16} className={`text-text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>
      {open && (
        <div className="border-t border-border overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.08] text-text-secondary text-[11px] uppercase tracking-wider">
                <th className="text-left p-3 font-medium">Position</th>
                <th className="text-right p-3 font-medium">Stück</th>
                <th className="text-right p-3 font-medium">Kauf</th>
                <th className="text-right p-3 font-medium">Verkauf</th>
                <th className="text-right p-3 font-medium">Einstand</th>
                <th className="text-right p-3 font-medium">Erlös</th>
                <th className="text-right p-3 font-medium">Gebühren</th>
                <th className="text-right p-3 font-medium">Gewinn/Verlust</th>
                <th className="text-right p-3 font-medium">%</th>
                <th className="text-right p-3 font-medium">Haltedauer</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p, i) => (
                <tr key={i} className="border-b border-border/50 hover:bg-card-alt/50 transition-colors">
                  <td className="p-3">
                    <div className="flex flex-col">
                      <MiniChartTooltip ticker={p.ticker}>
                        <Link to={`/stock/${encodeURIComponent(p.ticker)}`} className="text-primary font-medium hover:underline">{p.ticker}</Link>
                      </MiniChartTooltip>
                      <span className="text-xs text-text-secondary truncate max-w-[160px]">{p.name}</span>
                    </div>
                  </td>
                  <td className="p-3 text-right text-text-secondary tabular-nums">{formatNumber(p.shares, 4, { minDecimals: 0 })}</td>
                  <td className="p-3 text-right text-text-secondary tabular-nums text-xs">{p.buy_date ? formatDateShort(p.buy_date) : '–'}</td>
                  <td className="p-3 text-right text-text-secondary tabular-nums text-xs">{formatDateShort(p.sell_date)}</td>
                  <td className="p-3 text-right text-text-secondary tabular-nums">{formatCHF(p.cost_basis_chf)}</td>
                  <td className="p-3 text-right text-text-secondary tabular-nums">{formatCHF(p.proceeds_chf)}</td>
                  <td className="p-3 text-right text-text-muted tabular-nums">{formatCHF(p.fees_chf)}</td>
                  <td className={`p-3 text-right font-medium tabular-nums ${pnlColor(p.realized_pnl_chf)}`}>{formatCHF(p.realized_pnl_chf)}</td>
                  <td className={`p-3 text-right tabular-nums ${pnlColor(p.realized_pnl_pct)}`}>{formatPct(p.realized_pnl_pct)}</td>
                  <td className="p-3 text-right text-text-muted tabular-nums text-xs">{p.holding_period_days != null ? `${p.holding_period_days}d` : '–'}</td>
                </tr>
              ))}
              <tr className="bg-card-alt/30">
                <td className="p-3 text-text-primary font-medium" colSpan={7}>Total</td>
                <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(total)}`}>{formatCHF(total)}</td>
                <td colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {open && data.positions.length > 0 && (
        <p className="text-xs text-text-secondary px-4 py-2 opacity-60">
          Nicht für steuerliche Zwecke geeignet. Konsultiere deinen Steuerberater.
        </p>
      )}
    </div>
  )
}

