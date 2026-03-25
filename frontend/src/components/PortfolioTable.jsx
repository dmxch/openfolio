import { useState, useMemo, useCallback, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { formatCHF, formatPct, formatNumber, pnlColor, formatDate } from '../lib/format'
import { ArrowUpDown, TrendingUp, ChevronUp, ChevronDown, MoreVertical, Search, AlertTriangle, Loader2, Calendar, Eye, EyeOff, Upload, Plus } from 'lucide-react'
import ContextMenu from './ContextMenu'
import EditPositionModal from './EditPositionModal'
import TransactionModal from './TransactionModal'
import StopLossModal from './StopLossModal'
import DeleteConfirm from './DeleteConfirm'
import MiniChartTooltip from './MiniChartTooltip'
import G from './GlossarTooltip'
import { apiDelete, apiPut, authFetch } from '../hooks/useApi'
import { useToast } from './Toast'

function MrsCell({ value }) {
  if (value == null) return <span className="text-text-muted">–</span>
  const color = value > 1 ? 'text-success' : value > 0 ? 'text-success/70' : value > -1 ? 'text-warning' : 'text-danger'
  return <span className={`font-mono text-xs ${color}`}>{value > 0 ? '+' : ''}{value.toFixed(2)}</span>
}

function StopCell({ position: p, onClick }) {
  const sl = p.stop_loss_price
  const confirmed = p.stop_loss_confirmed_at_broker
  const method = p.stop_loss_method
  const currency = p.price_currency || p.currency
  const currentPrice = p.current_price
  const isCore = p.position_type === 'core'

  if (sl == null) {
    if (isCore) {
      // Core without stop-loss: neutral display, no warning
      return (
        <button onClick={(e) => { e.stopPropagation(); onClick() }} className="text-text-muted text-xs font-mono cursor-pointer hover:underline" title="Optional für Core — klicken zum Setzen">
          —
        </button>
      )
    }
    return (
      <button onClick={(e) => { e.stopPropagation(); onClick() }} className="text-danger text-xs font-mono cursor-pointer hover:underline" title="Kein Stop-Loss gesetzt — klicken zum Setzen">
        –
      </button>
    )
  }

  const color = confirmed ? 'text-success' : 'text-warning'
  const distPct = currentPrice && sl > 0 ? ((currentPrice - sl) / currentPrice * 100).toFixed(1) : null
  const methodLabel = method === 'structural' ? 'Strukturell' : method === 'trailing_pct' ? 'Trailing %' : method === 'higher_low' ? 'Higher Low' : method === 'ma_based' ? 'MA-basiert' : ''
  const updatedAt = formatDate(p.stop_loss_updated_at)
  const tooltip = [
    p.position_type ? `Typ: ${p.position_type === 'core' ? 'Core' : 'Satellite'}` : null,
    distPct ? `Abstand: -${distPct}%` : null,
    `Letzte Aktualisierung: ${updatedAt}`,
    methodLabel ? `Methode: ${methodLabel}` : null,
    `Status: ${confirmed ? 'Bestätigt' : 'Nicht bestätigt'}`,
  ].filter(Boolean).join('\n')

  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick() }}
      className={`font-mono text-xs ${color} cursor-pointer hover:underline whitespace-nowrap`}
      title={tooltip}
    >
      {formatNumber(sl, 2)}
    </button>
  )
}

function daysSince(dateStr) {
  if (!dateStr) return null
  const d = new Date(dateStr)
  const now = new Date()
  return Math.floor((now - d) / (1000 * 60 * 60 * 24))
}

function daysUntilEarnings(dateStr) {
  if (!dateStr) return null
  const ed = new Date(dateStr)
  const now = new Date()
  return Math.ceil((ed - now) / (1000 * 60 * 60 * 24))
}

