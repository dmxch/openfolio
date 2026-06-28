import { Bell } from 'lucide-react'

/**
 * Sticky Seiten-Header (Titel + Mono-Untertitel + Aktionen + Suche + Glocke).
 * Bricht via negativer Margins aus dem Padding des <main> in Layout aus, damit
 * er randlos ueber die volle Breite klebt — Layout muss dafuer NICHT angepasst
 * werden und nicht-migrierte Seiten bleiben unveraendert.
 */
function openPalette() {
  window.dispatchEvent(new CustomEvent('openCommandPalette'))
}

export default function PageHeader({
  title,
  subtitle,
  actions,
  showSearch = true,
  showBell = true,
  alertCount = 0,
  onBellClick,
}) {
  return (
    <header className="sticky top-0 z-30 -mx-4 md:-mx-6 -mt-4 md:-mt-6 mb-4 md:mb-[18px] flex items-center gap-3 md:gap-4 px-4 md:px-6 py-[14px] border-b border-border-soft bg-body/[0.86] backdrop-blur-md">
      <div className="flex items-baseline gap-3 min-w-0">
        <h1 className="text-[17px] md:text-[19px] font-semibold tracking-[-0.01em] text-text-primary whitespace-nowrap">
          {title}
        </h1>
        {subtitle && (
          <span className="font-mono text-[11.5px] text-text-faint truncate hidden sm:inline">
            {subtitle}
          </span>
        )}
      </div>
      <div className="flex-1" />
      {actions}
      {showSearch && (
        <button
          onClick={openPalette}
          className="hidden md:flex items-center gap-[10px] bg-surface border border-border rounded-lg px-3 py-[7px] text-text-muted text-[12.5px] hover:border-border-hover transition-colors"
        >
          Suchen
          <kbd className="font-mono text-[11px] bg-border-soft border border-border-hover rounded px-[5px] py-px text-text-muted">
            ⌘K
          </kbd>
        </button>
      )}
      {showBell && (
        <button
          onClick={onBellClick}
          className="relative w-9 h-9 rounded-lg bg-surface border border-border text-text-muted hover:border-border-hover transition-colors flex items-center justify-center"
          aria-label="Benachrichtigungen"
        >
          <Bell size={16} />
          {alertCount > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-lg bg-danger text-white text-[10px] font-semibold flex items-center justify-center">
              {alertCount}
            </span>
          )}
        </button>
      )}
    </header>
  )
}
