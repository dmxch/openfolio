import { formatCHF, formatPct, pnlColor } from '../lib/format'
import { Wallet, Building2, TrendingUp, TrendingDown, Clock } from 'lucide-react'
import G from './GlossarTooltip'

function TotalReturnCard({ totalReturn }) {
  if (!totalReturn) {
    return (
      <div className="rounded-lg border border-border/50 p-5 animate-pulse">
        <div className="flex items-center justify-between mb-3">
          <div className="h-4 bg-card-alt rounded w-28"></div>
          <div className="h-4 bg-card-alt rounded w-4"></div>
        </div>
        <div className="h-3 bg-card-alt rounded w-20 mb-2"></div>
        <div className="h-7 bg-card-alt rounded w-32 mb-3"></div>
        <div className="space-y-1.5">
          <div className="h-3 bg-card-alt rounded w-full"></div>
          <div className="h-3 bg-card-alt rounded w-3/4"></div>
        </div>
        <div className="mt-3 pt-3 border-t border-border/30">
          <div className="h-3 bg-card-alt rounded w-36 mb-2"></div>
          <div className="h-6 bg-card-alt rounded w-24"></div>
        </div>
      </div>
    )
  }

  const tr = totalReturn
  const total = tr.total_return_chf
  const color = pnlColor(total)
  const accent = total >= 0 ? 'bg-success/5 border-success/20' : 'bg-danger/5 border-danger/20'
  const Icon = total >= 0 ? TrendingUp : TrendingDown

  const lines = [
    { label: 'Unrealisiert', value: tr.unrealized_pnl_chf, tooltip: 'Differenz zwischen aktuellem Wert und Einstandswert deiner offenen Positionen' },
    { label: 'Realisiert', value: tr.realized_pnl_chf, tooltip: 'Gewinne und Verluste aus verkauften Positionen' },
    { label: <G term="Dividende">Dividenden</G>, value: tr.dividends_net_chf, tooltip: 'Erhaltene Dividenden nach Quellensteuer' },
    { label: 'Kapitalgewinne', value: tr.capital_gains_dist_chf, tooltip: 'Fondsausschüttungen (Capital Gains Distributions)' },
    { label: 'Zinsen', value: tr.interest_chf, tooltip: 'Erhaltene Zinserträge' },
    { label: 'Gebühren', value: -tr.other_fees_chf, tooltip: 'Depotgebühren und sonstige Spesen' },
  ]
  // Only show lines that are non-zero (except unrealized which always shows)
  const visibleLines = lines.filter((l, i) => i === 0 || l.value !== 0)

  const mwrColor = pnlColor(tr.total_return_pct)

  return (
    <div className={`rounded-lg border p-5 ${accent}`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-text-secondary">Gesamtrendite</h3>
        <Icon size={18} className="text-text-muted" />
      </div>

      {/* Block 1: Absoluter Gewinn/Verlust */}
      <p className="text-[11px] text-text-muted mb-1">Absoluter Gewinn / Verlust</p>
      <p className={`text-2xl font-bold ${color}`}>{formatCHF(total)}</p>

      <div className="mt-2 space-y-1">
        {visibleLines.map((line) => (
          <div key={line.label} className="flex justify-between text-xs" title={line.tooltip}>
            <span className="text-text-muted">{line.label}</span>
            <span className={`tabular-nums font-medium ${pnlColor(line.value)}`}>{formatCHF(line.value)}</span>
          </div>
        ))}
      </div>

      {/* Block 2: Annualisierte Rendite (MWR) */}
      <div className="mt-3 pt-3 border-t border-border/30">
        <p className="text-[11px] text-text-muted mb-1"><G term="MWR">Annualisierte Rendite (MWR)</G></p>
        <p className={`text-xl font-bold ${mwrColor}`}>{formatPct(tr.total_return_pct)}</p>
        <p className="text-[10px] text-text-muted mt-0.5">Geldgewichtete Rendite seit Start</p>
      </div>

      {/* Block 3: YTD */}
      {tr.ytd_chf != null && (
        <div className="mt-3 pt-3 border-t border-border/30 space-y-1">
          <div className="flex justify-between items-baseline">
            <span className="text-xs font-medium text-text-secondary"><G term="YTD">YTD</G> {tr.ytd_year}</span>
            <span className={`text-sm tabular-nums font-bold ${pnlColor(tr.ytd_chf)}`}>
              {formatCHF(tr.ytd_chf)}{' '}
              <span className="font-normal opacity-70 text-xs">({formatPct(tr.ytd_pct)})</span>
            </span>
          </div>
          {[
            { label: 'Unrealisiert', value: tr.ytd_unrealized_chf },
            { label: 'Realisiert', value: tr.ytd_realized_chf },
            { label: 'Dividenden', value: tr.ytd_dividends_chf },
          ].filter(l => l.value !== 0).map(line => (
            <div key={`ytd-${line.label}`} className="flex justify-between text-xs">
              <span className="text-text-muted">{line.label}</span>
              <span className={`tabular-nums font-medium ${pnlColor(line.value)}`}>{formatCHF(line.value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PerformanceCard({ summary, realEstateEquity = 0, dailyChange, totalReturn }) {
  if (!summary) return null

  const dailyIcon = (dailyChange?.daily_change_chf ?? 0) >= 0 ? TrendingUp : TrendingDown

  const pensionValue = summary.positions?.filter((p) => p.type === 'pension').reduce((s, p) => s + p.market_value_chf, 0) || 0
  const liquidValue = summary.total_market_value_chf - pensionValue
  const posCount = summary.positions?.filter((p) => p.type !== 'cash' && p.type !== 'pension').length || 0

  const cards = [
    {
      label: 'Liquides Vermögen',
      value: formatCHF(liquidValue),
      sub: `${posCount} Positionen`,
      icon: Wallet,
      color: 'text-primary',
      bgAccent: 'bg-primary/5 border-primary/20',
    },
    ...(realEstateEquity > 0 ? [{
      label: 'Gesamtvermögen',
      value: formatCHF(summary.total_market_value_chf + realEstateEquity),
      sub: 'inkl. Vorsorge & Immobilien',
      icon: Building2,
      color: 'text-primary',
      bgAccent: 'bg-primary/5 border-primary/20',
    }] : []),
    ...(dailyChange ? [{
      label: 'Heute',
      value: formatCHF(dailyChange.daily_change_chf),
      sub: formatPct(dailyChange.daily_change_pct),
      icon: dailyIcon,
      color: pnlColor(dailyChange.daily_change_chf),
      bgAccent: (dailyChange.daily_change_chf ?? 0) >= 0
        ? 'bg-success/5 border-success/20'
        : 'bg-danger/5 border-danger/20',
    }] : []),
  ]

  // +1 for the TotalReturnCard which is always shown
  const totalCards = cards.length + 1
  const colClass = totalCards >= 4 ? 'md:grid-cols-4' : totalCards === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2'

  const lastUpdate = dailyChange?.timestamp
    ? new Date(dailyChange.timestamp).toLocaleString('de-CH', { hour: '2-digit', minute: '2-digit' })
    : null

  return (
    <div>
      <div className={`grid grid-cols-1 ${colClass} gap-4`}>
        {cards.map(({ label, value, sub, icon: Icon, color, bgAccent, title }) => (
          <div key={label} className={`rounded-lg border p-5 ${bgAccent}`} title={title}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-text-secondary">{label}</h3>
              <Icon size={18} className="text-text-muted" />
            </div>
            <p className={`text-2xl font-bold ${color}`}>{value}</p>
            {sub && <p className={`text-sm mt-1 ${color === 'text-text-primary' ? 'text-text-muted' : color} opacity-80`}>{sub}</p>}
          </div>
        ))}
        <TotalReturnCard totalReturn={totalReturn} />
      </div>
      <div className="flex items-center justify-between mt-2">
        {lastUpdate && (
          <div className="flex items-center gap-1.5 text-xs text-text-muted">
            <Clock size={11} />
            <span>Stand: {lastUpdate}</span>
          </div>
        )}
        <span className="text-xs text-text-muted opacity-60">Nicht für steuerliche Zwecke geeignet</span>
      </div>
    </div>
  )
}
