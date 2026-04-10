import { useEffect, useRef } from 'react'

export default function SectorRotation() {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return
    // Clear previous widget on re-render
    const wrapper = containerRef.current.querySelector('.tradingview-widget-container__widget')
    if (wrapper) wrapper.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js'
    script.type = 'text/javascript'
    script.async = true
    script.textContent = JSON.stringify({
      exchanges: [],
      dataSource: 'SPX500',
      grouping: 'sector',
      blockSize: 'market_cap_basic',
      blockColor: 'change',
      locale: 'de_DE',
      symbolUrl: '',
      colorTheme: 'dark',
      hasTopBar: true,
      isDataSetEnabled: true,
      isZoomEnabled: true,
      hasSymbolTooltip: true,
      isMonoSize: false,
      width: '100%',
      height: '100%',
    })

    containerRef.current.appendChild(script)

    return () => {
      if (containerRef.current && script.parentNode === containerRef.current) {
        containerRef.current.removeChild(script)
      }
    }
  }, [])

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden" style={{ height: 500 }}>
      <div ref={containerRef} className="tradingview-widget-container h-full">
        <div className="tradingview-widget-container__widget h-full" />
      </div>
    </div>
  )
}
