import { useState, useEffect } from 'react'
import { X, Check, Loader2 } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import { authFetch } from '../hooks/useApi'
import TickerAutocomplete from './TickerAutocomplete'
import DateInput from './DateInput'

const TYPES = ['buy', 'sell', 'dividend', 'fee_correction', 'capital_gain', 'deposit', 'withdrawal']
const TYPE_LABELS = {
  buy: 'Kauf', sell: 'Verkauf', dividend: 'Dividende', fee: 'Gebuehren',
  deposit: 'Einzahlung', withdrawal: 'Auszahlung',
  capital_gain: 'Kapitalgewinn', interest: 'Zinsertrag',
  fx_credit: 'FX Gutschrift', fx_debit: 'FX Belastung',
  fee_correction: 'Gebuehren', tax: 'Steuer', tax_refund: 'Steuererstattung',
}
const TYPE_COLORS = {
  buy: 'bg-success/15 text-success border-success/30',
  sell: 'bg-danger/15 text-danger border-danger/30',
  dividend: 'bg-primary/15 text-primary border-primary/30',
  fee: 'bg-warning/15 text-warning border-warning/30',
  deposit: 'bg-card-alt text-text-secondary border-border',
  withdrawal: 'bg-card-alt text-text-secondary border-border',
  capital_gain: 'bg-success/15 text-success border-success/30',
  interest: 'bg-primary/15 text-primary border-primary/30',
  fx_credit: 'bg-text-muted/15 text-text-muted border-text-muted/30',
  fx_debit: 'bg-text-muted/15 text-text-muted border-text-muted/30',
  fee_correction: 'bg-warning/15 text-warning border-warning/30',
  tax: 'bg-warning/15 text-warning border-warning/30',
  tax_refund: 'bg-success/15 text-success border-success/30',
}

const INPUT = 'bg-card border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

