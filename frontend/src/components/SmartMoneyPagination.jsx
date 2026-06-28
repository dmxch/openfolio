import { ChevronLeft, ChevronRight } from 'lucide-react'

/**
 * Pagination-Footer (generisch, auch von der EPS-Seite genutzt). Server-Side-
 * Pagination. Disabled-States an den Enden; bei nur 1 Seite nur die Total-Zeile.
 */
export default function SmartMoneyPagination({ currentPage, totalPages, totalItems, onPageChange }) {
  if (totalPages <= 1) {
    return (
      <div className="mt-4 font-mono text-[11.5px] text-text-faint tabular-nums">
        {totalItems ?? 0} Ticker
      </div>
    )
  }

  const canPrev = currentPage > 1
  const canNext = currentPage < totalPages

  const navBtn = (enabled) =>
    `inline-flex items-center gap-1.5 px-3 py-[7px] rounded-lg text-[12.5px] font-medium border transition-colors ${
      enabled
        ? 'bg-surface border-border-2 text-text-secondary hover:border-border-hover'
        : 'bg-surface border-border-2 text-text-faint opacity-40 cursor-not-allowed'
    }`

  return (
    <div className="mt-4 flex items-center justify-between">
      <span className="font-mono text-[11.5px] text-text-faint tabular-nums">
        Seite {currentPage} von {totalPages} · {totalItems} Ticker
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(currentPage - 1)}
          disabled={!canPrev}
          aria-label="Vorherige Seite"
          className={navBtn(canPrev)}
        >
          <ChevronLeft size={14} />
          Zurück
        </button>
        <button
          onClick={() => onPageChange(currentPage + 1)}
          disabled={!canNext}
          aria-label="Nächste Seite"
          className={navBtn(canNext)}
        >
          Weiter
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}
