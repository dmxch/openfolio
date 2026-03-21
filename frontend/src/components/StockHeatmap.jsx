import { useEffect, useRef } from 'react'

export default function StockHeatmap() {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current) return

    containerRef.current.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js'
    script.type = 'text/javascript'
    script.async = true
    script.innerHTML = JSON.stringify({
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
      height: '100%'
    })

    containerRef.current.appendChild(script)
  }, [])

  return (
    <div>
      <h3 className="text-lg font-semibold text-text-primary mb-3">S&P 500 Heatmap</h3>
      <div className="bg-card rounded-2xl overflow-hidden" style={{ height: 'calc(100vh - 200px)', minHeight: '700px' }}>
        <div className="tradingview-widget-container h-full" ref={containerRef}>
          <div className="tradingview-widget-container__widget" />
        </div>
      </div>
    </div>
  )
}
