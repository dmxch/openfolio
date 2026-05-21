import { SIGNAL_CONFIG, MOMENTUM_CONFIG } from '../lib/screeningConfig'

const MOMENTUM_OPTIONS = [
  { value: 'tailwind', label: MOMENTUM_CONFIG.tailwind.label },
  { value: 'headwind', label: MOMENTUM_CONFIG.headwind.label },
  { value: 'concentrated', label: MOMENTUM_CONFIG.concentrated.label },
  { value: 'neutral', label: 'Neutral' },
]

export default function SmartMoneyFilters({ filters, setFilters, availableSectors }) {
  const toggleSector = (sec) => {
    setFilters((f) => {
      const next = new Set(f.sectors)
      if (next.has(sec)) next.delete(sec)
      else next.add(sec)
      return { ...f, sectors: next }
    })
  }
  const toggleSignal = (sig) => {
    setFilters((f) => {
      const next = new Set(f.signals)
      if (next.has(sig)) next.delete(sig)
      else next.add(sig)
      return { ...f, signals: next }
    })
  }
  const toggleMomentum = (mom) => {
    setFilters((f) => {
      const next = new Set(f.momentums)
      if (next.has(mom)) next.delete(mom)
      else next.add(mom)
      return { ...f, momentums: next }
    })
  }

  return (
    <aside className="w-64 shrink-0 space-y-6 pr-4 border-r border-border">
      <div>
        <label className="block text-xs uppercase text-text-muted mb-2">Min-Score</label>
        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={filters.minScore}
          onChange={(e) => setFilters((f) => ({ ...f, minScore: Number(e.target.value) }))}
          className="w-full"
        />
        <div className="text-sm font-mono text-text-secondary">≥ {filters.minScore}</div>
      </div>

      <div>
        <label className="block text-xs uppercase text-text-muted mb-2">Sektor-Momentum</label>
        <div className="space-y-1">
          {MOMENTUM_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={filters.momentums.has(opt.value)}
                onChange={() => toggleMomentum(opt.value)}
              />
              <span>{opt.label}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-xs uppercase text-text-muted mb-2">Signal-Typ</label>
        <div className="space-y-1 max-h-56 overflow-y-auto">
          {Object.entries(SIGNAL_CONFIG).map(([key, cfg]) => (
            <label key={key} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={filters.signals.has(key)}
                onChange={() => toggleSignal(key)}
              />
              <span className="truncate">{cfg.label}</span>
            </label>
          ))}
        </div>
      </div>

      {availableSectors && availableSectors.length > 0 && (
        <div>
          <label className="block text-xs uppercase text-text-muted mb-2">Sektor</label>
          <div className="space-y-1 max-h-56 overflow-y-auto">
            {availableSectors.map((sec) => (
              <label key={sec} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.sectors.has(sec)}
                  onChange={() => toggleSector(sec)}
                />
                <span className="truncate">{sec}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-2 pt-4 border-t border-border">
        <label className="flex items-center gap-2 text-sm text-text-muted cursor-not-allowed opacity-60" title="Kommt in Iteration 4 mit Strategy-Doc">
          <input type="checkbox" disabled />
          <span>Nur über SMA 150 (Iteration 4)</span>
        </label>
        <label className="flex items-center gap-2 text-sm text-text-muted cursor-not-allowed opacity-60" title="Kommt in Iteration 4 mit Strategy-Doc">
          <input type="checkbox" disabled />
          <span>Nur RSI &lt; 75 (Iteration 4)</span>
        </label>
      </div>
    </aside>
  )
}
