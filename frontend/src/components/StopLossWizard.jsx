import { useState, useEffect } from 'react'
import { Shield, Loader2, Check, AlertTriangle, X } from 'lucide-react'
import { useToast } from './Toast'
import { authFetch } from '../hooks/useApi'
import { notifyAlertsChanged } from './AlertsBanner'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import useEscClose from '../hooks/useEscClose'

const ALL_METHODS = {
  structural: 'Strukturell',
  trailing_pct: 'Trailing %',
  higher_low: 'Higher Low',
  ma_based: 'MA-basiert',
}

// Phase 3 (v0.40): keine position_type-Filterung mehr — alle Methoden
// stehen unabhängig vom Bucket zur Auswahl.
function getMethods() {
  return [{ value: '', label: '–' }, ...Object.entries(ALL_METHODS).map(([k, v]) => ({ value: k, label: v }))]
}

const INPUT = 'bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'

export default function StopLossWizard({ onClose, onSaved }) {
  useScrollLock(true)
  useEscClose(onClose)
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
            initial[p.ticker] = { price: '', method: '', confirmed: false }
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
    // Phase 3: alle Positionen können optional bleiben — Backend
    // weist Stop-Pflicht via 422 zurück wenn Bucket-Rules es erfordern.
    const val = parseFloat(f.price)
    return val === 0 || isNaN(val) || (val > 0 && (!p.current_price || val < p.current_price))
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
      notifyAlertsChanged()
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
      <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4">
        <div className="bg-modal border border-border-hover rounded-[14px] shadow-2xl p-12">
          <Loader2 size={24} className="animate-spin text-primary mx-auto" />
        </div>
      </div>
    )
  }

  if (!positions.length) return null

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4">
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Stop-Loss festlegen"
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-warning/15 flex items-center justify-center">
              <Shield size={18} className="text-warning" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-text-primary">Stop-Loss festlegen</h2>
              <p className="text-xs text-text-muted">
                Für folgende aktive Positionen fehlt ein Stop-Loss.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-[30px] h-[30px] rounded-lg bg-border-row border border-border-hover flex items-center justify-center text-text-muted hover:text-text-primary transition-colors shrink-0"
            aria-label="Schliessen"
          >
            <X size={16} />
          </button>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-table-head border-b border-border-2 text-text-faint font-mono text-[10px] uppercase tracking-[0.05em]">
                <th className="text-left p-3 font-medium">Ticker</th>
                <th className="text-left p-3 font-medium">Name</th>
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
                  <tr key={p.ticker} className="border-b border-border-row hover:bg-hover transition-colors">
                    <td className="p-3 font-mono text-primary font-medium">{p.ticker}</td>
                    <td className="p-3 text-text-primary">{p.name}</td>
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
                        placeholder="Optional"
                      />
                      {invalid && (
                        <p className="text-[10px] text-danger mt-0.5">Muss &lt; Kurs sein</p>
                      )}
                    </td>
                    <td className="p-3">
                      <select
                        className={`${INPUT} w-28`}
                        value={f.method || ''}
                        onChange={(e) => updateField(p.ticker, 'method', e.target.value)}
                      >
                        {getMethods().map((m) => (
                          <option key={m.value} value={m.value}>{m.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="p-3 text-center">
                      <input
                        type="checkbox"
                        aria-label={`Stop-Loss bestätigt ${p.ticker}`}
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

        {/* Hint */}
        <div className="px-5 py-3 border-t border-border-2 space-y-1">
          <p className="text-xs text-text-secondary">
            Stop-Loss-Pflicht hängt vom Bucket der Position ab. Backend lehnt das Speichern
            ohne Stop ab, wenn der Bucket einen technischen Stop verlangt.
          </p>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-border-2">
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <AlertTriangle size={13} className="text-warning" />
            <span>Ohne Stop-Loss werden kritische Alerts generiert</span>
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg bg-surface border border-border text-text-secondary hover:border-border-hover transition-colors"
            >
              Später erledigen
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !allFilled}
              className="px-4 py-2 text-sm rounded-lg font-semibold bg-primary-btn border border-primary-btn-border text-white hover:bg-primary-btn-border transition-colors disabled:opacity-40 flex items-center gap-2"
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
