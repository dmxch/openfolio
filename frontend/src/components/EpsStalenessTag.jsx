/**
 * Staleness- und Coverage-Warnungen fuer eine Scanner-Zeile.
 * - "< 6Q": weniger als 6 Quartale verfuegbar (Finnhub-Luecke, yfinance-Fallback)
 * - "Veraltet": letzter Fetch > 14 Tage her
 */
export default function EpsStalenessTag({ quarterCount, dataAgeDays }) {
  const tags = []
  if (quarterCount !== null && quarterCount !== undefined && quarterCount < 6) {
    tags.push(
      <span
        key="fewq"
        className="inline-block px-1.5 py-0.5 rounded text-xs bg-card-alt text-text-muted"
        title="Weniger als 6 Quartale verfügbar — z.B. junge Aktie/Spinoff oder Datenlücke (Finanzsektor wird bei Finnhub nicht abgedeckt, dann greift der yfinance-Fallback)"
      >
        &lt; 6Q
      </span>
    )
  }
  if (dataAgeDays !== null && dataAgeDays !== undefined && dataAgeDays > 14) {
    tags.push(
      <span
        key="stale"
        className="inline-block px-1.5 py-0.5 rounded text-xs bg-warning/15 text-warning"
        title={`Veraltet — letzter Fetch vor ${dataAgeDays} Tagen`}
      >
        Veraltet
      </span>
    )
  }
  if (tags.length === 0) return null
  return <span className="inline-flex gap-1">{tags}</span>
}
