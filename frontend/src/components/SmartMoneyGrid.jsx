import TickerLogo from './TickerLogo'
import MiniChartTooltip from './MiniChartTooltip'
import { SIGNAL_CONFIG, MOMENTUM_CONFIG } from '../lib/screeningConfig'

function ScoreBar100({ score }) {
  const clamped = Math.max(0, Math.min(100, score))
  let color = 'bg-text-muted'
  if (clamped >= 70) color = 'bg-success'
  else if (clamped >= 40) color = 'bg-primary'
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="flex-1 h-2 bg-border rounded-sm overflow-hidden" aria-label={`Score: ${clamped} von 100`}>
        <div className={`h-full ${color}`} style={{ width: `${clamped}%` }} />
      </div>
      <span className="text-sm font-mono text-text-secondary w-8 text-right">{clamped}</span>
    </div>
  )
}

function SignalChip({ signalKey }) {
  const cfg = SIGNAL_CONFIG[signalKey]
  if (!cfg) return null
  const colorClass = cfg.type === 'warning'
    ? 'bg-warning/15 text-warning'
    : cfg.type === 'flag'
      ? 'bg-text-muted/15 text-text-muted'
      : 'bg-primary/15 text-primary'
  return (
    <span
      title={cfg.description}
      className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold cursor-help ${colorClass}`}
    >
      {cfg.short}
    </span>
  )
}

function MomentumTag({ momentum, industryName }) {
  const cfg = MOMENTUM_CONFIG[momentum]
  if (!cfg) return <span className="text-xs text-text-muted">—</span>
  const tooltip = industryName ? `${cfg.label}: ${industryName} — ${cfg.description}` : cfg.description
  return (
    <span
      title={tooltip}
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium cursor-help ${cfg.color}`}
    >
      {cfg.label}
    </span>
  )
}

export default function SmartMoneyGrid({ rows, onSelect }) {
  if (!rows || rows.length === 0) {
    return <div className="p-8 text-center text-text-muted">Keine Treffer für aktuelle Filter.</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-text-muted text-xs uppercase border-b border-border">
          <tr>
            <th className="text-left py-2 pr-3">Ticker</th>
            <th className="text-left py-2 pr-3">Name</th>
            <th className="text-left py-2 pr-3">Sektor / Momentum</th>
            <th className="text-left py-2 pr-3 w-48">Score</th>
            <th className="text-left py-2">Signale</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.ticker}
              onClick={() => onSelect(r.ticker)}
              className="border-b border-border/50 hover:bg-card-hover cursor-pointer transition-colors"
            >
              <td className="py-2 pr-3">
                <MiniChartTooltip ticker={r.ticker}>
                  <div className="flex items-center gap-2">
                    <TickerLogo ticker={r.ticker} size={18} />
                    <span className="font-mono font-medium">{r.ticker}</span>
                  </div>
                </MiniChartTooltip>
              </td>
              <td className="py-2 pr-3 text-text-secondary truncate max-w-[18rem]">{r.name}</td>
              <td className="py-2 pr-3">
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-text-muted truncate max-w-[12rem]">{r.industry_name || r.sector || '—'}</span>
                  <MomentumTag momentum={r.sector_momentum} industryName={r.industry_name} />
                </div>
              </td>
              <td className="py-2 pr-3">
                <ScoreBar100 score={r.score_display ?? 0} />
              </td>
              <td className="py-2">
                <div className="flex flex-wrap gap-1">
                  {Object.keys(r.signals || {}).map((sig) => (
                    <SignalChip key={sig} signalKey={sig} />
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
