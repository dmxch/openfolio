import MiniChartTooltip from './MiniChartTooltip'
import TickerChip from './ui/TickerChip'
import { SIGNAL_CONFIG, MOMENTUM_CONFIG } from '../lib/screeningConfig'

function scoreTextColor(score) {
  if (score >= 70) return 'text-success'
  if (score >= 40) return 'text-primary'
  return 'text-text-muted'
}
function scoreBarColor(score) {
  if (score >= 70) return 'bg-success'
  if (score >= 40) return 'bg-primary'
  return 'bg-text-muted'
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
      className={`inline-flex items-center justify-center min-w-[22px] h-[22px] px-1 rounded-[5px] font-mono text-[11px] font-bold cursor-help ${colorClass}`}
    >
      {cfg.short}
    </span>
  )
}

function MomentumTag({ momentum, industryName }) {
  const cfg = MOMENTUM_CONFIG[momentum]
  if (!cfg) return null
  const tooltip = industryName ? `${cfg.label}: ${industryName} — ${cfg.description}` : cfg.description
  return (
    <span
      title={tooltip}
      className={`inline-flex items-center px-[7px] py-[3px] rounded-[5px] text-[10.5px] font-medium leading-none whitespace-nowrap cursor-help ${cfg.color}`}
    >
      {cfg.label}
    </span>
  )
}

function SmartMoneyCard({ row, onSelect }) {
  const score = Math.max(0, Math.min(100, row.score_display ?? 0))
  const signalKeys = Object.keys(row.signals || {})
  return (
    <button
      type="button"
      onClick={() => onSelect(row.ticker)}
      className="group flex flex-col gap-3 text-left bg-card border border-border rounded-card p-[15px] hover:border-border-hover hover:bg-card-2 transition-colors"
    >
      {/* Header: Ticker + Name + Typ-Tag */}
      <div className="flex items-center gap-2 min-w-0">
        <MiniChartTooltip ticker={row.ticker}>
          <TickerChip>{row.ticker}</TickerChip>
        </MiniChartTooltip>
        <span className="flex-1 min-w-0 text-[12.5px] text-text-secondary truncate">{row.name || '—'}</span>
        <MomentumTag momentum={row.sector_momentum} industryName={row.industry_name} />
      </div>

      {/* Headline: Score (mono, farbig) + Balken */}
      <div>
        <div className="flex items-baseline gap-1.5">
          <span className={`font-mono text-[28px] font-semibold tracking-[-0.01em] leading-none ${scoreTextColor(score)}`}>
            {score}
          </span>
          <span className="font-mono text-[11px] text-text-faint">/100</span>
        </div>
        <div className="mt-2 h-[5px] bg-border rounded-sm overflow-hidden" aria-label={`Score: ${score} von 100`}>
          <div className={`h-full ${scoreBarColor(score)}`} style={{ width: `${score}%` }} />
        </div>
      </div>

      {/* Sub: Branche / Sektor */}
      <div className="text-[11px] text-text-muted truncate">
        {row.industry_name || row.sector || '—'}
      </div>

      {/* Footer: Signal-Chips (Konviktion) + Details */}
      <div className="mt-auto flex items-center justify-between gap-2 pt-3 border-t border-border-2">
        <div className="flex flex-wrap gap-1 min-w-0">
          {signalKeys.length > 0
            ? signalKeys.map((sig) => <SignalChip key={sig} signalKey={sig} />)
            : <span className="text-[11px] text-text-faint">Keine Signale</span>}
        </div>
        <span className="text-[11.5px] text-link whitespace-nowrap group-hover:text-primary transition-colors">
          Details →
        </span>
      </div>
    </button>
  )
}

export default function SmartMoneyGrid({ rows, onSelect }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="rounded-card border border-border bg-card p-12 text-center">
        <p className="text-sm text-text-muted">Keine Treffer für die aktuellen Filter.</p>
      </div>
    )
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-[14px]">
      {rows.map((r) => (
        <SmartMoneyCard key={r.ticker} row={r} onSelect={onSelect} />
      ))}
    </div>
  )
}
