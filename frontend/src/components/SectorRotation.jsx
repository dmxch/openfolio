import { useState, useCallback, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useApi, apiPost } from '../hooks/useApi'
import { useToast } from './Toast'
import { formatPct, formatNumber, pnlColor } from '../lib/format'
import { ArrowUp, ArrowDown, Minus, Loader2, Plus, Star } from 'lucide-react'
import MiniChartTooltip from './MiniChartTooltip'
import Skeleton from './Skeleton'
import G from './GlossarTooltip'
import LoadingSpinner from './LoadingSpinner'

function isAllZero(sectors) {
  if (!sectors?.length) return true
  return sectors.every(s => s.perf_1d === 0 && s.perf_1w === 0 && s.perf_1m === 0 && s.perf_3m === 0)
}

export default function SectorRotation() {
  const { data, loading, error, refetch } = useApi('/market/sectors')
  const [expanded, setExpanded] = useState(null)
  const retryRef = useRef(null)

  const allZero = !loading && !error && isAllZero(data)

  useEffect(() => {
    if (allZero) {
      retryRef.current = setTimeout(() => refetch(), 5000)
      return () => clearTimeout(retryRef.current)
    }
  }, [allZero, refetch])

  const toggleSector = (etf) => {
    setExpanded(expanded === etf ? null : etf)
  }

  if (loading || allZero) return (
    <div className="rounded-lg border border-border bg-card p-8">
      <LoadingSpinner size={16} text="Sektordaten werden geladen..." />
    </div>
  )
  if (error) return <div className="rounded-lg border border-danger/30 bg-danger/10 p-5 text-sm text-danger">Sektordaten nicht verfügbar</div>

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="p-4 border-b border-border">
        <h3 className="text-sm font-medium text-text-secondary"><G term="Sektor-Rotation">Sektor-Rotation</G> (SPDR ETFs)</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-text-muted">
              <th className="text-left p-3 font-medium">Sektor</th>
              <th className="text-right p-3 font-medium">1D</th>
              <th className="text-right p-3 font-medium">1W</th>
              <th className="text-right p-3 font-medium">1M</th>
              <th className="text-right p-3 font-medium">3M</th>
              <th className="text-center p-3 font-medium">Trend</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((s) => (
              <SectorRow
                key={s.etf}
                sector={s}
                isExpanded={expanded === s.etf}
                onToggle={() => toggleSector(s.etf)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SectorRow({ sector: s, isExpanded, onToggle }) {
  return (
    <>
      <tr
        className={`border-b border-border/50 hover:bg-card-alt/50 transition-colors cursor-pointer select-none ${isExpanded ? 'bg-card-alt/50 border-l-[3px] border-l-primary' : 'border-l-[3px] border-l-transparent'}`}
        onClick={onToggle}
      >
        <td className="p-3">
          <span className="text-text-primary">{s.sector}</span>
          <span className="text-text-muted ml-1 text-xs">({s.etf})</span>
        </td>
        <td className={`p-3 text-right ${pnlColor(s.perf_1d)}`}>{formatPct(s.perf_1d)}</td>
        <td className={`p-3 text-right ${pnlColor(s.perf_1w)}`}>{formatPct(s.perf_1w)}</td>
        <td className={`p-3 text-right ${pnlColor(s.perf_1m)}`}>{formatPct(s.perf_1m)}</td>
        <td className={`p-3 text-right ${pnlColor(s.perf_3m)}`}>{formatPct(s.perf_3m)}</td>
        <td className="p-3 text-center">
          {s.trend === 'up' ? <ArrowUp size={14} className="inline text-success" /> :
           s.trend === 'down' ? <ArrowDown size={14} className="inline text-danger" /> :
           <Minus size={14} className="inline text-text-muted" />}
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={6} className="p-0">
            <HoldingsPanel etf={s.etf} />
          </td>
        </tr>
      )}
    </>
  )
}

function HoldingsPanel({ etf }) {
  const { data, loading } = useApi(`/market/sectors/${etf}/holdings`)
  const [addedTickers, setAddedTickers] = useState(new Set())
  const toast = useToast()

  const handleAddToWatchlist = useCallback(async (ticker, name) => {
    try {
      await apiPost('/analysis/watchlist', { ticker, name, sector: null })
      setAddedTickers((prev) => new Set([...prev, ticker]))
      toast(`${ticker} zur Watchlist hinzugefügt`, 'success')
    } catch {
      toast(`Fehler beim Hinzufügen von ${ticker}`, 'error')
    }
  }, [toast])

  if (loading) {
    return (
      <div className="bg-body border-t border-border p-6">
        <LoadingSpinner size={16} text="Holdings laden..." />
      </div>
    )
  }

  if (!data?.holdings?.length) return null

  return (
    <div className="bg-body border-t border-border">
      <table className="w-full">
        <thead>
          <tr className="text-text-muted text-[11px]">
            <th className="text-left px-4 py-2 font-medium">Ticker</th>
            <th className="text-left px-2 py-2 font-medium">Name</th>
            <th className="text-right px-2 py-2 font-medium">Gew.</th>
            <th className="text-right px-2 py-2 font-medium">Kurs</th>
            <th className="text-right px-2 py-2 font-medium">1D</th>
            <th className="text-right px-2 py-2 font-medium">1W</th>
            <th className="text-right px-2 py-2 font-medium">1M</th>
            <th className="text-right px-2 py-2 font-medium">3M</th>
            <th className="text-center px-2 py-2 font-medium">Trend</th>
            <th className="text-center px-4 py-2 font-medium" title="Watchlist">WL</th>
          </tr>
        </thead>
        <tbody>
          {data.holdings.map((h) => {
            const isAdded = addedTickers.has(h.ticker)
            return (
              <tr
                key={h.ticker}
                className="border-t border-border/30 transition-colors hover:bg-card/50"
              >
                <td className="px-4 py-1.5">
                  <MiniChartTooltip ticker={h.ticker}>
                    <Link to={`/stock/${encodeURIComponent(h.ticker)}`} className="font-mono text-primary text-xs font-medium hover:underline">
                      {h.ticker}
                    </Link>
                  </MiniChartTooltip>
                </td>
                <td className="px-2 py-1.5 text-text-secondary text-xs truncate max-w-[140px]">{h.name}</td>
                <td className="px-2 py-1.5 text-right text-text-secondary text-xs tabular-nums">{h.weight.toFixed(1)}%</td>
                <td className="px-2 py-1.5 text-right text-text-secondary text-xs tabular-nums">
                  {h.price != null ? formatNumber(h.price, 2) : '–'}
                </td>
                <td className={`px-2 py-1.5 text-right text-xs tabular-nums ${pnlColor(h.perf_1d)}`}>{formatPct(h.perf_1d)}</td>
                <td className={`px-2 py-1.5 text-right text-xs tabular-nums ${pnlColor(h.perf_1w)}`}>{formatPct(h.perf_1w)}</td>
                <td className={`px-2 py-1.5 text-right text-xs tabular-nums ${pnlColor(h.perf_1m)}`}>{formatPct(h.perf_1m)}</td>
                <td className={`px-2 py-1.5 text-right text-xs tabular-nums ${pnlColor(h.perf_3m)}`}>{formatPct(h.perf_3m)}</td>
                <td className="px-2 py-1.5 text-center">
                  {h.trend === 'up' ? <ArrowUp size={12} className="inline text-success" /> :
                   h.trend === 'down' ? <ArrowDown size={12} className="inline text-danger" /> :
                   <Minus size={12} className="inline text-text-muted" />}
                </td>
                <td className="px-4 py-1.5 text-center">
                  {(h.in_watchlist || isAdded) ? (
                    <Star size={13} className="inline text-primary fill-primary" />
                  ) : (
                    <button
                      onClick={() => handleAddToWatchlist(h.ticker, h.name)}
                      className="text-text-muted hover:text-primary transition-colors"
                      title="Zur Watchlist hinzufügen"
                    >
                      <Plus size={13} />
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
