/** Formatierungs-Helfer fuer den EPS-Scanner. */

const MONTH_TO_QUARTER = { 1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4 }

/**
 * Quartals-Kurzlabel aus einem ISO-Datum (Quartalsende), z.B. "Q3 '25".
 * Robuste Ableitung aus dem Monat — Fiskalquartale variieren je Firma.
 */
export function formatQuarterLabel(isoDate) {
  if (!isoDate) return '—'
  const d = new Date(isoDate)
  if (Number.isNaN(d.getTime())) return '—'
  const q = MONTH_TO_QUARTER[d.getUTCMonth() + 1]
  const yy = String(d.getUTCFullYear()).slice(2)
  return `Q${q} '${yy}`
}

/** YoY-Prozent als String mit Clamp-Anzeige bei Extremwerten (Rohwert bleibt erhalten). */
export function formatYoyPct(pct) {
  if (pct === null || pct === undefined) return '—'
  if (pct > 500) return '>500%'
  if (pct < -500) return '<-500%'
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(0)}%`
}
