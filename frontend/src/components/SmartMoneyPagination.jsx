import { ChevronLeft, ChevronRight } from 'lucide-react'

/**
 * Pagination-Footer fuer den SmartMoney-Grid. Server-Side-Pagination.
 * Disabled-States an den Enden; nichts rendern wenn nur 1 Page.
 */
export default function SmartMoneyPagination({ currentPage, totalPages, totalItems, onPageChange }) {
  if (totalPages <= 1) {
    return (
      <div className="mt-2 text-xs text-text-muted font-mono">
        {totalItems ?? 0} Ticker
      </div>
    )
  }

  const canPrev = currentPage > 1
  const canNext = currentPage < totalPages

  return (
    <div className="mt-3 flex items-center justify-between text-xs">
      <span className="text-text-muted font-mono">
        Seite {currentPage} von {totalPages} · {totalItems} Ticker
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(currentPage - 1)}
          disabled={!canPrev}
          aria-label="Vorherige Seite"
          className={`inline-flex items-center gap-1 px-2 py-1 rounded border border-border transition-colors ${
            canPrev
              ? 'text-text-primary hover:bg-card-hover'
              : 'text-text-muted opacity-50 cursor-not-allowed'
          }`}
        >
          <ChevronLeft size={14} />
          Zurück
        </button>
        <button
          onClick={() => onPageChange(currentPage + 1)}
          disabled={!canNext}
          aria-label="Nächste Seite"
          className={`inline-flex items-center gap-1 px-2 py-1 rounded border border-border transition-colors ${
            canNext
              ? 'text-text-primary hover:bg-card-hover'
              : 'text-text-muted opacity-50 cursor-not-allowed'
          }`}
        >
          Weiter
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}
