import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Radar, Play, AlertTriangle, BookmarkPlus, BookmarkCheck, ChevronDown, ChevronUp, ArrowUpDown, ArrowUp, ArrowDown, Users, TrendingDown, RotateCcw, Building2, Search, X, BarChart3, Volume2 } from 'lucide-react'
import { useApi, authFetch } from '../hooks/useApi'
import { useToast } from '../components/Toast'
import MiniChartTooltip from '../components/MiniChartTooltip'
import G from '../components/GlossarTooltip'
import TickerLogo from '../components/TickerLogo'

const SIGNAL_CONFIG = {
  insider_cluster: { label: 'Insider-Cluster', glossar: 'Insider-Cluster', short: 'I', icon: Users, description: 'Mehrere Insider kaufen gleichzeitig' },
  large_buy: { label: 'Grosser Insider-Kauf', glossar: 'Grosser Insider-Kauf', short: 'I', icon: Users, description: 'Insider-Kauf > $500k' },
  superinvestor: { label: 'Superinvestor', glossar: 'Superinvestor', short: 'A', icon: Users, description: 'Buffett, Icahn, Ackman etc. halten Position' },
  activist: { label: 'Aktivist (13D/13G)', glossar: 'Aktivist (13D/13G)', short: 'A', icon: Users, description: 'Aktivist mit 5%+ Beteiligung (SEC Filing)' },
  buyback: { label: 'Aktienrückkauf', glossar: 'Aktienrückkauf', short: 'B', icon: Building2, description: '8-K Rückkaufprogramm angekündigt' },
  congressional: { label: 'Kongresskauf', glossar: 'Kongresskauf', short: 'C', icon: Building2, description: 'US-Kongressmitglied hat gekauft' },
  short_trend: { label: 'Short-Trend', glossar: 'Short-Trend', short: 'S', icon: TrendingDown, description: 'Short-Ratio stark gestiegen (14 Tage)' },
  ftd: { label: 'Fails-to-Deliver', glossar: 'Fails-to-Deliver', short: 'F', icon: AlertTriangle, description: 'Hohe Anzahl nicht gelieferter Aktien (SEC FTD)' },
  unusual_volume: { label: 'Unusual Volume', glossar: 'Unusual Volume', short: 'V', icon: BarChart3, description: 'Volumen > 3× 20-Tage-Durchschnitt' },
}

function SignalBadge({ signalKey }) {
  const cfg = SIGNAL_CONFIG[signalKey]
  if (!cfg) return null
  return (
    <span
      title={cfg.description}
      className="inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold bg-primary/15 text-primary cursor-help"
    >
      {cfg.short}
    </span>
  )
}

function ScoreBar({ score, max = 10 }) {
  const segments = []
  for (let i = 0; i < max; i++) {
    segments.push(
      <div
        key={i}
        className={`h-2.5 flex-1 rounded-sm ${i < score ? 'bg-primary' : 'bg-border'}`}
      />
    )
  }
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex gap-0.5 w-24" aria-label={`Smart Money Score: ${score} von ${max}`}>
        {segments}
      </div>
      <span className="text-sm font-mono text-text-secondary w-4">{score}</span>
    </div>
  )
}

const SCAN_SOURCES = [
  { source: 'openinsider_cluster', label: 'OpenInsider Cluster Buys' },
  { source: 'openinsider_large', label: 'OpenInsider Grosse Käufe' },
  { source: 'sec_buyback', label: 'SEC Buyback-Ankündigungen' },
  { source: 'capitoltrades', label: 'Capitol Trades (Kongress)' },
  { source: 'dataroma', label: 'Dataroma Superinvestoren' },
  { source: 'finra', label: 'FINRA Short Volume' },
  { source: 'activist', label: 'Aktivisten-Tracking (SEC)' },
  { source: 'ftd', label: 'SEC Fails-to-Deliver' },
  { source: 'volume', label: 'Unusual Volume (yfinance)' },
]

