import { useState, useEffect, useMemo } from 'react'
import { X, Check, Loader2, Shield, ClipboardCheck } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import { apiPost, apiPut } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import DateInput from './DateInput'

const CORE_CHECKLIST = [
  { id: 'trend', label: 'Kurs über 150-DMA (Investor Line)' },
  { id: 'fundamental', label: 'Fundamentale Qualität geprüft (Umsatz, Gewinn, Margen)' },
  { id: 'moat', label: 'Wettbewerbsvorteil / Burggraben vorhanden' },
  { id: 'valuation', label: 'Bewertung akzeptabel (KGV, KUV, DCF)' },
  { id: 'sector', label: 'Sektor-Limit geprüft (max. 25%)' },
  { id: 'position_size', label: 'Positionsgrösse passt (max. 10%)' },
  { id: 'stop', label: 'Stop-Loss unter strukturellem Support gesetzt' },
]

const SATELLITE_CHECKLIST = [
  // Makro-Gate
  { id: 'macro', label: 'Makro-Gate bestanden (S&P 500 über 150-DMA, VIX < 20)' },
  // Säule 1: Breakout
  { id: 'breakout', label: 'Breakout über Widerstand (mind. 3× getestet)' },
  { id: 'no_earnings', label: 'Keine Earnings in den nächsten 7 Tagen' },
  // Säule 2: Moving Averages
  { id: 'ma50', label: 'Kurs über 50-DMA, 50-DMA steigend' },
  { id: 'ma150', label: 'Kurs über 150-DMA (Schwur 1)' },
  // Säule 3: Volumen
  { id: 'volume', label: 'Breakout-Volumen ≥ 2× Durchschnitt' },
  // Säule 4: Relative Stärke
  { id: 'rs', label: 'Mansfield RS steigend, nahe/über Nulllinie' },
  // Fundamental
  { id: 'fundamental', label: 'Umsatz wächst, Marge stabil, D/E < 1.0' },
  // Risikomanagement
  { id: 'position_size', label: 'Positionsgrösse nach 2%-Regel (max. 3–5%)' },
  { id: 'stop', label: 'Trailing Stop unter letztem Higher Low gesetzt' },
]

const CORE_STOP_METHODS = [
  { value: 'structural', label: 'Strukturell (Doppelboden)' },
  { value: 'ma_based', label: 'MA-basiert (150-DMA)' },
]
const SATELLITE_STOP_METHODS = [
  { value: 'trailing_pct', label: 'Trailing %' },
  { value: 'higher_low', label: 'Higher Low' },
  { value: 'ma_based', label: 'MA-basiert (50-DMA)' },
]

