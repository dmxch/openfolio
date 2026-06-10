import { useState, useMemo } from 'react'
import { Plus, Edit3, Trash2, Check, ListOrdered, RefreshCw } from 'lucide-react'
import { useApi, apiPost, apiPatch, apiDelete } from '../hooks/useApi'
import { formatNumber } from '../lib/format'
import { useToast } from '../components/Toast'
import LoadingSpinner from '../components/LoadingSpinner'
import PendingOrderModal from '../components/PendingOrderModal'
import PendingOrderFillModal from '../components/PendingOrderFillModal'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'

const STATUS_BADGE = {
  open: 'bg-primary/15 text-primary border-primary/30',
  filled: 'bg-success/15 text-success border-success/30',
  cancelled: 'bg-text-muted/15 text-text-muted border-text-muted/30',
  expired: 'bg-warning/15 text-warning border-warning/30',
}

const STATUS_LABEL = {
  open: 'Offen',
  filled: 'Gefüllt',
  cancelled: 'Storniert',
  expired: 'Abgelaufen',
}

const SIDE_BADGE = {
  buy: 'bg-success/15 text-success border-success/30',
  sell: 'bg-danger/15 text-danger border-danger/30',
}

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

function fmtDistance(d) {
  if (d === null || d === undefined) return { text: '—', color: 'text-text-muted', title: 'Kein Vergleichspreis (FX-Mismatch oder kein Quote)' }
  const pct = d * 100
  const sign = pct >= 0 ? '+' : ''
  const text = `${sign}${pct.toFixed(2)}%`
  if (pct < 0) {
    return { text, color: 'text-danger', title: 'Trigger durchbrochen — prüfen ob gefüllt' }
  }
  return { text, color: 'text-success', title: 'Order noch nicht erreicht' }
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

function DeleteConfirm({ order, onConfirm, onCancel, busy }) {
  useEscClose(onCancel)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-body/80 backdrop-blur-sm p-4">
      <div ref={trapRef} role="dialog" aria-modal="true" className="bg-card border border-danger/30 rounded-xl w-full max-w-sm p-6">
        <h3 className="text-base font-semibold text-text-primary">Limit-Order löschen?</h3>
        <p className="mt-2 text-sm text-text-secondary">
          {order.ticker} {order.side?.toUpperCase()} {fmtShares(order.shares)} @ {fmtPrice(order.limit_price, order.currency)}
        </p>
        {order.status === 'filled' && (
          <p className="mt-3 text-xs text-text-muted">
            Verknüpfte Transaktion bleibt erhalten.
          </p>
        )}
        <div className="mt-5 flex gap-2 justify-end">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
            Abbrechen
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="px-4 py-2 text-sm bg-danger text-white rounded-lg hover:bg-danger/80 disabled:opacity-40"
          >
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

  const tabs = useMemo(() => ([
    { id: 'open', label: 'Offen', count: counts.open },
    { id: 'closed', label: 'Erledigt', count: closedTotal },
    { id: 'all', label: 'Alle', count: allTotal },
  ]), [counts, closedTotal, allTotal])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ListOrdered size={22} className="text-primary" />
          <div>
            <h2 className="text-xl font-bold text-text-primary">Offene Limit-Orders</h2>
            <p className="text-xs text-text-muted mt-0.5">
              Manuell gepflegte Liste der beim Broker platzierten Orders. Source of Truth für Claude und den Daily-Digest.
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 bg-primary text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-primary/80"
        >
          <Plus size={16} />
          Neue Order
        </button>
      </div>

      <div className="flex items-center gap-1 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? 'border-primary text-text-primary'
                : 'border-transparent text-text-muted hover:text-text-primary'
            }`}
          >
            {t.label} <span className="ml-1 text-xs text-text-muted">({t.count})</span>
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : error ? (
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
          <span className="text-danger text-sm">Fehler beim Laden: {error}</span>
          <button
            onClick={refetch}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary/90 transition-colors"
          >
            <RefreshCw size={14} />
            Erneut laden
          </button>
        </div>
      ) : !items.length ? (
        <div className="rounded-lg border border-border bg-card p-10 text-center">
          <h3 className="text-base font-semibold text-text-primary">Keine Orders in dieser Ansicht</h3>
          <p className="text-sm text-text-secondary mt-1">
            {tab === 'open'
              ? 'Lege deine erste offene Limit-Order an, um sie hier zu tracken.'
              : 'Hier erscheinen erledigte Orders (gefüllt, storniert, abgelaufen).'}
          </p>
          {tab === 'open' && (
            <button
              onClick={() => setShowCreate(true)}
              className="mt-4 px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary/80"
            >
              Erste Order erstellen
            </button>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-text-muted bg-card-alt/30">
                <th className="text-left px-3 py-2 font-medium">Ticker</th>
                <th className="text-center px-3 py-2 font-medium">Side</th>
                <th className="text-right px-3 py-2 font-medium">Shares</th>
                <th className="text-right px-3 py-2 font-medium">Limit</th>
                <th className="text-right px-3 py-2 font-medium">Stop</th>
                <th className="text-right px-3 py-2 font-medium">Aktuell</th>
                <th className="text-right px-3 py-2 font-medium">Δ%</th>
                <th className="text-left px-3 py-2 font-medium">Gültigkeit</th>
                <th className="text-left px-3 py-2 font-medium">Broker</th>
                <th className="text-center px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 w-28" />
              </tr>
            </thead>
            <tbody>
              {items.map((o) => {
                const dist = fmtDistance(o.distance_pct)
                const eff = o.effective_status
                return (
                  <tr key={o.id} className="border-b border-border/50 hover:bg-card-alt/40 group">
                    <td className="px-3 py-2 font-mono text-primary font-medium">{o.ticker}</td>
                    <td className="px-3 py-2 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${SIDE_BADGE[o.side] || ''}`}>
                        {o.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right text-text-primary">{fmtShares(o.shares)}</td>
                    <td className="px-3 py-2 text-right text-text-primary">{fmtPrice(o.limit_price, o.currency)}</td>
                    <td className="px-3 py-2 text-right text-text-secondary">
                      {o.stop_price !== null && o.stop_price !== undefined ? fmtPrice(o.stop_price, o.currency) : '—'}
                    </td>
                    <td className="px-3 py-2 text-right text-text-primary">
                      {fmtPrice(o.current_price, o.quote_currency)}
                    </td>
                    <td className={`px-3 py-2 text-right font-medium ${dist.color}`} title={dist.title}>
                      {dist.text}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">
                      {fmtExpiry(o.expiry_type, o.expiry_date)}
                    </td>
                    <td className="px-3 py-2 text-text-secondary">{o.broker || '—'}</td>
                    <td className="px-3 py-2 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${STATUS_BADGE[eff] || ''}`}>
                        {STATUS_LABEL[eff] || eff}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-0.5 justify-end opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
                        {eff === 'open' && (
                          <button
                            onClick={() => setFillOrder(o)}
                            className="p-1.5 rounded text-text-muted hover:text-success hover:bg-success/10"
                            title="Als gefüllt markieren — wenn der Trade bereits via CSV-Import erfasst wurde, stattdessen Status auf 'Storniert' setzen, sonst Duplikat"
                          >
                            <Check size={14} />
                          </button>
                        )}
                        <button
                          onClick={() => setEditOrder(o)}
                          className="p-1.5 rounded text-text-muted hover:text-primary hover:bg-primary/10"
                          title="Bearbeiten"
                        >
                          <Edit3 size={14} />
                        </button>
                        <button
                          onClick={() => setDeleteOrder(o)}
                          className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10"
                          title="Löschen"
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
      )}

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
