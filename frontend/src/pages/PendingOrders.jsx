import { useState, useMemo } from 'react'
import { Plus, Edit3, Trash2, Check, RefreshCw, Zap } from 'lucide-react'
import { useApi, apiPost, apiPatch, apiDelete } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import { useToast } from '../components/Toast'
import LoadingSpinner from '../components/LoadingSpinner'
import PendingOrderModal from '../components/PendingOrderModal'
import PendingOrderFillModal from '../components/PendingOrderFillModal'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import PageHeader from '../components/ui/PageHeader'
import Button from '../components/ui/Button'
import FilterChips from '../components/ui/FilterChips'
import TickerChip from '../components/ui/TickerChip'
import { TypeBadge } from '../components/ui/Badge'

const STATUS_BADGE = {
  open: 'bg-primary/15 text-primary',
  filled: 'bg-success/15 text-success',
  cancelled: 'bg-text-muted/15 text-text-muted',
  expired: 'bg-warning/15 text-warning',
}

const STATUS_LABEL = {
  open: 'Offen',
  filled: 'Gefüllt',
  cancelled: 'Storniert',
  expired: 'Abgelaufen',
}

const BADGE = 'inline-flex items-center px-[7px] py-[3px] rounded-[5px] text-[10.5px] font-medium leading-none'

function fmtPrice(v, currency) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (!isFinite(n)) return '—'
  // 2-4 decimals depending on magnitude
  const decimals = n >= 100 ? 2 : 4
  const formatted = formatNumber(n, decimals)
  return currency ? `${formatted} ${currency}` : formatted
}

function fmtShares(v) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  return formatNumber(n, 4, { minDecimals: 0 })
}

function distMeta(d) {
  if (d === null || d === undefined) {
    return { text: '—', color: 'text-text-muted', title: 'Kein Vergleichspreis (FX-Mismatch oder kein Quote)' }
  }
  const pct = d * 100
  const sign = pct >= 0 ? '+' : ''
  const text = `${sign}${pct.toFixed(2)}%`
  if (pct < 0) {
    return { text, color: 'text-danger', title: 'Trigger durchbrochen — prüfen ob gefüllt' }
  }
  if (d <= 0.02) {
    return { text, color: 'text-warning', title: 'Nahe am Trigger' }
  }
  return { text, color: 'text-text-secondary', title: 'Order noch nicht erreicht' }
}

function fmtExpiry(type, date) {
  if (type === 'gtc') return 'GTC'
  if (type === 'day') return 'Day'
  if (type === 'gtd' && date) {
    const m = date.match(/^(\d{4})-(\d{2})-(\d{2})/)
    if (m) return `GTD bis ${m[3]}.${m[2]}.${m[1]}`
    return `GTD ${date}`
  }
  return type
}

// Order-Typ aus vorhandenen Feldern ableiten (kein separates Feld im Payload).
function orderTypeLabel(o) {
  return o.stop_price !== null && o.stop_price !== undefined ? 'Stop-Loss' : 'Limit'
}

// Clientseitiger Fill-Check: wuerde die Order bei current_price * (1 + move%) ausfuehren?
// null = nicht bewertbar (kein current_price).
function wouldFill(o, movePct) {
  const cur = o.current_price
  if (cur === null || cur === undefined) return null
  const curN = Number(cur)
  if (!isFinite(curN) || curN <= 0) return null
  const sim = curN * (1 + movePct / 100)
  if (o.stop_price !== null && o.stop_price !== undefined) {
    return sim <= Number(o.stop_price)
  }
  if (o.side === 'sell') {
    return sim >= Number(o.limit_price)
  }
  return sim <= Number(o.limit_price)
}

