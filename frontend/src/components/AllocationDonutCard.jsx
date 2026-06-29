import { useApi } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import { CHART_COLORS } from '../lib/chartColors'

// Klassenfarben — identisch zur Anlageklasse-Aufschlüsselung in AllocationCharts.jsx,
// damit Donut und Balken-Chart auf derselben Seite dieselben Farben zeigen.
const PALETTE_TYPE = {
  stock: CHART_COLORS.primary,
  etf: '#8b5cf6',
  crypto: CHART_COLORS.warning,
  commodity: CHART_COLORS.success,
  cash: CHART_COLORS.textMuted,
  pension: '#06b6d4',
  real_estate: '#805AD5',
  private_equity: '#059669',
}

const PALETTE_FALLBACK = [
  CHART_COLORS.primary, CHART_COLORS.success, CHART_COLORS.warning, CHART_COLORS.danger,
  '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#14b8a6', '#6366f1', '#a855f7',
]

const TYPE_LABELS = {
  stock: 'Aktien', etf: 'ETFs', crypto: 'Crypto', commodity: 'Rohstoffe',
  cash: 'Cash', pension: 'Pension', real_estate: 'Immobilien', private_equity: 'Private Equity',
}

const classColor = (name, i) => PALETTE_TYPE[name] || PALETTE_FALLBACK[i % PALETTE_FALLBACK.length]
const classLabel = (name) => TYPE_LABELS[name] || name

const R = 54
const CIRC = 2 * Math.PI * R

function Shell({ children }) {
  return (
    <div className="bg-card border border-border rounded-card p-[18px]">
      <h3 className="text-sm font-semibold text-text-primary mb-3.5">Allokation nach Klasse</h3>
      {children}
    </div>
  )
}

export default function AllocationDonutCard() {
  const { data, loading, error } = useApi('/portfolio/summary')

  if (loading) {
    return (
      <div className="bg-card border border-border rounded-card p-[18px] animate-pulse">
        <div className="h-4 bg-hover rounded w-44 mb-4" />
        <div className="flex items-center gap-[18px]">
          <div className="w-[130px] h-[130px] rounded-full bg-hover shrink-0" />
          <div className="flex-1 flex flex-col gap-2.5">
            <div className="h-3 bg-hover rounded" />
            <div className="h-3 bg-hover rounded" />
            <div className="h-3 bg-hover rounded" />
            <div className="h-3 bg-hover rounded" />
          </div>
        </div>
      </div>
    )
  }

  const items = [...(data?.allocations?.by_type || [])]
    .filter((d) => (d.value_chf || 0) > 0 && (d.pct || 0) > 0)
    .sort((a, b) => b.value_chf - a.value_chf)

  if (error || items.length === 0) {
    return (
      <Shell>
        <p className="text-xs text-text-muted py-6 text-center">Keine Allokationsdaten verfügbar.</p>
      </Shell>
    )
  }

  // Donut-Segmente: dasharray = sichtbare Bogenlänge + voller Umfang als Lücke
  // (so zeigt jeder Kreis genau einen Bogen), offset = negativer kumulierter Start.
  let cursor = 0
  const segments = items.map((d, i) => {
    const seg = (d.pct / 100) * CIRC
    const offset = -(cursor / 100) * CIRC
    cursor += d.pct
    return {
      key: d.name,
      color: classColor(d.name, i),
      label: classLabel(d.name),
      pct: d.pct,
      dash: `${seg.toFixed(3)} ${CIRC.toFixed(3)}`,
      offset: offset.toFixed(3),
    }
  })

  return (
    <Shell>
      <div className="flex flex-col items-center gap-4">
        <svg viewBox="0 0 140 140" className="w-full max-w-[200px] aspect-square">
          <g transform="rotate(-90 70 70)">
            {segments.map((s) => (
              <circle
                key={s.key}
                cx="70"
                cy="70"
                r={R}
                fill="none"
                stroke={s.color}
                strokeWidth="18"
                strokeDasharray={s.dash}
                strokeDashoffset={s.offset}
              />
            ))}
          </g>
          <text
            x="70"
            y="66"
            textAnchor="middle"
            className="fill-text-primary font-sans tabular-nums"
            fontSize="17"
            fontWeight="600"
          >
            {formatNumber(items.length)}
          </text>
          <text
            x="70"
            y="82"
            textAnchor="middle"
            className="fill-text-muted font-mono"
            fontSize="9"
            letterSpacing="0.06em"
          >
            KLASSEN
          </text>
        </svg>

        <div className="w-full flex flex-col gap-1.5">
          {segments.map((s) => (
            <div key={s.key} className="flex items-center gap-2 text-xs">
              <span
                className="w-[9px] h-[9px] rounded-[2px] shrink-0"
                style={{ background: s.color }}
              />
              <span className="flex-1 text-text-secondary truncate" title={s.label}>
                {s.label}
              </span>
              <span className="font-mono font-medium tabular-nums text-text-bright shrink-0">
                {formatNumber(s.pct, 1)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </Shell>
  )
}
