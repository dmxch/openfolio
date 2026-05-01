import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Briefcase, Plus, Check, Loader2, TrendingUp, RotateCcw } from 'lucide-react'
import { useApi, apiPost, authFetch } from '../hooks/useApi'
import { usePortfolioData } from '../contexts/DataContext'
import { formatCHF, formatPct, pnlColor } from '../lib/format'
import G from '../components/GlossarTooltip'
import { useToast } from '../components/Toast'
import TradingViewChart from '../components/TradingViewChart'
import StockScoreCard from '../components/StockScoreCard'
import FundamentalCharts from '../components/FundamentalCharts'
import EtfSectorPanel from '../components/EtfSectorPanel'
import DisclaimerBanner from '../components/DisclaimerBanner'
import SmartMoneyPanel from '../components/SmartMoneyPanel'
import TickerLogo from '../components/TickerLogo'
import ConcentrationBanner from '../components/ConcentrationBanner'

function MyPositionPanel({ ticker }) {
  const { data: summary } = usePortfolioData()
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
          <div className="text-xs text-text-secondary">Anzahl</div>
          <div className="text-sm font-medium text-text-primary tabular-nums">{position.shares}</div>
        </div>
        <div>
          <div className="text-xs text-text-secondary">Marktwert</div>
          <div className="text-sm font-medium text-text-primary tabular-nums">{formatCHF(position.market_value_chf)}</div>
        </div>
        <div>
          <div className="text-xs text-text-secondary">Einstand</div>
          <div className="text-sm font-medium text-text-primary tabular-nums">{formatCHF(position.cost_basis_chf)}</div>
        </div>
        <div>
          <div className="text-xs text-text-secondary">Performance</div>
          <div className={`text-sm font-medium tabular-nums ${pnlColor(position.pnl_pct)}`}>
            {formatPct(position.pnl_pct)} ({formatCHF(position.pnl_chf)})
          </div>
        </div>
      </div>
    </div>
  )
}

function EtfSectorPanelWrapper({ ticker }) {
  const { data: summary } = usePortfolioData()
  const position = summary?.positions?.find((p) => p.ticker === ticker)

  if (!position || !position.is_multi_sector) return null

  return <EtfSectorPanel ticker={ticker} marketValueChf={position.market_value_chf || 0} />
}

function MrsPanel({ mrs }) {
  if (mrs === null || mrs === undefined) return null

  const isPositive = mrs >= 0

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3"><G term="MRS">Mansfield RS (MRS)</G></h4>
      <div className={`text-2xl font-mono font-bold ${isPositive ? 'text-success' : 'text-danger'}`}>
        {isPositive ? '+' : ''}{mrs.toFixed(2)}
      </div>
      <div className="text-xs text-text-secondary mt-1">
        {isPositive ? 'Relative Stärke positiv' : 'Relative Stärke negativ'}
      </div>
    </div>
  )
}

