import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Briefcase, Plus, Check, Loader2, TrendingUp } from 'lucide-react'
import { useApi, apiPost, authFetch } from '../hooks/useApi'
import { formatCHF, formatPct, pnlColor } from '../lib/format'
import G from '../components/GlossarTooltip'
import { useToast } from '../components/Toast'
import TradingViewChart from '../components/TradingViewChart'
import StockScoreCard from '../components/StockScoreCard'
import FundamentalCharts from '../components/FundamentalCharts'
import EtfSectorPanel from '../components/EtfSectorPanel'
import DisclaimerBanner from '../components/DisclaimerBanner'

function MyPositionPanel({ ticker }) {
  const { data: summary } = useApi('/portfolio/summary')
  const position = summary?.positions?.find((p) => p.ticker === ticker)

  if (!position) return null

  return (
    <div className="rounded-lg border border-primary/20 bg-primary/5 p-5">
      <div className="flex items-center gap-2 mb-3">
        <Briefcase size={16} className="text-primary" />
        <h3 className="text-sm font-medium text-text-secondary">Meine Position</h3>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <div className="text-xs text-text-muted">Anzahl</div>
          <div className="text-sm font-medium text-text-primary tabular-nums">{position.shares}</div>
        </div>
        <div>
          <div className="text-xs text-text-muted">Marktwert</div>
          <div className="text-sm font-medium text-text-primary tabular-nums">{formatCHF(position.market_value_chf)}</div>
        </div>
        <div>
          <div className="text-xs text-text-muted">Einstand</div>
          <div className="text-sm font-medium text-text-primary tabular-nums">{formatCHF(position.cost_basis_chf)}</div>
        </div>
        <div>
          <div className="text-xs text-text-muted">Performance</div>
          <div className={`text-sm font-medium tabular-nums ${pnlColor(position.pnl_pct)}`}>
            {formatPct(position.pnl_pct)} ({formatCHF(position.pnl_chf)})
          </div>
        </div>
      </div>
    </div>
  )
}

function EtfSectorPanelWrapper({ ticker }) {
  const { data: summary } = useApi('/portfolio/summary')
  const position = summary?.positions?.find((p) => p.ticker === ticker)

  if (!position || !position.is_multi_sector) return null

  return <EtfSectorPanel ticker={ticker} marketValueChf={position.market_value_chf || 0} />
}

function MrsPanel({ ticker }) {
  const [mrs, setMrs] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/score/${ticker}`)
        if (res.ok && !cancelled) {
          const json = await res.json()
          setMrs(json.mansfield_rs)
        }
      } catch { /* ignore */ }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (mrs === null || mrs === undefined) return null

  const isPositive = mrs >= 0

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3"><G term="MRS">Mansfield RS (MRS)</G></h4>
      <div className={`text-2xl font-mono font-bold ${isPositive ? 'text-success' : 'text-danger'}`}>
        {isPositive ? '+' : ''}{mrs.toFixed(2)}
      </div>
      <div className="text-xs text-text-muted mt-1">
        {isPositive ? 'Relative Stärke positiv' : 'Relative Stärke negativ'}
      </div>
    </div>
  )
}

function BreakoutEvents({ ticker }) {
  const [breakouts, setBreakouts] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/breakouts/${ticker}?period=1y`)
        if (res.ok && !cancelled) {
          const json = await res.json()
          setBreakouts(json.breakouts || [])
        }
      } catch { /* ignore */ }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (!breakouts || breakouts.length === 0) return null

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3">Breakout-Ereignisse (1J)</h4>
      <div className="space-y-2">
        {breakouts.map((b, i) => (
          <div key={i} className="flex items-center gap-3 text-xs">
            <TrendingUp size={14} className="text-success shrink-0" />
            <span className="text-text-muted w-20">{new Date(b.date).toLocaleDateString('de-CH')}</span>
            <span className="text-text-primary font-mono">{b.price}</span>
            <span className="text-text-muted">über {b.resistance}</span>
            <span className="text-text-muted">Vol: {b.volume_ratio}×</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function LevelsPanel({ ticker }) {
  const [levels, setLevels] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/levels/${ticker}`)
        if (res.ok && !cancelled) setLevels(await res.json())
      } catch { /* ignore */ }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (!levels || (!levels.resistance && !levels.support)) return null

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3"><G term="S/R">Support & Resistance</G></h4>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs text-text-muted mb-1">Widerstand (52W Hoch)</div>
          <div className="text-sm font-mono font-medium text-danger">{levels.resistance}</div>
          {levels.resistance_historical?.length > 0 && (
            <div className="mt-2 space-y-1">
              {levels.resistance_historical.slice(0, 3).map((r, i) => (
                <div key={i} className="text-xs text-text-muted font-mono">{r}</div>
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="text-xs text-text-muted mb-1">Unterstützung (52W Tief)</div>
          <div className="text-sm font-mono font-medium text-success">{levels.support}</div>
          {levels.support_historical?.length > 0 && (
            <div className="mt-2 space-y-1">
              {levels.support_historical.slice(0, 3).map((s, i) => (
                <div key={i} className="text-xs text-text-muted font-mono">{s}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function StockDetail() {
  const { ticker } = useParams()
  const navigate = useNavigate()
  const { data: watchlist } = useApi('/analysis/watchlist')
  const [inWatchlist, setInWatchlist] = useState(false)
  const [addingToWl, setAddingToWl] = useState(false)
  const toast = useToast()

  useEffect(() => {
    if (watchlist && ticker) {
      const items = watchlist?.items || watchlist || []
      setInWatchlist(items.some((w) => w.ticker === ticker.toUpperCase() || w.ticker === ticker))
    }
  }, [watchlist, ticker])

  const handleAddToWatchlist = async () => {
    setAddingToWl(true)
    try {
      await apiPost('/analysis/watchlist', { ticker: ticker.toUpperCase(), name: ticker.toUpperCase(), sector: null })
      setInWatchlist(true)
      toast('Zur Watchlist hinzugefügt', 'success')
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    } finally {
      setAddingToWl(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-text-secondary hover:text-text-primary hover:bg-card-alt transition-colors"
          >
            <ArrowLeft size={16} />
            Zurück
          </button>
          <h2 className="text-xl font-bold text-text-primary font-mono">{ticker}</h2>
        </div>
        {inWatchlist ? (
          <span className="flex items-center gap-1.5 py-1.5 px-3 bg-success/15 text-success border border-success/30 rounded-lg text-xs">
            <Check size={14} />
            In Watchlist
          </span>
        ) : (
          <button
            onClick={handleAddToWatchlist}
            disabled={addingToWl}
            className="flex items-center gap-1.5 py-1.5 px-3 bg-primary/15 text-primary border border-primary/30 rounded-lg text-xs hover:bg-primary/25 transition-colors disabled:opacity-50"
          >
            {addingToWl ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Zur Watchlist
          </button>
        )}
      </div>

      {/* Position info */}
      <MyPositionPanel ticker={ticker} />
      <EtfSectorPanelWrapper ticker={ticker} />

      {/* Chart with controls */}
      <TradingViewChart ticker={ticker} height={600} showControls />

      {/* Analysis panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <LevelsPanel ticker={ticker} />
        <MrsPanel ticker={ticker} />
      </div>

      <BreakoutEvents ticker={ticker} />

      {/* Score + Fundamentals */}
      <StockScoreCard ticker={ticker} />
      <FundamentalCharts ticker={ticker} />

      <DisclaimerBanner />
    </div>
  )
}