export default function TransactionCreateModal({ positions, initial, onSave, onClose }) {
  const isEdit = !!initial
  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  // Selected ticker item from autocomplete (null = nothing selected yet)
  const [selectedItem, setSelectedItem] = useState(
    isEdit && initial?.position_id
      ? { ticker: initial.ticker || '', name: initial.position_name || '', position_id: initial.position_id, is_existing: true }
      : null
  )

  const [form, setForm] = useState({
    type: initial?.type || 'buy',
    date: initial?.date || new Date().toISOString().slice(0, 10),
    shares: initial?.shares?.toString() || '',
    price_per_share: initial?.price_per_share?.toString() || '',
    currency: initial?.currency || 'CHF',
    fx_rate_to_chf: initial?.fx_rate_to_chf?.toString() || '1',
    fees_chf: initial?.fees_chf?.toString() || '0',
    total_chf: initial?.total_chf?.toString() || '',
    notes: initial?.notes || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [fxLoading, setFxLoading] = useState(false)

  // Auto-fill currency when selecting a position/ticker
  useEffect(() => {
    if (selectedItem?.currency && !isEdit) {
      setForm((f) => ({ ...f, currency: selectedItem.currency }))
    }
  }, [selectedItem, isEdit])

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

  // Auto-calculate total CHF
  useEffect(() => {
    const shares = parseFloat(form.shares) || 0
    const price = parseFloat(form.price_per_share) || 0
    const fx = parseFloat(form.fx_rate_to_chf) || 1
    if (shares > 0 && price > 0) {
      setForm((f) => ({ ...f, total_chf: (shares * price * fx).toFixed(2) }))
    }
  }, [form.shares, form.price_per_share, form.fx_rate_to_chf])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!selectedItem) return
    setSaving(true)
    setError(null)
    try {
      const payload = {
        ...form,
        shares: parseFloat(form.shares) || 0,
        price_per_share: parseFloat(form.price_per_share) || 0,
        fx_rate_to_chf: parseFloat(form.fx_rate_to_chf) || 1,
        fees_chf: parseFloat(form.fees_chf) || 0,
        total_chf: parseFloat(form.total_chf) || 0,
      }
      if (selectedItem.is_existing && selectedItem.position_id) {
        payload.position_id = selectedItem.position_id
      } else {
        payload.ticker = selectedItem.ticker
        payload.asset_type = selectedItem.type || 'stock'
      }
      await onSave(payload)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-body/80 backdrop-blur-sm" onClick={onClose}>
      <div ref={trapRef} role="dialog" aria-modal="true" aria-label={isEdit ? 'Transaktion bearbeiten' : 'Neue Transaktion'} className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-xl mx-4" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h3 className="text-lg font-bold text-text-primary">
            {isEdit ? 'Transaktion bearbeiten' : 'Neue Transaktion'}
          </h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Row 1: Ticker Autocomplete + Type */}
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2 sm:col-span-1">
              <TickerAutocomplete
                positions={positions}
                value={selectedItem}
                onChange={setSelectedItem}
                disabled={isEdit}
              />
              {selectedItem && !selectedItem.is_existing && (
                <p className="text-[11px] text-primary mt-1">Neue Position wird automatisch erstellt</p>
              )}
            </div>
            <div>
              <label className={LABEL}>Typ *</label>
              <div className="flex gap-1 flex-wrap">
                {TYPES.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setForm({ ...form, type: t })}
                    className={`px-2 py-1 rounded text-[11px] font-semibold border transition-colors ${
                      form.type === t ? TYPE_COLORS[t] : 'border-border text-text-muted hover:text-text-primary'
                    }`}
                  >
                    {TYPE_LABELS[t]}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Row 2: Date + Shares + Price */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="txnpage-date" className={LABEL}>Datum *</label>
              <DateInput
                id="txnpage-date"
                value={form.date}
                onChange={(v) => setForm({ ...form, date: v })}
                className={`${INPUT} w-full`}
                required
              />
            </div>
            <div>
              <label htmlFor="txnpage-shares" className={LABEL}>Anzahl</label>
              <input
                id="txnpage-shares"
                type="number"
                step="any"
                min="0"
                value={form.shares}
                onChange={(e) => setForm({ ...form, shares: e.target.value })}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
            <div>
              <label htmlFor="txnpage-price" className={LABEL}>Preis/Stueck</label>
              <input
                id="txnpage-price"
                type="number"
                step="any"
                min="0"
                value={form.price_per_share}
                onChange={(e) => setForm({ ...form, price_per_share: e.target.value })}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
          </div>

          {/* Row 3: Currency + FX + Fees + Total */}
          <div className="grid grid-cols-4 gap-4">
            <div>
              <label htmlFor="txnpage-ccy" className={LABEL}>Waehrung</label>
              <select
                id="txnpage-ccy"
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className={`${INPUT} w-full`}
              >
                {['CHF', 'USD', 'EUR', 'GBP', 'CAD', 'GBX'].map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="txnpage-fx" className={LABEL}>
                FX → CHF {fxLoading && <Loader2 size={10} className="inline animate-spin ml-1" />}
              </label>
              <input
                id="txnpage-fx"
                type="number"
                step="any"
                value={form.fx_rate_to_chf}
                onChange={(e) => setForm({ ...form, fx_rate_to_chf: e.target.value })}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
            <div>
              <label htmlFor="txnpage-fees" className={LABEL}>Gebuehren CHF</label>
              <input
                id="txnpage-fees"
                type="number"
                step="any"
                min="0"
                value={form.fees_chf}
                onChange={(e) => setForm({ ...form, fees_chf: e.target.value })}
                className={`${INPUT} w-full tabular-nums`}
              />
            </div>
            <div>
              <label htmlFor="txnpage-total" className={LABEL}>Total CHF</label>
              <input
                id="txnpage-total"
                type="number"
                step="any"
                value={form.total_chf}
                onChange={(e) => setForm({ ...form, total_chf: e.target.value })}
                className={`${INPUT} w-full font-medium`}
              />
            </div>
          </div>

          {/* Row 4: Notes */}
          <div>
            <label htmlFor="txnpage-notes" className={LABEL}>Notizen</label>
            <input
              id="txnpage-notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Optional"
              className={`${INPUT} w-full`}
            />
          </div>

          {/* Error */}
          {error && (
            <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors">
              Abbrechen
            </button>
            <button
              type="submit"
              disabled={saving || !selectedItem || !form.date}
              className="flex items-center gap-2 bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {isEdit ? 'Speichern' : 'Erstellen'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
