import { formatQuarterLabel, formatYoyPct } from '../lib/epsFormat'

/**
 * Einzelne EPS-Quartalszelle als Heatzelle.
 * - EPS gross, mono; Vorzeichen-Farbe (negativ = danger).
 * - YoY% (sofern berechenbar) als kleine farbige Zweitzeile.
 * - Hintergrund-Tint (rgba) nach YoY-Magnitude — gruen bei Wachstum, rot bei
 *   Schrumpfung. Reine Darstellung; EPS-Wert/Format bleiben unveraendert.
 */

// success #45c08a -> rgb(69,192,138), danger #e8625a -> rgb(232,98,90)
function heatBackground(yoy) {
  if (yoy === null || yoy === undefined) return 'transparent'
  const mag = Math.min(Math.abs(yoy) / 50, 1) // 50% YoY = volle Intensitaet
  const a = (0.10 + mag * 0.22).toFixed(3)
  return yoy >= 0 ? `rgba(69,192,138,${a})` : `rgba(232,98,90,${a})`
}

export default function EpsQuarterCell({ periodEnd, eps, yoy }) {
  if (eps === null || eps === undefined) {
    return (
      <td className="px-1.5 py-1.5 text-center font-mono tabular-nums text-text-muted" aria-label="EPS nicht verfügbar">
        —
      </td>
    )
  }
  const negative = eps < 0
  const yoyText = yoy === null || yoy === undefined ? null : formatYoyPct(yoy)
  const label = `EPS ${formatQuarterLabel(periodEnd)}: ${eps.toFixed(2)}${yoyText ? `, YoY ${yoyText}` : ''}`
  return (
    <td className="px-1.5 py-1" aria-label={label} title={label}>
      <div className="rounded-md px-1.5 py-1 text-center" style={{ background: heatBackground(yoy) }}>
        <div className={`font-mono text-[12px] tabular-nums leading-tight ${negative ? 'text-danger' : 'text-text-primary'}`}>
          {eps.toFixed(2)}
        </div>
        {yoyText && (
          <div className={`font-mono text-[9.5px] tabular-nums leading-tight mt-0.5 ${yoy >= 0 ? 'text-success' : 'text-danger'}`}>
            {yoyText}
          </div>
        )}
      </div>
    </td>
  )
}
