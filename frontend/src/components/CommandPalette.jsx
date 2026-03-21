import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Briefcase, Eye, FileText, Zap, X } from 'lucide-react'
import { usePortfolioData, useWatchlistData } from '../contexts/DataContext'
import { useAuth } from '../contexts/AuthContext'

const PAGES = [
  { label: 'Markt & Sektoren', path: '/' },
  { label: 'Portfolio', path: '/portfolio' },
  { label: 'Watchlist', path: '/analysis' },
  { label: 'Transaktionen', path: '/transactions' },
  { label: 'Einstellungen', path: '/settings' },
  { label: 'Hilfe', path: '/hilfe' },
  { label: 'Glossar', path: '/hilfe#glossar-link' },
  { label: 'Rechtliches', path: '/rechtliches' },
  { label: 'Datenschutz', path: '/rechtliches#datenschutz' },
  { label: 'Disclaimer', path: '/rechtliches#disclaimer' },
  { label: 'Nutzungsbedingungen', path: '/nutzungsbedingungen' },
  { label: 'Impressum', path: '/rechtliches#impressum' },
]

const ACTIONS = [
  { label: 'CSV Import', path: '/transactions', query: '?import=true' },
]

export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const navigate = useNavigate()
  const { user } = useAuth()

  const { positions } = usePortfolioData()
  const { items: watchlist } = useWatchlistData()

  // Keyboard shortcut to open
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery('')
      setActiveIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  const q = query.toLowerCase().trim()

  const filteredItems = useMemo(() => {
    const items = []

    // Portfolio positions
    const filteredPositions = positions.filter(p =>
      !q || p.ticker?.toLowerCase().includes(q) || p.name?.toLowerCase().includes(q)
    )
    if (filteredPositions.length > 0) {
      items.push({ type: 'header', label: 'Portfolio' })
      filteredPositions.slice(0, 5).forEach(p => {
        items.push({
          type: 'position',
          label: `${p.ticker} — ${p.name}`,
          ticker: p.ticker,
          detail: p.current_price ? `${p.currency || 'CHF'} ${p.current_price.toFixed(2)}` : '',
          action: () => navigate(`/stock/${p.ticker}`),
        })
      })
    }

    // Watchlist
    const filteredWatchlist = watchlist.filter(w =>
      !q || w.ticker?.toLowerCase().includes(q) || w.name?.toLowerCase().includes(q)
    )
    if (filteredWatchlist.length > 0) {
      items.push({ type: 'header', label: 'Watchlist' })
      filteredWatchlist.slice(0, 5).forEach(w => {
        items.push({
          type: 'watchlist',
          label: `${w.ticker} — ${w.name || w.ticker}`,
          ticker: w.ticker,
          action: () => navigate(`/stock/${w.ticker}`),
        })
      })
    }

    // Pages
    const filteredPages = PAGES.filter(p => !q || p.label.toLowerCase().includes(q))
    if (filteredPages.length > 0) {
      items.push({ type: 'header', label: 'Seiten' })
      filteredPages.forEach(p => {
        items.push({
          type: 'page',
          label: p.label,
          action: () => navigate(p.path),
        })
      })
    }

    // Admin page
    if (user?.is_admin && (!q || 'admin'.includes(q))) {
      if (!filteredPages.length) items.push({ type: 'header', label: 'Seiten' })
      items.push({
        type: 'page',
        label: 'Admin',
        action: () => navigate('/admin'),
      })
    }

    // Actions
    const filteredActions = ACTIONS.filter(a => !q || a.label.toLowerCase().includes(q))
    if (filteredActions.length > 0) {
      items.push({ type: 'header', label: 'Aktionen' })
      filteredActions.forEach(a => {
        items.push({
          type: 'action',
          label: a.label,
          action: () => navigate(a.path + (a.query || '')),
        })
      })
    }

    // Fallback: search ticker
    if (q && items.filter(i => i.type !== 'header').length === 0) {
      items.push({ type: 'header', label: 'Suche' })
      items.push({
        type: 'search',
        label: `Ticker "${query.toUpperCase()}" analysieren`,
        action: () => navigate(`/stock/${query.toUpperCase()}`),
      })
    }

    return items
  }, [q, positions, watchlist, user, navigate, query])

  const selectableItems = useMemo(
    () => filteredItems.filter(i => i.type !== 'header'),
    [filteredItems]
  )

  const select = useCallback((item) => {
    if (item?.action) {
      item.action()
      setOpen(false)
    }
  }, [])

  // Keyboard navigation
  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex(i => Math.min(i + 1, selectableItems.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      select(selectableItems[activeIndex])
    }
  }

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return
    const active = listRef.current.querySelector('[data-active="true"]')
    active?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  // Reset active index when results change
  useEffect(() => {
    setActiveIndex(0)
  }, [q])

  if (!open) return null

  const iconForType = (type) => {
    switch (type) {
      case 'position': return <Briefcase size={14} className="text-primary" />
      case 'watchlist': return <Eye size={14} className="text-warning" />
      case 'page': return <FileText size={14} className="text-text-muted" />
      case 'action': return <Zap size={14} className="text-success" />
      case 'search': return <Search size={14} className="text-text-muted" />
      default: return null
    }
  }

  let selectableIndex = -1

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh]">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />

      {/* Palette */}
      <div className="relative w-full max-w-lg mx-4 bg-card border border-border rounded-xl shadow-2xl overflow-hidden">
        {/* Input */}
        <div className="flex items-center gap-3 px-4 border-b border-border">
          <label htmlFor="cmd-palette-search" className="sr-only">Suchen</label>
          <Search size={16} className="text-text-muted shrink-0" />
          <input
            id="cmd-palette-search"
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Suchen..."
            aria-label="Befehl oder Seite suchen"
            className="flex-1 py-3 bg-transparent text-text-primary text-sm outline-none placeholder:text-text-muted"
          />
          <button
            onClick={() => setOpen(false)}
            className="text-text-muted hover:text-text-primary transition-colors"
          >
            <kbd className="text-[10px] bg-card-alt border border-border rounded px-1.5 py-0.5 font-mono">Esc</kbd>
          </button>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-y-auto py-2">
          {filteredItems.length === 0 ? (
            <div className="px-4 py-8 text-center text-text-muted text-sm">
              Keine Ergebnisse
            </div>
          ) : (
            filteredItems.map((item, i) => {
              if (item.type === 'header') {
                return (
                  <div key={`h-${i}`} className="px-4 pt-3 pb-1 text-[11px] font-semibold text-text-muted uppercase tracking-wider">
                    {item.label}
                  </div>
                )
              }

              selectableIndex++
              const isActive = selectableIndex === activeIndex

              return (
                <button
                  key={`${item.type}-${item.label}-${i}`}
                  data-active={isActive}
                  onClick={() => select(item)}
                  className={`w-full flex items-center gap-3 px-4 py-2 text-sm text-left transition-colors ${
                    isActive ? 'bg-primary/15 text-text-primary' : 'text-text-secondary hover:bg-card-alt hover:text-text-primary'
                  }`}
                >
                  {iconForType(item.type)}
                  <span className="flex-1 truncate">{item.label}</span>
                  {item.detail && (
                    <span className="text-xs text-text-muted">{item.detail}</span>
                  )}
                </button>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
