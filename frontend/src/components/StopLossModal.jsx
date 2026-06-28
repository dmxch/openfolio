import { useState } from 'react'
import { X, Shield, Loader2, Check, AlertTriangle } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import { apiPatch } from '../hooks/useApi'
import { useToast } from './Toast'
import { notifyAlertsChanged } from './AlertsBanner'

const METHODS = [
  { value: '', label: 'Keine Angabe' },
  { value: 'structural', label: 'Strukturell (Doppelboden)' },
  { value: 'trailing_pct', label: 'Trailing %' },
  { value: 'higher_low', label: 'Higher Low' },
  { value: 'ma_based', label: 'MA-basiert' },
]

export default function StopLossModal({ position, onClose, onSaved }) {
  const currentStop = position.stop_loss_price
  const [price, setPrice] = useState(currentStop ?? '')
  const [method, setMethod] = useState(position.stop_loss_method || '')
  const [confirmed, setConfirmed] = useState(position.stop_loss_confirmed_at_broker || false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const toast = useToast()

  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  const currency = position.price_currency || position.currency
  const currentPrice = position.current_price

  // Phase 3 (v0.40): Pflicht-Logik kommt vom Backend (alert_service via
  // Bucket-Rules). Frontend zeigt nur den Validation-Error wenn Backend
  // 422 zurückgibt.

  const handleSave = async () => {
    const sl = parseFloat(price)
    if (!sl || sl <= 0) {
      setError('Stop-Loss muss grösser als 0 sein')
      return
    }
    if (currentPrice && sl >= currentPrice) {
      setError('Stop-Loss muss unter dem aktuellen Kurs liegen')
      return
    }

    setSaving(true)
    setError(null)
    try {
      const result = await apiPatch(`/portfolio/positions/${position.id}/stop-loss`, {
        stop_loss_price: sl,
        confirmed_at_broker: confirmed,
        method: method || null,
      })
      if (result.warning) {
        toast(result.warning, 'warning')
      }
      notifyAlertsChanged()
      onSaved?.()
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async () => {
    setSaving(true)
    setError(null)
    try {
      await apiPatch(`/portfolio/positions/${position.id}/stop-loss`, {
        stop_loss_price: 0,
        confirmed_at_broker: false,
        method: null,
      })
      toast('Stop-Loss entfernt', 'success')
      notifyAlertsChanged()
      onSaved?.()
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const distancePct = currentPrice && parseFloat(price) > 0
    ? (((currentPrice - parseFloat(price)) / currentPrice) * 100).toFixed(1)
    : null

  const inputClass = 'w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
  const labelClass = 'block text-xs font-medium text-text-secondary mb-1.5'

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4" role="presentation" onClick={onClose}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Stop-Loss anpassen"
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl w-full max-w-sm flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <div>
            <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Shield size={16} className="text-warning" />
              Stop-Loss
            </h2>
            <span className="text-xs text-text-muted">
              {position.name} <span className="font-mono text-primary">({position.ticker})</span>
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-[30px] h-[30px] rounded-lg bg-border-row border border-border-hover flex items-center justify-center text-text-muted hover:text-text-primary transition-colors shrink-0"
            aria-label="Schliessen"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {currentPrice && (
            <div className="flex items-center justify-between text-xs text-text-secondary">
              <span>Aktueller Kurs</span>
              <span className="font-mono text-text-primary">{currency} {currentPrice.toFixed(2)}</span>
            </div>
          )}

          {currentStop != null && (
            <div className="flex items-center justify-between text-xs text-text-secondary">
              <span>Aktueller Stop</span>
              <span className="font-mono text-text-secondary">{currency} {currentStop.toFixed(2)}</span>
            </div>
          )}

          {/* Stop-Loss Price */}
          <div>
            <label htmlFor="sl-price" className={labelClass}>
              {currentStop != null ? 'Neuer Stop-Loss' : 'Stop-Loss Kurs'} ({currency})
            </label>
            <input
              id="sl-price"
              type="number"
              step="any"
              min="0"
              className={inputClass}
              value={price}
              onChange={(e) => { setPrice(e.target.value); setError(null) }}
              placeholder="0.00"
              autoFocus
            />
            {distancePct && parseFloat(price) > 0 && parseFloat(price) < currentPrice && (
              <p className="text-xs text-text-secondary mt-1">
                Abstand: <span className="text-warning font-medium">-{distancePct}%</span> vom aktuellen Kurs
              </p>
            )}
          </div>

          {/* Method */}
          <div>
            <label htmlFor="sl-method" className={labelClass}>Methode</label>
            <select
              id="sl-method"
              className={inputClass}
              value={method}
              onChange={(e) => setMethod(e.target.value)}
            >
              {METHODS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          {/* Confirmed */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="accent-success w-4 h-4"
            />
            <span className="text-sm text-text-secondary">Bei Broker gesetzt</span>
          </label>

          <p className="text-xs text-text-secondary">
            Ob ein Stop-Loss Pflicht ist, hängt vom Bucket der Position ab —
            Buy-and-hold-Buckets brauchen keinen technischen Stop.
          </p>

          {currentStop != null && parseFloat(price) > 0 && parseFloat(price) < currentStop && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-danger/10 border border-danger/20">
              <AlertTriangle size={14} className="text-danger mt-0.5 shrink-0" />
              <div className="text-xs text-danger">
                <p className="font-medium">Ein Trailing Stop darf nur nach oben verschoben werden.</p>
                <p className="text-text-secondary mt-0.5">Nach einem Nachkauf darf der Stop tiefer gesetzt werden.</p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-border-2">
          <div>
            {error && <span role="alert" className="text-danger text-sm">{error}</span>}
            {!error && currentStop != null && (
              <button
                onClick={handleRemove}
                disabled={saving}
                className="text-xs text-text-secondary underline hover:text-danger transition-colors disabled:opacity-50"
                title="Backend lehnt Entfernung ab wenn Bucket-Rules es nicht erlauben"
              >
                Stop-Loss entfernen
              </button>
            )}
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg bg-surface border border-border text-text-secondary hover:border-border-hover transition-colors"
            >
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-sm rounded-lg font-medium bg-warning text-black hover:bg-warning/90 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Speichern
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
