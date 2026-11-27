import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router'
import { formatCHF, formatPct, formatNumber, pnlColor, formatDate } from '../lib/format'
import { ArrowUpDown, TrendingUp, ChevronUp, ChevronDown, MoreVertical, Search, AlertTriangle, Loader2, Calendar, Eye, EyeOff, Upload, Plus, ChevronRight, Bell, BellRing, MessageSquare, Check, X } from 'lucide-react'
import ContextMenu from './ContextMenu'
import EditPositionModal from './EditPositionModal'
import TransactionModal from './TransactionModal'
import StopLossModal from './StopLossModal'
import DeleteConfirm from './DeleteConfirm'
import MiniChartTooltip from './MiniChartTooltip'
import TickerLogo from './TickerLogo'
import AlertPopover from './AlertPopover'
import G from './GlossarTooltip'
import { apiDelete, apiPut, authFetch, authFetchRetry } from '../hooks/useApi'
import { useToast } from './Toast'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import useIsMobile from '../hooks/useIsMobile'

// FX-vs-Lokal-Renditezerlegung: eigene "FX %"-Spalte neben "Perf %". Backend
// liefert local_return_pct/fx_return_pct bereits gerundet (null wo nicht
// zerlegbar); der Tooltip zeigt die additive Kurs-/Waehrungs-Aufteilung.
function fxBreakdownTitle(p) {
  if (p.local_return_pct == null || p.fx_return_pct == null) return undefined
  return `Kursanteil ${formatPct(p.local_return_pct)} · Währungsanteil ${formatPct(p.fx_return_pct)}`
}

// Drossel: max. `limit` gleichzeitige Worker, Rest rueckt nach. Score-Requests
// landen bei Cache-Miss serverseitig auf yfinance — unbegrenzte Bursts riskieren
// 429/IP-Ban (Backend-Konvention: Semaphore <= 3).
async function runLimited(items, limit, worker) {
  const queue = [...items]
  const runners = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift()
      try { await worker(item) } catch { /* worker faengt selbst; Sicherheitsnetz */ }
    }
  })
  await Promise.all(runners)
}

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

  if (sl == null) {
    // Phase 3: einheitliches neutrales Display — Pflicht-Logik kommt vom
    // Backend (alert_service via Bucket-Rules).
    return (
      <button onClick={(e) => { e.stopPropagation(); onClick() }} className="text-text-secondary text-xs font-mono cursor-pointer hover:underline" title="Kein Stop-Loss gesetzt — klicken zum Setzen">
        —
      </button>
    )
  }

  const color = confirmed ? 'text-success' : 'text-warning'
  const distPct = currentPrice && sl > 0 ? ((currentPrice - sl) / currentPrice * 100).toFixed(1) : null
  const methodLabel = method === 'structural' ? 'Strukturell' : method === 'trailing_pct' ? 'Trailing %' : method === 'higher_low' ? 'Higher Low' : method === 'ma_based' ? 'MA-basiert' : ''
  const updatedAt = formatDate(p.stop_loss_updated_at)
  const tooltip = [
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

function EarningsBadge({ date }) {
  const days = daysUntilEarnings(date)
  if (days == null || days < 0) return null
  // Phase 3: einheitliche 7-Tage-Schwelle (vorher satellite=14, core=7).
  // Bucket-spezifische Earnings-Logik kommt vom alert_service.
  if (days > 7) return null
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

function AddDropdown({ navigate }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-label="Position hinzufügen"
        aria-expanded={open}
        className="flex items-center justify-center gap-1.5 px-3 py-1.5 max-md:min-h-[36px] max-md:min-w-[36px] text-xs rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
      >
        <Plus size={13} />
        <span className="hidden sm:inline">Position hinzufügen</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 min-w-[180px] rounded-lg border border-border bg-card shadow-xl py-1 text-xs">
          <button
            onClick={() => { setOpen(false); navigate('/transactions?action=add') }}
            className="w-full text-left px-3 py-2 max-md:py-3 hover:bg-card-alt/50 text-text-secondary hover:text-text-primary flex items-center gap-2"
          >
            <Plus size={13} className="text-primary" /> Transaktion erfassen
          </button>
          <button
            onClick={() => { setOpen(false); navigate('/transactions?action=import') }}
            className="w-full text-left px-3 py-2 max-md:py-3 hover:bg-card-alt/50 text-text-secondary hover:text-text-primary flex items-center gap-2"
          >
            <Upload size={13} className="text-primary" /> CSV importieren
          </button>
        </div>
      )}
    </div>
  )
}

