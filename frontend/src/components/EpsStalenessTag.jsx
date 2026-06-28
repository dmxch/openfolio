/**
 * Staleness- und Coverage-Warnungen fuer eine Scanner-Zeile.
 * - "< 6Q": weniger als 6 Quartale verfuegbar (Finnhub-Luecke, yfinance-Fallback)
 * - "Veraltet": letzter Fetch > 14 Tage her
 *
 * Zusaetzlich exportiert: die Staleness-Stufen + ein Mapper data_age_days -> Stufe,
 * gemeinsam genutzt vom Tabellen-Punkt (EpsTable) und der Header-Legende (EpsScanner),
 * damit Punkt-Farbe und Legende deckungsgleich bleiben.
 */

// Stufen rein zur Anzeige (Punkt/Legende). Schwelle "Veraltet" (> 14 Tage)
// spiegelt die bestehende Tag-Logik; "Kuerzlich" (> 7 Tage) ist eine reine
// Darstellungsabstufung und beeinflusst keine Filter-/Score-Logik.
export const STALENESS_LEVELS = [
  { key: 'fresh', label: 'Aktuell', color: '#45c08a' },
  { key: 'recent', label: 'Kürzlich', color: '#e0a64b' },
  { key: 'stale', label: 'Veraltet', color: '#e8625a' },
]

export function stalenessLevel(dataAgeDays) {
  if (dataAgeDays === null || dataAgeDays === undefined) return null
  if (dataAgeDays > 14) return STALENESS_LEVELS[2]
  if (dataAgeDays > 7) return STALENESS_LEVELS[1]
  return STALENESS_LEVELS[0]
}

export default function EpsStalenessTag({ quarterCount, dataAgeDays }) {
  const tags = []
  if (quarterCount !== null && quarterCount !== undefined && quarterCount < 6) {
    tags.push(
      <span
        key="fewq"
        className="inline-flex items-center rounded-[5px] px-[7px] py-[3px] text-[10.5px] font-medium leading-none bg-surface border border-border-2 text-text-muted"
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
        className="inline-flex items-center rounded-[5px] px-[7px] py-[3px] text-[10.5px] font-medium leading-none bg-warning/15 text-warning"
        title={`Veraltet — letzter Fetch vor ${dataAgeDays} Tagen`}
      >
        Veraltet
      </span>
    )
  }
  if (tags.length === 0) return null
  return <span className="inline-flex gap-1">{tags}</span>
}
