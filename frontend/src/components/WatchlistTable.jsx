import { useState, useEffect, useCallback, useMemo, forwardRef, useImperativeHandle } from 'react'
import { Link } from 'react-router-dom'
import { useApi, apiPost, apiDelete, authFetch } from '../hooks/useApi'
import { formatPct } from '../lib/format'
import { Trash2, Plus, Loader2, Search, RefreshCw, ChevronUp, ChevronDown, Bell, BellRing, X, MessageSquare, Tag, Crosshair } from 'lucide-react'
import TickerSearch from './TickerSearch'
import AlertPopover from './AlertPopover'
import MiniChartTooltip from './MiniChartTooltip'
import G from './GlossarTooltip'
import LoadingSpinner from './LoadingSpinner'

const SIGNAL_COLORS = {
  ETF_KAUFSIGNAL: 'text-teal-400',
  KAUFSIGNAL: 'text-success',
  WATCHLIST: 'text-warning',
  BEOBACHTEN: 'text-text-muted',
  'KEIN SETUP': 'text-danger',
}

function SignalDot({ score, loading }) {
  if (loading) {
    return <Loader2 size={10} className="animate-spin text-text-muted flex-shrink-0" />
  }
  if (score == null) {
    return <span className="w-2.5 h-2.5 rounded-full bg-border flex-shrink-0" />
  }
  const color = SIGNAL_COLORS[score.signal] || SIGNAL_COLORS['KEIN SETUP']
  return (
    <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${color}`} style={{ backgroundColor: 'currentColor' }} title={score.signal} />
  )
}

const WatchlistTable = forwardRef(function WatchlistTable({ onSelectTicker, selectedTicker }, ref) {
  const { data: rawData, loading, refetch } = useApi('/analysis/watchlist')
  const data = rawData?.items || rawData || []
  const activeAlertsCount = rawData?.active_alerts_count || 0

  useImperativeHandle(ref, () => ({ refetch }))
  const [adding, setAdding] = useState(false)
  const [newTicker, setNewTicker] = useState('')
  const [newName, setNewName] = useState('')
  const [newSector, setNewSector] = useState('')
  const [scores, setScores] = useState({})
  const [loadingScores, setLoadingScores] = useState({})
  const [deleting, setDeleting] = useState(null)
  const [sortKey, setSortKey] = useState('signal')
  const [sortAsc, setSortAsc] = useState(false)
  const [alertTicker, setAlertTicker] = useState(null)
  const [editingNotes, setEditingNotes] = useState(null)
  const [notesValue, setNotesValue] = useState('')
  const [tagInput, setTagInput] = useState(null)
  const [tagValue, setTagValue] = useState('')
  const [filterTags, setFilterTags] = useState([])
  const [knownTags, setKnownTags] = useState([])
  const [tagSuggestions, setTagSuggestions] = useState([])
  const [resistanceTicker, setResistanceTicker] = useState(null)
  const [resistanceValue, setResistanceValue] = useState('')
  const [resistanceSaving, setResistanceSaving] = useState(false)

  const signalOrder = { ETF_KAUFSIGNAL: 0, KAUFSIGNAL: 1, WATCHLIST: 2, BEOBACHTEN: 3, 'KEIN SETUP': 4 }

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(key === 'ticker' || key === 'name' || key === 'sector')
    }
  }

  // Collect all unique tags for filter bar
  const allTags = useMemo(() => {
    if (!data?.length) return []
    const tagMap = {}
    for (const w of data) {
      for (const t of (w.tags || [])) {
        tagMap[t.id] = t
      }
    }
    return Object.values(tagMap).sort((a, b) => a.name.localeCompare(b.name))
  }, [data])

  // Fetch all known tags for autocomplete
  useEffect(() => {
    authFetch('/api/analysis/tags')
      .then(r => r.ok ? r.json() : [])
      .then(data => setKnownTags(data))
      .catch(() => {})
  }, [data]) // refetch when watchlist data changes (new tags may have been created)

  const filteredData = useMemo(() => {
    if (!data?.length) return []
    if (filterTags.length === 0) return data
    return data.filter((w) => {
      const itemTagIds = (w.tags || []).map((t) => t.id)
      return filterTags.every((ft) => itemTagIds.includes(ft))
    })
  }, [data, filterTags])

  const sortedData = useMemo(() => {
    if (!filteredData?.length) return []
    return [...filteredData].sort((a, b) => {
      let va, vb
      if (sortKey === 'signal') {
        va = signalOrder[scores[a.ticker]?.signal] ?? 99
        vb = signalOrder[scores[b.ticker]?.signal] ?? 99
      } else if (sortKey === 'setup') {
        va = scores[a.ticker]?.passed ?? -1
        vb = scores[b.ticker]?.passed ?? -1
      } else if (sortKey === 'distance') {
        va = scores[a.ticker]?.distance ?? -999
        vb = scores[b.ticker]?.distance ?? -999
      } else if (sortKey === 'volume_ratio') {
        va = scores[a.ticker]?.volume_ratio ?? -1
        vb = scores[b.ticker]?.volume_ratio ?? -1
      } else if (sortKey === 'price') {
        va = a.price ?? -1
        vb = b.price ?? -1
      } else if (sortKey === 'change_pct') {
        va = a.change_pct ?? -999
        vb = b.change_pct ?? -999
      } else if (sortKey === 'tags') {
        va = a.tags?.[0]?.name || '\uffff'
        vb = b.tags?.[0]?.name || '\uffff'
      } else {
        va = a[sortKey] ?? ''
        vb = b[sortKey] ?? ''
      }
      if (typeof va === 'string') {
        const cmp = va.localeCompare(vb)
        return sortAsc ? cmp : -cmp
      }
      return sortAsc ? va - vb : vb - va
    })
  }, [filteredData, scores, sortKey, sortAsc])

  const loadScore = useCallback(async (ticker) => {
    if (scores[ticker] || loadingScores[ticker]) return
    setLoadingScores((prev) => ({ ...prev, [ticker]: true }))
    try {
      const res = await authFetch(`/api/analysis/score/${ticker}`)
      if (res.ok) {
        const json = await res.json()
        setScores((prev) => ({
          ...prev,
          [ticker]: {
            passed: json.score,
            total: json.max_score,
            pct: json.pct,
            rating: json.rating,
            signal: json.signal,
            signal_label: json.signal_label,
            distance: json.breakout?.distance_to_resistance_pct ?? null,
            volume_ratio: json.breakout?.volume_ratio ?? null,
          },
        }))
      }
    } catch {
      // Silently fail
    } finally {
      setLoadingScores((prev) => ({ ...prev, [ticker]: false }))
    }
  }, [scores, loadingScores])

  useEffect(() => {
    if (!data?.length) return
    let cancelled = false
    const tickers = data.map(d => d.ticker).filter(t => !scores[t] && !loadingScores[t])
    if (!tickers.length) return
    Promise.allSettled(tickers.map(ticker => {
      if (cancelled) return Promise.resolve()
      return loadScore(ticker)
    }))
    return () => { cancelled = true }
  }, [data]) // intentionally only depend on data

  const handleAdd = async (e) => {
    e.preventDefault()
    if (!newTicker.trim()) return
    try {
      await apiPost('/analysis/watchlist', {
        ticker: newTicker.toUpperCase(),
        name: newName || newTicker.toUpperCase(),
        sector: newSector || null,
      })
      setNewTicker('')
      setNewName('')
      setNewSector('')
      setAdding(false)
      refetch()
    } catch (err) {
      console.error(err)
    }
  }

  const handleDelete = async (id) => {
    setDeleting(id)
    try {
      await apiDelete(`/analysis/watchlist/${id}`)
      refetch()
    } catch (err) {
      console.error(err)
    } finally {
      setDeleting(null)
    }
  }

  const refreshScore = async (ticker) => {
    setScores((prev) => {
      const copy = { ...prev }
      delete copy[ticker]
      return copy
    })
    setLoadingScores((prev) => ({ ...prev, [ticker]: false }))
    setTimeout(() => loadScore(ticker), 100)
  }

  const saveNotes = async (itemId) => {
    try {
      await authFetch(`/api/analysis/watchlist/${itemId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: notesValue }),
      })
      refetch()
    } catch (err) {
      console.error(err)
    }
    setEditingNotes(null)
  }

  const saveResistance = async (ticker) => {
    setResistanceSaving(true)
    try {
      const val = resistanceValue.trim() === '' ? null : parseFloat(resistanceValue)
      await authFetch(`/api/analysis/resistance/${encodeURIComponent(ticker)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ manual_resistance: val }),
      })
      refreshScore(ticker)
      refetch()
    } catch (err) {
      console.error(err)
    }
    setResistanceSaving(false)
    setResistanceTicker(null)
  }

  const addTag = async (itemId, tagName) => {
    const name = (tagName || tagValue).trim()
    if (!name) return
    try {
      await apiPost(`/analysis/watchlist/${itemId}/tags`, { name })
      setTagInput(null)
      setTagValue('')
      setTagSuggestions([])
      refetch()
    } catch (err) {
      console.error(err)
    }
  }

  const handleTagInputChange = (value, itemId) => {
    setTagValue(value)
    if (value.trim()) {
      const itemTags = (data.find(i => i.id === itemId)?.tags || []).map(t => t.name.toLowerCase())
      const filtered = knownTags
        .filter(t => t.name.toLowerCase().includes(value.toLowerCase()))
        .filter(t => !itemTags.includes(t.name.toLowerCase()))
        .slice(0, 5)
      setTagSuggestions(filtered)
    } else {
      setTagSuggestions([])
    }
  }

  const removeTag = async (itemId, tagId) => {
    try {
      await apiDelete(`/analysis/watchlist/${itemId}/tags/${tagId}`)
      refetch()
    } catch (err) {
      console.error(err)
    }
  }

  const toggleFilterTag = (tagId) => {
    setFilterTags((prev) =>
      prev.includes(tagId) ? prev.filter((t) => t !== tagId) : [...prev, tagId]
    )
  }

  const headers = [
    { key: 'ticker', label: 'Ticker', align: 'text-left' },
    { key: 'name', label: 'Name', align: 'text-left' },
    { key: 'price', label: 'Kurs', align: 'text-right' },
    { key: 'change_pct', label: 'Veränderung', align: 'text-right' },
    { key: 'sector', label: 'Sektor', align: 'text-left', hideMobile: true },
    { key: 'setup', label: <G term="Setup-Score">Score</G>, align: 'text-center' },
    { key: 'distance', label: <G term="Breakout">Breakout</G>, align: 'text-right', hideMobile: true },
    { key: 'volume_ratio', label: 'Vol-Ratio', align: 'text-right', hideMobile: true },
  ]

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Search size={16} className="text-text-muted" />
          <h3 className="text-sm font-medium text-text-secondary">
            Watchlist
            {data?.length > 0 && <span className="text-text-muted ml-1">({data.length})</span>}
            <span className="text-text-muted ml-1">— 18-Punkte Kauf-Checkliste</span>
            {activeAlertsCount > 0 && (
              <span className="ml-2 text-xs px-1.5 py-0.5 rounded-full bg-warning/20 text-warning">{activeAlertsCount} Alarme</span>
            )}
          </h3>
        </div>
        <button
          onClick={() => setAdding(!adding)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            adding
              ? 'bg-danger/10 text-danger hover:bg-danger/20'
              : 'bg-primary/10 text-primary hover:bg-primary/20'
          }`}
        >
          {adding ? (
            <><Trash2 size={13} /> Abbrechen</>
          ) : (
            <><Plus size={13} /> Aktie hinzufügen</>
          )}
        </button>
      </div>

      {/* Tag filter bar */}
      {allTags.length > 0 && (
        <div className="px-4 py-2 border-b border-border/50 flex items-center gap-1.5 flex-wrap">
          <Tag size={12} className="text-text-muted" />
          {allTags.map((t) => (
            <button
              key={t.id}
              onClick={() => toggleFilterTag(t.id)}
              className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                filterTags.includes(t.id)
                  ? 'border-transparent text-white'
                  : 'border-border text-text-muted hover:border-text-secondary'
              }`}
              style={filterTags.includes(t.id) ? { backgroundColor: t.color } : {}}
            >
              {t.name}
            </button>
          ))}
          {filterTags.length > 0 && (
            <button onClick={() => setFilterTags([])} className="text-xs text-text-muted hover:text-danger ml-1">
              <X size={12} />
            </button>
          )}
        </div>
      )}

      {/* Add form */}
      {adding && (
        <form onSubmit={handleAdd} className="p-4 border-b border-border bg-card-alt/30">
          <div className="flex gap-2 flex-wrap items-start">
            <TickerSearch
              value={newTicker}
              onChange={setNewTicker}
              onSelect={(s) => {
                setNewTicker(s.ticker)
                setNewName(s.name || '')
                setNewSector(s.sector || '')
              }}
              onSubmit={() => {}}
              placeholder="Ticker *"
              autoFocus
              className="w-40"
            />
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Name (auto-fill)"
              className="bg-card border border-border rounded-lg px-3 py-2.5 text-sm text-text-primary flex-1 min-w-[160px] focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
            <input
              value={newSector}
              onChange={(e) => setNewSector(e.target.value)}
              placeholder="Sektor (auto-fill)"
              className="bg-card border border-border rounded-lg px-3 py-2.5 text-sm text-text-primary w-40 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
            />
            <button type="submit" className="bg-primary text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-primary/80 transition-colors">
              Hinzufügen
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="p-12">
          <LoadingSpinner text="Watchlist laden..." />
        </div>
      ) : !data?.length ? (
        <div className="p-12 text-center">
          <p className="text-text-muted text-sm">Noch keine Aktien auf der Watchlist.</p>
          <button
            onClick={() => setAdding(true)}
            className="mt-3 text-primary text-sm hover:underline"
          >
            Erste Aktie hinzufügen
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-text-muted">
                {headers.map((h) => (
                  <th
                    key={h.key}
                    className={`${h.align} p-3 font-medium cursor-pointer hover:text-text-primary transition-colors select-none whitespace-nowrap ${sortKey === h.key ? 'text-primary' : ''} ${h.hideMobile ? 'hidden md:table-cell' : ''}`}
                    onClick={() => handleSort(h.key)}
                  >
                    {h.label}
                    {sortKey === h.key && <span className="ml-1 text-primary inline-flex">{sortAsc ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>}
                  </th>
                ))}
                <th className="p-3 text-center font-medium whitespace-nowrap hidden md:table-cell">Alarm</th>
                <th className="p-3 text-left font-medium whitespace-nowrap hidden md:table-cell">Tags</th>
                <th className="p-3 text-left font-medium whitespace-nowrap hidden md:table-cell">Notizen</th>
                <th className="p-3 w-20" />
              </tr>
            </thead>
            <tbody>
              {sortedData.map((w) => {
                const isSelected = selectedTicker === w.ticker
                const s = scores[w.ticker]
                const isLoading = loadingScores[w.ticker]
                return (
                  <tr
                    key={w.id}
                    className={`border-b border-border/50 transition-colors cursor-pointer ${
                      isSelected ? 'bg-primary/5' : 'hover:bg-card-alt/50'
                    }`}
                    onClick={() => onSelectTicker?.(w.ticker)}
                  >
                    {/* Ticker */}
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <SignalDot score={s} loading={isLoading} />
                        <MiniChartTooltip ticker={w.ticker}><Link to={`/stock/${encodeURIComponent(w.ticker)}`} onClick={(e) => e.stopPropagation()} className="font-mono text-primary font-medium hover:underline">{w.ticker}</Link></MiniChartTooltip>
                      </div>
                    </td>
                    {/* Name */}
                    <td className="p-3 text-text-primary">{w.name}</td>
                    {/* Price */}
                    <td className="p-3 text-right tabular-nums">
                      {w.price != null ? (
                        <span className="text-text-primary">{w.currency} {w.price.toLocaleString('de-CH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                      ) : (
                        <span className="text-text-muted text-xs">–</span>
                      )}
                    </td>
                    {/* Change % */}
                    <td className="p-3 text-right tabular-nums">
                      {w.change_pct != null ? (
                        <span className={`text-xs font-mono ${w.change_pct >= 0 ? 'text-success' : 'text-danger'}`}>
                          {w.change_pct > 0 ? '+' : ''}{w.change_pct.toFixed(2)}%
                        </span>
                      ) : (
                        <span className="text-text-muted text-xs">–</span>
                      )}
                    </td>
                    {/* Sector */}
                    <td className="p-3 text-text-secondary text-xs hidden md:table-cell">{w.sector || '–'}</td>
                    {/* Score */}
                    <td className="p-3 text-center">
                      {isLoading ? (
                        <Loader2 size={14} className="animate-spin text-text-muted mx-auto" />
                      ) : s ? (
                        <span className="font-mono text-xs text-text-secondary">
                          {s.passed}/{s.total}
                        </span>
                      ) : (
                        <span className="text-text-muted text-xs">–</span>
                      )}
                    </td>
                    {/* Breakout */}
                    <td className="p-3 text-right hidden md:table-cell">
                      {s?.distance != null ? (
                        <span className={`font-mono text-xs ${s.distance >= 0 ? 'text-success' : 'text-danger'}`}>
                          {s.distance > 0 ? '+' : ''}{s.distance.toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-text-muted text-xs">–</span>
                      )}
                    </td>
                    {/* Vol-Ratio */}
                    <td className="p-3 text-right hidden md:table-cell">
                      {s?.volume_ratio != null ? (
                        <span className={`font-mono text-xs ${s.volume_ratio >= 2 ? 'text-success' : 'text-text-secondary'}`}>
                          {s.volume_ratio.toFixed(1)}×
                        </span>
                      ) : (
                        <span className="text-text-muted text-xs">–</span>
                      )}
                    </td>
                    {/* Alarm */}
                    <td className="p-3 text-center hidden md:table-cell" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => setAlertTicker(alertTicker === w.ticker ? null : w.ticker)}
                        className={`p-1.5 rounded transition-colors ${
                          w.active_alerts > 0
                            ? 'text-warning hover:bg-warning/10'
                            : 'text-text-muted hover:text-primary hover:bg-primary/10'
                        }`}
                        title={w.active_alerts > 0 ? `${w.active_alerts} aktive Alarme` : 'Alarm erstellen'}
                        aria-label={w.active_alerts > 0 ? `${w.active_alerts} aktive Alarme` : 'Alarm erstellen'}
                      >
                        {w.active_alerts > 0 ? <BellRing size={14} /> : <Bell size={14} />}
                      </button>
                      {alertTicker === w.ticker && (
                        <AlertPopover
                          ticker={w.ticker}
                          currency={w.currency}
                          resistance={w.manual_resistance}
                          onClose={() => { setAlertTicker(null); refetch() }}
                        />
                      )}
                    </td>
                    {/* Tags */}
                    <td className="p-3 hidden md:table-cell" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1 flex-wrap">
                        {(w.tags || []).map((t) => (
                          <span
                            key={t.id}
                            className="text-xs px-1.5 py-0.5 rounded-full text-white flex items-center gap-0.5 cursor-pointer"
                            style={{ backgroundColor: t.color }}
                            onClick={() => toggleFilterTag(t.id)}
                          >
                            {t.name}
                            <button
                              onClick={(e) => { e.stopPropagation(); removeTag(w.id, t.id) }}
                              className="hover:text-white/60"
                              aria-label="Tag entfernen"
                            >
                              <X size={10} />
                            </button>
                          </span>
                        ))}
                        {(w.tags || []).length < 5 && (
                          tagInput === w.id ? (
                            <div className="relative">
                              <input
                                value={tagValue}
                                onChange={(e) => handleTagInputChange(e.target.value, w.id)}
                                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag(w.id) } if (e.key === 'Escape') { setTagInput(null); setTagValue(''); setTagSuggestions([]) } }}
                                onBlur={(e) => { if (e.relatedTarget?.dataset?.tagSuggestion) return; setTimeout(() => { if (tagValue.trim()) addTag(w.id); else { setTagInput(null); setTagValue(''); setTagSuggestions([]) } }, 150) }}
                                placeholder="Tag..."
                                className="w-20 text-xs bg-transparent border-b border-text-muted text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                                autoFocus
                              />
                              {tagSuggestions.length > 0 && tagInput === w.id && (
                                <div className="absolute top-full left-0 mt-1 bg-card border border-border rounded-lg shadow-lg z-10 min-w-[150px]">
                                  {tagSuggestions.map(tag => (
                                    <button
                                      key={tag.id}
                                      data-tag-suggestion="true"
                                      onMouseDown={(e) => { e.preventDefault(); addTag(w.id, tag.name); setTagSuggestions([]) }}
                                      className="w-full text-left px-3 py-1.5 text-xs text-text-primary hover:bg-card-alt transition-colors"
                                    >
                                      <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ backgroundColor: tag.color }} />
                                      {tag.name}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          ) : (
                            <button
                              onClick={() => { setTagInput(w.id); setTagValue(''); setTagSuggestions([]) }}
                              className="text-text-muted hover:text-primary p-0.5"
                              title="Tag hinzufügen"
                              aria-label="Tag hinzufügen"
                            >
                              <Plus size={12} />
                            </button>
                          )
                        )}
                      </div>
                    </td>
                    {/* Notes */}
                    <td className="p-3 max-w-[200px] hidden md:table-cell" onClick={(e) => e.stopPropagation()}>
                      {editingNotes === w.id ? (
                        <textarea
                          value={notesValue}
                          onChange={(e) => { setNotesValue(e.target.value); e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px' }}
                          onBlur={() => saveNotes(w.id)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveNotes(w.id) } if (e.key === 'Escape') setEditingNotes(null) }}
                          className="w-full text-xs bg-card border border-border rounded px-1.5 py-1 text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 resize-none"
                          rows={1}
                          ref={(el) => { if (el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px' } }}
                          autoFocus
                        />
                      ) : (
                        <button
                          onClick={() => { setEditingNotes(w.id); setNotesValue(w.notes || '') }}
                          className="text-left w-full group"
                          title={w.notes || 'Notiz hinzufügen'}
                        >
                          {w.notes ? (
                            <span className="text-xs text-text-secondary whitespace-pre-wrap block max-h-[5lh] overflow-y-auto">{w.notes}</span>
                          ) : (
                            <MessageSquare size={12} className="text-text-muted group-hover:text-primary" />
                          )}
                        </button>
                      )}
                    </td>
                    {/* Actions */}
                    <td className="p-3">
                      <div className="flex items-center gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
                        <div className="relative">
                          <button
                            onClick={() => { setResistanceTicker(resistanceTicker === w.ticker ? null : w.ticker); setResistanceValue(w.manual_resistance != null ? String(w.manual_resistance) : '') }}
                            className={`p-1.5 rounded transition-colors ${
                              w.manual_resistance != null
                                ? 'text-primary hover:bg-primary/10'
                                : 'text-text-muted hover:text-primary hover:bg-primary/10'
                            }`}
                            title="Resistance-Level (Breakout) anpassen"
                            aria-label="Resistance-Level anpassen"
                          >
                            <Crosshair size={13} />
                          </button>
                          {resistanceTicker === w.ticker && (
                            <>
                              <div className="fixed inset-0 z-10" onClick={() => setResistanceTicker(null)} />
                              <div className="absolute right-0 top-full mt-1 z-20 bg-card border border-border rounded-lg shadow-xl p-3 w-56">
                                <label htmlFor={`resistance-${w.ticker}`} className="block text-xs font-medium text-text-muted mb-1">
                                  Resistance-Level (Breakout)
                                </label>
                                <input
                                  id={`resistance-${w.ticker}`}
                                  type="number"
                                  step="0.01"
                                  value={resistanceValue}
                                  onChange={(e) => setResistanceValue(e.target.value)}
                                  onKeyDown={(e) => { if (e.key === 'Enter') saveResistance(w.ticker); if (e.key === 'Escape') setResistanceTicker(null) }}
                                  placeholder="Leer = auto (52W-Hoch)"
                                  className="w-full bg-card-alt border border-border rounded px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30"
                                  autoFocus
                                />
                                <div className="flex justify-end gap-2 mt-2">
                                  <button
                                    onClick={() => setResistanceTicker(null)}
                                    className="text-xs text-text-muted hover:text-text-primary"
                                  >
                                    Abbrechen
                                  </button>
                                  <button
                                    onClick={() => saveResistance(w.ticker)}
                                    disabled={resistanceSaving}
                                    className="text-xs bg-primary text-white rounded px-3 py-1 hover:bg-primary/80 disabled:opacity-40"
                                  >
                                    {resistanceSaving ? 'Speichern...' : 'Speichern'}
                                  </button>
                                </div>
                              </div>
                            </>
                          )}
                        </div>
                        <button
                          onClick={() => refreshScore(w.ticker)}
                          className="p-1.5 rounded text-text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                          title="Score neu laden"
                          aria-label="Score neu laden"
                        >
                          <RefreshCw size={13} />
                        </button>
                        <button
                          onClick={() => handleDelete(w.id)}
                          disabled={deleting === w.id}
                          className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors disabled:opacity-40"
                          title="Entfernen"
                          aria-label="Entfernen"
                        >
                          {deleting === w.id ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <Trash2 size={13} />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
})

export default WatchlistTable
