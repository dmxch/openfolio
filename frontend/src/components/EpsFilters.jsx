import { useState, useEffect } from 'react'
import { Info, Search, X, ChevronDown, RotateCcw } from 'lucide-react'
import EpsThresholdSettings from './EpsThresholdSettings'

const INDEX_OPTIONS = [
  { value: 'sp500', label: 'S&P 500 (Large Cap)' },
  { value: 'sp400', label: 'S&P 400 (Mid Cap)' },
  { value: 'sp600', label: 'S&P 600 (Small Cap)' },
]

const SORT_OPTIONS = [
  { value: 'yoy_growth', label: 'YoY-Wachstum' },
  { value: 'streak_count', label: 'Streak-Count' },
  { value: 'latest_eps', label: 'Jüngster EPS' },
  { value: 'ticker', label: 'Ticker' },
]

const TOGGLES = [
  {
    key: 'superQuarterOnly',
    label: 'Nur Super-Quartale',
    info: 'Super-Quartal-Kriterien erfüllt: YoY-Wachstum ≥ Schwelle, beschleunigt gegenüber den Vorquartalen, positive Vorjahresbasis, kein Einmaleffekt.',
    descClass: 'text-warning',
    desc: 'Schwellenwerte noch nicht backtest-validiert',
  },
  {
    key: 'recordQuarterOnly',
    label: 'Nur Record-Quartale',
    info: 'Jüngstes Quartal = neues 8-Quartals-EPS-Hoch (absolutes Niveau-Signal). Kombinierbar mit Super-Quartal (UND-Verknüpfung).',
    descClass: 'text-text-muted',
    desc: 'Neues 8-Quartals-EPS-Hoch',
  },
  {
    key: 'turnaroundOnly',
    label: 'Nur Turnarounds',
    info: 'Verlust → Gewinn: im 8-Quartals-Fenster war mindestens ein Quartal negativ, das jüngste ist wieder profitabel. Kombinierbar mit den anderen Filtern.',
    descClass: 'text-text-muted',
    desc: 'Verlust → Gewinn (jüngstes Q profitabel)',
  },
]

const SECTION_LABEL = 'font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label'

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={`relative w-9 h-5 rounded-full shrink-0 transition-colors ${checked ? 'bg-primary' : 'bg-border-hover'}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : ''}`}
      />
    </button>
  )
}

export default function EpsFilters({ filters, setFilters, availableSectors, thresholds, onThresholdsSaved, onReset }) {
  const [showThresholds, setShowThresholds] = useState(false)

  const toggleSector = (sec) => {
    setFilters((f) => {
      const next = new Set(f.sectors)
      if (next.has(sec)) next.delete(sec)
      else next.add(sec)
      return { ...f, sectors: next }
    })
  }

  const toggleIndex = (idx) => {
    setFilters((f) => {
      const next = new Set(f.indices)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return { ...f, indices: next }
    })
  }

  // Debounced Suche (Ticker oder Name) — 300ms, damit nicht pro Tastendruck gefetcht wird.
  const [searchValue, setSearchValue] = useState(filters.search || '')
  useEffect(() => { setSearchValue(filters.search || '') }, [filters.search])
  useEffect(() => {
    const id = setTimeout(() => {
      setFilters((f) => (f.search === searchValue ? f : { ...f, search: searchValue }))
    }, 300)
    return () => clearTimeout(id)
  }, [searchValue, setFilters])

  return (
    <aside className="bg-card border border-border rounded-card p-4 space-y-5">
      <div>
        <label htmlFor="eps-search" className="sr-only">Suche nach Ticker oder Name</label>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
          <input
            id="eps-search"
            type="text"
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            placeholder="Ticker oder Name…"
            className="w-full pl-8 pr-8 py-2 text-sm bg-surface border border-border rounded-lg text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
          />
          {searchValue && (
            <button
              type="button"
              onClick={() => setSearchValue('')}
              aria-label="Suche löschen"
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-text-muted hover:text-text-primary"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="space-y-3.5">
        {TOGGLES.map((t) => (
          <div key={t.key} className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[13px] text-text-primary">
                {t.label}
                <Info
                  size={13}
                  className="text-text-muted shrink-0"
                  aria-label={`${t.label} — Erklärung`}
                  title={t.info}
                />
              </div>
              <p className={`text-[11px] mt-0.5 ${t.descClass}`}>{t.desc}</p>
            </div>
            <Toggle
              checked={!!filters[t.key]}
              label={t.label}
              onChange={() => setFilters((f) => ({ ...f, [t.key]: !f[t.key] }))}
            />
          </div>
        ))}
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label htmlFor="eps-minq" className={SECTION_LABEL}>Min. Quartale</label>
          <span className="font-mono text-xs text-text-secondary tabular-nums">{filters.minQuarters}</span>
        </div>
        <input
          id="eps-minq"
          type="range"
          min={4}
          max={8}
          step={2}
          value={filters.minQuarters}
          onChange={(e) => setFilters((f) => ({ ...f, minQuarters: Number(e.target.value) }))}
          className="w-full"
          aria-label="Mindestanzahl verfügbarer Quartale"
        />
        <div className="flex justify-between font-mono text-[10px] text-text-faint mt-1">
          <span>4</span><span>6</span><span>8</span>
        </div>
      </div>

      <div>
        <div className={`${SECTION_LABEL} mb-2`}>Sortieren nach</div>
        <div className="space-y-1.5">
          {SORT_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-[13px] text-text-secondary cursor-pointer hover:text-text-primary transition-colors">
              <input
                type="radio"
                name="eps-sort"
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

      <div>
        <div className={`${SECTION_LABEL} mb-2`}>Index</div>
        <div className="space-y-1.5">
          {INDEX_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-[13px] text-text-secondary cursor-pointer hover:text-text-primary transition-colors">
              <input
                type="checkbox"
                checked={filters.indices.has(opt.value)}
                onChange={() => toggleIndex(opt.value)}
              />
              <span className="truncate">{opt.label}</span>
            </label>
          ))}
        </div>
      </div>

      {availableSectors && availableSectors.length > 0 && (
        <div>
          <div className={`${SECTION_LABEL} mb-2`}>Sektoren</div>
          <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
            {availableSectors.map((sec) => (
              <label key={sec} className="flex items-center gap-2 text-[13px] text-text-secondary cursor-pointer hover:text-text-primary transition-colors">
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

      <div className="pt-4 border-t border-border-2">
        <button
          type="button"
          onClick={() => setShowThresholds((s) => !s)}
          aria-expanded={showThresholds}
          className="flex items-center justify-between w-full text-left"
        >
          <span className={SECTION_LABEL}>Schwellenwerte</span>
          <ChevronDown size={14} className={`text-text-muted transition-transform ${showThresholds ? 'rotate-180' : ''}`} />
        </button>
        {showThresholds && (
          <div className="mt-3">
            <EpsThresholdSettings thresholds={thresholds} onSaved={onThresholdsSaved} />
          </div>
        )}
      </div>

      {onReset && (
        <div className="pt-4 border-t border-border-2">
          <button
            type="button"
            onClick={onReset}
            className="flex items-center gap-1.5 text-[12.5px] text-text-muted hover:text-text-primary transition-colors"
          >
            <RotateCcw size={13} />
            Zurücksetzen
          </button>
        </div>
      )}
    </aside>
  )
}
