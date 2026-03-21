import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'

function MiniChartPopup({ ticker, anchorRect }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return
    containerRef.current.innerHTML = ''

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
      symbol: ticker,
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

    widget.appendChild(script)
    containerRef.current.appendChild(widget)

    return () => {
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
