/**
 * Farbige Mini-Badges. Generisches <Badge> mit color/bg, plus <TypeBadge>
 * fuer Anlageklassen / Buchungstypen / Order-Status mit eingebauter Farb-Map.
 */
export function Badge({ color, bg, border, className = '', children }) {
  return (
    <span
      className={`inline-flex items-center text-[10.5px] font-medium rounded-[5px] px-[7px] py-[3px] leading-none ${className}`}
      style={{ color, background: bg, ...(border ? { border: `1px solid ${border}` } : {}) }}
    >
      {children}
    </span>
  )
}

// [text, background-tint]
const tint = (hex, a = 0.13) => {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255
  return `rgba(${r},${g},${b},${a})`
}

const CLASS_COLORS = {
  Aktien: '#5b8def', stock: '#5b8def',
  ETF: '#29c3b1', etf: '#29c3b1',
  Krypto: '#b06ee8', crypto: '#b06ee8',
  Edelmetall: '#e0a64b', commodity: '#e0a64b',
  Immobilien: '#6b8aa0', real_estate: '#6b8aa0',
  'Private Equity': '#8a7de0', private_equity: '#8a7de0',
  Cash: '#7a8698', cash: '#7a8698',
  Vorsorge: '#45c08a', pension: '#45c08a',
}

const TXN_COLORS = {
  Kauf: '#5b8def', buy: '#5b8def',
  Verkauf: '#e0a64b', sell: '#e0a64b',
  Dividende: '#45c08a', dividend: '#45c08a',
  Gebühr: '#7a8698', fee: '#7a8698',
  Einzahlung: '#29c3b1', deposit: '#29c3b1',
  Steuer: '#e8625a', tax: '#e8625a',
}

/** Anlageklassen-Badge (label + Farbe aus Map). */
export function TypeBadge({ label, kind = 'class', className = '' }) {
  const map = kind === 'txn' ? TXN_COLORS : CLASS_COLORS
  const color = map[label] || '#7a8698'
  return <Badge color={color} bg={tint(color)} className={className}>{label}</Badge>
}

export { tint }
