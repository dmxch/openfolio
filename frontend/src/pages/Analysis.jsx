import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import WatchlistTable from '../components/WatchlistTable'
import TickerSearch from '../components/TickerSearch'
import DisclaimerBanner from '../components/DisclaimerBanner'
import PageHeader from '../components/ui/PageHeader'
import Button from '../components/ui/Button'
import { Plus } from 'lucide-react'

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
    <div className="pb-10">
      <PageHeader
        title="Watchlist"
        subtitle="18-Punkte-Kauf-Checkliste · 6 Kategorien"
        showSearch={false}
        showBell={false}
        actions={
          <>
            {/* Analyse-Suche: nur Desktop — auf Mobile wuerde die w-72-Box die Top-App-Bar sprengen */}
            <div className="hidden md:block">
              <TickerSearch
                value={inputValue}
                onChange={setInputValue}
                onSelect={handleSelect}
                onSubmit={handleSubmit}
                placeholder="Ticker analysieren…"
                className="w-72"
              />
            </div>
            <Button variant="primary" icon={Plus} onClick={() => watchlistRef.current?.openAdd()}>
              Ticker
            </Button>
          </>
        }
      />

      <div className="flex flex-col gap-[14px] md:gap-[18px]">
        <WatchlistTable ref={watchlistRef} onSelectTicker={handleAnalyze} />
        <DisclaimerBanner />
      </div>
    </div>
  )
}
