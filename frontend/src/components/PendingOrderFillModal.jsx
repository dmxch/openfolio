import { useState, useEffect } from 'react'
import { X, Check, Loader2 } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import { authFetch } from '../hooks/useApi'
import DateInput from './DateInput'

const INPUT = 'bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

const CURRENCIES = ['CHF', 'USD', 'EUR', 'GBP', 'CAD', 'GBX', 'JPY']

export default function PendingOrderFillModal({ order, onSave, onClose, busy }) {
  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  const today = new Date().toISOString().slice(0, 10)
  const orderCurrency = (order.currency || 'USD').toUpperCase()
  const [form, setForm] = useState({
    price_per_share: order.limit_price?.toString() || '',
    fill_date: today,
    currency: orderCurrency,
    fx_rate_to_chf: '1',
    fees_chf: '0',
    taxes_chf: '0',
    total_chf: '',
    notes: `Aus Limit-Order ${order.id?.slice(0, 8) || ''}`,
  })
  const [error, setError] = useState(null)
  const [fxLoading, setFxLoading] = useState(false)

  // Auto-fetch FX rate when currency changes
  useEffect(() => {
    if (form.currency === 'CHF') {
      setForm((f) => ({ ...f, fx_rate_to_chf: '1' }))
      return
    }
    let cancelled = false
    const fetchFx = async () => {
      setFxLoading(true)
      try {
        const res = await authFetch(`/api/market/fx/${form.currency}`)
        if (res.ok && !cancelled) {
          const data = await res.json()
          setForm((f) => ({ ...f, fx_rate_to_chf: data.rate.toString() }))
        }
      } catch { /* ignore */ } finally {
        if (!cancelled) setFxLoading(false)
      }
    }
    fetchFx()
    return () => { cancelled = true }
  }, [form.currency])

  // Auto-calculate Total CHF (brutto inkl. Gebuehren + Steuern, wie im Backend)
  useEffect(() => {
    const shares = parseFloat(order.shares) || 0
    const price = parseFloat(form.price_per_share) || 0
    const fx = parseFloat(form.fx_rate_to_chf) || 1
    const fees = parseFloat(form.fees_chf) || 0
    const taxes = parseFloat(form.taxes_chf) || 0
    if (shares > 0 && price > 0) {
      const total = shares * price * fx + fees + taxes
      setForm((f) => ({ ...f, total_chf: total.toFixed(2) }))
    }
  }, [order.shares, form.price_per_share, form.fx_rate_to_chf, form.fees_chf, form.taxes_chf])

  const update = (field, val) => setForm((f) => ({ ...f, [field]: val }))

  const handleSubmit = (e) => {
    e.preventDefault()
    setError(null)

    const price = parseFloat(form.price_per_share)
    if (!(price > 0)) {
      setError('Fill-Preis muss > 0 sein')
      return
    }
    if (!form.fill_date) {
      setError('Fill-Datum ist Pflicht')
      return
    }
    const fx = parseFloat(form.fx_rate_to_chf)
    if (!(fx > 0)) {
      setError('FX-Rate muss > 0 sein')
      return
    }
    const fees = parseFloat(form.fees_chf || '0')
    const taxes = parseFloat(form.taxes_chf || '0')

    onSave({
      price_per_share: price,
      fill_date: form.fill_date,
      currency: form.currency,
      fees_chf: isFinite(fees) ? fees : 0,
      taxes_chf: isFinite(taxes) ? taxes : 0,
      fx_rate_to_chf: fx,
      notes: form.notes || null,
    })
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4">
      <form
        ref={trapRef}
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="fill-modal-title"
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl w-full max-w-xl"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <h3 id="fill-modal-title" className="text-base font-semibold text-text-primary flex items-center gap-2">
            <Check size={18} className="text-success" />
            Order als gefüllt markieren
          </h3>
          <button type="button" onClick={onClose} className="text-text-muted hover:text-text-primary" aria-label="Schliessen">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-5 space-y-4">
          <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-text-secondary">
            <span className="font-mono text-primary">{order.ticker}</span>
            {' '}{order.side?.toUpperCase()} {order.shares} @ Limit {order.limit_price} {orderCurrency}
            {order.broker && <span className="text-text-muted"> · {order.broker}</span>}
          </div>
          <p className="text-xs text-text-muted">
            Erzeugt eine Transaktion und verknüpft sie mit dieser Order. Wenn der Trade bereits via CSV-Import erfasst wurde,
            stattdessen Order über „Bearbeiten" auf Status „Storniert" setzen — sonst Duplikat.
          </p>

          {/* Row 1: Datum + Fill-Preis */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="fill-date" className={LABEL}>Fill-Datum *</label>
              <DateInput
                id="fill-date"
                value={form.fill_date}
                onChange={(v) => update('fill_date', v)}
                className={`${INPUT} w-full`}
                required
              />
            </div>
            <div>
              <label htmlFor="fill-price" className={LABEL}>Fill-Preis *</label>
              <input
                id="fill-price"
                type="number"
                step="any"
                min="0"
                value={form.price_per_share}
                onChange={(e) => update('price_per_share', e.target.value)}
                className={`${INPUT} w-full tabular-nums`}
                required
              />
            </div>
          </div>

          {/* Row 2: Currency + FX + Gebühren + Total CHF */}
          <div className="grid grid-cols-4 gap-4">
            <div>
              <label htmlFor="fill-ccy" className={LABEL}>Währung</label>
              <select
                id="fill-ccy"
                value={form.currency}
                onChange={(e) => update('currency', e.target.value)}
                className={`${INPUT} w-full`}
              >
                {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="fill-fx" className={LABEL}>
                FX → CHF {fxLoading && <Loader2 size={10} className="inline animate-spin ml-1" />}
              </label>
              <input
                id="fill-fx"
                type="number"
                step="any"
                value={form.fx_rate_to_chf}
                onChange={(e) => update('fx_rate_to_chf', e.target.value)}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
            <div>
              <label htmlFor="fill-fees" className={LABEL}>Gebühren CHF</label>
              <input
                id="fill-fees"
                type="number"
                step="any"
                min="0"
                value={form.fees_chf}
                onChange={(e) => update('fees_chf', e.target.value)}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
            <div>
              <label htmlFor="fill-total" className={LABEL}>Total CHF</label>
              <input
                id="fill-total"
                type="number"
                step="any"
                value={form.total_chf}
                onChange={(e) => update('total_chf', e.target.value)}
                className={`${INPUT} w-full font-medium tabular-nums`}
                readOnly
              />
            </div>
          </div>

          {/* Row 3: Steuern (zusätzlich, weil Pending-Order-Fill üblicher mit Steuern) */}
          <div className="grid grid-cols-4 gap-4">
            <div>
              <label htmlFor="fill-taxes" className={LABEL}>Steuern CHF</label>
              <input
                id="fill-taxes"
                type="number"
                step="any"
                min="0"
                value={form.taxes_chf}
                onChange={(e) => update('taxes_chf', e.target.value)}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
            <div className="col-span-3" />
          </div>

          {/* Notizen */}
          <div>
            <label htmlFor="fill-notes" className={LABEL}>Notiz auf der Transaktion</label>
            <input
              id="fill-notes"
              type="text"
              value={form.notes}
              onChange={(e) => update('notes', e.target.value)}
              className={`${INPUT} w-full`}
            />
          </div>

          {error && (
            <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-border-2 flex items-center justify-end gap-3">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors">
            Abbrechen
          </button>
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-2 bg-success text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-success/80 transition-colors disabled:opacity-40"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            {busy ? 'Wird gebucht...' : 'Transaktion anlegen'}
          </button>
        </div>
      </form>
    </div>
  )
}
