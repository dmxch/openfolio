export function formatCHF(value, { decimals = 0 } = {}) {
  if (value == null) return '–'
  const abs = Math.abs(value)
  const formatted = abs.toLocaleString('de-CH', {
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
  return value.toLocaleString('de-CH', {
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

export function formatDate(dateStr) {
  if (!dateStr) return '–'
  const d = new Date(dateStr)
  return d.toLocaleDateString('de-CH')
}

export function formatDateTime(dateStr) {
  if (!dateStr) return '–'
  const d = new Date(dateStr)
  return d.toLocaleDateString('de-CH') + ', ' +
    d.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
}

export function formatDateRelative(dateStr) {
  if (!dateStr) return '–'
  const d = new Date(dateStr)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return `Heute, ${d.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })}`
  }
  return d.toLocaleDateString('de-CH')
}
