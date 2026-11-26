import { useEffect, useRef, useState, useMemo } from 'react'
import useIsMobile from '../hooks/useIsMobile'
import { ShoppingCart, TrendingDown, Pencil, Trash2, Shield, ArrowDownCircle, ArrowUpCircle, RefreshCw, Banknote } from 'lucide-react'

const ALL_ITEMS = [
  // Stocks & ETFs
  { key: 'buy', label: 'Kaufen', icon: ShoppingCart, color: 'text-success', types: ['stock', 'etf', 'bond', 'crypto', 'commodity'] },
  { key: 'sell', label: 'Verkaufen', icon: TrendingDown, color: 'text-warning', types: ['stock', 'etf', 'bond', 'crypto', 'commodity'] },
  { key: 'dividend', label: 'Dividende erfassen', icon: Banknote, color: 'text-primary', types: ['stock', 'etf', 'bond'] },
  // Stop-Loss ohne 'bond': Anleihen unterliegen keiner Stop-Loss-Pflicht — ein
  // defensiver Anleihen-Sleeve wird nicht über Stops bewirtschaftet.
  { key: 'stop_loss', label: 'Stop-Loss anpassen', icon: Shield, color: 'text-warning', types: ['stock', 'etf', 'crypto'] },
  // Phase 3 (v0.40): "Typ aendern" entfernt — Bucket-Wechsel via Edit-Modal "Bucket"-Dropdown.
  // Cash
  { key: 'deposit', label: 'Einzahlung erfassen', icon: ArrowDownCircle, color: 'text-success', types: ['cash'] },
  { key: 'withdrawal', label: 'Entnahme erfassen', icon: ArrowUpCircle, color: 'text-warning', types: ['cash'] },
  // Pension
  { key: 'deposit', label: 'Einzahlung erfassen', icon: ArrowDownCircle, color: 'text-success', types: ['pension'] },
  { key: 'update_value', label: 'Wert aktualisieren', icon: RefreshCw, color: 'text-primary', types: ['pension', 'real_estate'] },
  // Common
  { key: 'edit', label: 'Bearbeiten', icon: Pencil, color: 'text-primary', types: null },
  { key: 'delete', label: 'Löschen', icon: Trash2, color: 'text-danger', types: null },
]

// Mobil (< md) erscheint das Menue als unten angedocktes Aktionsblatt; `title`
// (z.B. Positionsname) ist dort die Kopfzeile. Desktop positioniert per x/y.
export default function ContextMenu({ x, y, onAction, onClose, positionType, title }) {
  const isMobile = useIsMobile()
  const ref = useRef(null)
  const [focusIdx, setFocusIdx] = useState(0)

  const visibleItems = useMemo(
    () => ALL_ITEMS.filter((item) => item.types === null || item.types.includes(positionType)),
    [positionType]
  )

  useEffect(() => {
    const handleClick = (e) => {
      // Mobil schliesst das Antippen des Hintergrunds (onClick am Backdrop); ein
      // mousedown-Schliessen entfernte den Backdrop vor dem Klick und liesse
      // diesen auf das Element darunter durchfallen.
      if (isMobile) return
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    const handleKeyDown = (e) => {
      switch (e.key) {
        case 'Escape':
          e.preventDefault()
          onClose()
          break
        case 'ArrowDown':
          e.preventDefault()
          setFocusIdx((prev) => (prev + 1) % visibleItems.length)
          break
        case 'ArrowUp':
          e.preventDefault()
          setFocusIdx((prev) => (prev - 1 + visibleItems.length) % visibleItems.length)
          break
        case 'Enter':
        case ' ':
          e.preventDefault()
          onAction(visibleItems[focusIdx].key)
          onClose()
          break
        case 'Home':
          e.preventDefault()
          setFocusIdx(0)
          break
        case 'End':
          e.preventDefault()
          setFocusIdx(visibleItems.length - 1)
          break
      }
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose, onAction, visibleItems, focusIdx, isMobile])

  useEffect(() => {
    const btns = ref.current?.querySelectorAll('[role="menuitem"]')
    btns?.[focusIdx]?.focus()
  }, [focusIdx])

  // Keep menu within viewport
  const style = { position: 'fixed', zIndex: 50 }
  if (typeof window !== 'undefined') {
    const menuW = 180
    const menuH = visibleItems.length * 40 + 8
    style.left = x + menuW > window.innerWidth ? x - menuW : x
    style.top = y + menuH > window.innerHeight ? y - menuH : y
  }

  if (isMobile) {
    return (
      <div className="fixed inset-0 z-[70] flex items-end bg-[#04070c]/[0.6]" onClick={onClose}>
        <div
          ref={ref}
          role="menu"
          aria-label={title ? `Aktionen für ${title}` : 'Aktionen'}
          onClick={(e) => e.stopPropagation()}
          className="w-full bg-modal border-t border-border-hover rounded-t-[14px] shadow-2xl pt-1 pb-[calc(8px+env(safe-area-inset-bottom))] max-h-[80dvh] overflow-y-auto"
        >
          {title && (
            <div className="px-4 py-2.5 text-[11.5px] font-mono text-text-muted truncate border-b border-border-2">{title}</div>
          )}
          {visibleItems.map((item, i) => {
            const isDanger = item.color === 'text-danger'
            return (
              <button
                key={`${item.key}-${i}`}
                role="menuitem"
                tabIndex={i === focusIdx ? 0 : -1}
                onClick={() => { onAction(item.key); onClose() }}
                className={`w-full flex items-center gap-3 px-4 min-h-[48px] text-sm text-left active:bg-hover ${isDanger ? 'text-danger' : 'text-text-primary'}`}
              >
                <item.icon size={17} className={item.color} />
                <span>{item.label}</span>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div ref={ref} style={style} role="menu" aria-label="Aktionen" className="bg-modal border border-border-hover rounded-lg shadow-2xl py-1 min-w-[170px]">
      {visibleItems.map((item, i) => {
        const isDanger = item.color === 'text-danger'
        const focused = i === focusIdx
        return (
          <button
            key={`${item.key}-${i}`}
            role="menuitem"
            tabIndex={focused ? 0 : -1}
            onClick={() => { onAction(item.key); onClose() }}
            onMouseEnter={() => setFocusIdx(i)}
            className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors ${isDanger ? 'text-danger' : 'text-text-primary'} ${isDanger ? 'hover:bg-danger/10' : 'hover:bg-hover'} ${focused ? (isDanger ? 'bg-danger/10' : 'bg-hover') : ''}`}
          >
            <item.icon size={15} className={item.color} />
            <span>{item.label}</span>
          </button>
        )
      })}
    </div>
  )
}
