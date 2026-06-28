import { useState, useEffect, useCallback, useMemo, forwardRef, useImperativeHandle } from 'react'
import { Link } from 'react-router-dom'
import { useApi, apiPost, apiDelete, authFetch } from '../hooks/useApi'
import { formatDate, formatNumber } from '../lib/format'
import {
  Trash2, Plus, Loader2, RefreshCw, ChevronUp, ChevronDown, Bell, BellRing, X,
  MessageSquare, Tag, Crosshair, Bot, Check, Minus, AlertTriangle, Hourglass,
} from 'lucide-react'
import TickerSearch from './TickerSearch'
import AlertPopover from './AlertPopover'
import MiniChartTooltip from './MiniChartTooltip'
import G from './GlossarTooltip'
import LoadingSpinner from './LoadingSpinner'
import TickerLogo from './TickerLogo'
import TickerChip from './ui/TickerChip'
import Button from './ui/Button'

const INPUT = 'bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'

const SIGNAL_COLORS = {
  ETF_KAUFSIGNAL: 'text-etf-light',
  KAUFSIGNAL: 'text-success',
  WATCHLIST: 'text-warning',
  BEOBACHTEN: 'text-text-muted',
  'KEIN SETUP': 'text-danger',
}

// Neutrale, farbige Signal-Tags (keine Imperative).
const SIGNAL_BADGE = {
  ETF_KAUFSIGNAL: { label: 'ETF-Kriterien', cls: 'text-etf-light bg-etf/15' },
  KAUFSIGNAL: { label: 'Kaufkriterien', cls: 'text-success bg-success/15' },
  WATCHLIST: { label: 'Watchlist', cls: 'text-warning bg-warning/15' },
  BEOBACHTEN: { label: 'Beobachten', cls: 'text-text-secondary bg-hover' },
  'KEIN SETUP': { label: 'Kein Setup', cls: 'text-danger bg-danger/15' },
}

// Reale Kriterien-Gruppen aus dem Scoring-Service (vgl. StockScoreCard).
const GROUP_ORDER = ['Moving Averages', 'Trendbestätigung', 'Modifier', 'Breakout', 'Relative Stärke', 'Industry-Stärke', 'Volumen & Liquidität', 'Trendwende', 'Risiken']
const GROUP_GLOSSAR = {
  'Moving Averages': 'Moving Averages',
  Breakout: 'Breakout',
  'Relative Stärke': 'Mansfield RS',
  'Volumen & Liquidität': 'Volumen',
  Trendwende: '3-Punkt-Umkehr',
  Trendbestätigung: 'Trendbestätigung',
  Risiken: 'Risiken',
  Modifier: 'Modifier',
  'Industry-Stärke': 'Industry-MRS',
}

