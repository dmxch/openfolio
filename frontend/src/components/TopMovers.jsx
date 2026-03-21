import { Link } from 'react-router-dom'
import { formatCHF, formatPct, pnlColor } from '../lib/format'
import { TrendingUp, TrendingDown } from 'lucide-react'
import MiniChartTooltip from './MiniChartTooltip'

function MoverCard({ position, rank }) {
  const isPositive = position.pnl_pct >= 0
  const Icon = isPositive ? TrendingUp : TrendingDown

  return (
    <div className={`rounded-lg border p-4 flex items-center gap-4 ${
      isPositive ? 'bg-success/5 border-success/20' : 'bg-danger/5 border-danger/20'
    }`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${
        isPositive ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger'
      }`}>
        {rank}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <MiniChartTooltip ticker={position.ticker}><Link to={`/stock/${encodeURIComponent(position.ticker)}`} className="font-mono text-sm font-medium text-primary hover:underline">{position.ticker}</Link></MiniChartTooltip>
          <span className="text-xs text-text-muted truncate">{position.name}</span>
        </div>
        <div className="text-xs text-text-secondary mt-0.5">{formatCHF(position.market_value_chf)}</div>
      </div>
      <div className="text-right flex-shrink-0">
        <div className={`text-sm font-bold tabular-nums ${pnlColor(position.pnl_pct)}`}>
          {formatPct(position.pnl_pct)}
        </div>
        <div className={`text-xs tabular-nums ${pnlColor(position.pnl_chf)}`}>
          {formatCHF(position.pnl_chf)}
        </div>
      </div>
      <Icon size={16} className={isPositive ? 'text-success' : 'text-danger'} />
    </div>
  )
}

export default function TopMovers({ positions }) {
  if (!positions?.length) return null

  const tradable = positions.filter((p) => p.type !== 'cash' && p.type !== 'pension' && p.shares > 0)
  if (tradable.length < 2) return null

  const sorted = [...tradable].sort((a, b) => b.pnl_pct - a.pnl_pct)
  const winners = sorted.slice(0, 3).filter((p) => p.pnl_pct > 0)
  const losers = sorted.slice(-3).reverse().filter((p) => p.pnl_pct < 0)

  if (!winners.length && !losers.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center">
        <p className="text-sm text-text-muted">Noch keine Kursveränderungen vorhanden.</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {winners.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={16} className="text-success" />
            <h3 className="text-sm font-medium text-text-secondary">Top Gewinner</h3>
          </div>
          <div className="space-y-2">
            {winners.map((p, i) => (
              <MoverCard key={p.id} position={p} rank={i + 1} />
            ))}
          </div>
        </div>
      )}
      {losers.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown size={16} className="text-danger" />
            <h3 className="text-sm font-medium text-text-secondary">Top Verlierer</h3>
          </div>
          <div className="space-y-2">
            {losers.map((p, i) => (
              <MoverCard key={p.id} position={p} rank={i + 1} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
