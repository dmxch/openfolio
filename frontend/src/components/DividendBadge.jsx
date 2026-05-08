import { useDividendCount } from '../contexts/DividendCountContext'

/**
 * Kleiner Pip-Counter für offene Pending-Dividenden.
 * Wird in der Sidebar am "Transaktionen"-Eintrag angezeigt, analog AlertBadge.
 * Null-Render wenn count === 0.
 */
export default function DividendBadge() {
  const { count } = useDividendCount()
  if (!count) return null
  return (
    <span
      className="bg-warning text-white text-xs font-bold px-1.5 py-0.5 rounded-full"
      aria-label={`${count} offene Dividende${count === 1 ? '' : 'n'}`}
    >
      {count}
    </span>
  )
}
