/**
 * Filter-Chip-Leiste. options: [{ key, label, count? }].
 * Aktiver Chip = blauer Tint; Zaehler in Mono.
 */
export default function FilterChips({ options, value, onChange, className = '' }) {
  return (
    <div className={`flex items-center gap-2 flex-wrap ${className}`}>
      {options.map((o) => {
        const on = o.key === value
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onChange(o.key)}
            className={`flex items-center gap-[7px] text-[12.5px] font-medium px-3 py-[7px] rounded-lg border transition-colors ${
              on
                ? 'bg-active-tint border-border-active text-text-bright'
                : 'bg-surface border-border-2 text-text-muted hover:border-border-hover'
            }`}
          >
            {o.label}
            {o.count != null && (
              <span className="font-mono text-[10.5px] text-text-label">{o.count}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}
