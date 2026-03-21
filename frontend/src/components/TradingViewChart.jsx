import { useState, useEffect, useRef, useMemo } from 'react'

const TV_EXCHANGE_MAP = {
  '.SW': 'SIX', '.L': 'LSE', '.AS': 'AMS', '.DE': 'XETR',
  '.PA': 'EPA', '.MI': 'MIL', '.TO': 'TSX', '.V': 'TSXV',
  '.HK': 'HKEX', '.T': 'TSE', '.AX': 'ASX',
}

function toTradingViewSymbol(yfinanceTicker) {
  if (!yfinanceTicker) return yfinanceTicker
  for (const [suffix, exchange] of Object.entries(TV_EXCHANGE_MAP)) {
    if (yfinanceTicker.endsWith(suffix)) {
      return `${exchange}:${yfinanceTicker.slice(0, -suffix.length)}`
    }
  }
  return yfinanceTicker // US tickers work without prefix
}

const TIMEFRAMES = [
  { label: '1T', range: '1D' },
  { label: '1W', range: '5D' },
  { label: '1M', range: '1M' },
  { label: '3M', range: '3M' },
  { label: '6M', range: '6M' },
  { label: '1J', range: '12M' },
  { label: '2J', range: '24M' },
  { label: '5J', range: '60M' },
]

const SMA_OPTIONS = [
  { key: 'sma20', label: 'SMA(20)', study: 'MASimple@tv-basicstudies', inputs: { length: 20 } },
  { key: 'sma50', label: 'SMA(50)', study: 'MASimple@tv-basicstudies', inputs: { length: 50 } },
  { key: 'sma150', label: 'SMA(150)', study: 'MASimple@tv-basicstudies', inputs: { length: 150 } },
  { key: 'sma200', label: 'SMA(200)', study: 'MASimple@tv-basicstudies', inputs: { length: 200 } },
]

const INDICATOR_OPTIONS = [
  { key: 'sr', label: 'S/R', study: 'PivotPointsHighLow@tv-basicstudies', inputs: { length: 20 } },
  { key: 'bb', label: 'BB(20)', study: 'BB@tv-basicstudies' },
  { key: 'rsi', label: 'RSI(14)', study: 'RSI@tv-basicstudies' },
]

export default function TradingViewChart({ ticker, height = 600, showControls = false }) {
  const containerRef = useRef(null)
  const [timeframe, setTimeframe] = useState(5) // Default: 1J
  const [smaToggles, setSmaToggles] = useState({ sma50: true, sma150: true })
  const [indicators, setIndicators] = useState({ sr: true })
  const [smaOpen, setSmaOpen] = useState(false)

  // Build a stable string key so useEffect triggers on actual changes
  const studiesKey = useMemo(() => {
    const parts = []
    SMA_OPTIONS.forEach(s => { if (smaToggles[s.key]) parts.push(`${s.study}|${s.inputs?.length || ''}`) })
    INDICATOR_OPTIONS.forEach(i => { if (indicators[i.key]) parts.push(i.study) })
    return parts.join(',')
  }, [smaToggles, indicators])

  const activeStudies = useMemo(() => {
    const studies = []
    SMA_OPTIONS.forEach(s => {
      if (smaToggles[s.key]) {
        studies.push({ id: s.study, inputs: s.inputs || {} })
      }
    })
    INDICATOR_OPTIONS.forEach(i => {
      if (indicators[i.key]) {
        const entry = { id: i.study }
        if (i.inputs) entry.inputs = i.inputs
        studies.push(entry)
      }
    })
    return studies
  }, [studiesKey])

  const tf = TIMEFRAMES[timeframe]

  useEffect(() => {
    if (!containerRef.current) return
    containerRef.current.innerHTML = ''

    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container'

    const widgetInner = document.createElement('div')
    widgetInner.className = 'tradingview-widget-container__widget'
    widget.appendChild(widgetInner)

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.type = 'text/javascript'
    script.async = true
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: toTradingViewSymbol(ticker),
      interval: 'D',
      timezone: 'Europe/Zurich',
      theme: 'dark',
      locale: 'de_DE',
      style: '1',
      enable_publishing: false,
      allow_symbol_change: true,
      hide_top_toolbar: false,
      hide_side_toolbar: false,
      range: tf.range,
      studies: activeStudies,
      support_host: 'https://www.tradingview.com',
    })

    widget.appendChild(script)
    containerRef.current.appendChild(widget)

    return () => {
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, [ticker, tf.range, studiesKey])

  if (!showControls) {
    return (
      <div
        ref={containerRef}
        style={{ height: `${height}px` }}
        className="rounded-lg overflow-hidden border border-border"
      />
    )
  }

  const toggleSma = (key) => setSmaToggles(prev => ({ ...prev, [key]: !prev[key] }))
  const toggleIndicator = (key) => setIndicators(prev => ({ ...prev, [key]: !prev[key] }))

  return (
    <div className="space-y-3">
      {/* Timeframe buttons */}
      <div className="flex items-center gap-1">
        {TIMEFRAMES.map((tf, i) => (
          <button
            key={tf.label}
            onClick={() => setTimeframe(i)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              timeframe === i
                ? 'bg-primary text-white'
                : 'bg-card-alt text-text-secondary hover:text-text-primary'
            }`}
          >
            {tf.label}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div
        ref={containerRef}
        style={{ height: 'calc(100vh - 350px)', minHeight: '600px' }}
        className="rounded-lg overflow-hidden border border-border"
      />

      {/* Indicator toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {/* SMA dropdown */}
        <div className="relative">
          <button
            onClick={() => setSmaOpen(!smaOpen)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              Object.values(smaToggles).some(Boolean)
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'bg-card-alt text-text-secondary hover:text-text-primary'
            }`}
          >
            SMA ▾
          </button>
          {smaOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setSmaOpen(false)} />
              <div className="absolute top-full left-0 mt-1 z-20 bg-card border border-border rounded-lg shadow-xl py-1 min-w-[140px]">
                {SMA_OPTIONS.map(s => (
                  <button
                    key={s.key}
                    onClick={() => toggleSma(s.key)}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-card-alt transition-colors"
                  >
                    <span className={`w-3 h-3 rounded border ${smaToggles[s.key] ? 'bg-primary border-primary' : 'border-border'}`} />
                    <span className={smaToggles[s.key] ? 'text-text-primary' : 'text-text-secondary'}>
                      {s.label}
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Indicator toggles */}
        {INDICATOR_OPTIONS.map(ind => (
          <button
            key={ind.key}
            onClick={() => toggleIndicator(ind.key)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              indicators[ind.key]
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'bg-card-alt text-text-secondary hover:text-text-primary'
            }`}
          >
            {ind.label}
          </button>
        ))}
      </div>
    </div>
  )
}
