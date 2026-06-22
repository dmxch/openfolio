import { formatYoyPct } from '../lib/epsFormat'

/**
 * YoY-Wachstums-Anzeige fuer das juengste Quartal.
 * - pos_to_pos: Prozent-Badge (gruen bei Wachstum, danger bei Schrumpfung)
 * - turnaround / neg_to_neg / pos_to_neg / zero_basis: erklaerende Pill
 */
const FLAG_PILLS = {
  turnaround: { label: 'Turnaround', cls: 'bg-violet-500/15 text-violet-300', title: 'Verlust → Gewinn (kein YoY-Prozentwert berechenbar)' },
  neg_to_neg: { label: 'Verlust', cls: 'bg-danger/15 text-danger', title: 'Vorjahr und aktuell negativ' },
  pos_to_neg: { label: 'Einbruch', cls: 'bg-danger/15 text-danger', title: 'Gewinn → Verlust' },
  zero_basis: { label: 'Basis 0', cls: 'bg-card-alt text-text-muted', title: 'Vorjahresquartal = 0, kein YoY berechenbar' },
}

export default function EpsYoyBadge({ yoyGrowthPct, yoyFlag }) {
  if (yoyFlag === 'pos_to_pos' && yoyGrowthPct !== null && yoyGrowthPct !== undefined) {
    const positive = yoyGrowthPct >= 0
    return (
      <span
        className={`inline-block px-1.5 py-0.5 rounded text-xs font-mono ${positive ? 'text-success' : 'text-danger'}`}
        aria-label={`YoY-Wachstum ${formatYoyPct(yoyGrowthPct)}`}
      >
        {formatYoyPct(yoyGrowthPct)}
      </span>
    )
  }
  const pill = FLAG_PILLS[yoyFlag]
  if (!pill) return <span className="text-text-muted">—</span>
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs ${pill.cls}`} title={pill.title}>
      {pill.label}
    </span>
  )
}
