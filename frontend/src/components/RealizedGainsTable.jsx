import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { formatCHF, formatDateShort, formatNumber, formatPct, pnlColor } from '../lib/format'
import { TrendingUp, TrendingDown, ArrowRightLeft, ChevronDown } from 'lucide-react'
import MiniChartTooltip from './MiniChartTooltip'

const THEAD = 'bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint'

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
    <div className="rounded-card border border-border bg-card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-[18px] py-4 flex items-center justify-between hover:bg-hover transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <ArrowRightLeft size={16} className="text-primary" />
          <h3 className="text-sm font-semibold text-text-primary">Realisierte Gewinne & Verluste</h3>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Icon size={14} className={pnlColor(total)} />
            <span className={`text-sm font-mono font-semibold tabular-nums ${pnlColor(total)}`}>{formatCHF(total)}</span>
          </div>
          <ChevronDown size={16} className={`text-text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>
      {open && (
        <div className="border-t border-border-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className={THEAD}>
                <th className="text-left pl-[18px] pr-3 py-2.5 font-medium">Position</th>
                <th className="text-right px-3 py-2.5 font-medium">Stück</th>
                <th className="text-right px-3 py-2.5 font-medium">Kauf</th>
                <th className="text-right px-3 py-2.5 font-medium">Verkauf</th>
                <th className="text-right px-3 py-2.5 font-medium">Einstand</th>
                <th className="text-right px-3 py-2.5 font-medium">Erlös</th>
                <th className="text-right px-3 py-2.5 font-medium">Gebühren</th>
                <th className="text-right px-3 py-2.5 font-medium">Gewinn/Verlust</th>
                <th className="text-right px-3 py-2.5 font-medium">%</th>
                <th className="text-right px-3 py-2.5 font-medium pr-[18px]">Haltedauer</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p, i) => (
                <tr key={i} className="border-b border-border-row hover:bg-hover transition-colors">
                  <td className="pl-[18px] pr-3 py-3">
                    <div className="flex flex-col">
                      <MiniChartTooltip ticker={p.ticker}>
                        <Link to={`/stock/${encodeURIComponent(p.ticker)}`} className="text-link font-medium hover:underline">{p.ticker}</Link>
                      </MiniChartTooltip>
                      <span className="text-xs text-text-secondary truncate max-w-[160px]">{p.name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-text-secondary tabular-nums">{formatNumber(p.shares, 4, { minDecimals: 0 })}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums text-xs">{p.buy_date ? formatDateShort(p.buy_date) : '–'}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums text-xs">{formatDateShort(p.sell_date)}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-secondary tabular-nums">{formatCHF(p.cost_basis_chf)}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-secondary tabular-nums">{formatCHF(p.proceeds_chf)}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums">{formatCHF(p.fees_chf)}</td>
                  <td className={`px-3 py-3 text-right font-mono font-medium tabular-nums ${pnlColor(p.realized_pnl_chf)}`}>{formatCHF(p.realized_pnl_chf)}</td>
                  <td className={`px-3 py-3 text-right font-mono tabular-nums ${pnlColor(p.realized_pnl_pct)}`}>{formatPct(p.realized_pnl_pct)}</td>
                  <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums text-xs pr-[18px]">{p.holding_period_days != null ? `${p.holding_period_days}d` : '–'}</td>
                </tr>
              ))}
              <tr className="bg-table-head border-t border-border-2">
                <td className="pl-[18px] pr-3 py-2.5 text-text-primary font-medium" colSpan={7}>Total</td>
                <td className={`px-3 py-2.5 text-right font-mono font-semibold tabular-nums ${pnlColor(total)}`}>{formatCHF(total)}</td>
                <td colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {open && data.positions.length > 0 && (
        <p className="text-[11px] text-text-muted px-[18px] py-2.5 border-t border-border-2 opacity-80">
          Nicht für steuerliche Zwecke geeignet. Konsultiere deinen Steuerberater.
        </p>
      )}
    </div>
  )
}
