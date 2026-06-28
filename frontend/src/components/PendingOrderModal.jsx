import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import { authFetch } from '../hooks/useApi'
import DateInput from './DateInput'

const INPUT = 'w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

export default function PendingOrderModal({ initial, onSave, onClose, busy }) {
  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  const isEdit = !!initial
  const isFilled = initial?.status === 'filled'

  const [form, setForm] = useState({
    ticker: initial?.ticker || '',
    side: initial?.side || 'buy',
    shares: initial?.shares?.toString() || '',
    limit_price: initial?.limit_price?.toString() || '',
    stop_price: initial?.stop_price?.toString() || '',
    currency: initial?.currency || 'USD',
    expiry_type: initial?.expiry_type || 'gtc',
    expiry_date: initial?.expiry_date || '',
    broker: initial?.broker || '',
    notes: initial?.notes || '',
    bucket_id_target: initial?.bucket_id_target || '',
    status: initial?.status === 'cancelled' ? 'cancelled' : 'open',
  })
  const [error, setError] = useState(null)
  const [buckets, setBuckets] = useState([])

  // Buckets laden — bestimmt, wo eine neu auto-erstellte Position bei Fill landet.
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await authFetch('/api/portfolio/buckets')
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        const eligible = (data.buckets || []).filter(
          (b) => !b.deleted_at && (b.kind === 'user' || b.system_role === 'liquid_default'),
        )
        setBuckets(eligible)
        if (!initial?.bucket_id_target) {
          const def = eligible.find((b) => b.system_role === 'liquid_default')
          if (def) setForm((f) => ({ ...f, bucket_id_target: f.bucket_id_target || def.id }))
        }
      } catch { /* ignore */ }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const showBucketSelector = !isFilled && buckets.length > 1

  const update = (field, val) => setForm((f) => ({ ...f, [field]: val }))

  const handleSubmit = (e) => {
    e.preventDefault()
    setError(null)

    if (isFilled) {
      // Nur notes editierbar — direkt PATCH mit nur dem notes-Feld
      onSave({ notes: form.notes || null })
      return
    }

    const ticker = form.ticker.trim().toUpperCase()
    if (!ticker) {
      setError('Ticker ist Pflicht')
      return
    }
    const shares = parseFloat(form.shares)
    if (!(shares > 0)) {
      setError('Shares muss > 0 sein')
      return
    }
    const limit = parseFloat(form.limit_price)
    if (!(limit > 0)) {
      setError('Limit-Preis muss > 0 sein')
      return
    }
    const stop = form.stop_price ? parseFloat(form.stop_price) : null
    if (form.stop_price && !(stop > 0)) {
      setError('Stop-Preis muss > 0 sein (oder leer lassen)')
      return
    }
    if (form.expiry_type === 'gtd' && !form.expiry_date) {
      setError('Ablaufdatum ist bei GTD Pflicht')
      return
    }
    if (form.expiry_type !== 'gtd' && form.expiry_date) {
      setError('Ablaufdatum nur bei GTD setzen')
      return
    }

    const payload = {
      ticker,
      side: form.side,
      shares,
      limit_price: limit,
      stop_price: stop,
      currency: form.currency.trim().toUpperCase() || 'USD',
      expiry_type: form.expiry_type,
      expiry_date: form.expiry_type === 'gtd' ? form.expiry_date : null,
      broker: form.broker.trim() || null,
      notes: form.notes || null,
      bucket_id_target: form.bucket_id_target || null,
    }
    if (isEdit) {
      payload.status = form.status
    }
    onSave(payload)
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4">
      <form
        ref={trapRef}
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="po-modal-title"
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl w-full max-w-xl max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <h3 id="po-modal-title" className="text-base font-semibold text-text-primary">
            {isEdit ? (isFilled ? 'Gefüllte Order — Notizen' : 'Limit-Order bearbeiten') : 'Neue Limit-Order'}
          </h3>
          <button type="button" onClick={onClose} className="text-text-muted hover:text-text-primary" aria-label="Schliessen">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {isFilled && (
            <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
              Gefüllte Order ist historisch. Nur Notizen sind editierbar.
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Ticker</label>
              <input
                type="text"
                value={form.ticker}
                onChange={(e) => update('ticker', e.target.value)}
                onBlur={(e) => update('ticker', e.target.value.trim().toUpperCase())}
                className={INPUT}
                placeholder="z.B. AAPL"
                disabled={isFilled}
                required
              />
            </div>
            <div>
              <label className={LABEL}>Side</label>
              <select
                value={form.side}
                onChange={(e) => update('side', e.target.value)}
                className={INPUT}
                disabled={isFilled}
              >
                <option value="buy">Kauf (BUY)</option>
                <option value="sell">Verkauf (SELL)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className={LABEL}>Shares</label>
              <input
                type="number"
                step="any"
                min="0"
                value={form.shares}
                onChange={(e) => update('shares', e.target.value)}
                className={INPUT}
                disabled={isFilled}
                required={!isFilled}
              />
            </div>
            <div>
              <label className={LABEL}>Limit-Preis</label>
              <input
                type="number"
                step="any"
                min="0"
                value={form.limit_price}
                onChange={(e) => update('limit_price', e.target.value)}
                className={INPUT}
                disabled={isFilled}
                required={!isFilled}
              />
            </div>
            <div>
              <label className={LABEL}>Currency</label>
              <select
                value={form.currency}
                onChange={(e) => update('currency', e.target.value)}
                className={INPUT}
                disabled={isFilled}
              >
                <option value="USD">USD</option>
                <option value="CHF">CHF</option>
                <option value="EUR">EUR</option>
                <option value="GBP">GBP</option>
                <option value="GBX">GBX</option>
                <option value="JPY">JPY</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className={LABEL}>Stop-Preis (opt.)</label>
              <input
                type="number"
                step="any"
                min="0"
                value={form.stop_price}
                onChange={(e) => update('stop_price', e.target.value)}
                className={INPUT}
                disabled={isFilled}
                placeholder="—"
              />
            </div>
            <div>
              <label className={LABEL}>Gültigkeit</label>
              <select
                value={form.expiry_type}
                onChange={(e) => {
                  const v = e.target.value
                  update('expiry_type', v)
                  if (v !== 'gtd') update('expiry_date', '')
                }}
                className={INPUT}
                disabled={isFilled}
              >
                <option value="gtc">GTC (good till cancelled)</option>
                <option value="day">Day</option>
                <option value="gtd">GTD (good till date)</option>
              </select>
            </div>
            <div>
              <label className={LABEL}>Ablaufdatum</label>
              <DateInput
                value={form.expiry_date}
                onChange={(v) => update('expiry_date', v)}
                disabled={isFilled || form.expiry_type !== 'gtd'}
                className={INPUT}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Broker (opt.)</label>
              <input
                type="text"
                value={form.broker}
                onChange={(e) => update('broker', e.target.value)}
                className={INPUT}
                placeholder="z.B. IBKR, Swissquote, Pocket"
                disabled={isFilled}
              />
            </div>
            {isEdit && !isFilled && (
              <div>
                <label className={LABEL}>Status</label>
                <select
                  value={form.status}
                  onChange={(e) => update('status', e.target.value)}
                  className={INPUT}
                >
                  <option value="open">Offen</option>
                  <option value="cancelled">Storniert</option>
                </select>
              </div>
            )}
          </div>

          <div>
            <label className={LABEL}>Notizen</label>
            <textarea
              value={form.notes}
              onChange={(e) => update('notes', e.target.value)}
              className={`${INPUT} min-h-[80px] font-sans`}
              placeholder="Optional: Begruendung, Setup, etc."
            />
          </div>

          {showBucketSelector && (
            <div>
              <label className={LABEL}>
                Ziel-Bucket <span className="text-text-muted/70 font-normal">(wird beim Fill verwendet, falls Position neu angelegt wird)</span>
              </label>
              <select
                value={form.bucket_id_target}
                onChange={(e) => update('bucket_id_target', e.target.value)}
                className={INPUT}
              >
                {buckets.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            </div>
          )}

          {error && (
            <div className="text-sm text-danger">{error}</div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-border-2 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors"
          >
            Abbrechen
          </button>
          <button
            type="submit"
            disabled={busy}
            className="bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40"
          >
            {busy ? 'Speichern...' : 'Speichern'}
          </button>
        </div>
      </form>
    </div>
  )
}