function DeleteConfirm({ order, onConfirm, onCancel, busy }) {
  useEscClose(onCancel)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm" onClick={onCancel}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Limit-Order löschen"
        className="bg-modal border border-danger/40 rounded-[14px] shadow-2xl w-full max-w-sm mx-4 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-text-primary mb-2">Limit-Order löschen?</h3>
        <p className="text-sm text-text-secondary">
          {order.ticker} {order.side?.toUpperCase()} {fmtShares(order.shares)} @ {fmtPrice(order.limit_price, order.currency)}
        </p>
        {order.status === 'filled' && (
          <p className="mt-3 text-xs text-text-muted">
            Verknüpfte Transaktion bleibt erhalten.
          </p>
        )}
        <div className="mt-5 flex gap-3 justify-end">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
            Abbrechen
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="flex items-center gap-2 bg-danger text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-danger/80 disabled:opacity-40"
          >
            <Trash2 size={14} />
            {busy ? 'Löschen...' : 'Löschen'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function PendingOrders() {
  const addToast = useToast()
  const [tab, setTab] = useState('open')
  const [showCreate, setShowCreate] = useState(false)
  const [editOrder, setEditOrder] = useState(null)
  const [deleteOrder, setDeleteOrder] = useState(null)
  const [fillOrder, setFillOrder] = useState(null)
  const [busy, setBusy] = useState(false)
  const [move, setMove] = useState(0)

  const { data, loading, error, refetch } = useApi(`/orders/pending?status=${tab}`)

  const counts = data?.counts || { open: 0, filled: 0, cancelled: 0, expired: 0 }
  const closedTotal = counts.filled + counts.cancelled + counts.expired
  const allTotal = counts.open + closedTotal

  const items = data?.items || []

  const handleCreate = async (payload) => {
    setBusy(true)
    try {
      await apiPost('/orders/pending', payload)
      addToast('Limit-Order erstellt', 'success')
      setShowCreate(false)
      refetch()
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const handleUpdate = async (payload) => {
    if (!editOrder) return
    setBusy(true)
    try {
      await apiPatch(`/orders/pending/${editOrder.id}`, payload)
      addToast('Limit-Order aktualisiert', 'success')
      setEditOrder(null)
      refetch()
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteOrder) return
    setBusy(true)
    try {
      await apiDelete(`/orders/pending/${deleteOrder.id}`)
      addToast('Limit-Order gelöscht', 'success')
      setDeleteOrder(null)
      refetch()
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const handleFill = async (payload) => {
    if (!fillOrder) return
    setBusy(true)
    try {
      const res = await apiPost(`/orders/pending/${fillOrder.id}/fill`, payload)
      addToast(`Order ausgeführt — Transaktion ${res.transaction_id?.slice(0, 8)}...`, 'success')
      setFillOrder(null)
      refetch()
    } catch (err) {
      addToast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const tabOptions = useMemo(() => ([
    { key: 'open', label: 'Offen', count: counts.open },
    { key: 'closed', label: 'Erledigt', count: closedTotal },
    { key: 'all', label: 'Alle', count: allTotal },
  ]), [counts, closedTotal, allTotal])

  const openOrders = useMemo(
    () => items.filter((o) => o.effective_status === 'open'),
    [items],
  )
  const fillCount = useMemo(
    () => openOrders.reduce((n, o) => n + (wouldFill(o, move) === true ? 1 : 0), 0),
    [openOrders, move],
  )

  const moveLabel = `${move > 0 ? '+' : ''}${move.toFixed(1)}%`
  const moveColor = move > 0 ? 'text-success' : move < 0 ? 'text-danger' : 'text-text-secondary'

  const actions = (
    <Button variant="primary" icon={Plus} onClick={() => setShowCreate(true)}>Order</Button>
  )

  return (
    <div className="pb-10">
      <PageHeader
        title="Offene Orders"
        subtitle="Limit-Orders & Fills"
        actions={actions}
        showBell={false}
      />

      <div className="flex flex-col gap-[18px]">
        {/* Fill-Simulator */}
        {openOrders.length > 0 && (
          <div className="bg-card border border-border rounded-card overflow-hidden">
            <div className="px-[18px] py-4 flex items-start justify-between gap-6">
              <div className="flex items-start gap-3 min-w-0">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <Zap size={16} className="text-primary" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-text-primary">Fill-Simulator</div>
                  <p className="text-xs text-text-muted mt-0.5 max-w-md">
                    Simuliert eine Marktbewegung und zeigt, welche offenen Orders bei diesem Spot ausführen würden. Rein clientseitig — keine echten Trades.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-8 shrink-0">
                <div className="text-right">
                  <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-[6px]">Marktbewegung</div>
                  <div className={`font-mono text-[20px] font-semibold leading-none tabular-nums ${moveColor}`}>{moveLabel}</div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-[6px]">Würde ausführen</div>
                  <div className="font-mono text-[20px] font-semibold leading-none tabular-nums">
                    <span className={fillCount > 0 ? 'text-success' : 'text-text-primary'}>{fillCount}</span>
                    <span className="text-text-muted"> / {openOrders.length}</span>
                  </div>
                </div>
              </div>
            </div>
            <div className="px-[18px] pb-4">
              <input
                type="range"
                min={-15}
                max={15}
                step={0.5}
                value={move}
                onChange={(e) => setMove(parseFloat(e.target.value))}
                className="w-full"
                aria-label="Simulierte Marktbewegung in Prozent"
              />
              <div className="flex justify-between font-mono text-[10px] text-text-faint mt-1">
                <span>-15%</span>
                <span>0%</span>
                <span>+15%</span>
              </div>
            </div>
          </div>
        )}

        {/* Tabs */}
        <FilterChips options={tabOptions} value={tab} onChange={setTab} />

        {/* Tabelle / States */}
        {loading ? (
          <div className="p-12"><LoadingSpinner /></div>
        ) : error ? (
          <div className="rounded-card border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
            <span className="text-danger text-sm">Fehler beim Laden: {error}</span>
            <Button variant="primary" icon={RefreshCw} onClick={refetch}>Erneut laden</Button>
          </div>
        ) : !items.length ? (
          <div className="rounded-card border border-border bg-card p-12 text-center">
            <h3 className="text-base font-semibold text-text-primary mb-1">Keine Orders in dieser Ansicht</h3>
            <p className="text-sm text-text-muted max-w-md mx-auto">
              {tab === 'open'
                ? 'Lege deine erste offene Limit-Order an, um sie hier zu tracken.'
                : 'Hier erscheinen erledigte Orders (gefüllt, storniert, abgelaufen).'}
            </p>
            {tab === 'open' && (
              <div className="mt-5">
                <Button variant="primary" icon={Plus} onClick={() => setShowCreate(true)}>Erste Order erstellen</Button>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-card border border-border bg-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] tracking-[0.05em] uppercase text-text-faint">
                    <th className="text-left px-[18px] py-[11px] font-medium">Titel</th>
                    <th className="text-left px-3 py-[11px] font-medium">Seite</th>
                    <th className="text-left px-3 py-[11px] font-medium">Typ</th>
                    <th className="text-right px-3 py-[11px] font-medium">Limit</th>
                    <th className="text-right px-3 py-[11px] font-medium">Aktuell</th>
                    <th className="text-right px-3 py-[11px] font-medium">Distanz</th>
                    <th className="text-right px-3 py-[11px] font-medium">Menge</th>
                    <th className="text-center px-3 py-[11px] font-medium">Status</th>
                    <th className="px-3 py-[11px] w-24" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((o) => {
                    const dist = distMeta(o.distance_pct)
                    const eff = o.effective_status
                    const sim = eff === 'open' ? wouldFill(o, move) : null
                    return (
                      <tr
                        key={o.id}
                        className={`border-b border-border-row transition-colors group ${
                          sim === true ? 'bg-success/[0.07] hover:bg-success/10' : 'hover:bg-hover'
                        }`}
                      >
                        <td className="px-[18px] py-3">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <TickerChip>{o.ticker}</TickerChip>
                            {o.broker && (
                              <span className="text-text-muted text-xs truncate hidden lg:inline">{o.broker}</span>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <TypeBadge label={o.side === 'sell' ? 'Verkauf' : 'Kauf'} kind="txn" />
                        </td>
                        <td className="px-3 py-3">
                          <div className="text-text-secondary text-xs">{orderTypeLabel(o)}</div>
                          <div className="text-text-faint text-[10.5px] font-mono">{fmtExpiry(o.expiry_type, o.expiry_date)}</div>
                        </td>
                        <td className="px-3 py-3 text-right font-mono tabular-nums text-text-primary">
                          {fmtPrice(o.limit_price, o.currency)}
                          {o.stop_price !== null && o.stop_price !== undefined && (
                            <div className="text-text-faint text-[10.5px]">Stop {fmtPrice(o.stop_price, o.currency)}</div>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right font-mono tabular-nums text-text-secondary">
                          {fmtPrice(o.current_price, o.quote_currency)}
                        </td>
                        <td className={`px-3 py-3 text-right font-mono tabular-nums font-medium ${dist.color}`} title={dist.title}>
                          {dist.text}
                        </td>
                        <td className="px-3 py-3 text-right font-mono tabular-nums text-text-primary">{fmtShares(o.shares)}</td>
                        <td className="px-3 py-3 text-center">
                          {sim === true ? (
                            <span className={`${BADGE} bg-success/15 text-success`}>würde ausführen</span>
                          ) : (
                            <span className={`${BADGE} ${STATUS_BADGE[eff] || ''}`}>{STATUS_LABEL[eff] || eff}</span>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-0.5 justify-end md:opacity-0 md:group-hover:opacity-100 transition-opacity">
                            {eff === 'open' && (
                              <button
                                onClick={() => setFillOrder(o)}
                                className="p-1.5 rounded text-text-muted hover:text-success hover:bg-success/10 transition-colors"
                                title="Als gefüllt markieren — wenn der Trade bereits via CSV-Import erfasst wurde, stattdessen Status auf 'Storniert' setzen, sonst Duplikat"
                                aria-label="Als gefüllt markieren"
                              >
                                <Check size={14} />
                              </button>
                            )}
                            <button
                              onClick={() => setEditOrder(o)}
                              className="p-1.5 rounded text-text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                              title="Bearbeiten"
                              aria-label="Bearbeiten"
                            >
                              <Edit3 size={14} />
                            </button>
                            <button
                              onClick={() => setDeleteOrder(o)}
                              className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors"
                              title="Löschen"
                              aria-label="Löschen"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {showCreate && (
        <PendingOrderModal
          onSave={handleCreate}
          onClose={() => setShowCreate(false)}
          busy={busy}
        />
      )}
      {editOrder && (
        <PendingOrderModal
          initial={editOrder}
          onSave={handleUpdate}
          onClose={() => setEditOrder(null)}
          busy={busy}
        />
      )}
      {deleteOrder && (
        <DeleteConfirm
          order={deleteOrder}
          onConfirm={handleDelete}
          onCancel={() => setDeleteOrder(null)}
          busy={busy}
        />
      )}
      {fillOrder && (
        <PendingOrderFillModal
          order={fillOrder}
          onSave={handleFill}
          onClose={() => setFillOrder(null)}
          busy={busy}
        />
      )}
    </div>
  )
}