function EarningsBadge({ date, positionType }) {
  const days = daysUntilEarnings(date)
  if (days == null || days < 0) return null
  const isSatellite = positionType === 'satellite'
  const isUrgent = isSatellite ? days <= 14 : days <= 7
  if (!isUrgent) return null
  const color = days <= 3 ? 'text-danger' : 'text-warning'
  const ed = new Date(date)
  return (
    <span className={`inline-flex items-center gap-0.5 ${color}`} title={`Earnings am ${formatDate(date)} (in ${days} Tagen)`}>
      <Calendar size={11} />
      <span className="text-[10px] font-medium">{days}T</span>
    </span>
  )
}

function formatHoldingPeriod(dateStr) {
  const days = daysSince(dateStr)
  if (days == null) return '–'
  if (days < 30) return `${days}T`
  if (days < 365) return `${Math.floor(days / 30)}M`
  const years = Math.floor(days / 365)
  const months = Math.floor((days % 365) / 30)
  return months > 0 ? `${years}J ${months}M` : `${years}J`
}

export default function PortfolioTable({ positions, onRefresh, totalFees = 0 }) {
  const toast = useToast()
  const navigate = useNavigate()
  const [sortKey, setSortKey] = useState('market_value_chf')
  const [sortAsc, setSortAsc] = useState(false)
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editPosition, setEditPosition] = useState(null)
  const [txnModal, setTxnModal] = useState(null)
  const [stopLossTarget, setStopLossTarget] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [typeTarget, setTypeTarget] = useState(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [showClosed, setShowClosed] = useState(false)
  const [scores, setScores] = useState({})
  const [loadingScores, setLoadingScores] = useState({})

  const allTradable = useMemo(
    () => positions?.filter((p) => p.type !== 'cash' && p.type !== 'pension') || [],
    [positions]
  )

  const tradablePositions = useMemo(
    () => allTradable.filter((p) => p.shares > 0),
    [allTradable]
  )

  const closedPositions = useMemo(
    () => allTradable.filter((p) => p.shares <= 0),
    [allTradable]
  )

  const filteredPositions = useMemo(() => {
    if (!searchTerm.trim()) return tradablePositions
    const q = searchTerm.toLowerCase()
    return tradablePositions.filter((p) =>
      p.ticker?.toLowerCase().includes(q) ||
      p.name?.toLowerCase().includes(q) ||
      p.sector?.toLowerCase().includes(q) ||
      p.industry?.toLowerCase().includes(q)
    )
  }, [tradablePositions, searchTerm])

  // Listen for external edit requests (e.g. from AlertsBanner)
  useEffect(() => {
    const handler = (e) => setEditPosition(e.detail)
    window.addEventListener('openEditPosition', handler)
    return () => window.removeEventListener('openEditPosition', handler)
  }, [])

  // Auto-load setup scores for all tradable positions (parallel, no delay)
  useEffect(() => {
    if (!tradablePositions.length) return
    let cancelled = false
    const tickers = tradablePositions.map(p => p.ticker).filter(t => !scores[t])
    if (!tickers.length) return
    setLoadingScores((prev) => {
      const next = { ...prev }
      tickers.forEach(t => { next[t] = true })
      return next
    })
    Promise.all(tickers.map(async (ticker) => {
      if (cancelled) return
      try {
        const res = await authFetch(`/api/analysis/score/${ticker}`)
        if (res.ok && !cancelled) {
          const json = await res.json()
          setScores((prev) => ({ ...prev, [ticker]: { passed: json.score, total: json.max_score } }))
        }
      } catch { /* ignore */ }
      if (!cancelled) setLoadingScores((prev) => ({ ...prev, [ticker]: false }))
    }))
    return () => { cancelled = true }
  }, [tradablePositions]) // eslint-disable-line react-hooks/exhaustive-deps

  const openCtxFor = useCallback((e, position) => {
    const rect = e.currentTarget.getBoundingClientRect()
    setCtxMenu({ x: rect.left, y: rect.bottom + 4, position })
  }, [])

  const handleContextMenu = useCallback((e, position) => {
    e.preventDefault()
    setCtxMenu({ x: e.clientX, y: e.clientY, position })
  }, [])

  const handleAction = useCallback(async (action) => {
    const pos = ctxMenu?.position
    if (!pos) return

    if (action === 'edit') {
      try {
        const res = await authFetch(`/api/portfolio/positions/${pos.id}`)
        const full = await res.json()
        setEditPosition(full)
      } catch {
        setEditPosition(pos)
      }
    } else if (action === 'buy') {
      setTxnModal({ position: pos, type: 'buy' })
    } else if (action === 'sell') {
      setTxnModal({ position: pos, type: 'sell' })
    } else if (action === 'stop_loss') {
      setStopLossTarget(pos)
    } else if (action === 'change_type') {
      setTypeTarget(pos)
    } else if (action === 'delete') {
      setDeleteTarget(pos)
    }
  }, [ctxMenu])

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return
    try {
      await apiDelete(`/portfolio/positions/${deleteTarget.id}`)
      onRefresh?.()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
    setDeleteTarget(null)
  }, [deleteTarget, onRefresh, toast])

  if (!tradablePositions.length) return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-emerald-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08] flex items-center gap-2">
        <TrendingUp size={16} className="text-primary" />
        <h3 className="text-sm font-medium text-text-secondary">Aktien & ETFs</h3>
      </div>
      <div className="p-8 text-center">
        <p className="text-text-muted text-sm mb-1">Noch keine Aktien oder ETFs.</p>
        <p className="text-text-muted text-xs mb-4">Positionen werden automatisch aus Transaktionen erstellt.</p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => navigate('/transactions?action=add')}
            className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary transition-colors"
          >
            <Plus size={14} />
            Transaktion erfassen
          </button>
          <button
            onClick={() => navigate('/transactions?action=import')}
            className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors"
          >
            <Upload size={14} />
            CSV importieren
          </button>
        </div>
      </div>
    </div>
  )

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(false)
    }
  }

  const sorted = [...filteredPositions].sort((a, b) => {
    let va, vb
    if (sortKey === 'stop_distance') {
      va = a.stop_loss_price && a.current_price ? ((a.current_price - a.stop_loss_price) / a.current_price) * 100 : -Infinity
      vb = b.stop_loss_price && b.current_price ? ((b.current_price - b.stop_loss_price) / b.current_price) * 100 : -Infinity
    } else if (sortKey === 'setup') {
      va = scores[a.ticker]?.passed ?? -1
      vb = scores[b.ticker]?.passed ?? -1
    } else {
      va = a[sortKey]
      vb = b[sortKey]
    }
    // string sort for ticker, name
    if (typeof va === 'string' && typeof vb === 'string') {
      return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va)
    }
    va = va ?? -Infinity
    vb = vb ?? -Infinity
    return sortAsc ? va - vb : vb - va
  })

  const headers = [
    { key: 'ticker', label: 'Ticker', align: 'left' },
    { key: 'name', label: 'Name', align: 'left' },
    { key: 'position_type', label: 'Typ', align: 'center', hideMobile: true },
    { key: 'shares', label: 'Anzahl', align: 'right', hideMobile: true },
    { key: 'current_price', label: 'Kurs', align: 'right' },
    { key: 'stop_loss_price', label: <G term="Stop-Loss">Stop</G>, align: 'right', title: 'Stop-Loss Kurs', hideMobile: true },
    { key: 'stop_distance', label: '\u0394 Stop', align: 'right', title: 'Abstand zum Stop-Loss in %', hideMobile: true },
    { key: 'market_value_chf', label: 'Wert CHF', align: 'right' },
    { key: 'weight_pct', label: 'Anteil %', align: 'right', hideMobile: true },
    { key: 'pnl_pct', label: 'Perf %', align: 'right', title: 'Performance inkl. Transaktionsgebühren' },
    { key: 'pnl_chf', label: 'Perf CHF', align: 'right', title: 'Performance inkl. Transaktionsgebühren', hideMobile: true },
    { key: 'mansfield_rs', label: <G term="MRS">MRS</G>, align: 'right', title: 'Mansfield Relative Stärke', hideMobile: true },
    { key: 'setup', label: 'Score', align: 'center', title: '18-Punkte Kauf-Checkliste', hideMobile: true },
    { key: 'buy_date', label: 'Seit', align: 'right', hideMobile: true },
  ]

  return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-emerald-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08] flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">
            Aktien & ETFs
            <span className="text-text-muted ml-2">({filteredPositions.length}{searchTerm ? `/${tradablePositions.length}` : ''} Titel)</span>
          </h3>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/transactions?action=add')}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
          >
            <Plus size={13} />
            <span className="hidden sm:inline">Position hinzufügen</span>
          </button>
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Suchen..."
              aria-label="Positionen durchsuchen"
              className="bg-card border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs text-text-primary w-44 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
            />
          </div>
          {closedPositions.length > 0 && (
            <button
              onClick={() => setShowClosed(!showClosed)}
              className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
                showClosed ? 'text-primary border-primary/30 bg-primary/5' : 'text-text-muted border-border hover:text-text-primary'
              }`}
              title={showClosed ? 'Geschlossene ausblenden' : 'Geschlossene anzeigen'}
            >
              {showClosed ? <EyeOff size={12} /> : <Eye size={12} />}
              {closedPositions.length} geschlossen
            </button>
          )}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
              {headers.map((h) => (
                <th
                  key={h.key}
                  className={`p-3 font-medium cursor-pointer hover:text-text-primary transition-colors whitespace-nowrap select-none ${
                    h.align === 'right' ? 'text-right' : h.align === 'center' ? 'text-center' : 'text-left'
                  } ${sortKey === h.key ? 'text-primary' : ''} ${h.key === 'ticker' ? 'sticky left-0 z-10 bg-card' : ''} ${h.hideMobile ? 'hidden md:table-cell' : ''}`}
                  onClick={() => handleSort(h.key)}
                >
                  <span title={h.title}>{h.label}</span>
                  {sortKey === h.key ? (
                    sortAsc ? <ChevronUp size={14} className="inline ml-0.5 text-primary" /> : <ChevronDown size={14} className="inline ml-0.5 text-primary" />
                  ) : null}
                </th>
              ))}
              <th className="p-3 w-10" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr key={p.id} data-ticker={p.ticker} tabIndex={0} className="border-b border-border/50 hover:bg-card-alt/50 transition-colors cursor-context-menu focus:outline-none focus:bg-card-alt/50" onContextMenu={(e) => handleContextMenu(e, p)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCtxFor(e, p) } }}>
                <td className="p-3 font-mono text-primary font-medium sticky left-0 z-10 bg-card"><MiniChartTooltip ticker={p.ticker}><Link to={`/stock/${encodeURIComponent(p.ticker)}`} className="hover:underline">{p.ticker}</Link></MiniChartTooltip></td>
                <td className="p-3 text-text-primary whitespace-nowrap">
                  <span className="inline-flex items-center gap-1.5">
                    {p.name}
                    <EarningsBadge date={p.next_earnings_date} positionType={p.position_type} />
                  </span>
                </td>
                <td className="p-3 text-center hidden md:table-cell">
                  {['stock', 'etf'].includes(p.type) ? (
                    p.position_type === 'core' ? (
                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-primary/15 text-primary"><G term="Core">Core</G></span>
                    ) : p.position_type === 'satellite' ? (
                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-warning/15 text-warning"><G term="Satellite">Satellite</G></span>
                    ) : (
                      <span className="text-text-muted text-xs">—</span>
                    )
                  ) : null}
                </td>
                <td className="p-3 text-right text-text-secondary tabular-nums text-xs hidden md:table-cell">{formatNumber(p.shares, p.shares % 1 !== 0 ? 2 : 0)}</td>
                <td className="p-3 text-right text-text-secondary tabular-nums text-xs whitespace-nowrap">
                  {p.current_price != null ? `${p.price_currency || p.currency} ${formatNumber(p.current_price, 2)}` : '–'}
                </td>
                <td className="p-3 text-right hidden md:table-cell">
                  <StopCell position={p} onClick={() => setStopLossTarget(p)} />
                </td>
                <td className="p-3 text-right text-xs tabular-nums whitespace-nowrap hidden md:table-cell">
                  {(() => {
                    if (p.stop_loss_price == null || p.current_price == null) return <span className="text-text-muted">—</span>
                    const distance = ((p.current_price - p.stop_loss_price) / p.current_price) * 100
                    if (distance < 0) {
                      return <span className="text-danger font-bold">Stop!</span>
                    }
                    const color = distance > 20 ? 'text-success' : distance > 10 ? 'text-warning' : 'text-danger'
                    return <span className={color}>{distance.toFixed(1)}%</span>
                  })()}
                </td>
                <td className="p-3 text-right font-medium tabular-nums">
                  {p.is_stale ? (
                    <span className="inline-flex items-center gap-1 text-warning" title={p.stale_reason || 'Kein aktueller Kurs. Angezeigter Wert basiert auf dem Einstandswert.'}>
                      <AlertTriangle size={13} className="shrink-0" />
                      {formatCHF(p.market_value_chf)}
                    </span>
                  ) : (
                    <span className="text-text-primary">{formatCHF(p.market_value_chf)}</span>
                  )}
                </td>
                <td className="p-3 text-right text-text-secondary tabular-nums hidden md:table-cell">{p.weight_pct.toFixed(1)}%</td>
                <td className={`p-3 text-right font-medium tabular-nums ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</td>
                <td className={`p-3 text-right tabular-nums hidden md:table-cell ${pnlColor(p.pnl_chf)}`}>{formatCHF(p.pnl_chf)}</td>
                <td className="p-3 text-right hidden md:table-cell" title={p.mansfield_rs != null ? `MRS ${p.mansfield_rs > 0 ? 'positiv: stärker als Markt' : 'negativ: schwächer als Markt'}` : ''}><MrsCell value={p.mansfield_rs} /></td>
                <td className="p-3 text-center hidden md:table-cell">
                  {loadingScores[p.ticker] ? (
                    <Loader2 size={14} className="animate-spin text-text-muted mx-auto" />
                  ) : scores[p.ticker] ? (
                    <span className="font-mono text-xs text-text-secondary">{scores[p.ticker].passed}/{scores[p.ticker].total}</span>
                  ) : (
                    <span className="text-text-muted text-xs">–</span>
                  )}
                </td>
                <td className="p-3 text-right text-text-muted text-xs whitespace-nowrap hidden md:table-cell" title={p.buy_date || ''}>
                  {formatHoldingPeriod(p.buy_date)}
                </td>
                <td className="p-3 text-center">
                  <button
                    onClick={(e) => { e.stopPropagation(); openCtxFor(e, p) }}
                    className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
                    title="Aktionen"
                    aria-label="Aktionen öffnen"
                  >
                    <MoreVertical size={16} />
                  </button>
                </td>
              </tr>
            ))}
              {(() => {
                const totalValue = tradablePositions.reduce((s, p) => s + p.market_value_chf, 0)
                const totalPnl = tradablePositions.reduce((s, p) => s + p.pnl_chf, 0)
                const totalInvested = tradablePositions.reduce((s, p) => s + p.cost_basis_chf, 0)
                const totalPnlPct = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0
                const totalWeight = tradablePositions.reduce((s, p) => s + p.weight_pct, 0)
                const rows = [
                  <tr key="total" className="bg-card-alt/30 border-t border-border">
                    <td className="p-3 text-text-primary font-medium sticky left-0 z-10 bg-card" colSpan={7}>Total</td>
                    <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(totalValue)}</td>
                    <td className="p-3 text-right text-text-secondary font-medium tabular-nums">{totalWeight.toFixed(1)}%</td>
                    <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnlPct)}`}>{formatPct(totalPnlPct)}</td>
                    <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnl)}`}>{formatCHF(totalPnl)}</td>
                    <td className="p-3" colSpan={4}></td>
                  </tr>
                ]
                if (totalFees > 0) {
                  rows.push(
                    <tr key="fees-note">
                      <td colSpan={15} className="px-3 pb-2 pt-1">
                        <span className="text-xs text-text-muted">Inkl. Gebühren von {formatCHF(totalFees)}</span>
                      </td>
                    </tr>
                  )
                }
                return rows
              })()}
              {showClosed && closedPositions.length > 0 && (
                <>
                  <tr>
                    <td colSpan={15} className="px-3 pt-4 pb-2">
                      <span className="text-xs font-medium text-text-muted uppercase tracking-wide">Geschlossene Positionen</span>
                    </td>
                  </tr>
                  {closedPositions.map((p) => (
                    <tr key={p.id} className="border-b border-border/30 opacity-40">
                      <td className="p-3 font-mono text-text-muted font-medium">{p.ticker}</td>
                      <td className="p-3 text-text-muted whitespace-nowrap">{p.name}</td>
                      <td className="p-3 text-center"><span className="text-text-muted text-xs">—</span></td>
                      <td className="p-3 text-right text-text-muted tabular-nums text-xs">0</td>
                      <td className="p-3 text-right text-text-muted tabular-nums text-xs">–</td>
                      <td className="p-3 text-text-muted">–</td>
                      <td className="p-3 text-text-muted">–</td>
                      <td className="p-3 text-right text-text-muted tabular-nums">{formatCHF(0)}</td>
                      <td className="p-3 text-right text-text-muted tabular-nums">0.0%</td>
                      <td className={`p-3 text-right font-medium tabular-nums ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</td>
                      <td className={`p-3 text-right tabular-nums ${pnlColor(p.pnl_chf)}`}>{formatCHF(p.pnl_chf)}</td>
                      <td className="p-3" colSpan={4}></td>
                    </tr>
                  ))}
                </>
              )}
          </tbody>
        </table>
      </div>

      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          onAction={handleAction}
          onClose={() => setCtxMenu(null)}
          positionType={ctxMenu.position?.type}
        />
      )}

      {editPosition && (
        <EditPositionModal
          position={editPosition}
          onClose={() => setEditPosition(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {txnModal && (
        <TransactionModal
          position={txnModal.position}
          type={txnModal.type}
          onClose={() => setTxnModal(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {stopLossTarget && (
        <StopLossModal
          position={stopLossTarget}
          onClose={() => setStopLossTarget(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {deleteTarget && (
        <DeleteConfirm
          name={deleteTarget.name}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {typeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setTypeTarget(null)}>
          <div role="dialog" aria-modal="true" aria-label="Positions-Typ ändern" className="bg-card border border-border rounded-xl shadow-2xl p-6 max-w-xs" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-text-primary mb-1">Positions-Typ ändern</h3>
            <p className="text-xs text-text-muted mb-4">{typeTarget.name} ({typeTarget.ticker})</p>
            <div className="flex gap-3">
              <button
                onClick={async () => {
                  await apiPut(`/portfolio/positions/${typeTarget.id}`, { position_type: 'core' })
                  setTypeTarget(null)
                  onRefresh?.()
                }}
                className={`flex-1 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                  typeTarget.position_type === 'core'
                    ? 'bg-primary text-white border-primary'
                    : 'border-border text-text-secondary hover:border-primary hover:text-primary'
                }`}
              >
                Core
              </button>
              <button
                onClick={async () => {
                  await apiPut(`/portfolio/positions/${typeTarget.id}`, { position_type: 'satellite' })
                  setTypeTarget(null)
                  onRefresh?.()
                }}
                className={`flex-1 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                  typeTarget.position_type === 'satellite'
                    ? 'bg-warning text-white border-warning'
                    : 'border-border text-text-secondary hover:border-warning hover:text-warning'
                }`}
              >
                Satellite
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
