import { Info } from 'lucide-react'
import EpsThresholdSettings from './EpsThresholdSettings'

const MIN_QUARTER_OPTIONS = [4, 6, 8]

const SORT_OPTIONS = [
  { value: 'yoy_growth', label: 'YoY-Wachstum' },
  { value: 'streak_count', label: 'Streak-Count' },
  { value: 'latest_eps', label: 'Jüngster EPS' },
  { value: 'ticker', label: 'Ticker' },
]

export default function EpsFilters({ filters, setFilters, availableSectors, thresholds, onThresholdsSaved }) {
  const toggleSector = (sec) => {
    setFilters((f) => {
      const next = new Set(f.sectors)
      if (next.has(sec)) next.delete(sec)
      else next.add(sec)
      return { ...f, sectors: next }
    })
  }

  return (
    <aside className="w-64 shrink-0 space-y-6 pr-4 border-r border-border">
      <div className="space-y-3">
        <label className="flex items-start gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            className="mt-0.5 focus:ring-2 focus:ring-primary"
            checked={!!filters.superQuarterOnly}
            onChange={() => setFilters((f) => ({ ...f, superQuarterOnly: !f.superQuarterOnly }))}
          />
          <span>
            <span className="flex items-center gap-1">
              Nur Super-Quartale
              <Info
                size={13}
                className="text-text-muted"
                aria-label="Super-Quartal-Erklärung"
                title="Super-Quartal-Kriterien erfüllt: YoY-Wachstum ≥ Schwelle, beschleunigt gegenüber den Vorquartalen, positive Vorjahresbasis, kein Einmaleffekt."
              />
            </span>
            <span className="block text-xs text-warning mt-0.5">
              Schwellenwerte noch nicht backtest-validiert
            </span>
          </span>
        </label>

        <label className="flex items-start gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            className="mt-0.5 focus:ring-2 focus:ring-primary"
            checked={!!filters.recordQuarterOnly}
            onChange={() => setFilters((f) => ({ ...f, recordQuarterOnly: !f.recordQuarterOnly }))}
          />
          <span>
            <span className="flex items-center gap-1">
              Nur Record-Quartale
              <Info
                size={13}
                className="text-text-muted"
                aria-label="Record-Quartal-Erklärung"
                title="Jüngstes Quartal = neues 8-Quartals-EPS-Hoch (absolutes Niveau-Signal). Kombinierbar mit Super-Quartal (UND-Verknüpfung)."
              />
            </span>
            <span className="block text-xs text-text-muted mt-0.5">
              Neues 8-Quartals-EPS-Hoch
            </span>
          </span>
        </label>
      </div>

      <div>
        <label htmlFor="eps-minq" className="block text-xs uppercase text-text-muted mb-2">
          Min. Quartale verfügbar
        </label>
        <select
          id="eps-minq"
          value={filters.minQuarters}
          onChange={(e) => setFilters((f) => ({ ...f, minQuarters: Number(e.target.value) }))}
          className="w-full bg-card-alt border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        >
          {MIN_QUARTER_OPTIONS.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs uppercase text-text-muted mb-2">Sortieren nach</label>
        <div className="space-y-1">
          {SORT_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="eps-sort"
                className="focus:ring-2 focus:ring-primary"
                checked={filters.sortBy === opt.value}
                onChange={() => setFilters((f) => ({
                  ...f,
                  sortBy: opt.value,
                  // Ticker aufsteigend, alles andere absteigend als Default
                  sortAsc: opt.value === 'ticker',
                }))}
              />
              <span>{opt.label}</span>
            </label>
          ))}
        </div>
      </div>

      {availableSectors && availableSectors.length > 0 && (
        <div>
          <label className="block text-xs uppercase text-text-muted mb-2">Sektoren</label>
          <div className="space-y-1 max-h-56 overflow-y-auto">
            {availableSectors.map((sec) => (
              <label key={sec} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  className="focus:ring-2 focus:ring-primary"
                  checked={filters.sectors.has(sec)}
                  onChange={() => toggleSector(sec)}
                />
                <span className="truncate">{sec}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="pt-4 border-t border-border">
        <EpsThresholdSettings thresholds={thresholds} onSaved={onThresholdsSaved} />
      </div>
    </aside>
  )
}
