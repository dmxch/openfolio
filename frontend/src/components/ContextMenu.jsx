import { useEffect, useRef, useState, useMemo } from 'react'
import { ShoppingCart, TrendingDown, Pencil, Trash2, Shield, ArrowDownCircle, ArrowUpCircle, RefreshCw } from 'lucide-react'

const ALL_ITEMS = [
  // Stocks & ETFs
  { key: 'buy', label: 'Kaufen', icon: ShoppingCart, color: 'text-success', types: ['stock', 'etf', 'crypto', 'commodity'] },
  { key: 'sell', label: 'Verkaufen', icon: TrendingDown, color: 'text-warning', types: ['stock', 'etf', 'crypto', 'commodity'] },
  { key: 'stop_loss', label: 'Stop-Loss anpassen', icon: Shield, color: 'text-warning', types: ['stock', 'etf', 'crypto'] },
  { key: 'change_type', label: 'Typ ändern', icon: RefreshCw, color: 'text-text-secondary', types: ['stock', 'etf'] },
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

export default function ContextMenu({ x, y, onAction, onClose, positionType }) {
  const ref = useRef(null)
  const [focusIdx, setFocusIdx] = useState(0)

  const visibleItems = useMemo(
    () => ALL_ITEMS.filter((item) => item.types === null || item.types.includes(positionType)),
    [positionType]
  )

  useEffect(() => {
    const handleClick = (e) => {
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
  }, [onClose, onAction, visibleItems, focusIdx])

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

  return (
    <div ref={ref} style={style} role="menu" aria-label="Aktionen" className="bg-card border border-border rounded-lg shadow-xl py-1 min-w-[170px]">
      {visibleItems.map((item, i) => (
        <button
          key={`${item.key}-${i}`}
          role="menuitem"
          tabIndex={i === focusIdx ? 0 : -1}
          onClick={() => { onAction(item.key); onClose() }}
          onMouseEnter={() => setFocusIdx(i)}
          className={`w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors ${i === focusIdx ? 'bg-card-alt' : ''}`}
        >
          <item.icon size={15} className={item.color} />
          <span>{item.label}</span>
        </button>
      ))}
    </div>
  )
}
