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

/**
 * Format a number with the user's number locale.
 * `decimals` sets both min and max fraction digits; pass `minDecimals`
 * to allow fewer digits (e.g. formatNumber(x, 4, { minDecimals: 0 })).
 */
export function formatNumber(value, decimals = 0, { minDecimals } = {}) {
  if (value == null) return '–'
  return value.toLocaleString(getLocale(), {
    minimumFractionDigits: minDecimals ?? decimals,
    maximumFractionDigits: decimals,
  })
}

/**
 * Abbreviate a USD amount with unit suffix ("$1.2B", "$300M", "$5.6T", "$900K").
 * Handles negatives with leading minus before "$". Returns "–" for null/undefined.
 */
export function formatAbbrevUSD(value, { decimals = 1 } = {}) {
  if (value == null || isNaN(value)) return '–'
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  let unit = ''
  let divisor = 1
  if (abs >= 1e12) { unit = 'T'; divisor = 1e12 }
  else if (abs >= 1e9) { unit = 'B'; divisor = 1e9 }
  else if (abs >= 1e6) { unit = 'M'; divisor = 1e6 }
  else if (abs >= 1e3) { unit = 'K'; divisor = 1e3 }
  const scaled = abs / divisor
  // Use 0 decimals when abbreviation covers the magnitude cleanly (>= 100),
  // otherwise the caller-requested precision.
  const dec = scaled >= 100 ? 0 : decimals
  return `${sign}$${scaled.toFixed(dec)}${unit}`
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

const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/

/**
 * Parse a date string. Date-only strings ("YYYY-MM-DD") are parsed as LOCAL
 * dates — `new Date("YYYY-MM-DD")` would parse UTC midnight and shift to the
 * previous day west of UTC. Timestamps keep native parsing (behavior unchanged).
 */
function parseDate(dateStr) {
  if (typeof dateStr === 'string' && DATE_ONLY_RE.test(dateStr)) {
    const [y, m, d] = dateStr.split('-').map(Number)
    return new Date(y, m - 1, d)
  }
  return new Date(dateStr)
}

/**
 * Local YYYY-MM-DD for a Date (default: now). Use instead of
 * `toISOString().split('T')[0]`, which converts to UTC and yields the
 * previous/next day around local midnight.
 */
export function localDateStr(date = new Date()) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function formatDate(dateStr) {
  if (!dateStr) return '–'
  const d = parseDate(dateStr)
  return _formatDateObj(d)
}

/** Compact date (2-digit year), respecting the user's date_format preference. */
export function formatDateShort(dateStr) {
  if (!dateStr) return '–'
  const d = parseDate(dateStr)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const yy = String(d.getFullYear()).slice(-2)
  if (_dateFormat === 'yyyy-mm-dd') {
    return `${yy}-${m}-${day}`
  }
  return d.toLocaleDateString(getLocale(), {
    day: '2-digit', month: '2-digit', year: '2-digit',
  })
}

/** Time only (HH:MM) with the user's number locale. */
export function formatTime(dateStr) {
  if (!dateStr) return '–'
  const d = new Date(dateStr)
  return d.toLocaleTimeString(getLocale(), { hour: '2-digit', minute: '2-digit' })
}

export function formatDateTime(dateStr) {
  if (!dateStr) return '–'
  const d = parseDate(dateStr)
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

/**
 * Volle Tage zwischen `dateStr` und jetzt (>= 0). Liefert null bei fehlender
 * oder ungueltiger Eingabe. Zukunfts-Daten werden auf 0 geklemmt.
 * Genutzt fuer Signal-Frische-Badges im Smart-Money-Detail.
 */
export function daysSince(dateStr) {
  if (!dateStr) return null
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return null
  const diffMs = Date.now() - d.getTime()
  if (diffMs < 0) return 0
  return Math.floor(diffMs / 86400000)
}
