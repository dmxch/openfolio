import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import WatchlistTable from '../components/WatchlistTable'
import TickerSearch from '../components/TickerSearch'
import DisclaimerBanner from '../components/DisclaimerBanner'
import { Zap } from 'lucide-react'

export default function Analysis() {
  const navigate = useNavigate()
  const [inputValue, setInputValue] = useState('')
  const watchlistRef = useRef(null)

  const handleAnalyze = (ticker) => {
    navigate(`/stock/${encodeURIComponent(ticker)}`)
  }

  const handleSelect = (suggestion) => {
    handleAnalyze(suggestion.ticker)
  }

  const handleSubmit = () => {
    const val = inputValue.trim().toUpperCase()
    if (val) handleAnalyze(val)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Zap size={22} className="text-primary" />
        <h2 className="text-xl font-bold text-text-primary">Watchlist</h2>
        <span className="text-sm text-text-muted">18-Punkte Kauf-Checkliste</span>
      </div>

      {/* Search bar with autocomplete */}
      <div className="flex gap-3">
        <TickerSearch
          value={inputValue}
          onChange={setInputValue}
          onSelect={handleSelect}
          onSubmit={handleSubmit}
          placeholder="Ticker analysieren (z.B. MSFT, COST, V)"
          className="flex-1 max-w-sm"
        />
        <button
          onClick={handleSubmit}
          disabled={!inputValue.trim()}
          className="bg-primary text-white rounded-lg px-5 py-2.5 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <Zap size={14} />
          Analysieren
        </button>
      </div>

      {/* Watchlist */}
      <WatchlistTable
        ref={watchlistRef}
        onSelectTicker={handleAnalyze}
      />

      <DisclaimerBanner />
    </div>
  )
}