function scoreBadgeCls(passed, total) {
  if (passed == null || !total) return 'text-text-muted bg-hover'
  const ratio = passed / total
  if (ratio >= 12 / 18) return 'text-success bg-success/15'
  if (ratio >= 8 / 18) return 'text-warning bg-warning/15'
  return 'text-danger bg-danger/15'
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
    <span role="img" aria-label={`Signal: ${score.signal_label || score.signal}`} className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${color}`} style={{ backgroundColor: 'currentColor' }} />
  )
}

// Eine Kategorie der Kauf-Checkliste (reale Scoring-Gruppe).
function CategoryCard({ group, criteria }) {
  const isRiskGroup = group === 'Risiken'
  const isModifierGroup = group === 'Modifier'

  const passedItems = criteria.filter((c) => c.passed !== null && c.passed !== undefined)
  const passed = passedItems.filter((c) => c.passed === true).length
  const modifierItems = criteria.filter((c) => c.score_modifier !== null && c.score_modifier !== undefined)
  const modifierSum = modifierItems.reduce((s, c) => s + c.score_modifier, 0)

  let counterText, counterCls
  if (isModifierGroup) {
    counterText = modifierItems.length === 0 ? '0' : `${modifierSum >= 0 ? '+' : ''}${modifierSum}`
    counterCls = modifierSum > 0 ? 'text-success bg-success/15'
      : modifierSum < 0 ? 'text-danger bg-danger/15'
        : 'text-text-muted bg-hover'
  } else {
    const total = passedItems.length
    counterText = `${passed}/${total}`
    counterCls = total === 0 ? 'text-text-muted bg-hover'
      : passed === total ? 'text-success bg-success/15'
        : passed > 0 ? 'text-warning bg-warning/15'
          : 'text-danger bg-danger/15'
  }

  return (
    <div className="rounded-[10px] border border-border-2 bg-card-2 p-3">
      <div className="flex items-center justify-between mb-2.5">
        <h4 className="text-[12.5px] font-semibold text-text-primary">
          <G term={GROUP_GLOSSAR[group] || group}>{group}</G>
        </h4>
        <span className={`font-mono text-[10.5px] px-1.5 py-0.5 rounded ${counterCls}`}>{counterText}</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {criteria.map((c) => {
          const showWarning = isRiskGroup && c.passed === false
          const isPending = c.pending === true
          const isModifier = c.score_modifier !== null && c.score_modifier !== undefined
          let Icon, boxCls, labelCls
          if (isPending) {
            Icon = Hourglass; boxCls = 'bg-warning/15 text-warning'; labelCls = 'text-warning font-medium'
          } else if (isModifier && c.score_modifier > 0) {
            Icon = Plus; boxCls = 'bg-success/15 text-success'; labelCls = 'text-text-primary'
          } else if (isModifier && c.score_modifier < 0) {
            Icon = Minus; boxCls = 'bg-danger/15 text-danger'; labelCls = 'text-danger font-medium'
          } else if (isModifier) {
            Icon = Minus; boxCls = 'bg-hover text-text-muted'; labelCls = 'text-text-muted'
          } else if (c.passed === true) {
            Icon = Check; boxCls = 'bg-success/15 text-success'; labelCls = 'text-text-primary'
          } else if (showWarning) {
            Icon = AlertTriangle; boxCls = 'bg-danger/15 text-danger'; labelCls = 'text-danger font-medium'
          } else if (c.passed === false) {
            Icon = X; boxCls = 'bg-hover text-text-muted'; labelCls = 'text-text-secondary'
          } else {
            Icon = Minus; boxCls = 'bg-hover text-text-muted'; labelCls = 'text-text-muted'
          }
          return (
            <div key={c.id} className="flex items-start gap-2">
              <span className={`mt-px w-[18px] h-[18px] rounded-[5px] flex items-center justify-center flex-shrink-0 ${boxCls}`}>
                <Icon size={11} />
              </span>
              <div className="flex-1 min-w-0">
                <p className={`text-[12px] leading-snug ${labelCls}`}>{c.name}</p>
                {c.detail && <p className="text-[10px] text-text-muted truncate mt-0.5" title={c.detail}>{c.detail}</p>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const WatchlistTable = forwardRef(function WatchlistTable({ onSelectTicker, selectedTicker }, ref) {
  const { data: rawData, loading, error, refetch } = useApi('/analysis/watchlist')
  // Memoized: a fresh [] per render would re-trigger every effect with [data] dep
  // (endless /api/analysis/tags polling while rawData is null).
  const data = useMemo(() => rawData?.items || rawData || [], [rawData])
  const activeAlertsCount = rawData?.active_alerts_count || 0

  const [adding, setAdding] = useState(false)
  useImperativeHandle(ref, () => ({ refetch, openAdd: () => setAdding(true) }))
  const [newTicker, setNewTicker] = useState('')
  const [newName, setNewName] = useState('')
  const [newSector, setNewSector] = useState('')
  const [scores, setScores] = useState({})
  const [loadingScores, setLoadingScores] = useState({})
  const [deleting, setDeleting] = useState(null)
  const [sortKey, setSortKey] = useState('signal')
  const [sortAsc, setSortAsc] = useState(false)
  const [expanded, setExpanded] = useState(() => new Set())
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

  const toggleExpand = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(key === 'ticker' || key === 'name' || key === 'sector')
    }
  }

  const caret = (key) => (sortKey === key ? (sortAsc ? <ChevronUp size={11} /> : <ChevronDown size={11} />) : null)

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
        va = a.tags?.[0]?.name || '￿'
        vb = b.tags?.[0]?.name || '￿'
      } else if (sortKey === 'overlap') {
        va = a.etf_overlap_max_weight_pct ?? -1
        vb = b.etf_overlap_max_weight_pct ?? -1
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
            setup_quality: json.setup_quality,
            distance: json.breakout?.distance_to_resistance_pct ?? null,
            volume_ratio: json.breakout?.volume_ratio ?? null,
            mansfield_rs: json.mansfield_rs ?? null,
            criteria: json.criteria || [],
            earnings_date: json.earnings_date ?? null,
            days_until_earnings: json.days_until_earnings ?? null,
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

  // ---- Add-Form (per "+ Ticker" im PageHeader getriggert) ----
  const addForm = adding && (
    <form onSubmit={handleAdd} className="bg-card border border-border rounded-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-text-primary">Ticker zur Watchlist hinzufügen</h3>
        <button type="button" onClick={() => setAdding(false)} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Abbrechen">
          <X size={16} />
        </button>
      </div>
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
          className="w-44"
        />
        <input
          aria-label="Name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Name (auto-fill)"
          className={`${INPUT} flex-1 min-w-[160px]`}
        />
        <input
          aria-label="Sektor"
          value={newSector}
          onChange={(e) => setNewSector(e.target.value)}
          placeholder="Sektor (auto-fill)"
          className={`${INPUT} w-44`}
        />
        <Button variant="primary" type="submit">Hinzufügen</Button>
      </div>
    </form>
  )

  // ---- Loading / Error / Empty ----
  if (loading) {
    return (
      <div className="flex flex-col gap-[18px]">
        {addForm}
        <div className="bg-card border border-border rounded-card p-12">
          <LoadingSpinner text="Watchlist laden..." />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col gap-[18px]">
        {addForm}
        <div className="rounded-card border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
          <span className="text-danger text-sm">Fehler beim Laden{error ? `: ${error}` : ''}</span>
          <Button variant="primary" icon={RefreshCw} onClick={refetch}>Erneut laden</Button>
        </div>
      </div>
    )
  }

  if (!data?.length) {
    return (
      <div className="flex flex-col gap-[18px]">
        {addForm}
        <div className="bg-card border border-border rounded-card p-12 text-center">
          <p className="text-text-muted text-sm">Noch keine Aktien auf der Watchlist.</p>
          <button onClick={() => setAdding(true)} className="mt-3 text-link text-sm hover:underline">
            Erste Aktie hinzufügen
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-[18px]">
      {addForm}

      <div className="bg-card border border-border rounded-card overflow-hidden">
        {/* Karten-Header: Anzahl + aktive Alarme */}
        <div className="px-[18px] py-4 border-b border-border-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <h3 className="text-sm font-semibold text-text-primary">Titel</h3>
            <span className="font-mono text-[11px] text-text-faint">{data.length}</span>
            {activeAlertsCount > 0 && (
              <span className="font-mono text-[10.5px] px-1.5 py-0.5 rounded bg-warning/15 text-warning">
                {activeAlertsCount} Alarm{activeAlertsCount === 1 ? '' : 'e'}
              </span>
            )}
          </div>
        </div>

        {/* Tag-Filter */}
        {allTags.length > 0 && (
          <div className="px-[18px] py-2.5 border-b border-border-2 flex items-center gap-1.5 flex-wrap">
            <Tag size={12} className="text-text-muted" />
            {allTags.map((t) => {
              const on = filterTags.includes(t.id)
              return (
                <button
                  key={t.id}
                  onClick={() => toggleFilterTag(t.id)}
                  className={`text-[11px] px-2 py-0.5 rounded-md border transition-colors ${on ? 'border-transparent text-white' : 'border-border-2 text-text-muted hover:border-border-hover'}`}
                  style={on ? { backgroundColor: t.color } : {}}
                >
                  {t.name}
                </button>
              )
            })}
            {filterTags.length > 0 && (
              <button onClick={() => setFilterTags([])} className="text-text-muted hover:text-danger ml-1" aria-label="Filter zurücksetzen">
                <X size={12} />
              </button>
            )}
          </div>
        )}

        {/* Spalten-Mini-Header */}
        <div className="flex items-center gap-3 px-[18px] py-[9px] bg-table-head border-b border-border-2 font-mono text-[10px] uppercase tracking-[0.05em] text-text-faint select-none">
          <button type="button" onClick={() => handleSort('name')} className="flex-1 flex items-center gap-1 hover:text-text-secondary transition-colors text-left">
            Titel {caret('name')}
          </button>
          <button type="button" onClick={() => handleSort('price')} className="w-24 flex items-center justify-end gap-1 hover:text-text-secondary transition-colors">
            Kurs {caret('price')}
          </button>
          <button type="button" onClick={() => handleSort('signal')} className="w-[120px] flex items-center gap-1 hover:text-text-secondary transition-colors">
            Signal {caret('signal')}
          </button>
          <div className="w-16 text-right">RS</div>
          <button type="button" onClick={() => handleSort('setup')} className="w-14 flex items-center justify-center gap-1 hover:text-text-secondary transition-colors">
            Score {caret('setup')}
          </button>
          <button type="button" onClick={() => handleSort('tags')} className="w-[150px] flex items-center justify-end gap-1 hover:text-text-secondary transition-colors">
            Tags {caret('tags')}
          </button>
          <div className="w-5" />
        </div>

        {/* Liste */}
        {sortedData.length === 0 ? (
          <div className="p-10 text-center text-text-muted text-sm">Keine Treffer für die gewählten Tags.</div>
        ) : (
          sortedData.map((w) => {
            const s = scores[w.ticker]
            const isLoading = loadingScores[w.ticker]
            const isExp = expanded.has(w.id)
            const isSelected = selectedTicker === w.ticker

            const grouped = {}
            if (isExp && s?.criteria?.length) {
              for (const c of s.criteria) {
                const g = c.group || 'Sonstige'
                ;(grouped[g] = grouped[g] || []).push(c)
              }
            }

            return (
              <div key={w.id} className={`border-b border-border-row last:border-b-0 ${isExp || isSelected ? 'bg-card-2/40' : ''}`}>
                {/* Kollabierte Zeile */}
                <div
                  className="flex items-center gap-3 px-[18px] py-3 cursor-pointer hover:bg-hover transition-colors"
                  onClick={() => toggleExpand(w.id)}
                >
                  {/* Titel */}
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <SignalDot score={s} loading={isLoading} />
                    <TickerLogo ticker={w.ticker} size={22} />
                    <MiniChartTooltip ticker={w.ticker}>
                      <Link to={`/stock/${encodeURIComponent(w.ticker)}`} onClick={(e) => e.stopPropagation()} className="inline-flex">
                        <TickerChip>{w.ticker}</TickerChip>
                      </Link>
                    </MiniChartTooltip>
                    <span className="text-[12.5px] text-text-primary truncate">{w.name}</span>
                  </div>

                  {/* Kurs */}
                  <div className="w-24 text-right">
                    {w.price != null ? (
                      <>
                        <div className="font-mono text-[12px] text-text-primary tabular-nums">
                          {formatNumber(w.price, 2)} <span className="text-text-faint text-[9px]">{w.currency}</span>
                        </div>
                        {w.change_pct != null && (
                          <div className={`font-mono text-[10.5px] tabular-nums ${w.change_pct >= 0 ? 'text-success' : 'text-danger'}`}>
                            {w.change_pct > 0 ? '+' : ''}{w.change_pct.toFixed(2)}%
                          </div>
                        )}
                      </>
                    ) : (
                      <span className="text-text-muted text-xs">–</span>
                    )}
                  </div>

                  {/* Signal */}
                  <div className="w-[120px]">
                    {s ? (
                      <span className={`inline-flex items-center px-2 py-1 rounded-md text-[10.5px] font-medium ${(SIGNAL_BADGE[s.signal] || SIGNAL_BADGE['KEIN SETUP']).cls}`}>
                        {(SIGNAL_BADGE[s.signal] || SIGNAL_BADGE['KEIN SETUP']).label}
                      </span>
                    ) : isLoading ? (
                      <Loader2 size={12} className="animate-spin text-text-muted" />
                    ) : (
                      <span className="text-text-muted text-xs">–</span>
                    )}
                  </div>

                  {/* RS (Mansfield) */}
                  <div className="w-16 text-right">
                    {s?.mansfield_rs != null ? (
                      <span className={`font-mono text-[11.5px] tabular-nums ${s.mansfield_rs >= 0 ? 'text-success' : 'text-danger'}`}>
                        {s.mansfield_rs > 0 ? '+' : ''}{s.mansfield_rs.toFixed(1)}
                      </span>
                    ) : (
                      <span className="text-text-muted text-xs">–</span>
                    )}
                  </div>

                  {/* Score */}
                  <div className="w-14 flex justify-center">
                    {s ? (
                      <span className={`font-mono text-[11px] font-semibold px-2 py-1 rounded-md ${scoreBadgeCls(s.passed, s.total)}`}>
                        {s.passed}/{s.total}
                      </span>
                    ) : isLoading ? (
                      <Loader2 size={12} className="animate-spin text-text-muted" />
                    ) : (
                      <span className="text-text-muted text-xs">–</span>
                    )}
                  </div>

                  {/* Tags (Anzeige + Filter) */}
                  <div className="w-[150px] flex flex-wrap gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
                    {(w.tags || []).slice(0, 3).map((t) => (
                      <button
                        key={t.id}
                        onClick={() => toggleFilterTag(t.id)}
                        className="text-[10px] px-1.5 py-0.5 rounded-md text-white font-medium"
                        style={{ backgroundColor: t.color }}
                      >
                        {t.name}
                      </button>
                    ))}
                    {(w.tags || []).length > 3 && (
                      <span className="text-[10px] text-text-muted self-center">+{w.tags.length - 3}</span>
                    )}
                  </div>

                  {/* Caret */}
                  <div className="w-5 flex justify-center text-text-muted">
                    <ChevronDown size={16} className={`transition-transform ${isExp ? 'rotate-180' : ''}`} />
                  </div>
                </div>

                {/* Aufgeklappte Detail-Ansicht */}
                {isExp && (
                  <div className="px-[18px] py-4 border-t border-border-2 bg-card-2/30">
                    {/* Kopf der Checkliste + Aktionen */}
                    <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <h4 className="text-sm font-semibold text-text-primary"><G term="Setup-Score">Kauf-Checkliste</G></h4>
                        {s && (
                          <span className="font-mono text-[11px] text-text-muted">
                            · {s.passed} von {s.total} Kriterien erfüllt
                          </span>
                        )}
                        {w.etf_overlap_max_weight_pct != null && (
                          <span className="font-mono text-[10px] text-warning bg-warning/10 px-1.5 py-0.5 rounded" title={`Höchstes ETF-Gewicht für ${w.ticker} in deinen US-Portfolio-ETFs (≥2%).`}>
                            <G term="Core-Overlap">Overlap</G> {w.etf_overlap_max_weight_pct.toFixed(1)}%
                          </span>
                        )}
                        {s?.earnings_date && (
                          <span className="font-mono text-[10px] text-text-muted bg-hover px-1.5 py-0.5 rounded">
                            Earnings {formatDate(s.earnings_date)}{s.days_until_earnings != null ? ` · ${s.days_until_earnings}T` : ''}
                          </span>
                        )}
                      </div>

                      {/* Aktionen */}
                      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                        <div className="relative">
                          <button
                            onClick={() => setAlertTicker(alertTicker === w.ticker ? null : w.ticker)}
                            className={`p-1.5 rounded transition-colors ${w.active_alerts > 0 ? 'text-warning hover:bg-warning/10' : 'text-text-muted hover:text-primary hover:bg-primary/10'}`}
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
                        </div>
                        <div className="relative">
                          <button
                            onClick={() => { setResistanceTicker(resistanceTicker === w.ticker ? null : w.ticker); setResistanceValue(w.manual_resistance != null ? String(w.manual_resistance) : '') }}
                            className={`p-1.5 rounded transition-colors ${w.manual_resistance != null ? 'text-primary hover:bg-primary/10' : 'text-text-muted hover:text-primary hover:bg-primary/10'}`}
                            title="Resistance-Level (Breakout) anpassen"
                            aria-label="Resistance-Level anpassen"
                          >
                            <Crosshair size={14} />
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
                                  className={`${INPUT} w-full`}
                                  autoFocus
                                />
                                <div className="flex justify-end gap-2 mt-2">
                                  <button onClick={() => setResistanceTicker(null)} className="text-xs text-text-secondary hover:text-text-primary">
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
                          <RefreshCw size={14} />
                        </button>
                        <button
                          onClick={() => handleDelete(w.id)}
                          disabled={deleting === w.id}
                          className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors disabled:opacity-40"
                          title="Entfernen"
                          aria-label="Entfernen"
                        >
                          {deleting === w.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                      </div>
                    </div>

                    {/* Kategorien (reale Scoring-Gruppen) */}
                    {s?.criteria?.length ? (
                      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                        {GROUP_ORDER.map((g) => (grouped[g] ? <CategoryCard key={g} group={g} criteria={grouped[g]} /> : null))}
                      </div>
                    ) : isLoading ? (
                      <div className="py-6 flex justify-center"><Loader2 size={18} className="animate-spin text-text-muted" /></div>
                    ) : (
                      <p className="text-xs text-text-muted py-3">Keine Detail-Kriterien verfügbar.</p>
                    )}

                    {/* Tags verwalten */}
                    <div className="mt-3 flex items-center gap-2 flex-wrap" onClick={(e) => e.stopPropagation()}>
                      <span className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-text-label flex items-center gap-1">
                        <Tag size={11} /> Tags
                      </span>
                      {(w.tags || []).map((t) => (
                        <span
                          key={t.id}
                          className="text-[11px] px-1.5 py-0.5 rounded-md text-white flex items-center gap-1"
                          style={{ backgroundColor: t.color }}
                        >
                          {t.name}
                          <button onClick={() => removeTag(w.id, t.id)} className="hover:text-white/60" aria-label="Tag entfernen">
                            <X size={10} />
                          </button>
                        </span>
                      ))}
                      {(w.tags || []).length < 5 && (
                        tagInput === w.id ? (
                          <div className="relative">
                            <input
                              aria-label="Tag hinzufügen"
                              value={tagValue}
                              onChange={(e) => handleTagInputChange(e.target.value, w.id)}
                              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag(w.id) } if (e.key === 'Escape') { setTagInput(null); setTagValue(''); setTagSuggestions([]) } }}
                              onBlur={(e) => { if (e.relatedTarget?.dataset?.tagSuggestion) return; setTimeout(() => { if (tagValue.trim()) addTag(w.id); else { setTagInput(null); setTagValue(''); setTagSuggestions([]) } }, 150) }}
                              placeholder="Tag..."
                              className="w-24 text-xs bg-transparent border-b border-text-muted text-text-primary focus:outline-none focus:border-primary"
                              autoFocus
                            />
                            {tagSuggestions.length > 0 && tagInput === w.id && (
                              <div className="absolute top-full left-0 mt-1 bg-card border border-border rounded-lg shadow-lg z-10 min-w-[150px]">
                                {tagSuggestions.map(tag => (
                                  <button
                                    key={tag.id}
                                    data-tag-suggestion="true"
                                    onMouseDown={(e) => { e.preventDefault(); addTag(w.id, tag.name); setTagSuggestions([]) }}
                                    className="w-full text-left px-3 py-1.5 text-xs text-text-primary hover:bg-hover transition-colors"
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

                    {/* Notiz */}
                    <div className="mt-3 rounded-[10px] border border-border-2 bg-card-2 p-3" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1.5 mb-2 font-mono text-[10.5px] uppercase tracking-[0.06em] text-text-label">
                        <MessageSquare size={12} /> Notiz
                      </div>
                      {editingNotes === w.id ? (
                        <textarea
                          aria-label="Notiz bearbeiten"
                          value={notesValue}
                          onChange={(e) => { setNotesValue(e.target.value); e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px' }}
                          onBlur={() => saveNotes(w.id)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveNotes(w.id) } if (e.key === 'Escape') setEditingNotes(null) }}
                          className="w-full text-xs bg-surface border border-border rounded px-2 py-1.5 text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 resize-none"
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
                            <span className="text-xs text-text-secondary whitespace-pre-wrap block">{w.notes}</span>
                          ) : (
                            <span className="text-xs text-text-muted group-hover:text-primary">Notiz hinzufügen…</span>
                          )}
                          {w.notes && w.notes_last_api_write_at && (
                            <span className="flex items-center gap-1 mt-1 text-[10px] text-text-muted" title={`Zuletzt via API aktualisiert${w.notes_last_api_token_name ? ` durch ${w.notes_last_api_token_name}` : ''}`}>
                              <Bot size={10} />
                              <span className="truncate">
                                API: {formatDate(w.notes_last_api_write_at)}
                                {w.notes_last_api_token_name ? ` · ${w.notes_last_api_token_name}` : ''}
                              </span>
                            </span>
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
})

export default WatchlistTable
