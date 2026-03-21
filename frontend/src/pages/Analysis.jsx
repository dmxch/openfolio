import { useState, useRef } from 'react'
import WatchlistTable from '../components/WatchlistTable'
import StockScoreCard from '../components/StockScoreCard'
import TickerSearch from '../components/TickerSearch'
import DisclaimerBanner from '../components/DisclaimerBanner'
import { Zap } from 'lucide-react'

export default function Analysis() {
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [inputValue, setInputValue] = useState('')
  const scoreRef = useRef(null)
  const watchlistRef = useRef(null)

  const handleAnalyze = (ticker) => {
    setSelectedTicker(ticker)
    setInputValue('')
    setTimeout(() => {
      scoreRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 100)
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

      {/* Score Card */}
      {selectedTicker && (
        <div ref={scoreRef}>
          <StockScoreCard
            key={selectedTicker}
            ticker={selectedTicker}
            onClose={() => setSelectedTicker(null)}
            onWatchlistChange={() => watchlistRef.current?.refetch?.()}
          />
        </div>
      )}

      {/* Watchlist */}
      <WatchlistTable
        ref={watchlistRef}
        onSelectTicker={handleAnalyze}
        selectedTicker={selectedTicker}
      />

      <DisclaimerBanner />
    </div>
  )
}
