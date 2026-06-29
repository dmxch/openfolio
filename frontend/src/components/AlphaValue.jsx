import { formatNumber, pnlColor } from '../lib/format'

// Signifikanz: |t| >= 2 → der OLS-Intercept ist statistisch von 0 unterscheidbar.
export function isAlphaSignificant(alpha) {
  const t = alpha?.t_stat
  return t != null && Math.abs(t) >= 2
}

/**
 * Signifikanz-bewusste Anzeige des annualisierten Alpha.
 *
 * Annualisiertes Alpha = OLS-Intercept der Faktor-Regression, geometrisch auf
 * 252 Handelstage hochgerechnet. Diese ×252-Hochrechnung amplifiziert jede
 * winzige Aenderung des Tages-Intercepts massiv. Bei |t| < 2 ist Alpha
 * statistisch NICHT von 0 unterscheidbar — die Punktschaetzung wandert stark
 * (das Konfidenzband enthaelt die Null). Dann zeigen wir den Wert NEUTRAL/grau
 * mit n.s.-Badge + Tooltip statt als rot/gruene Headline, damit Rauschen nicht
 * als Signal (Out-/Underperformance) gelesen wird.
 */
export default function AlphaValue({ alpha, className = '' }) {
  const pct = alpha?.annualized_pct
  if (pct == null) return <span className={className}>–</span>

  const t = alpha?.t_stat
  const text = `${pct > 0 ? '+' : ''}${formatNumber(pct, 2)}%`

  if (isAlphaSignificant(alpha)) {
    return <span className={`${pnlColor(pct)} ${className}`}>{text}</span>
  }

  const title =
    `Statistisch nicht signifikant${t != null ? ` (t = ${formatNumber(t, 2)})` : ''} — ` +
    'Alpha ist von 0 nicht unterscheidbar. Den exakten Wert nicht ueberinterpretieren.'
  return (
    <span className={`text-text-muted ${className}`} title={title}>
      {text}
      <span className="ml-1.5 align-middle font-mono text-[0.55em] font-semibold uppercase tracking-wide px-1 py-0.5 rounded bg-hover text-text-muted">
        n.s.
      </span>
    </span>
  )
}
