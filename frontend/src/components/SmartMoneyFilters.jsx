import { SIGNAL_CONFIG, MOMENTUM_CONFIG } from '../lib/screeningConfig'

const MOMENTUM_OPTIONS = [
  { value: 'tailwind', label: MOMENTUM_CONFIG.tailwind.label },
  { value: 'headwind', label: MOMENTUM_CONFIG.headwind.label },
  { value: 'concentrated', label: MOMENTUM_CONFIG.concentrated.label },
  { value: 'neutral', label: 'Neutral' },
]

// Die drei "Schwur"-Filter (Konviktions-Gates). Reihenfolge + Semantik 1:1 zur
// bisherigen Logik — nur als Chips dargestellt statt als Checkboxen.
const SCHWUR_OPTIONS = [
  { key: 'schwur1', label: 'Trend', title: 'Schwur 1: Kurs über SMA150 — Trend-Filter' },
  { key: 'schwur2', label: 'Earnings-Veto', title: 'Schwur 2: keine Hits mit Earnings in den nächsten 7 Tagen' },
  { key: 'schwur3', label: 'Klumpen', title: 'Schwur 3: filtert Ticker, die du über deine ETFs bereits hoch gewichtet hältst' },
]

const SECTION_LABEL = 'font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-2'

function ChipToggle({ active, onClick, title, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`text-[12px] font-medium px-[10px] py-[6px] rounded-lg border transition-colors ${
        active
          ? 'bg-active-tint border-border-active text-text-bright'
          : 'bg-surface border-border-2 text-text-muted hover:border-border-hover'
      }`}
    >
      {children}
    </button>
  )
}

function CheckRow({ checked, onChange, children }) {
  return (
    <label className="flex items-center gap-2 text-[12.5px] text-text-secondary cursor-pointer py-[3px] hover:text-text-primary transition-colors">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="shrink-0 accent-primary"
      />
      <span className="truncate">{children}</span>
    </label>
  )
}

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
  const toggleSchwur = (key) => {
    setFilters((f) => ({ ...f, [key]: !f[key] }))
  }

  const resetFilters = () => {
    setFilters({
      minScore: 30,
      sectors: new Set(),
      momentums: new Set(),
      signals: new Set(),
      schwur1: false,
      schwur2: false,
      schwur3: false,
    })
  }

  const hasFilters =
    filters.minScore !== 30 ||
    filters.sectors.size > 0 ||
    filters.momentums.size > 0 ||
    filters.signals.size > 0 ||
    filters.schwur1 || filters.schwur2 || filters.schwur3

  return (
    <aside className="sticky top-[60px] max-h-[calc(100vh-76px)] overflow-y-auto border-r border-border-soft pr-4 flex flex-col gap-5 pb-4">
      {/* Min-Score */}
      <div>
        <label className={SECTION_LABEL}>Min-Score</label>
        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={filters.minScore}
          onChange={(e) => setFilters((f) => ({ ...f, minScore: Number(e.target.value) }))}
          className="w-full"
        />
        <div className="font-mono text-[12.5px] text-text-secondary tabular-nums mt-1">≥ {filters.minScore}</div>
      </div>

      {/* Konviktion (Schwur-Gates) */}
      <div>
        <label className={SECTION_LABEL}>Konviktion</label>
        <div className="flex flex-wrap gap-1.5">
          {SCHWUR_OPTIONS.map((opt) => (
            <ChipToggle
              key={opt.key}
              active={!!filters[opt.key]}
              onClick={() => toggleSchwur(opt.key)}
              title={opt.title}
            >
              {opt.label}
            </ChipToggle>
          ))}
        </div>
      </div>

      {/* Sektor-Momentum */}
      <div>
        <label className={SECTION_LABEL}>Sektor-Momentum</label>
        <div className="space-y-0.5">
          {MOMENTUM_OPTIONS.map((opt) => (
            <CheckRow
              key={opt.value}
              checked={filters.momentums.has(opt.value)}
              onChange={() => toggleMomentum(opt.value)}
            >
              {opt.label}
            </CheckRow>
          ))}
        </div>
      </div>

      {/* Signal-Typ */}
      <div>
        <label className={SECTION_LABEL}>Signal-Typ</label>
        <div className="space-y-0.5 max-h-60 overflow-y-auto pr-1">
          {Object.entries(SIGNAL_CONFIG).map(([key, cfg]) => (
            <CheckRow
              key={key}
              checked={filters.signals.has(key)}
              onChange={() => toggleSignal(key)}
            >
              {cfg.label}
            </CheckRow>
          ))}
        </div>
      </div>

      {/* Sektor */}
      {availableSectors && availableSectors.length > 0 && (
        <div>
          <label className={SECTION_LABEL}>Sektor</label>
          <div className="space-y-0.5 max-h-60 overflow-y-auto pr-1">
            {availableSectors.map((sec) => (
              <CheckRow
                key={sec}
                checked={filters.sectors.has(sec)}
                onChange={() => toggleSector(sec)}
              >
                {sec}
              </CheckRow>
            ))}
          </div>
        </div>
      )}

      {/* Reset */}
      <button
        type="button"
        onClick={resetFilters}
        disabled={!hasFilters}
        className="self-start text-[12px] text-text-muted hover:text-danger transition-colors disabled:opacity-40 disabled:hover:text-text-muted"
      >
        Filter zurücksetzen
      </button>
    </aside>
  )
}