// Generische Positions-Tabelle. Die Klassen-Zugehörigkeit entscheidet die Seite
// (Portfolio.jsx) über `positions` — hier wird nur noch dargestellt.
// showScores=false für Klassen ohne Aktien-Scoring (Anleihen): unterdrückt die
// Score-Requests, die Zelle bleibt leer.
export default function PortfolioTable({
  positions,
  onRefresh,
  totalFees = 0,
  bucketMap = null,
  title = 'Aktien & ETFs',
  emptyText = 'Noch keine Aktien oder ETFs.',
  dotClass = 'bg-success',
  showScores = true,
  // Mobil haengt die Tabelle in einem Abschnitt; der Event-Empfang liegt dann
  // bei der Seite (sonst oeffneten zwei Listener zwei Edit-Dialoge).
  listenEditEvent = true,
}) {
  const toast = useToast()
  const navigate = useNavigate()
  const [sortKey, setSortKey] = useState('market_value_chf')
  const [sortAsc, setSortAsc] = useState(false)
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editPosition, setEditPosition] = useState(null)
  const [txnModal, setTxnModal] = useState(null)
  const [stopLossTarget, setStopLossTarget] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  // Phase 3 (v0.40): typeTarget-Dialog entfernt — Bucket-Zuordnung erfolgt
  // via Edit-Modal "Bucket"-Dropdown.
  const [searchTerm, setSearchTerm] = useState('')
  const [showClosed, setShowClosed] = useState(false)
  const [scores, setScores] = useState({})
  const [loadingScores, setLoadingScores] = useState({})
  const [alertTicker, setAlertTicker] = useState(null)
  const isMobile = useIsMobile()
  const [editingNotes, setEditingNotes] = useState(null)
  const [notesValue, setNotesValue] = useState('')
  const [savingNotes, setSavingNotes] = useState(false)

  // Nur noch der Schutz gegen Konten-Zeilen, die nie in eine Titel-Tabelle gehören.
  // count_as_cash muss mit, sonst zeigt die Tabelle einen Titel, den die Seite
  // bereits der Liquidität zugeordnet hat (zwei Tabellen, zwei Wahrheiten).
  const allTradable = useMemo(
    () => positions?.filter((p) => p.type !== 'cash' && p.type !== 'pension' && !p.count_as_cash) || [],
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

  // Memoized: sonst laeuft der Sort bei jedem Render (z.B. pro Tastendruck
  // im Inline-Notizen-Textarea) ueber die ganze Tabelle.
  const sorted = useMemo(() => {
    return [...filteredPositions].sort((a, b) => {
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
  }, [filteredPositions, sortKey, sortAsc, scores])

  // Listen for external edit requests (e.g. from AlertsBanner)
  useEffect(() => {
    if (!listenEditEvent) return undefined
    const handler = (e) => setEditPosition(e.detail)
    window.addEventListener('openEditPosition', handler)
    return () => window.removeEventListener('openEditPosition', handler)
  }, [listenEditEvent])

  // Nur auf Änderungen der Ticker-MENGE reagieren (K066). Die Seite reicht bei
  // jedem Render ein neues positions-Array herein (65s-Poll, Bucket-Liste);
  // hinge der Effekt an dessen Identität, bräche er jedes Mal den Lauf ab und
  // fragte dieselben Ticker erneut an.
  const tickerKey = useMemo(
    () => [...new Set(tradablePositions.map((p) => p.ticker))].join('\n'),
    [tradablePositions]
  )
  // Laufende Requests überleben einen Neustart des Laufs und werden nicht
  // doppelt gestartet. Endgültig abgelehnte Ticker (404, 400) werden nicht
  // automatisch wiederholt.
  const inFlightScores = useRef(new Set())
  const failedScores = useRef(new Set())

  // Auto-load setup scores for all tradable positions (gedrosselt, max. 3 parallel)
  useEffect(() => {
    if (!showScores || !tickerKey) return
    let cancelled = false
    const tickers = tickerKey.split('\n').filter(
      (t) => !scores[t] && !inFlightScores.current.has(t) && !failedScores.current.has(t)
    )
    if (!tickers.length) return
    setLoadingScores((prev) => {
      const next = { ...prev }
      tickers.forEach(t => { next[t] = true })
      return next
    })
    runLimited(tickers, 3, async (ticker) => {
      if (cancelled) return
      inFlightScores.current.add(ticker)
      try {
        // Bei 429/503 wiederholen (X23): sonst bleiben in langen Listen die
        // hinteren Titel ohne Score.
        const res = await authFetchRetry(`/api/analysis/score/${encodeURIComponent(ticker)}`)
        if (res.ok) {
          const json = await res.json()
          setScores((prev) => ({ ...prev, [ticker]: { passed: json.score, total: json.max_score } }))
        } else if (res.status >= 400 && res.status < 500 && res.status !== 429) {
          failedScores.current.add(ticker)
        }
      } catch { /* ignore */ }
      inFlightScores.current.delete(ticker)
      setLoadingScores((prev) => ({ ...prev, [ticker]: false }))
    })
    return () => { cancelled = true }
  }, [tickerKey, showScores]) // eslint-disable-line react-hooks/exhaustive-deps

  const openCtxFor = useCallback((e, position) => {
    const rect = e.currentTarget.getBoundingClientRect()
    setCtxMenu({ x: rect.left, y: rect.bottom + 4, position })
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
    } else if (action === 'dividend') {
      setTxnModal({ position: pos, type: 'dividend' })
    } else if (action === 'stop_loss') {
      setStopLossTarget(pos)
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
    <div className="bg-card border border-border rounded-card overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex items-center gap-2.5">
        <span className={`w-[9px] h-[9px] rounded-[3px] ${dotClass}`} />
        <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
      </div>
      <div className="p-8 text-center">
        <p className="text-text-muted text-sm mb-1">{emptyText}</p>
        <p className="text-text-secondary text-xs mb-4">Positionen werden automatisch aus Transaktionen erstellt.</p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => navigate('/transactions?action=add')}
            className="flex items-center gap-1.5 px-4 py-2 max-md:min-h-[40px] text-sm rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary transition-colors"
          >
            <Plus size={14} />
            Transaktion erfassen
          </button>
          <button
            onClick={() => navigate('/transactions?action=import')}
            className="flex items-center gap-1.5 px-4 py-2 max-md:min-h-[40px] text-sm rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors"
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

  const headers = [
    { key: 'ticker', label: 'Ticker', align: 'left' },
    { key: 'name', label: 'Name', align: 'left' },
    { key: 'shares', label: 'Anzahl', align: 'right', hideMobile: true },
    { key: 'current_price', label: 'Kurs', align: 'right' },
    { key: 'stop_loss_price', label: <G term="Stop-Loss">Stop</G>, align: 'right', title: 'Stop-Loss Kurs', hideMobile: true },
    { key: 'stop_distance', label: '\u0394 Stop', align: 'right', title: 'Abstand zum Stop-Loss in %', hideMobile: true },
    { key: 'market_value_chf', label: 'Wert CHF', align: 'right' },
    { key: 'weight_pct', label: 'Anteil %', align: 'right', hideMobile: true },
    { key: 'pnl_pct', label: 'Perf %', align: 'right', title: 'Performance inkl. Transaktionsgebühren' },
    { key: 'fx_return_pct', label: 'FX %', align: 'right', title: 'Währungsanteil der CHF-Rendite (Wechselkurs-Effekt seit Kauf; nur Fremdwährungs-Titel)', noSort: true },
    { key: 'pnl_chf', label: 'Perf CHF', align: 'right', title: 'Performance inkl. Transaktionsgebühren', hideMobile: true },
    { key: 'mansfield_rs', label: <G term="MRS">MRS</G>, align: 'right', title: 'Mansfield Relative Stärke', hideMobile: true },
    { key: 'setup', label: 'Score', align: 'center', title: '18-Punkte Kauf-Checkliste', hideMobile: true },
    { key: 'buy_date', label: 'Seit', align: 'right', hideMobile: true },
    { key: 'alerts', label: '', align: 'center', title: 'Preis-Alarme', hideMobile: true, noSort: true },
    { key: 'notes', label: '', align: 'center', title: 'Notizen', hideMobile: true, noSort: true },
  ]

  return (
    <div className="bg-card border border-border rounded-card md:overflow-hidden">
      <div className="px-[18px] py-4 border-b border-border-2 flex flex-col md:flex-row md:items-center justify-between gap-3 md:gap-4">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`w-[9px] h-[9px] rounded-[3px] flex-none ${dotClass}`} />
          <h3 className="text-sm font-semibold text-text-primary">
            {title}
            <span className="text-xs font-normal text-text-muted ml-2">({filteredPositions.length}{searchTerm ? `/${tradablePositions.length}` : ''} Titel)</span>
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <AddDropdown navigate={navigate} />
          <div className="relative max-md:flex-1 max-md:min-w-[140px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Suchen..."
              aria-label="Positionen durchsuchen"
              className="bg-card border border-border rounded-lg pl-8 pr-3 py-1.5 text-xs text-text-primary w-full md:w-44 max-md:min-h-[36px] focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
            />
          </div>
          {closedPositions.length > 0 && (
            <button
              onClick={() => setShowClosed(!showClosed)}
              className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 max-md:min-h-[36px] rounded-lg border transition-colors ${
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
      {/* Mobil: Kartenliste mit allen Spalten der Tabelle (Regel 2). Die Zweige werden
          bedingt gemountet: beide im DOM hiesse zwei AlertPopover (jeder schliesst den
          anderen per Aussenklick) und zwei [data-ticker]-Ziele je Position. */}
      {isMobile && (<div className="md:hidden">
        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border-2">
          <label htmlFor={`pt-sort-${title}`} className="sr-only">Sortieren nach</label>
          <select
            id={`pt-sort-${title}`}
            value={sortKey}
            onChange={(e) => { setSortKey(e.target.value); setSortAsc(false) }}
            className="flex-1 min-w-0 bg-surface border border-border rounded-lg px-2.5 min-h-[40px] text-xs text-text-primary"
          >
            {MOBILE_SORTS.map((o) => <option key={o.key} value={o.key}>{`Sortierung: ${o.label}`}</option>)}
          </select>
          <button
            onClick={() => setSortAsc(!sortAsc)}
            className="flex-none w-10 h-10 flex items-center justify-center rounded-lg border border-border text-text-secondary"
            aria-label={sortAsc ? 'Aufsteigend sortiert, umkehren' : 'Absteigend sortiert, umkehren'}
          >
            {sortAsc ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
        <ul className="divide-y divide-border-row">
          {sorted.map((p) => (
            <MobilePositionRow
              key={p.id}
              p={p}
              bucket={bucketMap?.[p.bucket_id]}
              score={scores[p.ticker]}
              scoreLoading={!!loadingScores[p.ticker]}
              onMenu={(e) => openCtxFor(e, p)}
              menuOpen={ctxMenu?.position?.id === p.id}
              onStop={() => setStopLossTarget(p)}
              alertOpen={alertTicker === p.ticker}
              toggleAlert={() => setAlertTicker(alertTicker === p.ticker ? null : p.ticker)}
              onAlertClose={() => { setAlertTicker(null); onRefresh?.() }}
              editingNotes={editingNotes === p.id}
              notesValue={notesValue}
              setNotesValue={setNotesValue}
              startNotes={() => { setEditingNotes(p.id); setNotesValue(p.notes || '') }}
              cancelNotes={() => setEditingNotes(null)}
              savingNotes={savingNotes}
              saveNotes={async () => {
                setSavingNotes(true)
                try {
                  await apiPut(`/portfolio/positions/${p.id}`, { notes: notesValue })
                  setEditingNotes(null)
                  onRefresh?.()
                } catch (err) {
                  toast('Notiz konnte nicht gespeichert werden: ' + (err.message || 'Fehler'), 'error')
                } finally {
                  setSavingNotes(false)
                }
              }}
            />
          ))}
        </ul>
        {sorted.length === 0 && (
          <div className="p-6 text-center text-text-muted text-sm">Keine Treffer.</div>
        )}
        <div className={`px-4 py-3 border-t border-border bg-card-alt/30 text-sm ${showClosed && closedPositions.length > 0 ? '' : 'rounded-b-card'}`}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-text-primary font-medium">Total</span>
            <span className="font-mono tabular-nums text-text-primary font-bold">{formatNumber(tradablePositions.reduce((a, p) => a + p.market_value_chf, 0))}</span>
          </div>
          {(() => {
            const pnl = tradablePositions.reduce((a, p) => a + p.pnl_chf, 0)
            const inv = tradablePositions.reduce((a, p) => a + p.cost_basis_chf, 0)
            const pct = inv > 0 ? (pnl / inv) * 100 : 0
            return (
              <div className="flex items-baseline justify-between gap-3 mt-1 font-mono text-[11.5px] tabular-nums">
                <span className="text-text-muted">Anteil {tradablePositions.reduce((a, p) => a + p.weight_pct, 0).toFixed(1)}%</span>
                <span className={pnlColor(pnl)}>{formatPct(pct)} · {formatNumber(pnl)}</span>
              </div>
            )
          })()}
          {totalFees > 0 && <div className="text-xs text-text-secondary mt-1">Inkl. Gebühren von {formatCHF(totalFees)}</div>}
        </div>
        {showClosed && closedPositions.length > 0 && (
          <div className="border-t border-border-2">
            <div className="px-4 pt-3 pb-1 text-xs font-medium text-text-muted uppercase tracking-wide">Geschlossene Positionen</div>
            <ul className="divide-y divide-border-row opacity-60">
              {closedPositions.map((p) => (
                <li key={p.id} className="px-4 py-2.5 flex items-baseline justify-between gap-3 min-w-0">
                  <span className="min-w-0 truncate"><span className="font-mono text-text-muted font-medium">{p.ticker}</span> <span className="text-xs text-text-muted">{p.name}</span></span>
                  <span className={`font-mono text-[12px] tabular-nums flex-none ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)} · {formatNumber(p.pnl_chf)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>)}
      {!isMobile && (<div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-table-head border-b border-border-2 text-text-faint text-[10px] uppercase tracking-[0.05em] font-mono">
              {headers.map((h) => (
                <th
                  key={h.key}
                  className={`p-3 font-medium transition-colors whitespace-nowrap select-none ${
                    h.noSort ? '' : 'cursor-pointer hover:text-text-primary'
                  } ${
                    h.align === 'right' ? 'text-right' : h.align === 'center' ? 'text-center' : 'text-left'
                  } ${sortKey === h.key ? 'text-primary' : ''} ${h.key === 'ticker' ? 'sticky left-0 z-10 bg-card' : ''} ${h.hideMobile ? 'hidden md:table-cell' : ''}`}
                  onClick={h.noSort ? undefined : () => handleSort(h.key)}
                >
                  <span title={h.title}>{h.label}</span>
                  {!h.noSort && sortKey === h.key ? (
                    sortAsc ? <ChevronUp size={14} className="inline ml-0.5 text-primary" /> : <ChevronDown size={14} className="inline ml-0.5 text-primary" />
                  ) : null}
                </th>
              ))}
              <th className="p-3 w-10" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr key={p.id} data-ticker={p.ticker} tabIndex={0} className="border-b border-border/50 hover:bg-card-alt/50 transition-colors focus:outline-none focus:bg-card-alt/50" onKeyDown={(e) => { if (e.target !== e.currentTarget) return; if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCtxFor(e, p) } }}>
                <td className="p-3 font-mono text-primary font-medium sticky left-0 z-10 bg-card"><div className="flex items-center gap-2"><TickerLogo ticker={p.ticker} size={20} /><MiniChartTooltip ticker={p.ticker}><Link to={`/stock/${encodeURIComponent(p.ticker)}`} className="hover:underline">{p.ticker}</Link></MiniChartTooltip></div></td>
                <td className="p-3 text-text-primary whitespace-nowrap">
                  <span className="inline-flex items-center gap-1.5">
                    {p.name}
                    <EarningsBadge date={p.next_earnings_date} />
                    {bucketMap?.[p.bucket_id] && (
                      <span
                        className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border border-white/10 text-text-secondary"
                        title={`Bucket: ${bucketMap[p.bucket_id].name}`}
                      >
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: bucketMap[p.bucket_id].color || '#888' }} />
                        {bucketMap[p.bucket_id].name}
                      </span>
                    )}
                  </span>
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
                      {formatNumber(p.market_value_chf)}
                    </span>
                  ) : (
                    <span className="text-text-primary">{formatNumber(p.market_value_chf)}</span>
                  )}
                </td>
                <td className="p-3 text-right text-text-secondary tabular-nums hidden md:table-cell">{p.weight_pct.toFixed(1)}%</td>
                <td className={`p-3 text-right font-medium tabular-nums ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</td>
                <td className="p-3 text-right tabular-nums" title={fxBreakdownTitle(p)}>
                  {p.fx_return_pct != null && p.currency !== 'CHF'
                    ? <span className={pnlColor(p.fx_return_pct)}>{formatPct(p.fx_return_pct)}</span>
                    : <span className="text-text-muted">–</span>}
                </td>
                <td className={`p-3 text-right tabular-nums hidden md:table-cell ${pnlColor(p.pnl_chf)}`}>{formatNumber(p.pnl_chf)}</td>
                <td className="p-3 text-right hidden md:table-cell" title={p.mansfield_rs != null ? `MRS ${p.mansfield_rs > 0 ? 'positiv: stärker als Markt' : 'negativ: schwächer als Markt'}` : ''}><MrsCell value={p.mansfield_rs} /></td>
                <td className="p-3 text-center hidden md:table-cell">
                  {loadingScores[p.ticker] ? (
                    <Loader2 size={14} className="animate-spin text-text-muted mx-auto" />
                  ) : scores[p.ticker] ? (
                    <span className="font-mono text-xs text-text-secondary">{scores[p.ticker].passed}/{scores[p.ticker].total}</span>
                  ) : (
                    <span className="text-text-secondary text-xs">–</span>
                  )}
                </td>
                <td className="p-3 text-right text-text-secondary text-xs whitespace-nowrap hidden md:table-cell" title={p.buy_date || ''}>
                  {formatHoldingPeriod(p.buy_date)}
                </td>
                <td className="p-3 text-center hidden md:table-cell relative">
                  <button
                    onClick={(e) => { e.stopPropagation(); setAlertTicker(alertTicker === p.ticker ? null : p.ticker) }}
                    className={`p-1 rounded transition-colors ${
                      p.active_alerts > 0 ? 'text-warning hover:text-warning/80' : 'text-text-muted hover:text-text-primary'
                    }`}
                    title={p.active_alerts > 0 ? `${p.active_alerts} aktive${p.active_alerts === 1 ? 'r' : ''} Alarm${p.active_alerts === 1 ? '' : 'e'}` : 'Preis-Alarm setzen'}
                    aria-label="Preis-Alarm öffnen"
                  >
                    {p.active_alerts > 0 ? <BellRing size={15} /> : <Bell size={15} />}
                    {p.active_alerts > 0 && (
                      <span className="ml-0.5 text-[10px] font-semibold">{p.active_alerts}</span>
                    )}
                  </button>
                  {alertTicker === p.ticker && (
                    <AlertPopover
                      ticker={p.ticker}
                      currency={p.price_currency || p.currency}
                      resistance={p.manual_resistance}
                      onClose={() => { setAlertTicker(null); onRefresh?.() }}
                    />
                  )}
                </td>
                <td className="p-3 text-center hidden md:table-cell">
                  {editingNotes === p.id ? (
                    <div className="flex items-start gap-1">
                      <textarea
                        value={notesValue}
                        onChange={(e) => setNotesValue(e.target.value)}
                        maxLength={2000}
                        rows={2}
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                        className="w-48 bg-card border border-border rounded px-1.5 py-1 text-xs text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 resize-none"
                      />
                      <div className="flex flex-col gap-0.5">
                        <button
                          onClick={async (e) => {
                            e.stopPropagation()
                            setSavingNotes(true)
                            try {
                              await apiPut(`/portfolio/positions/${p.id}`, { notes: notesValue })
                              setEditingNotes(null)
                              onRefresh?.()
                            } catch (err) {
                              toast('Notiz konnte nicht gespeichert werden: ' + (err.message || 'Fehler'), 'error')
                            } finally {
                              setSavingNotes(false)
                            }
                          }}
                          disabled={savingNotes}
                          className="p-0.5 rounded text-success hover:bg-white/10 disabled:opacity-50"
                          title="Speichern"
                          aria-label="Notiz speichern"
                        >
                          <Check size={12} />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setEditingNotes(null) }}
                          className="p-0.5 rounded text-text-muted hover:text-danger hover:bg-white/10"
                          title="Abbrechen"
                          aria-label="Abbrechen"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    </div>
                  ) : p.notes ? (
                    <button
                      onClick={(e) => { e.stopPropagation(); setEditingNotes(p.id); setNotesValue(p.notes || '') }}
                      className="max-w-[180px] truncate text-xs text-text-secondary hover:text-text-primary text-left"
                      title={p.notes}
                    >
                      {p.notes}
                    </button>
                  ) : (
                    <button
                      onClick={(e) => { e.stopPropagation(); setEditingNotes(p.id); setNotesValue('') }}
                      className="p-1 rounded text-text-muted hover:text-text-primary transition-colors"
                      title="Notiz hinzufügen"
                      aria-label="Notiz hinzufügen"
                    >
                      <MessageSquare size={15} />
                    </button>
                  )}
                </td>
                <td className="p-3 text-center">
                  <button
                    onClick={(e) => { e.stopPropagation(); openCtxFor(e, p) }}
                    className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
                    title="Aktionen"
                    aria-label="Aktionen öffnen"
                    aria-expanded={ctxMenu?.position?.id === p.id}
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
                    <td className="p-3 text-text-primary font-medium sticky left-0 z-10 bg-card" colSpan={6}>Total</td>
                    <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatNumber(totalValue)}</td>
                    <td className="p-3 text-right text-text-secondary font-medium tabular-nums">{totalWeight.toFixed(1)}%</td>
                    <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnlPct)}`}>{formatPct(totalPnlPct)}</td>
                    <td className="p-3"></td>
                    <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnl)}`}>{formatNumber(totalPnl)}</td>
                    <td className="p-3" colSpan={6}></td>
                  </tr>
                ]
                if (totalFees > 0) {
                  rows.push(
                    <tr key="fees-note">
                      <td colSpan={17} className="px-3 pb-2 pt-1">
                        <span className="text-xs text-text-secondary">Inkl. Gebühren von {formatCHF(totalFees)}</span>
                      </td>
                    </tr>
                  )
                }
                return rows
              })()}
              {showClosed && closedPositions.length > 0 && (
                <>
                  <tr>
                    <td colSpan={18} className="px-3 pt-4 pb-2">
                      <span className="text-xs font-medium text-text-muted uppercase tracking-wide">Geschlossene Positionen</span>
                    </td>
                  </tr>
                  {closedPositions.map((p) => (
                    <tr key={p.id} className="border-b border-border/30 opacity-40">
                      <td className="p-3 font-mono text-text-muted font-medium">{p.ticker}</td>
                      <td className="p-3 text-text-muted whitespace-nowrap">{p.name}</td>
                      <td className="p-3 text-center"><span className="text-text-secondary text-xs">—</span></td>
                      <td className="p-3 text-right text-text-muted tabular-nums text-xs">0</td>
                      <td className="p-3 text-right text-text-muted tabular-nums text-xs">–</td>
                      <td className="p-3 text-text-muted">–</td>
                      <td className="p-3 text-text-muted">–</td>
                      <td className="p-3 text-right text-text-muted tabular-nums">{formatNumber(0)}</td>
                      <td className="p-3 text-right text-text-muted tabular-nums">0.0%</td>
                      <td className={`p-3 text-right font-medium tabular-nums ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</td>
                      <td className="p-3 text-right text-text-muted tabular-nums">–</td>
                      <td className={`p-3 text-right tabular-nums ${pnlColor(p.pnl_chf)}`}>{formatNumber(p.pnl_chf)}</td>
                      <td className="p-3" colSpan={6}></td>
                    </tr>
                  ))}
                </>
              )}
          </tbody>
        </table>
      </div>)}

      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          onAction={handleAction}
          onClose={() => setCtxMenu(null)}
          positionType={ctxMenu.position?.type}
          title={ctxMenu.position?.name}
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

    </div>
  )
}

// Sortierauswahl der Mobilansicht (die Desktop-Tabelle sortiert per Spaltenkopf).
const MOBILE_SORTS = [
  { key: 'market_value_chf', label: 'Wert' },
  { key: 'pnl_pct', label: 'Perf %' },
  { key: 'pnl_chf', label: 'Perf CHF' },
  { key: 'weight_pct', label: 'Anteil' },
  { key: 'ticker', label: 'Ticker' },
  { key: 'name', label: 'Name' },
  { key: 'stop_distance', label: 'Δ Stop' },
  { key: 'mansfield_rs', label: 'MRS' },
  { key: 'setup', label: 'Score' },
  { key: 'buy_date', label: 'Haltedauer' },
]

function MobilePair({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-2 min-w-0">
      <span className="text-text-faint">{label}</span>
      <span className="text-text-secondary tabular-nums text-right min-w-0 truncate">{children}</span>
    </div>
  )
}

// Mobile Zeile einer Position: dieselben Informationen und Aktionen wie die
// Desktop-Zeile (Stop, Abstand, Anteil, MRS, Score, Alarm, Notiz, Menue).
function MobilePositionRow({
  p, bucket, score, scoreLoading, onMenu, menuOpen, onStop,
  alertOpen, toggleAlert, onAlertClose,
  editingNotes, notesValue, setNotesValue, startNotes, cancelNotes, savingNotes, saveNotes,
}) {
  const stopDist = p.stop_loss_price != null && p.current_price != null
    ? ((p.current_price - p.stop_loss_price) / p.current_price) * 100
    : null
  return (
    <li data-ticker={p.ticker} className="relative px-4 py-3 min-w-0">
      <div className="flex items-start gap-3 min-w-0">
        <TickerLogo ticker={p.ticker} size={28} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <Link to={`/stock/${encodeURIComponent(p.ticker)}`} className="font-mono text-primary font-medium text-[13px] truncate inline-flex items-center min-h-[36px] -my-2">{p.ticker}</Link>
            <EarningsBadge date={p.next_earnings_date} />
          </div>
          <div className="text-[11.5px] text-text-faint truncate">{p.name}</div>
          {bucket && (
            <span className="inline-flex items-center gap-1 mt-1 text-[10px] px-1.5 py-0.5 rounded border border-border text-text-secondary max-w-full">
              <span className="w-1.5 h-1.5 rounded-full flex-none" style={{ background: bucket.color || '#888' }} />
              <span className="truncate">{bucket.name}</span>
            </span>
          )}
        </div>
        <div className="text-right flex-none">
          <div className="font-mono text-[13px] tabular-nums font-medium">
            {p.is_stale ? (
              <span className="inline-flex items-center gap-1 text-warning" title={p.stale_reason || 'Kein aktueller Kurs. Angezeigter Wert basiert auf dem Einstandswert.'}>
                <AlertTriangle size={12} className="shrink-0" />{formatNumber(p.market_value_chf)}
              </span>
            ) : (
              <span className="text-text-primary">{formatNumber(p.market_value_chf)}</span>
            )}
          </div>
          <div className={`font-mono text-[11.5px] tabular-nums ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</div>
        </div>
        <button
          onClick={onMenu}
          className="flex-none -mr-2 w-10 h-10 flex items-center justify-center rounded-lg text-text-secondary active:bg-hover"
          aria-label={`Aktionen für ${p.ticker} öffnen`}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <MoreVertical size={18} />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2 font-mono text-[11.5px]">
        <MobilePair label="Anzahl">{formatNumber(p.shares, p.shares % 1 !== 0 ? 2 : 0)}</MobilePair>
        <MobilePair label="Kurs">{p.current_price != null ? `${p.price_currency || p.currency} ${formatNumber(p.current_price, 2)}` : '–'}</MobilePair>
        <MobilePair label="Perf CHF"><span className={pnlColor(p.pnl_chf)}>{formatNumber(p.pnl_chf)}</span></MobilePair>
        <MobilePair label="Anteil">{p.weight_pct.toFixed(1)}%</MobilePair>
        <MobilePair label="FX">
          {p.fx_return_pct != null && p.currency !== 'CHF'
            ? <span className={pnlColor(p.fx_return_pct)} title={fxBreakdownTitle(p)}>{formatPct(p.fx_return_pct)}</span>
            : '–'}
        </MobilePair>
        <MobilePair label="Seit">{formatHoldingPeriod(p.buy_date)}</MobilePair>
        <MobilePair label="Stop">
          <button onClick={onStop} className="font-mono -my-2 py-2 min-h-[36px] inline-flex items-center" aria-label={`Stop-Loss für ${p.ticker} bearbeiten`}>
            {p.stop_loss_price != null
              ? <span className={p.stop_loss_confirmed_at_broker ? 'text-success' : 'text-warning'}>
                  {formatNumber(p.stop_loss_price, 2)}
                  {/* Zustand nicht nur ueber die Farbe: mobil gibt es keinen Tooltip. */}
                  <span className="font-sans text-[10.5px] ml-1">{p.stop_loss_confirmed_at_broker ? 'bestätigt' : 'offen'}</span>
                </span>
              : <span className="text-text-secondary">—</span>}
          </button>
        </MobilePair>
        <MobilePair label="Δ Stop">
          {stopDist == null ? '—' : stopDist < 0
            ? <span className="text-danger font-bold">Stop!</span>
            : <span className={stopDist > 20 ? 'text-success' : stopDist > 10 ? 'text-warning' : 'text-danger'}>{stopDist.toFixed(1)}%</span>}
        </MobilePair>
        <MobilePair label="MRS"><MrsCell value={p.mansfield_rs} /></MobilePair>
        <MobilePair label="Score">
          {scoreLoading ? <Loader2 size={12} className="animate-spin text-text-muted inline" /> : score ? `${score.passed} von ${score.total}` : '–'}
        </MobilePair>
      </div>

      <div className="flex items-start gap-2 mt-1.5 min-w-0">
        {editingNotes ? (
          <div className="flex-1 min-w-0 flex items-start gap-2">
            <textarea
              value={notesValue}
              onChange={(e) => setNotesValue(e.target.value)}
              maxLength={2000}
              rows={2}
              autoFocus
              aria-label={`Notiz für ${p.ticker}`}
              className="flex-1 min-w-0 bg-card border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 resize-none"
            />
            <button onClick={saveNotes} disabled={savingNotes} className="w-10 h-10 flex items-center justify-center rounded-lg text-success border border-border disabled:opacity-50" aria-label="Notiz speichern"><Check size={16} /></button>
            <button onClick={cancelNotes} className="w-10 h-10 flex items-center justify-center rounded-lg text-text-muted border border-border" aria-label="Abbrechen"><X size={16} /></button>
          </div>
        ) : (
          <>
            <button
              onClick={startNotes}
              className="flex-1 min-w-0 min-h-[40px] flex items-center gap-2 text-left text-xs text-text-secondary"
              aria-label={p.notes ? 'Notiz bearbeiten' : 'Notiz hinzufügen'}
            >
              <MessageSquare size={15} className="flex-none text-text-muted" />
              <span className="truncate">{p.notes || 'Notiz hinzufügen'}</span>
            </button>
            <button
              onClick={toggleAlert}
              className={`flex-none min-h-[40px] min-w-[40px] px-2 flex items-center justify-center gap-0.5 rounded-lg ${p.active_alerts > 0 ? 'text-warning' : 'text-text-muted'}`}
              aria-label={p.active_alerts > 0 ? `${p.active_alerts} aktive Alarme, Preis-Alarm öffnen` : 'Preis-Alarm setzen'}
            >
              {p.active_alerts > 0 ? <BellRing size={16} /> : <Bell size={16} />}
              {p.active_alerts > 0 && <span className="text-[11px] font-semibold">{p.active_alerts}</span>}
            </button>
          </>
        )}
      </div>
      {alertOpen && (
        <div className="absolute inset-x-0 bottom-0 h-0">
          <AlertPopover
            ticker={p.ticker}
            currency={p.price_currency || p.currency}
            resistance={p.manual_resistance}
            onClose={onAlertClose}
          />
        </div>
      )}
    </li>
  )
}