export default function TransactionModal({ position, type: initialType, onClose, onSaved }) {
  useScrollLock(true)
  const today = new Date().toISOString().slice(0, 10)

  const [form, setForm] = useState({
    type: initialType || 'buy',
    date: today,
    shares: '',
    price_per_share: '',
    fx_rate_to_chf: 1.0,
    fees_chf: '',
    taxes_chf: '',
    stop_loss_price: '',
    stop_loss_method: '',
    stop_loss_confirmed: false,
    position_type: '',  // 'core' or 'satellite'
  })
  const [checklist, setChecklist] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (position?.current_price != null) {
      setForm((f) => ({ ...f, price_per_share: position.current_price }))
    }
  }, [position])

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }))

  const subtotal = useMemo(() => {
    const shares = parseFloat(form.shares) || 0
    const price = parseFloat(form.price_per_share) || 0
    const fx = parseFloat(form.fx_rate_to_chf) || 1
    return shares * price * fx
  }, [form.shares, form.price_per_share, form.fx_rate_to_chf])

  const fees = parseFloat(form.fees_chf) || 0
  const taxes = parseFloat(form.taxes_chf) || 0
  const totalChf = subtotal + fees + taxes

  useEscClose(onClose)

  if (!position) return null

  const isSell = form.type === 'sell'
  const maxShares = position.shares || 0

  const handleSave = async () => {
    const shares = parseFloat(form.shares)
    if (!shares || shares <= 0) {
      setError('Bitte Anzahl eingeben')
      return
    }
    if (isSell && shares > maxShares) {
      setError(`Max. ${maxShares} verfügbar`)
      return
    }
    const price = parseFloat(form.price_per_share)
    if (!price || price <= 0) {
      setError('Bitte Preis eingeben')
      return
    }

    // Stop-loss validation for buy
    const isBuy = form.type === 'buy'
    const slPrice = parseFloat(form.stop_loss_price)
    const isSatellite = form.position_type === 'satellite'
    const isCore = form.position_type === 'core'
    if (isBuy && isSatellite && (!slPrice || slPrice <= 0)) {
      setError('Stop-Loss ist Pflicht für Satellite. Regel: Immer gleichzeitig mit dem Kauf setzen.')
      return
    }
    if (isBuy && slPrice > 0 && slPrice >= price) {
      setError('Stop-Loss muss unter dem Kaufkurs liegen')
      return
    }
    if (isBuy && !form.position_type) {
      setError('Bitte Positions-Typ wählen (Core oder Satellite)')
      return
    }
    // Checklist validation
    if (isBuy && form.position_type) {
      const items = form.position_type === 'core' ? CORE_CHECKLIST : SATELLITE_CHECKLIST
      const allChecked = items.every((item) => checklist[item.id])
      if (!allChecked) {
        setError('Bitte alle Punkte der Kauf-Checkliste bestätigen')
        return
      }
    }

    setSaving(true)
    setError(null)
    try {
      const payload = {
        position_id: position.id,
        type: form.type,
        date: form.date,
        shares,
        price_per_share: price,
        currency: position.price_currency || position.currency,
        fx_rate_to_chf: parseFloat(form.fx_rate_to_chf) || 1,
        fees_chf: fees,
        taxes_chf: taxes,
        total_chf: Math.round(totalChf * 100) / 100,
      }
      if (isBuy && slPrice > 0) {
        payload.stop_loss_price = slPrice
        payload.stop_loss_method = form.stop_loss_method || null
        payload.stop_loss_confirmed_at_broker = form.stop_loss_confirmed
      }
      if (isBuy && form.position_type) {
        payload.position_type = form.position_type
      }
      await apiPost('/transactions', payload)
      // Update position_type if set
      if (isBuy && form.position_type) {
        try {
          await apiPut(`/portfolio/positions/${position.id}`, { position_type: form.position_type })
        } catch {} // Best effort
      }
      onSaved?.()
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const inputClass = 'w-full bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isSell ? 'Verkaufen' : 'Kaufen'}
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h2 className="text-lg font-bold text-text-primary">
              {isSell ? 'Verkaufen' : 'Kaufen'}
            </h2>
            <span className="text-sm text-text-muted">
              {position.name} <span className="font-mono text-primary">({position.ticker})</span>
            </span>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <div className="p-6 space-y-4 overflow-y-auto">
          {/* Type Toggle */}
          <div role="radiogroup" aria-label="Transaktionstyp" className="flex rounded-lg border border-border overflow-hidden">
            <button
              role="radio"
              aria-checked={form.type === 'buy'}
              onClick={() => set('type', 'buy')}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${
                form.type === 'buy'
                  ? 'bg-success/20 text-success border-r border-border'
                  : 'text-text-muted hover:text-text-primary border-r border-border'
              }`}
            >
              Kaufen
            </button>
            <button
              role="radio"
              aria-checked={form.type === 'sell'}
              onClick={() => set('type', 'sell')}
              className={`flex-1 py-2 text-sm font-medium transition-colors ${
                form.type === 'sell'
                  ? 'bg-warning/20 text-warning'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Verkaufen
            </button>
          </div>

          {/* Position Type (Buy only) */}
          {form.type === 'buy' && (
            <div>
              <label className="block text-xs text-text-muted mb-1.5">Positions-Typ</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => { set('position_type', 'core'); set('stop_loss_method', 'structural'); setChecklist({}) }}
                  className={`flex-1 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                    form.position_type === 'core'
                      ? 'bg-primary text-white border-primary'
                      : 'border-border text-text-muted hover:border-primary hover:text-primary'
                  }`}
                >
                  Core
                </button>
                <button
                  type="button"
                  onClick={() => { set('position_type', 'satellite'); set('stop_loss_method', 'trailing_pct'); setChecklist({}) }}
                  className={`flex-1 py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                    form.position_type === 'satellite'
                      ? 'bg-warning text-white border-warning'
                      : 'border-border text-text-muted hover:border-warning hover:text-warning'
                  }`}
                >
                  Satellite
                </button>
              </div>
            </div>
          )}

          {/* Purchase Checklist (Buy only, after type selected) */}
          {form.type === 'buy' && form.position_type && (() => {
            const items = form.position_type === 'core' ? CORE_CHECKLIST : SATELLITE_CHECKLIST
            const checkedCount = items.filter((item) => checklist[item.id]).length
            const allDone = checkedCount === items.length
            return (
              <div className={`rounded-lg border p-4 space-y-2 ${allDone ? 'border-success/30 bg-success/5' : 'border-border bg-card-alt/30'}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-medium text-text-secondary">
                    <ClipboardCheck size={14} className={allDone ? 'text-success' : 'text-text-muted'} />
                    Kauf-Checkliste ({form.position_type === 'core' ? 'Core' : 'Satellite'})
                  </div>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${allDone ? 'bg-success/15 text-success' : 'bg-card-alt text-text-muted'}`}>
                    {checkedCount}/{items.length}
                  </span>
                </div>
                {items.map((item) => (
                  <label key={item.id} className="flex items-start gap-2 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={checklist[item.id] || false}
                      onChange={(e) => setChecklist((prev) => ({ ...prev, [item.id]: e.target.checked }))}
                      className="accent-success w-3.5 h-3.5 mt-0.5 shrink-0"
                    />
                    <span className={`text-xs leading-relaxed ${checklist[item.id] ? 'text-text-secondary line-through opacity-60' : 'text-text-primary'}`}>
                      {item.label}
                    </span>
                  </label>
                ))}
              </div>
            )
          })()}

          {/* Date */}
          <div>
            <label htmlFor="txn-date" className="block text-xs text-text-muted mb-1.5">Datum</label>
            <DateInput
              id="txn-date"
              className={inputClass}
              value={form.date}
              onChange={(v) => set('date', v)}
            />
          </div>

          {/* Shares */}
          <div>
            <label htmlFor="txn-shares" className="block text-xs text-text-muted mb-1.5">
              Anzahl
              {isSell && <span className="ml-1 text-warning">(max. {maxShares})</span>}
            </label>
            <input
              id="txn-shares"
              type="number"
              step="any"
              min="0"
              max={isSell ? maxShares : undefined}
              className={inputClass}
              value={form.shares}
              onChange={(e) => set('shares', e.target.value)}
              placeholder="0"
              autoFocus
            />
          </div>

          {/* Price */}
          <div>
            <label htmlFor="txn-price" className="block text-xs text-text-muted mb-1.5">
              Preis pro Einheit ({position.price_currency || position.currency})
            </label>
            <input
              id="txn-price"
              type="number"
              step="any"
              min="0"
              className={inputClass}
              value={form.price_per_share}
              onChange={(e) => set('price_per_share', e.target.value)}
            />
          </div>

          {/* FX Rate */}
          <div>
            <label htmlFor="txn-fx-rate" className="block text-xs text-text-muted mb-1.5">FX-Kurs zu CHF</label>
            <input
              id="txn-fx-rate"
              type="number"
              step="any"
              min="0"
              className={inputClass}
              value={form.fx_rate_to_chf}
              onChange={(e) => set('fx_rate_to_chf', e.target.value)}
            />
          </div>

          {/* Fees & Taxes */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="txn-fees" className="block text-xs text-text-muted mb-1.5">Gebühren CHF</label>
              <input
                id="txn-fees"
                type="number"
                step="any"
                min="0"
                className={inputClass}
                value={form.fees_chf}
                onChange={(e) => set('fees_chf', e.target.value)}
                placeholder="0"
              />
            </div>
            <div>
              <label htmlFor="txn-taxes" className="block text-xs text-text-muted mb-1.5">Steuern CHF</label>
              <input
                id="txn-taxes"
                type="number"
                step="any"
                min="0"
                className={inputClass}
                value={form.taxes_chf}
                onChange={(e) => set('taxes_chf', e.target.value)}
                placeholder="0"
              />
            </div>
          </div>

          {/* Stop-Loss (Buy only) */}
          {form.type === 'buy' && (
            <div className={`rounded-lg border p-4 space-y-3 ${form.position_type === 'core' ? 'border-border bg-card-alt/30' : 'border-warning/30 bg-warning/5'}`}>
              <div className={`flex items-center gap-2 text-xs font-medium ${form.position_type === 'core' ? 'text-text-secondary' : 'text-warning'}`}>
                <Shield size={14} />
                {form.position_type === 'core' ? 'Stop-Loss (Optional für Core)' : 'Stop-Loss (Pflicht für Satellite)'}
              </div>
              <div>
                <label htmlFor="txn-stop-loss" className="block text-xs text-text-muted mb-1.5">
                  Stop-Loss Kurs ({position.price_currency || position.currency})
                </label>
                <input
                  id="txn-stop-loss"
                  type="number"
                  step="any"
                  min="0"
                  className={inputClass}
                  value={form.stop_loss_price}
                  onChange={(e) => set('stop_loss_price', e.target.value)}
                  placeholder="0.00"
                />
              </div>
              <div>
                <label htmlFor="txn-stop-method" className="block text-xs text-text-muted mb-1.5">Methode</label>
                <select
                  id="txn-stop-method"
                  className={inputClass}
                  value={form.stop_loss_method}
                  onChange={(e) => set('stop_loss_method', e.target.value)}
                >
                  <option value="">Keine Angabe</option>
                  {(form.position_type === 'core' ? CORE_STOP_METHODS : SATELLITE_STOP_METHODS).map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.stop_loss_confirmed}
                  onChange={(e) => set('stop_loss_confirmed', e.target.checked)}
                  className="accent-success w-4 h-4"
                />
                <span className="text-sm text-text-secondary">Stop-Loss bei Broker gesetzt</span>
              </label>
              {form.position_type === 'core' && (
                <p className="text-xs text-text-muted bg-primary/5 rounded p-2">
                  Core-Stop unter strukturellem Support setzen (Doppelboden, Major Low). Typischer Abstand: 15–25%.
                </p>
              )}
              {form.position_type === 'satellite' && (
                <p className="text-xs text-text-muted bg-warning/5 rounded p-2">
                  Taktischer Stop unter das letzte Higher Low. Typischer Abstand: 5–12%.
                </p>
              )}
            </div>
          )}

          {/* Totals */}
          <div className="rounded-lg bg-card-alt border border-border px-4 py-3 space-y-1">
            <div className="flex items-center justify-between text-xs text-text-muted">
              <span>Subtotal</span>
              <span className="tabular-nums">{formatCHF(subtotal)}</span>
            </div>
            {fees > 0 && (
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>+ Gebühren</span>
                <span className="tabular-nums">{formatCHF(fees)}</span>
              </div>
            )}
            {taxes > 0 && (
              <div className="flex items-center justify-between text-xs text-text-muted">
                <span>+ Steuern</span>
                <span className="tabular-nums">{formatCHF(taxes)}</span>
              </div>
            )}
            <div className="flex items-center justify-between pt-1 border-t border-border/50">
              <span className="text-sm text-text-secondary font-medium">Netto-Total CHF</span>
              <span className="text-lg font-bold text-text-primary tabular-nums">
                {formatCHF(totalChf)}
              </span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border">
          <div>
            {error && <span role="alert" className="text-danger text-sm">{error}</span>}
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors"
            >
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className={`px-4 py-2 text-sm rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2 ${
                isSell
                  ? 'bg-warning text-black hover:bg-warning/90'
                  : 'bg-success text-black hover:bg-success/90'
              }`}
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {isSell ? 'Verkaufen' : 'Kaufen'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
