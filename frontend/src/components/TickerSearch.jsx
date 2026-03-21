import { useState, useRef, useEffect, useCallback } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { authFetch } from '../hooks/useApi'

const EXCHANGE_NAMES = {
  'AMS': 'Euronext Amsterdam', 'AS': 'Euronext Amsterdam',
  'LSE': 'LSE', 'L': 'LSE', 'LON': 'LSE',
  'EBS': 'SIX', 'SW': 'SIX', 'SWX': 'SIX',
  'TSX': 'TSX', 'TO': 'TSX', 'TOR': 'TSX',
  'CVE': 'TSXV', 'V': 'TSXV',
  'GER': 'XETRA', 'DE': 'XETRA', 'FRA': 'Frankfurt',
  'PAR': 'Euronext Paris', 'PA': 'Euronext Paris',
  'MIL': 'Borsa Italiana', 'MI': 'Borsa Italiana',
  'MCE': 'BME', 'MC': 'BME',
  'HKG': 'HKEX', 'HK': 'HKEX',
  'JPX': 'TSE', 'T': 'TSE',
  'ASX': 'ASX', 'AX': 'ASX',
  'NSI': 'NSE', 'NS': 'NSE',
  'BSE': 'BSE', 'BO': 'BSE',
  'KSC': 'KRX', 'KS': 'KRX',
  'TAI': 'TWSE', 'TW': 'TWSE',
  'SES': 'SGX', 'SI': 'SGX',
  'JKT': 'IDX', 'JK': 'IDX',
  'SAO': 'B3', 'SA': 'B3',
  'MEX': 'BMV', 'MX': 'BMV',
  'STO': 'Nasdaq Stockholm', 'ST': 'Nasdaq Stockholm',
  'OSL': 'Oslo Børs', 'OL': 'Oslo Børs',
  'NMS': 'NASDAQ', 'NGM': 'NASDAQ', 'NCM': 'NASDAQ',
  'NYQ': 'NYSE', 'NYS': 'NYSE',
  'PCX': 'NYSE Arca', 'ASE': 'NYSE MKT',
  'BTS': 'BATS',
}

function getExchangeName(exchange, ticker) {
  if (exchange && EXCHANGE_NAMES[exchange]) return EXCHANGE_NAMES[exchange]
  // Derive from ticker suffix
  if (ticker && ticker.includes('.')) {
    const suffix = ticker.split('.').pop()
    if (EXCHANGE_NAMES[suffix]) return EXCHANGE_NAMES[suffix]
  }
  return exchange || 'NYSE/NASDAQ'
}

function getBaseTicker(ticker) {
  return ticker ? ticker.split('.')[0] : ticker
}

export default function TickerSearch({ id, value, onChange, onSelect, onSubmit, placeholder, autoFocus, className = '' }) {
  const [suggestions, setSuggestions] = useState([])
  const [showDropdown, setShowDropdown] = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const debounceRef = useRef(null)
  const wrapperRef = useRef(null)
  const inputRef = useRef(null)

  const fetchSuggestions = useCallback(async (query) => {
    if (!query || query.length < 1) {
      setSuggestions([])
      setShowDropdown(false)
      return
    }
    setLoading(true)
    try {
      const resp = await authFetch(`/api/search/symbols?q=${encodeURIComponent(query)}&limit=8`)
      const data = await resp.json()
      setSuggestions(data.results || [])
      setShowDropdown(true)
    } catch {
      setSuggestions([])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleChange = (e) => {
    const val = e.target.value
    onChange(val)
    setActiveIndex(-1)

    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchSuggestions(val), 300)
  }

  const handleSelect = (suggestion) => {
    setShowDropdown(false)
    setSuggestions([])
    setActiveIndex(-1)
    onSelect?.(suggestion)
  }

  const handleKeyDown = (e) => {
    if (!showDropdown || suggestions.length === 0) {
      if (e.key === 'Enter') {
        e.preventDefault()
        onSubmit?.()
      }
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeIndex >= 0 && activeIndex < suggestions.length) {
        handleSelect(suggestions[activeIndex])
      } else {
        setShowDropdown(false)
        onSubmit?.()
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
      setActiveIndex(-1)
    }
  }

  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => () => clearTimeout(debounceRef.current), [])

  return (
    <div ref={wrapperRef} className={`relative ${className}`}>
      <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted z-10" />
      {loading && <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted animate-spin z-10" />}
      <input
        id={id}
        ref={inputRef}
        type="text"
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onFocus={() => { if (suggestions.length > 0) setShowDropdown(true) }}
        placeholder={placeholder || 'Ticker suchen...'}
        autoFocus={autoFocus}
        className="w-full bg-card border border-border rounded-lg pl-10 pr-4 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
      />

      {showDropdown && suggestions.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-card border border-border rounded-xl shadow-xl overflow-hidden max-h-80 overflow-y-auto">
          {suggestions.map((s, i) => (
            <button
              key={`${s.ticker}-${i}`}
              onClick={() => handleSelect(s)}
              className={`w-full flex items-center justify-between px-4 py-2.5 text-left transition-colors ${
                i === activeIndex ? 'bg-primary/10' : 'hover:bg-card-alt'
              }`}
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="text-primary font-mono font-bold text-sm w-16 shrink-0">
                  {getBaseTicker(s.ticker)}
                </span>
                <span className="text-text-primary text-sm truncate">{s.name}</span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0 ml-2">
                {s.type && (
                  <span className="text-[10px] text-text-muted bg-card-alt px-1.5 py-0.5 rounded">
                    {s.type}
                  </span>
                )}
                <span className="text-[10px] text-text-muted bg-card-alt px-1.5 py-0.5 rounded min-w-[32px] text-center">
                  {getExchangeName(s.exchange, s.ticker)}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
