import { useState, useEffect, useRef, useMemo } from 'react'
import { toTradingViewSymbol } from '../lib/tradingview'

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
  { key: 'zigzag', label: 'ZigZag', study: 'ZigZag@tv-basicstudies' },
  { key: 'rsi', label: 'RSI(14)', study: 'RSI@tv-basicstudies' },
]

export default function TradingViewChart({ ticker, height = 600, showControls = false, compact = false }) {
  const containerRef = useRef(null)
  const [timeframe, setTimeframe] = useState(5) // Default: 1J
  const [smaToggles, setSmaToggles] = useState({ sma50: true, sma150: true })
  const [indicators, setIndicators] = useState({ sr: true, zigzag: true, rsi: true })
  const [smaOpen, setSmaOpen] = useState(false)
  const [chartFailed, setChartFailed] = useState(false)

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
    setChartFailed(false)

    const tvSymbol = toTradingViewSymbol(ticker)

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
      symbol: tvSymbol,
      interval: 'D',
      timezone: 'Europe/Zurich',
      theme: 'dark',
      locale: 'de_DE',
      style: '1',
      enable_publishing: false,
      allow_symbol_change: true,
      hide_top_toolbar: compact,
      hide_side_toolbar: compact,
      range: tf.range,
      studies: activeStudies,
      support_host: 'https://www.tradingview.com',
    })

    // Detect widget load failure — if no iframe appears within 8s, show fallback
    const failTimer = setTimeout(() => {
      if (!containerRef.current) return
      const iframe = containerRef.current.querySelector('iframe')
      if (!iframe) {
        setChartFailed(true)
      }
    }, 8000)

    widget.appendChild(script)
    containerRef.current.appendChild(widget)

    return () => {
      clearTimeout(failTimer)
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, [ticker, tf.range, studiesKey])

  const tvSymbol = toTradingViewSymbol(ticker)
  const tvSearchUrl = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSymbol)}`

  const fallbackEl = chartFailed ? (
    <div
      style={{ height: showControls ? 'calc(100vh - 350px)' : `${height}px`, minHeight: showControls ? '600px' : undefined }}
      className="rounded-card border border-border-2 bg-card-2 flex flex-col items-center justify-center gap-3 text-text-secondary"
    >
      <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
      <p className="text-sm">TradingView-Chart für dieses Symbol nicht verfügbar.</p>
      <a
        href={tvSearchUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-primary hover:text-primary/80 underline"
      >
        Auf TradingView öffnen
      </a>
    </div>
  ) : null

  if (!showControls) {
    return fallbackEl || (
      <div
        ref={containerRef}
        style={{ height: `${height}px` }}
        className="rounded-card overflow-hidden border border-border-2"
      />
    )
  }

  const toggleSma = (key) => setSmaToggles(prev => ({ ...prev, [key]: !prev[key] }))
  const toggleIndicator = (key) => setIndicators(prev => ({ ...prev, [key]: !prev[key] }))

  return (
    <div className="space-y-3">
      {/* Timeframe buttons */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {TIMEFRAMES.map((tf, i) => (
          <button
            key={tf.label}
            onClick={() => setTimeframe(i)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
              timeframe === i
                ? 'bg-active-tint border-border-active text-text-bright'
                : 'bg-surface border-border-2 text-text-muted hover:border-border-hover'
            }`}
          >
            {tf.label}
          </button>
        ))}
      </div>

      {/* Chart */}
      {fallbackEl || (
        <div
          ref={containerRef}
          style={{ height: 'calc(100vh - 350px)', minHeight: '600px' }}
          className="rounded-card overflow-hidden border border-border-2"
        />
      )}

      {/* Indicator toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {/* SMA dropdown */}
        <div className="relative">
          <button
            onClick={() => setSmaOpen(!smaOpen)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
              Object.values(smaToggles).some(Boolean)
                ? 'bg-active-tint text-text-bright border-border-active'
                : 'bg-surface border-border-2 text-text-muted hover:border-border-hover'
            }`}
          >
            SMA {smaOpen ? '▴' : '▾'}
          </button>
          {smaOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setSmaOpen(false)} />
              {/* Nach OBEN oeffnen: die Toolbar sitzt am unteren Rand der SectionCard
                  (overflow-hidden) — ein Dropdown nach unten wuerde am Kartenrand
                  abgeschnitten. Oben ist im 600px-Chartbereich genug Platz. */}
              <div className="absolute bottom-full left-0 mb-1 z-20 bg-card border border-border rounded-lg shadow-xl py-1 min-w-[140px]">
                {SMA_OPTIONS.map(s => (
                  <button
                    key={s.key}
                    onClick={() => toggleSma(s.key)}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-hover transition-colors"
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
            className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
              indicators[ind.key]
                ? 'bg-active-tint text-text-bright border-border-active'
                : 'bg-surface border-border-2 text-text-muted hover:border-border-hover'
            }`}
          >
            {ind.label}
          </button>
        ))}
      </div>
    </div>
  )
}
