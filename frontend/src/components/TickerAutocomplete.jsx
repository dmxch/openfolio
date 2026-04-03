import { useState, useEffect, useCallback, useRef } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { authFetch } from '../hooks/useApi'

const INPUT = 'bg-card border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

export default function TickerAutocomplete({ positions, value, onChange, disabled }) {
  const [query, setQuery] = useState(value?.ticker || '')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const searchTimer = useRef(null)
  const wrapperRef = useRef(null)

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Search logic: local positions first, then API
  const doSearch = useCallback((q) => {
    if (!q || q.length < 1) { setResults([]); setOpen(false); return }

    const term = q.toUpperCase()

    // Local matches from existing positions
    const local = (positions || [])
      .filter((p) => p.ticker.toUpperCase().includes(term) || (p.name || '').toUpperCase().includes(term))
      .slice(0, 5)
      .map((p) => ({ ticker: p.ticker, name: p.name, type: p.type, currency: p.currency, position_id: p.id, is_existing: true }))

    setResults(local)
    setOpen(true)

    // Remote search (debounced)
    clearTimeout(searchTimer.current)
    if (q.length >= 2) {
      searchTimer.current = setTimeout(async () => {
        setSearching(true)
        try {
          const res = await authFetch(`/api/stock/search?q=${encodeURIComponent(q)}`)
          if (res.ok) {
            const data = await res.json()
            setResults(data)
            setOpen(true)
          }
        } catch { /* ignore */ } finally {
          setSearching(false)
        }
      }, 300)
    }
  }, [positions])

  useEffect(() => () => clearTimeout(searchTimer.current), [])

  const handleSelect = (item) => {
    setQuery(`${item.ticker} — ${item.name}`)
    setOpen(false)
    onChange(item)
  }

  const handleInputChange = (e) => {
    const v = e.target.value
    setQuery(v)
    // If user clears or changes text, reset selection
    onChange(null)
    doSearch(v)
  }

  return (
    <div ref={wrapperRef} className="relative">
      <label htmlFor="txnpage-ticker" className={LABEL}>Ticker / Position *</label>
      <div className="relative">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
        <input
          id="txnpage-ticker"
          value={query}
          onChange={handleInputChange}
          onFocus={() => { if (query.length >= 1) doSearch(query) }}
          placeholder="z.B. AAPL, Novartis, BTC..."
          disabled={disabled}
          autoComplete="off"
          className={`${INPUT} w-full pl-8 ${disabled ? 'opacity-60' : ''}`}
        />
        {searching && <Loader2 size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-text-muted" />}
      </div>
      {open && results.length > 0 && (
        <ul className="absolute z-50 w-full mt-1 bg-card border border-border rounded-lg shadow-lg max-h-56 overflow-y-auto">
          {results.map((item, i) => (
            <li key={`${item.ticker}-${i}`}>
              <button
                type="button"
                onClick={() => handleSelect(item)}
                className="w-full text-left px-3 py-2 hover:bg-card-alt/60 transition-colors flex items-center gap-2"
              >
                <span className="font-mono text-primary font-medium text-sm">{item.ticker}</span>
                <span className="text-text-secondary text-xs truncate flex-1">{item.name}</span>
                {item.is_existing ? (
                  <span className="text-[10px] text-success bg-success/10 border border-success/20 rounded px-1.5 py-0.5 shrink-0">Vorhanden</span>
                ) : (
                  <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 rounded px-1.5 py-0.5 shrink-0">Neu</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && query.length >= 2 && results.length === 0 && !searching && (
        <div className="absolute z-50 w-full mt-1 bg-card border border-border rounded-lg shadow-lg px-3 py-3 text-sm text-text-muted">
          Kein Ergebnis für «{query}»
        </div>
      )}
    </div>
  )
}
