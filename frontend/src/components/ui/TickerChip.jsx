/** Mono-Ticker-Chip: #161d27-Hintergrund, #232c39-Rand, radius 6px. */
export default function TickerChip({ children, className = '' }) {
  return (
    <span
      className={`inline-flex items-center font-mono text-[11px] font-semibold text-text-primary bg-border-row border border-border-chip rounded-md px-[7px] py-1 whitespace-nowrap ${className}`}
    >
      {children}
    </span>
  )
}
