// --- Configurable format settings (module-level state) ---
// number_format: 'ch' | 'de' | 'en'
// date_format: 'dd.mm.yyyy' | 'yyyy-mm-dd'

const LOCALE_MAP = {
  ch: 'de-CH',
  de: 'de-DE',
  en: 'en-US',
}

let _numberFormat = 'ch'
let _dateFormat = 'dd.mm.yyyy'

/** Configure format settings from user preferences (call after settings load). */
export function configureFormats({ number_format, date_format } = {}) {
  if (number_format && LOCALE_MAP[number_format]) _numberFormat = number_format
  if (date_format) _dateFormat = date_format
}

/** Get current number locale string for toLocaleString(). */
function getLocale() {
  return LOCALE_MAP[_numberFormat] || 'de-CH'
}

export function formatCHF(value, { decimals = 0 } = {}) {
  if (value == null) return '–'
  const abs = Math.abs(value)
  const formatted = abs.toLocaleString(getLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return value < 0 ? `CHF -${formatted}` : `CHF ${formatted}`
}

/** @deprecated Use formatCHF(value, { decimals: 2 }) instead */
export function formatCHFExact(value) {
  return formatCHF(value, { decimals: 2 })
}

export function formatPct(value) {
  if (value == null) return '–'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

export function formatNumber(value, decimals = 0) {
  if (value == null) return '–'
  return value.toLocaleString(getLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function pnlColor(value) {
  if (value > 0) return 'text-success'
  if (value < 0) return 'text-danger'
  return 'text-text-secondary'
}

export function climateColor(status) {
  if (status === 'bullish') return 'text-success'
  if (status === 'bearish') return 'text-danger'
  return 'text-warning'
}

export function climateBg(status) {
  if (status === 'bullish') return 'bg-success/10 border-success/30'
  if (status === 'bearish') return 'bg-danger/10 border-danger/30'
  return 'bg-warning/10 border-warning/30'
}

/** Format a date string according to user's date_format preference. */
function _formatDateObj(d) {
  if (_dateFormat === 'yyyy-mm-dd') {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  return d.toLocaleDateString(getLocale())
}

export function formatDate(dateStr) {
  if (!dateStr) return '–'
  const d = new Date(dateStr)
  return _formatDateObj(d)
}

export function formatDateTime(dateStr) {
  if (!dateStr) return '–'
  const d = new Date(dateStr)
  return _formatDateObj(d) + ', ' +
    d.toLocaleTimeString(getLocale(), { hour: '2-digit', minute: '2-digit' })
}

export function formatDateRelative(dateStr) {
  if (!dateStr) return '–'
  const d = new Date(dateStr)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return `Heute, ${d.toLocaleTimeString(getLocale(), { hour: '2-digit', minute: '2-digit' })}`
  }
  return _formatDateObj(d)
}
