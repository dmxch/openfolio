import { useId } from 'react'

/**
 * OpenFolio-Logo: geometrische Wortmarke mit offenem Ring (blau→teal).
 * `wordmark={false}` zeigt nur die Marke (z.B. kollabierte Sidebar / Icon).
 */
export default function Logo({ size = 26, wordmark = true, wordmarkSize = 15, className = '' }) {
  const gid = 'of-logo-' + useId().replace(/:/g, '')
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg viewBox="0 0 100 100" width={size} height={size} className="block shrink-0" aria-hidden="true">
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#5b8def" />
            <stop offset="100%" stopColor="#29c3b1" />
          </linearGradient>
        </defs>
        <circle cx="50" cy="50" r="34" fill="none" stroke={`url(#${gid})`} strokeWidth="13" strokeLinecap="round" strokeDasharray="176 38" transform="rotate(-52 50 50)" />
        <circle cx="78" cy="32" r="7" fill="#29c3b1" />
      </svg>
      {wordmark && (
        <span className="font-semibold tracking-[-0.01em] text-text-primary truncate" style={{ fontSize: wordmarkSize }}>
          Open<span className="text-[#9fb6e6]">Folio</span>
        </span>
      )}
    </span>
  )
}
