import { useApi } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import G from './GlossarTooltip'

// Karte "Top-Konzentration": die schwersten liquiden Positionen als Balken,
// im Header der HHI mit Klassifikation. Zwei Layouts via Prop `variant`:
//   'compact' (default) → Ticker + Balken + Gewicht (Mockup Performance, Übersicht)
//   'wide'              → Ticker + Titelname + breiter Balken + Gewicht (Risiko-Seite)
//
// Daten holt die Karte selbst:
//   /portfolio/summary                       → positions[] (Gewicht/Balken)
//   /portfolio/correlation-matrix?period=90d → concentration.{ hhi, classification }
//
// Korrektheits-Invariante: Immobilien, Private Equity und Vorsorge zählen NICHT
// zum liquiden Vermögen. Cash (und als Cash klassifizierte Geldmarkt-ETFs) wird
// ebenfalls ausgeschlossen — "Top-Konzentration" meint die Risiko-Positionen
// (Aktien/ETFs/Krypto/Rohstoffe), nicht den Cash-Saldo, der sie sonst dominiert.

const EXCLUDED_TYPES = new Set(['real_estate', 'private_equity', 'pension', 'cash'])

const CLASSIFICATION = {
  low: { label: 'tief', color: 'text-success' },
  moderate: { label: 'moderat', color: 'text-warning' },
  high: { label: 'hoch', color: 'text-danger' },
}

// Balkenfarbe je effektiver Anlageklasse (Geldmarkt-ETFs zählen als Cash).
// Default für Aktien: bg-primary, ETF/Fonds: bg-etf.
function barColor(p) {
  const cls = p.count_as_cash ? 'cash' : p.type
  switch (cls) {
    case 'etf': return 'bg-etf'
    case 'crypto': return 'bg-cls-crypto'
    case 'commodity': return 'bg-cls-metal'
    case 'cash': return 'bg-cls-cash'
    default: return 'bg-primary'
  }
}

function Skeleton() {
  return (
    <div className="bg-card border border-border rounded-card p-[18px] animate-pulse">
      <div className="h-4 bg-hover rounded w-40 mb-[14px]" />
      <div className="flex flex-col gap-2">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex items-center gap-[9px]">
            <div className="h-3 bg-hover rounded w-[46px] flex-none" />
            <div className="h-[7px] bg-hover rounded flex-1" />
            <div className="h-3 bg-hover rounded w-[38px] flex-none" />
          </div>
        ))}
      </div>
    </div>
  )
}

export default function TopConcentrationCard({ variant = 'compact' }) {
  const isWide = variant === 'wide'
  const { data: summary, loading } = useApi('/portfolio/summary')
  const { data: corr } = useApi('/portfolio/correlation-matrix?period=90d')

  if (loading) return <Skeleton />

  // Liquide Positionen mit positivem Wert (value_chf bzw. market_value_chf).
  const positions = (summary?.positions || [])
    .map((p) => ({ ...p, _value: p.value_chf ?? p.market_value_chf ?? 0 }))
    .filter((p) => !EXCLUDED_TYPES.has(p.type) && !p.count_as_cash && p._value > 0)

  const liquidTotal = positions.reduce((sum, p) => sum + p._value, 0)

  const top = [...positions]
    .sort((a, b) => b._value - a._value)
    .slice(0, 6)
    .map((p) => ({
      key: p.id ?? p.ticker ?? p.name,
      ticker: p.ticker || p.symbol || p.name || '–',
      name: p.name || p.ticker || '',
      weight: liquidTotal > 0 ? (p._value / liquidTotal) * 100 : 0,
      color: barColor(p),
    }))

  const maxWeight = top.length > 0 ? top[0].weight : 0

  const conc = corr?.concentration
  const cls = conc ? (CLASSIFICATION[conc.classification] || CLASSIFICATION.moderate) : null

  return (
    <div className="bg-card border border-border rounded-card p-[18px]">
      <div className="flex items-center justify-between mb-[14px]">
        <span className="text-sm font-semibold text-text-primary">Top-Konzentration</span>
        {conc && conc.hhi != null && (
          <span className="font-mono text-[11px] text-text-muted tabular-nums">
            HHI{' '}
            <G term="HHI">
              <b className={`font-semibold ${cls.color}`}>
                {formatNumber(conc.hhi, 3)} {cls.label}
              </b>
            </G>
          </span>
        )}
      </div>

      {top.length === 0 ? (
        <p className="text-[12px] text-text-muted py-2">Keine liquiden Positionen vorhanden.</p>
      ) : (
        <div className={`flex flex-col ${isWide ? 'gap-[9px]' : 'gap-2'}`}>
          {top.map((p) => {
            const widthPct = maxWeight > 0 ? Math.max((p.weight / maxWeight) * 100, 3) : 0
            return (
              <div key={p.key} className={`flex items-center ${isWide ? 'gap-2.5' : 'gap-[9px]'}`}>
                <span className="font-mono text-[11.5px] font-semibold text-text-bright w-[46px] flex-none truncate">
                  {p.ticker}
                </span>

                {isWide && (
                  <span className="text-[12px] text-text-muted flex-1 truncate" title={p.name}>
                    {p.name}
                  </span>
                )}

                <div
                  className={`h-[7px] bg-border-row rounded overflow-hidden ${isWide ? 'w-[120px] flex-none' : 'flex-1'}`}
                >
                  <div
                    className={`h-[7px] rounded ${p.color}`}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>

                <span
                  className={`font-mono text-[11.5px] text-text-secondary text-right flex-none tabular-nums ${isWide ? 'w-[40px]' : 'w-[38px]'}`}
                >
                  {formatNumber(p.weight, 1)}%
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