function ScanProgress({ scanId, onComplete }) {
  const [steps, setSteps] = useState(null)
  const [elapsed, setElapsed] = useState(0)

  // Poll progress
  useEffect(() => {
    if (!scanId) return
    let active = true
    const poll = async () => {
      try {
        const res = await authFetch(`/api/screening/scan/${scanId}/progress`)
        if (!res.ok) return
        const data = await res.json()
        if (active) {
          if (data.steps?.length) setSteps(data.steps)
          if (data.status === 'completed' || data.status === 'error') {
            onComplete(data)
            return
          }
        }
      } catch { /* ignore */ }
      if (active) setTimeout(poll, 2000)
    }
    poll()
    return () => { active = false }
  }, [scanId, onComplete])

  // Elapsed timer
  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(t)
  }, [])

  // Use server steps if available, otherwise show static list
  const displaySteps = steps || SCAN_SOURCES.map(s => ({ ...s, status: 'running', count: null }))
  const doneCount = displaySteps.filter(s => s.status === 'done' || s.status === 'error').length
  const totalCount = displaySteps.length
  const pct = totalCount > 0 ? (doneCount / totalCount) * 100 : 0

  const minutes = Math.floor(elapsed / 60)
  const seconds = elapsed % 60

  return (
    <div className="bg-card border border-border rounded-xl p-6 space-y-5">
      {/* Header with timer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <RotateCcw size={16} className="text-primary animate-spin" />
          <h3 className="text-sm font-semibold text-text-primary">Screening läuft...</h3>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-text-muted">{doneCount} von {totalCount} Quellen</span>
          <span className="text-xs font-mono text-text-muted bg-card-alt px-2 py-0.5 rounded">
            {minutes}:{seconds.toString().padStart(2, '0')}
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-border rounded-full h-2">
        <div
          className="bg-primary h-2 rounded-full transition-all duration-500"
          style={{ width: pct > 0 ? `${pct}%` : '5%' }}
        />
      </div>

      {/* Source steps */}
      <div className="space-y-2">
        {displaySteps.map(step => (
          <div key={step.source} className="flex items-center gap-3 text-sm">
            <span className="w-4 text-center">
              {step.status === 'done' && <span className="text-success">&#10003;</span>}
              {step.status === 'running' && <span className="text-primary animate-pulse">&#9679;</span>}
              {step.status === 'error' && <span className="text-danger">&#10007;</span>}
              {step.status === 'pending' && <span className="text-text-muted">&#9675;</span>}
            </span>
            <span className={step.status === 'done' ? 'text-text-primary' : 'text-text-muted'}>
              {step.label}
            </span>
            {step.count != null && (
              <span className="text-text-muted text-xs ml-auto">
                {Number(step.count).toLocaleString('de-CH')}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Warning notice */}
      <div className="bg-primary/5 border border-primary/20 rounded-lg px-4 py-3 space-y-1.5">
        <p className="text-sm text-text-secondary">
          Es werden über 11'000 US-Aktien aus 9 verschiedenen Datenquellen gescannt (SEC EDGAR, FINRA, OpenInsider, Capitol Trades, Dataroma, yfinance).
        </p>
        <p className="text-sm font-medium text-text-primary">
          Dieser Vorgang kann bis zu 2 Minuten dauern. Bitte dieses Fenster nicht schliessen oder aktualisieren.
        </p>
      </div>
    </div>
  )
}

function ExpandedRow({ signals }) {
  return (
    <div className="px-4 py-3 bg-card-alt/50 border-t border-border space-y-2">
      {Object.entries(signals).map(([key, data]) => {
        const cfg = SIGNAL_CONFIG[key]
        if (!cfg) return null
        const Icon = cfg.icon
        return (
          <div key={key} className="flex items-start gap-2 text-sm">
            <SignalBadge signalKey={key} />
            <div>
              <span className="text-text-primary font-medium"><G term={cfg.glossar}>{cfg.label}</G></span>
              {key === 'insider_cluster' && data.insider_count && (
                <span className="text-text-muted ml-2">
                  {data.insider_count} Insider, {data.total_value ? `$${Number(data.total_value).toLocaleString('en-US')}` : ''}
                  {data.trade_date ? ` (${data.trade_date})` : ''}
                </span>
              )}
              {key === 'large_buy' && (
                <span className="text-text-muted ml-2">
                  ${Number(data.value || 0).toLocaleString('en-US')}
                  {data.trade_date ? ` (${data.trade_date})` : ''}
                </span>
              )}
              {key === 'superinvestor' && (
                <span className="text-text-muted ml-2">
                  {data.source === 'dataroma_portfolio'
                    ? `${data.num_investors} Superinvestoren halten diese Position`
                    : `${data.investor || 'Superinvestor'} kauft${data.value ? ` ($${Number(data.value).toLocaleString('en-US')})` : ''}`
                  }
                </span>
              )}
              {key === 'activist' && (
                <span className="text-text-muted ml-2">
                  {data.investor || 'Aktivist'} &mdash; {data.form || '13D/13G'}
                  {data.filing_date ? ` (${data.filing_date})` : ''}
                </span>
              )}
              {key === 'buyback' && (
                <span className="text-text-muted ml-2">
                  8-K Filing{data.filing_date ? ` vom ${data.filing_date}` : ''}
                </span>
              )}
              {key === 'congressional' && (
                <span className="text-text-muted ml-2">
                  US-Kongressmitglied hat diese Aktie gekauft (90 Tage)
                </span>
              )}
              {key === 'short_trend' && (
                <span className="text-text-muted ml-2">
                  {data.ratio_start ? `${(data.ratio_start * 100).toFixed(1)}%` : '?'} &rarr; {data.ratio_end ? `${(data.ratio_end * 100).toFixed(1)}%` : '?'}
                  {data.change_pct != null ? ` (${data.change_pct > 0 ? '+' : ''}${data.change_pct}%)` : ''}
                </span>
              )}
              {key === 'ftd' && (
                <span className="text-text-muted ml-2">
                  {data.total_shares ? `${Number(data.total_shares).toLocaleString('de-CH')} Aktien nicht geliefert` : ''}
                  {data.period ? ` (Periode: ${data.period})` : ''}
                </span>
              )}
              {key === 'unusual_volume' && (
                <span className="text-text-muted ml-2">
                  {data.ratio ? `${data.ratio}×` : ''} des 20-Tage-Durchschnitts
                  {data.latest_volume ? ` (${Number(data.latest_volume).toLocaleString('de-CH')} Vol.)` : ''}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const SIGNAL_TYPES = Object.keys(SIGNAL_CONFIG)

function SortIcon({ column, sortBy, sortDir }) {
  if (sortBy !== column) return <ArrowUpDown size={12} className="text-text-muted/50" />
  return sortDir === 'asc' ? <ArrowUp size={12} className="text-primary" /> : <ArrowDown size={12} className="text-primary" />
}

function SortableHeader({ column, label, sortBy, sortDir, onSort, className = '' }) {
  return (
    <th
      className={`px-4 py-3 font-medium cursor-pointer select-none hover:text-text-primary transition-colors ${className}`}
      onClick={() => onSort(column)}
    >
      <div className="flex items-center gap-1.5">
        {label}
        <SortIcon column={column} sortBy={sortBy} sortDir={sortDir} />
      </div>
    </th>
  )
}

export default function Screening() {
  const navigate = useNavigate()
  const { addToast } = useToast()
  const [scanning, setScanning] = useState(false)
  const [scanId, setScanId] = useState(null)
  const [minScore, setMinScore] = useState(3)
  const [expandedRow, setExpandedRow] = useState(null)
  const [addedTickers, setAddedTickers] = useState(new Set())
  const [sortBy, setSortBy] = useState('score')
  const [sortDir, setSortDir] = useState('desc')
  const [tickerFilter, setTickerFilter] = useState('')
  const [signalFilter, setSignalFilter] = useState('')

  const { data: resultsData, loading, refetch } = useApi(
    '/screening/results?min_score=1&per_page=1000',
    { skip: scanning }
  )

  const handleSort = (column) => {
    if (sortBy === column) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(column)
      setSortDir(column === 'ticker' || column === 'name' ? 'asc' : 'desc')
    }
  }

  const handleStartScan = async () => {
    setScanning(true)
    setScanId(null)
    try {
      const res = await authFetch('/api/screening/scan', { method: 'POST' })
      if (!res.ok) {
        addToast('Scan konnte nicht gestartet werden', 'error')
        setScanning(false)
        return
      }
      const data = await res.json()
      setScanId(data.scan_id)
    } catch {
      addToast('Scan konnte nicht gestartet werden', 'error')
      setScanning(false)
    }
  }

  const handleScanComplete = useCallback((data) => {
    setScanning(false)
    setScanId(null)
    if (data.status === 'completed') {
      addToast(`Screening abgeschlossen — ${data.result_count} Aktien mit Smart-Money-Aktivität`, 'success')
      refetch()
    } else {
      addToast('Screening fehlgeschlagen', 'error')
    }
  }, [addToast, refetch])

  const handleAddToWatchlist = async (ticker, name, sector) => {
    try {
      const res = await authFetch('/api/analysis/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, name: name || ticker, sector: sector || '' }),
      })
      if (res.ok) {
        setAddedTickers(prev => new Set([...prev, ticker]))
        addToast(`${ticker} zur Watchlist hinzugefügt`, 'success')
      } else {
        const err = await res.json().catch(() => ({}))
        addToast(err.detail || 'Fehler beim Hinzufügen', 'error')
      }
    } catch {
      addToast('Fehler beim Hinzufügen', 'error')
    }
  }

  const handleResetFilters = () => {
    setMinScore(1)
    setTickerFilter('')
    setSignalFilter('')
    setSortBy('score')
    setSortDir('desc')
  }

  const allResults = resultsData?.results || []
  const scannedAt = resultsData?.scanned_at

  // Client-side filtering
  const filtered = allResults.filter(r => {
    if (r.score < minScore) return false
    if (tickerFilter && !r.ticker.toLowerCase().includes(tickerFilter.toLowerCase()) && !r.name.toLowerCase().includes(tickerFilter.toLowerCase())) return false
    if (signalFilter && !(r.signals && r.signals[signalFilter])) return false
    return true
  })

  // Client-side sorting
  const sorted = [...filtered].sort((a, b) => {
    let cmp = 0
    if (sortBy === 'ticker') cmp = a.ticker.localeCompare(b.ticker)
    else if (sortBy === 'name') cmp = (a.name || '').localeCompare(b.name || '')
    else if (sortBy === 'score') cmp = a.score - b.score
    else if (sortBy === 'signals') cmp = Object.keys(a.signals || {}).length - Object.keys(b.signals || {}).length
    return sortDir === 'asc' ? cmp : -cmp
  })

  const hasActiveFilters = minScore > 1 || tickerFilter || signalFilter

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Radar size={22} className="text-primary" />
          <h2 className="text-xl font-bold text-text-primary">Smart Money Tracker</h2>
          <span className="text-sm text-text-muted">Institutionelles Interesse in US-Aktien</span>
        </div>
        <button
          onClick={handleStartScan}
          disabled={scanning}
          className="bg-primary text-white rounded-lg px-5 py-2.5 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {scanning ? <RotateCcw size={14} className="animate-spin" /> : <Play size={14} />}
          {scanning ? 'Scannt...' : 'Jetzt scannen'}
        </button>
      </div>

      {/* Disclaimer */}
      <div className="bg-warning/10 border border-warning/30 rounded-lg px-4 py-3 flex items-start gap-3">
        <AlertTriangle size={16} className="text-warning mt-0.5 shrink-0" />
        <p className="text-sm text-text-secondary">
          Dieses Tool zeigt beobachtbare Marktaktivität. Es handelt sich um keine Handlungsempfehlung.
        </p>
      </div>

      {/* Scan Progress */}
      {scanning && scanId && (
        <ScanProgress scanId={scanId} onComplete={handleScanComplete} />
      )}

      {/* Filters & Status */}
      {!scanning && (
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3 flex-wrap">
            {/* Ticker/Name search */}
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                value={tickerFilter}
                onChange={e => setTickerFilter(e.target.value)}
                placeholder="Ticker oder Name..."
                aria-label="Ticker oder Name suchen"
                className="bg-card border border-border rounded pl-8 pr-7 py-1.5 text-sm text-text-primary w-48 placeholder:text-text-muted"
              />
              {tickerFilter && (
                <button onClick={() => setTickerFilter('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary">
                  <X size={12} />
                </button>
              )}
            </div>

            {/* Score filter */}
            <label className="text-sm text-text-secondary flex items-center gap-2">
              Score &ge;
              <select
                value={minScore}
                onChange={e => setMinScore(Number(e.target.value))}
                className="bg-card border border-border rounded px-2 py-1.5 text-sm text-text-primary"
              >
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>

            {/* Signal type filter */}
            <select
              value={signalFilter}
              onChange={e => setSignalFilter(e.target.value)}
              aria-label="Signal-Typ filtern"
              className="bg-card border border-border rounded px-2 py-1.5 text-sm text-text-primary"
            >
              <option value="">Alle Signale</option>
              {SIGNAL_TYPES.map(key => (
                <option key={key} value={key}>{SIGNAL_CONFIG[key].label}</option>
              ))}
            </select>

            {hasActiveFilters && (
              <button onClick={handleResetFilters} className="text-xs text-primary hover:underline">
                Alle Filter zurücksetzen
              </button>
            )}

            <span className="text-sm text-text-muted">{sorted.length} Aktien</span>
          </div>
          {scannedAt && (
            <span className="text-xs text-text-muted">
              Stand: {new Date(scannedAt).toLocaleString('de-CH')}
            </span>
          )}
        </div>
      )}

      {/* Results Table */}
      {!scanning && !loading && allResults.length === 0 && !scannedAt && (
        <div className="bg-card border border-border rounded-xl p-12 text-center">
          <Radar size={40} className="text-text-muted mx-auto mb-4" />
          <p className="text-text-secondary">
            Drücke "Jetzt scannen" um US-Aktien nach Smart-Money-Aktivität zu durchsuchen.
          </p>
        </div>
      )}

      {!scanning && !loading && sorted.length === 0 && allResults.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-8 text-center">
          <p className="text-text-secondary">Keine Aktien entsprechen den gewählten Filtern.</p>
          <button onClick={handleResetFilters} className="mt-3 text-sm text-primary hover:underline">
            Filter zurücksetzen
          </button>
        </div>
      )}

      {!scanning && sorted.length > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-4 py-3 font-medium w-8"></th>
                <SortableHeader column="ticker" label="Ticker" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <SortableHeader column="name" label="Name" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <SortableHeader column="score" label="Score" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <SortableHeader column="signals" label="Signale" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                <th className="px-4 py-3 font-medium text-right">Aktion</th>
              </tr>
            </thead>
            {sorted.map(r => {
              const isExpanded = expandedRow === r.ticker
              const isAdded = addedTickers.has(r.ticker)
              return (
                <tbody key={r.ticker}>
                  <tr
                    className="border-b border-border/50 hover:bg-card-alt/30 transition-colors cursor-pointer"
                    onClick={() => setExpandedRow(isExpanded ? null : r.ticker)}
                  >
                    <td className="px-4 py-3 text-text-muted">
                      {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </td>
                    <td className="px-4 py-3">
                      <MiniChartTooltip ticker={r.ticker}>
                        <button
                          onClick={e => { e.stopPropagation(); navigate(`/stock/${r.ticker}`) }}
                          className="flex items-center gap-2 font-mono font-semibold text-primary hover:underline"
                        >
                          <TickerLogo ticker={r.ticker} size={20} />
                          {r.ticker}
                        </button>
                      </MiniChartTooltip>
                    </td>
                    <td className="px-4 py-3 text-text-secondary truncate max-w-[200px]">{r.name}</td>
                    <td className="px-4 py-3">
                      <ScoreBar score={r.score} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1">
                        {Object.keys(r.signals || {}).map(key => (
                          <SignalBadge key={key} signalKey={key} />
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={e => { e.stopPropagation(); handleAddToWatchlist(r.ticker, r.name, r.sector) }}
                        disabled={isAdded}
                        className={`p-1.5 rounded-lg transition-colors ${
                          isAdded
                            ? 'text-success cursor-default'
                            : 'text-text-muted hover:text-primary hover:bg-primary/10'
                        }`}
                        title={isAdded ? 'In Watchlist' : `${r.ticker} zur Watchlist hinzufügen`}
                        aria-label={isAdded ? `${r.ticker} bereits in Watchlist` : `${r.ticker} zur Watchlist hinzufügen`}
                      >
                        {isAdded ? <BookmarkCheck size={16} /> : <BookmarkPlus size={16} />}
                      </button>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={6}>
                        <ExpandedRow signals={r.signals} />
                      </td>
                    </tr>
                  )}
                </tbody>
              )
            })}
          </table>
        </div>
      )}
    </div>
  )
}
