import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Radar, Play, AlertTriangle, BookmarkPlus, BookmarkCheck, ChevronDown, ChevronUp, Users, TrendingDown, RotateCcw, Building2 } from 'lucide-react'
import { useApi, authFetch } from '../hooks/useApi'
import { useToast } from '../components/Toast'

const SIGNAL_CONFIG = {
  insider_cluster: { label: 'Insider-Cluster', short: 'I', icon: Users, description: 'Mehrere Insider kaufen gleichzeitig' },
  large_buy: { label: 'Grosser Insider-Kauf', short: 'I', icon: Users, description: 'Insider-Kauf > $500k' },
  buyback: { label: 'Aktienrückkauf', short: 'B', icon: Building2, description: '8-K Rückkaufprogramm angekündigt' },
  short_trend: { label: 'Short-Trend', short: 'S', icon: TrendingDown, description: 'Short-Ratio stark gestiegen (14 Tage)' },
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

function ScanProgress({ scanId, onComplete }) {
  const [progress, setProgress] = useState(null)

  useEffect(() => {
    if (!scanId) return
    let active = true
    const poll = async () => {
      try {
        const res = await authFetch(`/api/screening/scan/${scanId}/progress`)
        if (!res.ok) return
        const data = await res.json()
        if (active) {
          setProgress(data)
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

  if (!progress) return null

  const steps = progress.steps || []
  const doneCount = steps.filter(s => s.status === 'done').length
  const totalCount = steps.length
  const pct = totalCount > 0 ? (doneCount / totalCount) * 100 : 0

  return (
    <div className="bg-card border border-border rounded-xl p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">Screening läuft...</h3>
        <span className="text-xs text-text-muted">{doneCount} von {totalCount} Quellen</span>
      </div>
      <div className="w-full bg-border rounded-full h-2">
        <div className="bg-primary h-2 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <div className="space-y-2">
        {steps.map(step => (
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
      <p className="text-xs text-text-muted">
        Über 11'000 US-Aktien werden nach institutioneller Aktivität durchsucht.
      </p>
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
              <span className="text-text-primary font-medium">{cfg.label}</span>
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
              {key === 'buyback' && (
                <span className="text-text-muted ml-2">
                  8-K Filing{data.filing_date ? ` vom ${data.filing_date}` : ''}
                </span>
              )}
              {key === 'short_trend' && (
                <span className="text-text-muted ml-2">
                  {data.ratio_start ? `${(data.ratio_start * 100).toFixed(1)}%` : '?'} &rarr; {data.ratio_end ? `${(data.ratio_end * 100).toFixed(1)}%` : '?'}
                  {data.change_pct != null ? ` (${data.change_pct > 0 ? '+' : ''}${data.change_pct}%)` : ''}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function Screening() {
  const navigate = useNavigate()
  const { addToast } = useToast()
  const [scanning, setScanning] = useState(false)
  const [scanId, setScanId] = useState(null)
  const [minScore, setMinScore] = useState(1)
  const [expandedRow, setExpandedRow] = useState(null)
  const [addedTickers, setAddedTickers] = useState(new Set())

  const { data: resultsData, loading, refetch } = useApi(
    `/screening/results?min_score=${minScore}&per_page=100`,
    { skip: scanning }
  )

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

  const results = resultsData?.results || []
  const total = resultsData?.total || 0
  const scannedAt = resultsData?.scanned_at

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
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <label className="text-sm text-text-secondary flex items-center gap-2">
              Score &ge;
              <select
                value={minScore}
                onChange={e => setMinScore(Number(e.target.value))}
                className="bg-card border border-border rounded px-2 py-1 text-sm text-text-primary"
              >
                {[1, 2, 3, 4, 5, 6, 7].map(n => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
            {total > 0 && (
              <span className="text-sm text-text-muted">{total} Aktien</span>
            )}
          </div>
          {scannedAt && (
            <span className="text-xs text-text-muted">
              Stand: {new Date(scannedAt).toLocaleString('de-CH')}
            </span>
          )}
        </div>
      )}

      {/* Results Table */}
      {!scanning && !loading && results.length === 0 && !scannedAt && (
        <div className="bg-card border border-border rounded-xl p-12 text-center">
          <Radar size={40} className="text-text-muted mx-auto mb-4" />
          <p className="text-text-secondary">
            Drücke "Jetzt scannen" um US-Aktien nach Smart-Money-Aktivität zu durchsuchen.
          </p>
        </div>
      )}

      {!scanning && !loading && results.length === 0 && scannedAt && (
        <div className="bg-card border border-border rounded-xl p-8 text-center">
          <p className="text-text-secondary">Keine Aktien entsprechen den gewählten Filtern.</p>
          <button
            onClick={() => setMinScore(1)}
            className="mt-3 text-sm text-primary hover:underline"
          >
            Filter zurücksetzen
          </button>
        </div>
      )}

      {!scanning && results.length > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-4 py-3 font-medium w-8"></th>
                <th className="px-4 py-3 font-medium">Ticker</th>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Score</th>
                <th className="px-4 py-3 font-medium">Signale</th>
                <th className="px-4 py-3 font-medium text-right">Aktion</th>
              </tr>
            </thead>
            {results.map(r => {
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
                      <button
                        onClick={e => { e.stopPropagation(); navigate(`/stock/${r.ticker}`) }}
                        className="font-mono font-semibold text-primary hover:underline"
                      >
                        {r.ticker}
                      </button>
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