function BreakoutEvents({ ticker }) {
  const [breakouts, setBreakouts] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/breakouts/${ticker}?period=1y`)
        if (res.ok && !cancelled) {
          const json = await res.json()
          setBreakouts(json.breakouts || [])
        }
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) return <div className="bg-card rounded-lg border border-border p-4 text-xs text-text-secondary">Breakout-Daten konnten nicht geladen werden.</div>
  if (!breakouts || breakouts.length === 0) return null

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3">Breakout-Ereignisse (1J, am Folgetag bestätigt)</h4>
      <div className="space-y-2">
        {breakouts.map((b, i) => {
          const isPending = b.status === 'pending'
          const tooltip = isPending
            ? `Ausbruch heute bei ${b.resistance} — Tag-2-Bestätigung steht noch aus`
            : `Ausbruch am ${new Date(b.date).toLocaleDateString('de-CH')} bei ${b.resistance}, am Folgetag (${b.day2_date ? new Date(b.day2_date).toLocaleDateString('de-CH') : '?'}) mit Close ${b.day2_close} bestätigt`
          return (
            <div key={i} className="flex items-center gap-3 text-xs" title={tooltip}>
              {isPending ? (
                <TrendingUp size={14} className="text-warning shrink-0" />
              ) : (
                <TrendingUp size={14} className="text-success shrink-0" />
              )}
              <span className="text-text-muted w-20">{new Date(b.date).toLocaleDateString('de-CH')}</span>
              <span className="text-text-primary font-mono">{b.price}</span>
              <span className="text-text-muted">über {b.resistance}</span>
              <span className="text-text-muted">Vol: {b.volume_ratio}×</span>
              {isPending && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-warning/15 text-warning ml-auto">pending</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function LevelsPanel({ ticker }) {
  const [levels, setLevels] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/levels/${ticker}`)
        if (res.ok && !cancelled) setLevels(await res.json())
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) return <div className="bg-card rounded-lg border border-border p-4 text-xs text-text-secondary">Support/Resistance-Daten konnten nicht geladen werden.</div>
  if (!levels || (!levels.resistance && !levels.support)) return null

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <h4 className="text-sm font-medium text-text-secondary mb-3"><G term="S/R">Support & Resistance</G></h4>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs text-text-secondary mb-1">Widerstand (52W Hoch)</div>
          <div className="text-sm font-mono font-medium text-danger">{levels.resistance}</div>
          {levels.resistance_historical?.length > 0 && (
            <div className="mt-2 space-y-1">
              {levels.resistance_historical.slice(0, 3).map((r, i) => (
                <div key={i} className="text-xs text-text-secondary font-mono">{r}</div>
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="text-xs text-text-secondary mb-1">Unterstützung (52W Tief)</div>
          <div className="text-sm font-mono font-medium text-success">{levels.support}</div>
          {levels.support_historical?.length > 0 && (
            <div className="mt-2 space-y-1">
              {levels.support_historical.slice(0, 3).map((s, i) => (
                <div key={i} className="text-xs text-text-secondary font-mono">{s}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function HeartbeatPanel({ ticker }) {
  const [heartbeat, setHeartbeat] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/heartbeat/${ticker}`)
        if (res.ok && !cancelled) setHeartbeat(await res.json())
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) return null
  if (!heartbeat || !heartbeat.detected) return null

  const { resistance_level, support_level, range_pct, touches, duration_days, current_price, position_in_range, atr_compression_ratio, wyckoff } = heartbeat
  const highTouches = touches.filter(t => t.type === 'high').length
  const lowTouches = touches.filter(t => t.type === 'low').length

  // Position-in-range visual (0..100% from support to resistance)
  const positionPct = resistance_level > support_level
    ? Math.max(0, Math.min(100, ((current_price - support_level) / (resistance_level - support_level)) * 100))
    : 50

  const positionLabel = position_in_range === 'near_resistance' ? 'nahe Resistance'
    : position_in_range === 'near_support' ? 'nahe Support'
    : 'Mitte'

  // Wyckoff-Quality (Phase 2 / v0.29.1) — additiv, optional. Bei score=-1
  // wird das gesamte Panel visuell degradiert (roter Border + Header-Tönung),
  // damit Distributions-Verdacht im Listing nicht übersehen wird.
  const wyckoffScore = wyckoff?.score
  const wyckoffLabel = wyckoff?.label
  const springDetected = wyckoff?.spring_detected === true
  const springDate = wyckoff?.spring_date
  const springRatio = wyckoff?.spring_volume_ratio

  const isDistribution = wyckoffScore === -1
  const panelClasses = isDistribution
    ? 'bg-card rounded-lg border border-danger/60 p-4'
    : 'bg-card rounded-lg border border-primary/30 p-4'
  const headerClasses = isDistribution
    ? 'flex items-center gap-2 mb-3 -mx-4 -mt-4 px-4 pt-4 pb-2 bg-danger/10 rounded-t-lg'
    : 'flex items-center gap-2 mb-3'

  let wyckoffBadgeClasses = 'text-[10px] px-2 py-0.5 rounded-full ml-auto font-medium'
  if (wyckoffScore === 1) wyckoffBadgeClasses += ' bg-success/15 text-success border border-success/30'
  else if (wyckoffScore === -1) wyckoffBadgeClasses += ' bg-danger/15 text-danger border border-danger/30'
  else if (wyckoffScore === 0) wyckoffBadgeClasses += ' bg-card-alt text-text-secondary border border-border'
  else wyckoffBadgeClasses += ' bg-card-alt/40 text-text-muted border border-border/50'

  return (
    <div className={panelClasses}>
      <div className={headerClasses}>
        <RotateCcw size={16} className="text-primary" />
        <h4 className="text-sm font-medium text-text-secondary">
          <G term="Heartbeat-Pattern">Heartbeat-Pattern aktiv</G>
        </h4>
        {wyckoffScore != null ? (
          <span className={wyckoffBadgeClasses}>
            <G term="Wyckoff-Volumen-Profil">Wyckoff: {wyckoffLabel}</G>
          </span>
        ) : (
          <span className="text-[10px] text-text-muted ml-auto">Wyckoff: keine Volumendaten</span>
        )}
      </div>

      {/* Box-Visualisierung: 2 horizontale Linien mit aktueller Position */}
      <div className="relative bg-card-alt/30 rounded p-3 mb-3" style={{ minHeight: '64px' }}>
        <div className="flex justify-between text-[11px] text-danger font-mono">
          <span>Resistance</span>
          <span>{resistance_level?.toFixed(2)}</span>
        </div>
        <div className="absolute left-3 right-3 border-t border-danger/40" style={{ top: '24px' }} />
        <div className="absolute left-3 right-3 border-t border-success/40" style={{ bottom: '24px' }} />
        <div className="absolute h-2 w-2 rounded-full bg-primary border border-card" style={{ left: `calc(${positionPct}% - 4px)`, top: '50%' }} title={`Aktuell: ${current_price?.toFixed(2)} (${positionLabel})`} />
        <div className="flex justify-between text-[11px] text-success font-mono mt-7">
          <span>Support</span>
          <span>{support_level?.toFixed(2)}</span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-text-muted">Touches</div>
          <div className="font-mono text-text-primary">{highTouches} Highs / {lowTouches} Lows</div>
        </div>
        <div>
          <div className="text-text-muted">Range</div>
          <div className="font-mono text-text-primary">{range_pct?.toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-text-muted">Dauer</div>
          <div className="font-mono text-text-primary">{duration_days} Tage</div>
        </div>
        <div>
          <div className="text-text-muted">Position</div>
          <div className="font-mono text-text-primary">{positionLabel}</div>
        </div>
      </div>

      {atr_compression_ratio !== null && atr_compression_ratio !== undefined && (
        <div className="mt-2 text-[11px] text-text-muted">
          ATR-Kompression: aktuell {(atr_compression_ratio * 100).toFixed(0)}% des 30%-Quantils der letzten 90 Tage
        </div>
      )}

      {springDetected && springDate && (
        <div className="mt-2 text-[11px]">
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-success/10 text-success border border-success/30"
            title={springRatio != null ? `Volumen am Spring-Tag: ${springRatio}x Range-Median` : undefined}
          >
            Spring am {springDate}
            {springRatio != null && (
              <span className="text-text-muted font-mono">({springRatio}x Vol.)</span>
            )}
          </span>
        </div>
      )}

      <p className="text-xs text-text-secondary mt-3">
        Heartbeat-Patterns sind Konsolidierungen — der Ausbruch in eine Richtung ist das eigentliche Setup. Das Wyckoff-Volumen-Profil bewertet die Range-Qualität: schrumpfendes Volumen deutet auf Akkumulation, steigendes auf Distribution.
      </p>
    </div>
  )
}

function ReversalPanel({ ticker }) {
  const [reversal, setReversal] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(false)
    ;(async () => {
      try {
        const res = await authFetch(`/api/analysis/reversal/${ticker}`)
        if (res.ok && !cancelled) setReversal(await res.json())
      } catch { if (!cancelled) setError(true) }
    })()
    return () => { cancelled = true }
  }, [ticker])

  if (error) return <div className="bg-card rounded-lg border border-border p-4 text-xs text-text-secondary">Umkehr-Daten konnten nicht geladen werden.</div>
  if (!reversal || !reversal.detected) return null

  return (
    <div className="bg-card rounded-lg border border-warning/30 p-4">
      <div className="flex items-center gap-2 mb-3">
        <RotateCcw size={16} className="text-warning" />
        <h4 className="text-sm font-medium text-text-secondary">
          <G term="3-Punkt-Umkehr">3-Punkt-Umkehr erkannt</G>
        </h4>
      </div>
      <div className="grid grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-text-muted">LL1</div>
          <div className="font-mono text-text-primary">{reversal.ll1}</div>
          <div className="text-text-muted">{new Date(reversal.ll1_date).toLocaleDateString('de-CH')}</div>
        </div>
        <div>
          <div className="text-text-muted">LL2</div>
          <div className="font-mono text-text-primary">{reversal.ll2}</div>
          <div className="text-text-muted">{new Date(reversal.ll2_date).toLocaleDateString('de-CH')}</div>
        </div>
        <div>
          <div className="text-text-muted">LL3</div>
          <div className="font-mono text-text-primary">{reversal.ll3}</div>
          <div className="text-text-muted">{new Date(reversal.ll3_date).toLocaleDateString('de-CH')}</div>
        </div>
        <div>
          <div className="text-warning font-medium">Higher Low</div>
          <div className="font-mono text-warning">{reversal.hl}</div>
          <div className="text-text-muted">{new Date(reversal.hl_date).toLocaleDateString('de-CH')}</div>
        </div>
      </div>
      <p className="text-xs text-text-secondary mt-3">Drei tiefere Tiefs gefolgt von einem höheren Tief — mögliche Trendwende.</p>
    </div>
  )
}

export default function StockDetail() {
  const { ticker } = useParams()
  const navigate = useNavigate()
  const { data: scoreData } = useApi(`/analysis/score/${ticker}`)
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
          <TickerLogo ticker={ticker} size={28} />
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

      {/* Phase 1.1: Konzentrations-Banner — Single-Name + Sektor */}
      <ConcentrationBanner
        concentration={scoreData?.concentration}
        ticker={ticker}
        liquidPortfolioChf={scoreData?.liquid_portfolio_chf}
      />

      {/* Position info */}
      <MyPositionPanel ticker={ticker} />
      <EtfSectorPanelWrapper ticker={ticker} />

      {/* Chart with controls */}
      <TradingViewChart ticker={ticker} height={600} showControls />

      {/* Analysis panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <LevelsPanel ticker={ticker} />
        <MrsPanel mrs={scoreData?.mansfield_rs} />
      </div>

      <BreakoutEvents ticker={ticker} />
      <ReversalPanel ticker={ticker} />
      <HeartbeatPanel ticker={ticker} />

      {/* Smart Money Context */}
      <SmartMoneyPanel ticker={ticker} />

      {/* Score + Fundamentals */}
      <StockScoreCard ticker={ticker} scoreData={scoreData} />
      <FundamentalCharts ticker={ticker} />

      <DisclaimerBanner />
    </div>
  )
}
