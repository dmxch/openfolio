import { formatQuarterLabel } from '../lib/epsFormat'

/**
 * Einzelne EPS-Quartalszelle, farbcodiert nach Vorzeichen.
 * - Positiv: text-text-primary
 * - Negativ: text-danger (WCAG 2.2 AA Kontrast auf Dark)
 * - Kein Wert (null): "—" in text-text-muted
 */
export default function EpsQuarterCell({ periodEnd, eps }) {
  if (eps === null || eps === undefined) {
    return (
      <td className="px-2 py-1.5 text-right tabular-nums text-text-muted" aria-label="EPS nicht verfügbar">
        —
      </td>
    )
  }
  const negative = eps < 0
  const label = `EPS ${formatQuarterLabel(periodEnd)}: ${eps.toFixed(2)}, ${negative ? 'negativ' : 'positiv'}`
  return (
    <td
      className={`px-2 py-1.5 text-right tabular-nums ${negative ? 'text-danger' : 'text-text-primary'}`}
      aria-label={label}
      title={label}
    >
      {eps.toFixed(2)}
    </td>
  )
}
