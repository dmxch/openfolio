const API_BASE = '/api'

export { API_BASE }

// authFetch wird zentral in hooks/useApi.js gepflegt (inkl. 401->Refresh->Retry).
// Frueher existierte hier eine duplizierte Variante ohne Refresh-Logik, die bei
// abgelaufenem Access-Token alle Settings-Klicks stumm scheitern liess.
export { authFetch } from '../../hooks/useApi'

/** Settings-Karte: bg-card, 1px border, radius 11px, Titel oben. */
export function Section({ title, desc, children }) {
  return (
    <div className="bg-card border border-border rounded-card p-5">
      {(title || desc) && (
        <div className="mb-4">
          {title && <h3 className="text-sm font-semibold text-text-primary">{title}</h3>}
          {desc && <p className="text-xs text-text-muted mt-1">{desc}</p>}
        </div>
      )}
      {children}
    </div>
  )
}

export function Input({ id, label, type = 'text', value, onChange }) {
  const inputId = id || `settings-${label.toLowerCase().replace(/[^a-z0-9]/g, '-')}`
  return (
    <div>
      <label htmlFor={inputId} className="block text-xs font-medium text-text-muted mb-1">{label}</label>
      <input
        id={inputId}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
      />
    </div>
  )
}

export function Select({ value, onChange, options, id }) {
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}

/**
 * Pill-Toggle (Switch). bg-primary-btn wenn an, bg-surface wenn aus.
 * Funktional ein boolescher Schalter — ersetzt rohe Checkboxen 1:1.
 */
export function Toggle({ checked, onChange, disabled = false, ariaLabel }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-[20px] w-[34px] shrink-0 items-center rounded-full border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        checked ? 'bg-primary-btn border-primary-btn-border' : 'bg-surface border-border'
      }`}
    >
      <span
        className={`inline-block h-[14px] w-[14px] rounded-full bg-white shadow-sm transition-transform ${
          checked ? 'translate-x-[16px]' : 'translate-x-[2px]'
        }`}
      />
    </button>
  )
}
