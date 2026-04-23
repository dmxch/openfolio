const API_BASE = '/api'

export { API_BASE }

// authFetch wird zentral in hooks/useApi.js gepflegt (inkl. 401->Refresh->Retry).
// Frueher existierte hier eine duplizierte Variante ohne Refresh-Logik, die bei
// abgelaufenem Access-Token alle Settings-Klicks stumm scheitern liess.
export { authFetch } from '../../hooks/useApi'

export function Section({ title, children }) {
  return (
    <div className="bg-card border border-border rounded-xl p-5">
      <h3 className="text-sm font-semibold text-text-primary mb-3">{title}</h3>
      {children}
    </div>
  )
}

export function Input({ id, label, type = 'text', value, onChange }) {
  const inputId = id || `settings-${label.toLowerCase().replace(/[^a-z0-9]/g, '-')}`
  return (
    <div>
      <label htmlFor={inputId} className="block text-sm text-text-secondary mb-1">{label}</label>
      <input
        id={inputId}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        className="w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
      />
    </div>
  )
}

export function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}
