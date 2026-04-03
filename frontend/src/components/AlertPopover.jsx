import { useState, useEffect, useRef } from 'react'
import { useApi, apiPost, apiDelete } from '../hooks/useApi'
import { formatCHFExact } from '../lib/format'
import { Bell, Trash2, Check, X } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'
import { useToast } from './Toast'

const ALERT_TYPES = [
  { value: 'price_above', label: 'Kurs über' },
  { value: 'price_below', label: 'Kurs unter' },
  { value: 'pct_change_day', label: 'Tagesveränderung %' },
]


export default function AlertPopover({ ticker, currency, resistance, onClose }) {
  const { data: alerts, refetch } = useApi(`/price-alerts?ticker=${ticker}`)
  const [alertType, setAlertType] = useState('price_above')
  const [targetValue, setTargetValue] = useState(resistance ? String(resistance) : '')
  const [note, setNote] = useState('')
  const [notifyInApp, setNotifyInApp] = useState(true)
  const [notifyEmail, setNotifyEmail] = useState(false)
  const [creating, setCreating] = useState(false)
  const popRef = useRef()
  const trapRef = useFocusTrap(true)
  const toast = useToast()
  useEscClose(onClose)

  useEffect(() => {
    const handleClick = (e) => {
      if (popRef.current && !popRef.current.contains(e.target)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [onClose])

  const handleCreate = async () => {
    if (!targetValue) return
    setCreating(true)
    try {
      const body = {
        ticker,
        alert_type: alertType,
        target_value: parseFloat(targetValue),
        currency: alertType !== 'pct_change_day' ? currency : null,
        notify_in_app: notifyInApp,
        notify_email: notifyEmail,
        note: note || null,
      }
      await apiPost('/price-alerts', body)
      setTargetValue('')
      setNote('')
      refetch()
    } catch (err) {
      toast('Alarm konnte nicht erstellt werden: ' + (err.message || 'Unbekannter Fehler'), 'error')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id) => {
    try {
      await apiDelete(`/price-alerts/${id}`)
      refetch()
    } catch (err) {
      toast('Alarm konnte nicht geloescht werden: ' + (err.message || 'Unbekannter Fehler'), 'error')
    }
  }

  const activeAlerts = (alerts || []).filter((a) => a.is_active)
  const triggeredAlerts = (alerts || []).filter((a) => a.is_triggered)

  return (
    <div
      ref={(el) => { popRef.current = el; trapRef.current = el }}
      role="dialog"
      aria-modal="true"
      aria-label={`Preis-Alarm für ${ticker}`}
      className="absolute z-50 right-0 mt-1 w-80 bg-card border border-border rounded-lg shadow-xl"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="p-3 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-1.5">
            <Bell size={14} /> Preis-Alarm für {ticker}
          </h4>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary" aria-label="Schliessen">
            <X size={14} />
          </button>
        </div>

        {/* Alert type */}
        <div className="flex gap-1 mb-2">
          {ALERT_TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => setAlertType(t.value)}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                alertType === t.value
                  ? 'bg-primary text-white'
                  : 'bg-card-alt text-text-muted hover:text-text-primary'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Target value */}
        <div className="flex gap-2 mb-2">
          <label htmlFor="alert-target" className="sr-only">Zielwert</label>
          <input
            id="alert-target"
            type="number"
            step="any"
            value={targetValue}
            onChange={(e) => setTargetValue(e.target.value)}
            placeholder={alertType === 'pct_change_day' ? 'z.B. 5' : 'Zielpreis'}
            className="flex-1 bg-card border border-border rounded px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 tabular-nums"
          />
          <span className="text-xs text-text-secondary self-center">
            {alertType === 'pct_change_day' ? '%' : currency || 'CHF'}
          </span>
        </div>

        {/* Note */}
        <label htmlFor="alert-note" className="sr-only">Notiz</label>
        <input
          id="alert-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Notiz (optional)"
          className="w-full bg-card border border-border rounded px-2 py-1.5 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 mb-2"
        />

        {/* Notifications */}
        <div className="flex items-center gap-3 mb-2 text-xs">
          <label className="flex items-center gap-1 text-text-secondary cursor-pointer">
            <input type="checkbox" checked={notifyInApp} onChange={(e) => setNotifyInApp(e.target.checked)} className="rounded" />
            In-App
          </label>
          <label className="flex items-center gap-1 text-text-secondary cursor-pointer">
            <input type="checkbox" checked={notifyEmail} onChange={(e) => setNotifyEmail(e.target.checked)} className="rounded" />
            E-Mail
          </label>
        </div>

        <button
          onClick={handleCreate}
          disabled={!targetValue || creating}
          className="w-full bg-primary text-white text-sm py-1.5 rounded hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {creating ? 'Erstelle...' : 'Alarm erstellen'}
        </button>
      </div>

      {/* Existing alerts */}
      {(activeAlerts.length > 0 || triggeredAlerts.length > 0) && (
        <div className="p-3 space-y-1.5 max-h-48 overflow-y-auto">
          {activeAlerts.map((a) => (
            <div key={a.id} className="flex items-center justify-between text-xs">
              <span className="text-text-secondary">
                {a.alert_type === 'price_above' ? '↑' : a.alert_type === 'price_below' ? '↓' : '↕'}{' '}
                {a.alert_type === 'pct_change_day' ? `${a.target_value}%` : `${a.currency || ''} ${a.target_value}`}
                {a.note && <span className="text-text-muted ml-1">({a.note})</span>}
              </span>
              <button onClick={() => handleDelete(a.id)} className="text-text-muted hover:text-danger p-0.5" aria-label="Alarm löschen">
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          {triggeredAlerts.map((a) => (
            <div key={a.id} className="flex items-center justify-between text-xs opacity-60">
              <span className="text-success flex items-center gap-1">
                <Check size={10} />
                {a.alert_type === 'pct_change_day' ? `${a.target_value}%` : `${a.currency || ''} ${a.target_value}`}
                <span className="text-text-muted">@ {a.trigger_price}</span>
              </span>
              <button onClick={() => handleDelete(a.id)} className="text-text-muted hover:text-danger p-0.5" aria-label="Alarm löschen">
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
