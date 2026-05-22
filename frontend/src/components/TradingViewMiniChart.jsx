import { useEffect, useRef, useState } from 'react'
import { toTradingViewSymbol } from '../lib/tradingview'

/**
 * Schmaler TradingView-Mini-Chart-Embed (mini-symbol-overview) fuer
 * eingebettete Vorschau-Boxen — z.B. SmartMoney-Detail-Modal.
 *
 * Fuer den vollausgestatteten Chart mit Indikator-Toolbar siehe
 * `TradingViewChart` (Portfolio-/Watchlist-Detail-Seiten).
 */
export default function TradingViewMiniChart({ ticker, height = 220, dateRange = '12M' }) {
  const containerRef = useRef(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    containerRef.current.innerHTML = ''
    setFailed(false)

    const tvSymbol = toTradingViewSymbol(ticker)

    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container'

    const widgetInner = document.createElement('div')
    widgetInner.className = 'tradingview-widget-container__widget'
    widget.appendChild(widgetInner)

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js'
    script.type = 'text/javascript'
    script.async = true
    script.innerHTML = JSON.stringify({
      symbol: tvSymbol,
      width: '100%',
      height,
      locale: 'de_DE',
      dateRange,
      colorTheme: 'dark',
      isTransparent: true,
      autosize: false,
      largeChartUrl: '',
      noTimeScale: false,
      chartOnly: false,
    })

    // Detect widget load failure — falls kein iframe in 5s, Fallback zeigen
    const failTimer = setTimeout(() => {
      if (!containerRef.current) return
      const iframe = containerRef.current.querySelector('iframe')
      if (!iframe) setFailed(true)
    }, 5000)

    widget.appendChild(script)
    containerRef.current.appendChild(widget)

    return () => {
      clearTimeout(failTimer)
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, [ticker, height, dateRange])

  if (failed) {
    return (
      <div
        style={{ height: `${height}px` }}
        className="rounded-lg border border-border bg-card flex items-center justify-center text-sm text-text-secondary"
      >
        Chart nicht verfügbar
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      style={{ height: `${height}px`, width: '100%' }}
      className="rounded-lg overflow-hidden border border-border"
    />
  )
}
