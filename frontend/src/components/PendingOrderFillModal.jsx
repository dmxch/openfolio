import { useState } from 'react'
import { X, Check } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import DateInput from './DateInput'

const INPUT = 'w-full bg-card border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

export default function PendingOrderFillModal({ order, onSave, onClose, busy }) {
  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState({
    price_per_share: order.limit_price?.toString() || '',
    fill_date: today,
    fees_chf: '0',
    taxes_chf: '0',
    fx_rate_to_chf: '1',
    notes: `Aus Limit-Order ${order.id?.slice(0, 8) || ''}`,
  })
  const [error, setError] = useState(null)

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
      fees_chf: isFinite(fees) ? fees : 0,
      taxes_chf: isFinite(taxes) ? taxes : 0,
      fx_rate_to_chf: fx,
      notes: form.notes || null,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-body/80 backdrop-blur-sm p-4">
      <form
        ref={trapRef}
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="fill-modal-title"
        className="bg-card border border-border rounded-xl w-full max-w-lg"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 id="fill-modal-title" className="text-base font-semibold text-text-primary flex items-center gap-2">
            <Check size={18} className="text-success" />
            Order als gefüllt markieren
          </h3>
          <button type="button" onClick={onClose} className="text-text-muted hover:text-text-primary" aria-label="Schliessen">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-text-secondary">
            <span className="font-mono text-primary">{order.ticker}</span>
            {' '}{order.side?.toUpperCase()} {order.shares} @ Limit {order.limit_price} {order.currency}
            {order.broker && <span className="text-text-muted"> · {order.broker}</span>}
          </div>
          <p className="text-xs text-text-muted">
            Erzeugt eine Transaktion und verknüpft sie mit dieser Order. Wenn der Trade bereits via CSV-Import erfasst wurde,
            stattdessen Order über „Bearbeiten” auf Status „Storniert” setzen — sonst Duplikat.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Fill-Preis</label>
              <input
                type="number"
                step="any"
                min="0"
                value={form.price_per_share}
                onChange={(e) => update('price_per_share', e.target.value)}
                className={INPUT}
                required
              />
            </div>
            <div>
              <label className={LABEL}>Fill-Datum</label>
              <DateInput
                value={form.fill_date}
                onChange={(v) => update('fill_date', v)}
                className={INPUT}
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className={LABEL}>Gebühren (CHF)</label>
              <input
                type="number"
                step="any"
                min="0"
                value={form.fees_chf}
                onChange={(e) => update('fees_chf', e.target.value)}
                className={INPUT}
              />
            </div>
            <div>
              <label className={LABEL}>Steuern (CHF)</label>
              <input
                type="number"
                step="any"
                min="0"
                value={form.taxes_chf}
                onChange={(e) => update('taxes_chf', e.target.value)}
                className={INPUT}
              />
            </div>
            <div>
              <label className={LABEL}>FX → CHF</label>
              <input
                type="number"
                step="any"
                min="0"
                value={form.fx_rate_to_chf}
                onChange={(e) => update('fx_rate_to_chf', e.target.value)}
                className={INPUT}
                title={`1 ${order.currency} = X CHF`}
              />
            </div>
          </div>

          <div>
            <label className={LABEL}>Notiz auf der Transaktion</label>
            <input
              type="text"
              value={form.notes}
              onChange={(e) => update('notes', e.target.value)}
              className={INPUT}
            />
          </div>

          {error && <div className="text-sm text-danger">{error}</div>}
        </div>

        <div className="px-5 py-4 border-t border-border flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
            Abbrechen
          </button>
          <button
            type="submit"
            disabled={busy}
            className="px-4 py-2 text-sm bg-success text-white rounded-lg hover:bg-success/80 disabled:opacity-40"
          >
            {busy ? 'Wird gebucht...' : 'Transaktion anlegen'}
          </button>
        </div>
      </form>
    </div>
  )
}
