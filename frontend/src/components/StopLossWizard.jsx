import { useState, useEffect } from 'react'
import { Shield, Loader2, Check, AlertTriangle } from 'lucide-react'
import { useToast } from './Toast'
import { authFetch } from '../hooks/useApi'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'

const ALL_METHODS = {
  structural: 'Strukturell',
  trailing_pct: 'Trailing %',
  higher_low: 'Higher Low',
  ma_based: 'MA-basiert',
}
const CORE_METHODS = ['structural', 'ma_based']
const SATELLITE_METHODS = ['trailing_pct', 'higher_low', 'ma_based']

function getMethodsForType(positionType) {
  const keys = positionType === 'core' ? CORE_METHODS : positionType === 'satellite' ? SATELLITE_METHODS : Object.keys(ALL_METHODS)
  return [{ value: '', label: '–' }, ...keys.map((k) => ({ value: k, label: ALL_METHODS[k] }))]
}

const INPUT = 'bg-body border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary'

export default function StopLossWizard({ onClose, onSaved }) {
  useScrollLock(true)
  const trapRef = useFocusTrap(true)
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({})
  const toast = useToast()

  useEffect(() => {
    const load = async () => {
      try {
        const res = await authFetch('/api/portfolio/positions-without-stoploss')
        if (res.ok) {
          const data = await res.json()
          setPositions(data)
          const initial = {}
          data.forEach((p) => {
            const defaultMethod = p.position_type === 'core' ? 'structural' : p.position_type === 'satellite' ? 'trailing_pct' : ''
            initial[p.ticker] = { price: '', method: defaultMethod, confirmed: false }
          })
          setForm(initial)
        }
      } catch { /* ignore */ }
      setLoading(false)
    }
    load()
  }, [])

  const updateField = (ticker, field, value) => {
    setForm((prev) => ({
      ...prev,
      [ticker]: { ...prev[ticker], [field]: value },
    }))
  }

  const allFilled = positions.every((p) => {
    const f = form[p.ticker]
    if (!f) return false
    // Core positions can skip stop-loss
    if (p.position_type === 'core') return true
    const val = parseFloat(f.price)
    return val > 0 && (!p.current_price || val < p.current_price)
  })

  const handleSave = async () => {
    setSaving(true)
    try {
      // Only include positions that have a stop-loss value set
      const items = positions
        .filter((p) => {
          const val = parseFloat(form[p.ticker]?.price)
          return val > 0
        })
        .map((p) => ({
          ticker: p.ticker,
          stop_loss_price: parseFloat(form[p.ticker].price),
          confirmed_at_broker: form[p.ticker].confirmed,
          method: form[p.ticker].method || null,
        }))
      const res = await authFetch('/api/portfolio/stop-loss/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Fehler beim Speichern')
      }
      toast('Stop-Loss für alle Positionen gesetzt', 'success')
      onSaved?.()
      onClose()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div className="bg-card border border-border rounded-xl shadow-2xl p-12">
          <Loader2 size={24} className="animate-spin text-primary mx-auto" />
        </div>
      </div>
    )
  }

  if (!positions.length) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Stop-Loss festlegen"
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-4xl mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-warning/15 flex items-center justify-center">
              <Shield size={20} className="text-warning" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-text-primary">Stop-Loss festlegen</h2>
              <p className="text-sm text-text-muted">
                Für folgende aktive Positionen fehlt ein Stop-Loss.
              </p>
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-text-muted bg-card-alt/30">
                <th className="text-left p-3 font-medium">Ticker</th>
                <th className="text-left p-3 font-medium">Name</th>
                <th className="text-center p-3 font-medium">Typ</th>
                <th className="text-right p-3 font-medium">Stück</th>
                <th className="text-right p-3 font-medium">Aktueller Kurs</th>
                <th className="text-center p-3 font-medium">Währung</th>
                <th className="p-3 font-medium">Stop-Loss</th>
                <th className="p-3 font-medium">Methode</th>
                <th className="text-center p-3 font-medium">Broker</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const f = form[p.ticker] || {}
                const val = parseFloat(f.price)
                const invalid = val > 0 && p.current_price && val >= p.current_price
                return (
                  <tr key={p.ticker} className="border-b border-border/50 hover:bg-card-alt/50 transition-colors">
                    <td className="p-3 font-mono text-primary font-medium">{p.ticker}</td>
                    <td className="p-3 text-text-primary">{p.name}</td>
                    <td className="p-3 text-center">
                      {p.position_type === 'core' ? (
                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-primary/15 text-primary">Core</span>
                      ) : p.position_type === 'satellite' ? (
                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-warning/15 text-warning">Satellite</span>
                      ) : (
                        <span className="text-text-muted text-xs">—</span>
                      )}
                    </td>
                    <td className="p-3 text-right text-text-secondary tabular-nums">{p.shares}</td>
                    <td className="p-3 text-right text-text-secondary tabular-nums">
                      {p.current_price != null ? p.current_price.toFixed(2) : '–'}
                    </td>
                    <td className="p-3 text-center">
                      <span className="text-xs px-2 py-0.5 rounded border bg-primary/10 text-primary border-primary/20">
                        {p.currency}
                      </span>
                    </td>
                    <td className="p-3">
                      <input
                        type="number"
                        step="any"
                        min="0"
                        aria-label={`Stop-Loss Preis ${p.ticker}`}
                        className={`${INPUT} w-28 ${invalid ? 'border-danger' : ''}`}
                        value={f.price || ''}
                        onChange={(e) => updateField(p.ticker, 'price', e.target.value)}
                        placeholder={p.position_type === 'core' ? 'Optional' : '0.00'}
                      />
                      {invalid && (
                        <p className="text-[10px] text-danger mt-0.5">Muss &lt; Kurs sein</p>
                      )}
                      {p.position_type === 'core' && !val && (
                        <p className="text-[10px] text-text-muted mt-0.5">Optional für Core</p>
                      )}
                    </td>
                    <td className="p-3">
                      <select
                        className={`${INPUT} w-28`}
                        value={f.method || ''}
                        onChange={(e) => updateField(p.ticker, 'method', e.target.value)}
                      >
                        {getMethodsForType(p.position_type).map((m) => (
                          <option key={m.value} value={m.value}>{m.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="p-3 text-center">
                      <input
                        type="checkbox"
                        aria-label={`Stop-Loss bestaetigt ${p.ticker}`}
                        checked={f.confirmed || false}
                        onChange={(e) => updateField(p.ticker, 'confirmed', e.target.checked)}
                        className="accent-success w-4 h-4"
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Type hints */}
        <div className="px-6 py-3 border-t border-border/50 space-y-1">
          <p className="text-xs text-primary">Core: Stop unter strukturellem Support (Doppelboden, Major Low). Abstand: 15–25%.</p>
          <p className="text-xs text-warning">Satellite: Taktischer Stop unter letztem Higher Low. Abstand: 5–12%.</p>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border">
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <AlertTriangle size={13} className="text-warning" />
            <span>Ohne Stop-Loss werden kritische Alerts generiert</span>
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors"
            >
              Später erledigen
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !allFilled}
              className="px-4 py-2 text-sm rounded-lg font-medium bg-primary text-white hover:bg-primary/80 transition-colors disabled:opacity-40 flex items-center gap-2"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              Alle speichern
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
