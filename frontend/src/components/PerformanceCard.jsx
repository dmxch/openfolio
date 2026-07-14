import { formatCHF, formatPct, formatTime, pnlColor } from '../lib/format'
import { TrendingUp, TrendingDown } from 'lucide-react'
import StatTile from './ui/StatTile'
import G from './GlossarTooltip'

function Row({ label, value, tooltip }) {
  return (
    <div className="flex justify-between text-xs" title={tooltip}>
      <span className="text-text-muted">{label}</span>
      <span className={`font-mono tabular-nums font-medium ${pnlColor(value)}`}>{formatCHF(value)}</span>
    </div>
  )
}

function TotalReturnCard({ totalReturn }) {
  if (!totalReturn) {
    return (
      <div className="bg-card border border-border rounded-card overflow-hidden">
        <div className="px-[18px] py-4 border-b border-border-2">
          <div className="h-4 bg-hover rounded w-28 animate-pulse" />
        </div>
        <div className="p-[18px] space-y-3 animate-pulse">
          <div className="h-7 bg-hover rounded w-32" />
          <div className="h-3 bg-hover rounded w-full" />
          <div className="h-3 bg-hover rounded w-3/4" />
        </div>
      </div>
    )
  }

  const tr = totalReturn
  const total = tr.total_return_chf
  const Icon = total >= 0 ? TrendingUp : TrendingDown

  const lines = [
    { label: 'Unrealisiert', value: tr.unrealized_pnl_chf, tooltip: 'Differenz zwischen aktuellem Wert und Einstandswert deiner offenen Positionen' },
    { label: 'Realisiert', value: tr.realized_pnl_chf, tooltip: 'Gewinne und Verluste aus verkauften Positionen' },
    { label: <G term="Dividende">Dividenden</G>, value: tr.dividends_net_chf, tooltip: 'Erhaltene Dividenden nach Quellensteuer' },
    { label: 'Kapitalgewinne', value: tr.capital_gains_dist_chf, tooltip: 'Fondsausschüttungen (Capital Gains Distributions)' },
    { label: 'Zinsen', value: tr.interest_chf, tooltip: 'Erhaltene Zinserträge' },
    { label: 'Gebühren', value: -tr.other_fees_chf, tooltip: 'Depotgebühren und sonstige Spesen' },
  ]
  const visibleLines = lines.filter((l, i) => i === 0 || l.value !== 0)

  return (
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">Gesamtrendite</h3>
        <Icon size={16} className="text-text-muted" />
      </div>
      <div className="p-[18px]">
        <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-[7px]">
          Absoluter Gewinn / Verlust
        </div>
        <p className={`text-[22px] font-mono font-semibold tracking-[-0.01em] leading-none ${pnlColor(total)}`}>{formatCHF(total)}</p>

        <div className="mt-3 space-y-1.5">
          {visibleLines.map((line, i) => (
            <Row key={i} label={line.label} value={line.value} tooltip={line.tooltip} />
          ))}
        </div>

        <div className="mt-4 pt-3 border-t border-border-2">
          <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-1">
            <G term="MWR">Annualisierte Rendite (MWR)</G>
          </div>
          <p className={`text-lg font-mono font-semibold tabular-nums ${pnlColor(tr.total_return_pct)}`}>{formatPct(tr.total_return_pct)}</p>
          <p className="text-[10px] text-text-muted mt-0.5">Geldgewichtete Rendite seit Start</p>
        </div>

        {tr.ytd_chf != null && (
          <div className="mt-4 pt-3 border-t border-border-2 space-y-1.5">
            <div className="flex justify-between items-baseline">
              <span className="text-xs font-medium text-text-secondary"><G term="YTD">YTD</G> {tr.ytd_year}</span>
              <span className={`font-mono text-sm tabular-nums font-semibold ${pnlColor(tr.ytd_chf)}`}>
                {formatCHF(tr.ytd_chf)}{' '}
                <span className="font-normal opacity-70 text-xs">({formatPct(tr.ytd_pct)})</span>
              </span>
            </div>
            {[
              { label: 'Unrealisiert', value: tr.ytd_unrealized_chf },
              { label: 'Realisiert', value: tr.ytd_realized_chf },
              { label: 'Dividenden', value: tr.ytd_dividends_chf },
            ].filter((l) => l.value !== 0).map((line, i) => (
              <Row key={i} label={line.label} value={line.value} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// netWorth = /analysis/net-worth, als Prop von Performance.jsx durchgereicht
// (eine Quelle der Wahrheit mit der Hero-Kachel, kein Doppel-Fetch des teuren
// Endpoints): enthält neben den Summary-Positionen auch Private Equity
// (Netto-Wert nach Discount) und Immobilien (brutto) minus Hypothek. Ohne
// Prop greift der bisherige Client-Fallback (summary + realEstateEquity).
export default function PerformanceCard({ summary, realEstateEquity = 0, dailyChange, totalReturn, netWorth = null }) {
  if (!summary) return null

  // PE-Positionen sind bewusst nie in summary.positions (liquide Sicht) —
  // illiquide ist hier nur die Vorsorge; PE fliesst über das Netto-Vermögen ein.
  const illiquidValue = summary.positions?.filter((p) => p.type === 'pension').reduce((s, p) => s + (p.market_value_chf || 0), 0) || 0
  const liquidValue = summary.total_market_value_chf - illiquidValue
  // Zählt die Titel hinter dem liquiden Vermögen — gleiche Regel wie die
  // "Positionen"-Kachel auf /portfolio: Konten raus, Geldmarkt-/T-Bill-ETFs
  // (count_as_cash) zählen als Cash, geschlossene Positionen (shares 0) sind
  // keine Positionen mehr. Anleihen zählen mit.
  const posCount = summary.positions?.filter(
    (p) => p.type !== 'cash' && p.type !== 'pension' && !p.count_as_cash && (p.shares || 0) > 0
  ).length || 0

  // Private-Equity-Anteil (netto) aus der Vermögensbilanz — steuert, ob die
  // Gesamtvermögen-Kachel auch ohne Immobilien erscheint.
  const peNetValue = netWorth?.components?.find((c) => c.key === 'private_equity')?.value_chf || 0
  const totalWealthParts = ['Vorsorge']
  if (realEstateEquity > 0) totalWealthParts.push('Immobilien')
  if (peNetValue > 0) totalWealthParts.push('Private Equity')
  const totalWealthSub = `inkl. ${totalWealthParts.slice(0, -1).join(', ')}${totalWealthParts.length > 1 ? ' & ' : ''}${totalWealthParts[totalWealthParts.length - 1]}`

  const tiles = [
    {
      label: 'Liquides Vermögen',
      value: formatCHF(liquidValue),
      sub: `${posCount} Positionen`,
      tone: 'default',
    },
    ...((realEstateEquity > 0 || peNetValue > 0) ? [{
      label: 'Gesamtvermögen',
      // Server-Zahl der Vermögensbilanz; Fallback = bisherige Client-Rechnung,
      // bis der Endpoint geladen ist (für Nutzer ohne PE dieselbe Zahl).
      value: formatCHF(netWorth?.net_worth_chf ?? (summary.total_market_value_chf + realEstateEquity)),
      sub: totalWealthSub,
      tone: 'default',
    }] : []),
    ...(dailyChange ? [{
      label: 'Heute',
      value: formatCHF(dailyChange.daily_change_chf),
      sub: formatPct(dailyChange.daily_change_pct),
      tone: (dailyChange.daily_change_chf ?? 0) >= 0 ? 'success' : 'danger',
    }] : []),
  ]

  const lastUpdate = dailyChange?.timestamp ? formatTime(dailyChange.timestamp) : null

  return (
    <div className="flex flex-col gap-[14px]">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-[14px] items-start">
        {tiles.map((t, i) => <StatTile key={i} {...t} />)}
        <TotalReturnCard totalReturn={totalReturn} />
      </div>
      <div className="flex items-center justify-between text-[11px] text-text-muted">
        {lastUpdate ? <span>Stand: {lastUpdate}</span> : <span />}
        <span className="opacity-70">Nicht für steuerliche Zwecke geeignet</span>
      </div>
    </div>
  )
}
