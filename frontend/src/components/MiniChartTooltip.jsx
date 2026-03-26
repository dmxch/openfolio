import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { toTradingViewSymbol } from '../lib/tradingview'

function MiniChartPopup({ ticker, anchorRect }) {
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
      width: 320,
      height: 180,
      locale: 'de_DE',
      dateRange: '3M',
      colorTheme: 'dark',
      isTransparent: true,
      autosize: false,
      largeChartUrl: '',
      noTimeScale: false,
      chartOnly: false,
    })

    // Detect widget load failure via timeout — if the iframe doesn't render
    // meaningful content within 5s, show fallback
    const failTimer = setTimeout(() => {
      if (!containerRef.current) return
      const iframe = containerRef.current.querySelector('iframe')
      if (!iframe) {
        setFailed(true)
      }
    }, 5000)

    widget.appendChild(script)
    containerRef.current.appendChild(widget)

    return () => {
      clearTimeout(failTimer)
      if (containerRef.current) {
        containerRef.current.innerHTML = ''
      }
    }
  }, [ticker])

  // Position the popup above or below the anchor
  const top = anchorRect.top > 220
    ? anchorRect.top - 195
    : anchorRect.bottom + 8
  const left = Math.min(anchorRect.left, window.innerWidth - 340)

  if (failed) {
    return createPortal(
      <div
        className="fixed z-[9999] rounded-lg border border-border bg-card shadow-xl overflow-hidden flex items-center justify-center"
        style={{ top, left, width: 320, height: 185 }}
      >
        <div className="flex flex-col items-center gap-1.5 text-text-secondary">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
          </svg>
          <span className="text-xs">Chart nicht verfügbar</span>
        </div>
      </div>,
      document.body
    )
  }

  return createPortal(
    <div
      className="fixed z-[9999] rounded-lg border border-border bg-card shadow-xl overflow-hidden"
      style={{ top, left, width: 320, height: 185 }}
    >
      <div ref={containerRef} style={{ width: 320, height: 180 }} />
    </div>,
    document.body
  )
}

export default function MiniChartTooltip({ ticker, children }) {
  const [show, setShow] = useState(false)
  const [rect, setRect] = useState(null)
  const ref = useRef(null)
  const timerRef = useRef(null)

  const handleEnter = useCallback(() => {
    timerRef.current = setTimeout(() => {
      if (ref.current) {
        setRect(ref.current.getBoundingClientRect())
        setShow(true)
      }
    }, 400)
  }, [])

  const handleLeave = useCallback(() => {
    clearTimeout(timerRef.current)
    setShow(false)
  }, [])

  useEffect(() => {
    return () => clearTimeout(timerRef.current)
  }, [])

  return (
    <span
      ref={ref}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      {children}
      {show && rect && <MiniChartPopup ticker={ticker} anchorRect={rect} />}
    </span>
  )
}
