import { useState, useEffect } from 'react'
import { PieChart, X } from 'lucide-react'
import { useApi, apiPut, apiDelete } from '../hooks/useApi'
import { formatCHF } from '../lib/format'
import { useToast } from './Toast'
import { FINVIZ_SECTORS } from '../lib/sectorMapping'
import useScrollLock from '../hooks/useScrollLock'

function EditModal({ ticker, initial, onClose, onSaved }) {
  useScrollLock(true)
  const toast = useToast()
  const [weights, setWeights] = useState(() => {
    const map = {}
    for (const s of initial || []) map[s.sector] = s.weight_pct
    return FINVIZ_SECTORS.map((s) => ({ sector: s, weight_pct: map[s] || 0 }))
  })
  const [saving, setSaving] = useState(false)

  const total = weights.reduce((s, w) => s + w.weight_pct, 0)
  const isValid = total >= 99.9 && total <= 100.1

  const handleChange = (index, val) => {
    const num = val === '' ? 0 : parseFloat(val)
    if (isNaN(num) || num < 0 || num > 100) return
    const next = [...weights]
    next[index] = { ...next[index], weight_pct: num }
    setWeights(next)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiPut(`/etf-sectors/${ticker}`, { sectors: weights.filter((w) => w.weight_pct > 0) })
      toast('Sektorverteilung gespeichert', 'success')
      onSaved()
      onClose()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Sektorverteilung bearbeiten" className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md mx-4 max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="text-sm font-bold text-text-primary">Sektorverteilung — {ticker}</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary" aria-label="Schliessen"><X size={18} /></button>
        </div>

        <div className="overflow-y-auto p-4 space-y-2 flex-1">
          <p className="text-xs text-text-muted mb-3">
            Die Sektorverteilung findest du auf der Website des ETF-Anbieters (z.B. iShares, Vanguard, SPDR).
          </p>
          {weights.map((w, i) => (
            <div key={w.sector} className="flex items-center gap-3">
              <span className="text-xs text-text-secondary w-40 shrink-0">{w.sector}</span>
              <input
                type="number"
                step="0.1"
                min="0"
                max="100"
                value={w.weight_pct || ''}
                onChange={(e) => handleChange(i, e.target.value)}
                placeholder="0"
                className="w-20 px-2 py-1 text-xs text-right bg-card-alt border border-border rounded text-text-primary tabular-nums focus:border-primary focus:outline-none"
              />
              <span className="text-xs text-text-muted">%</span>
            </div>
          ))}
        </div>

        <div className="p-4 border-t border-border flex items-center justify-between">
          <span className={`text-sm font-bold tabular-nums ${isValid ? 'text-success' : 'text-danger'}`}>
            Total: {total.toFixed(1)}%
          </span>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-xs text-text-muted hover:text-text-primary transition-colors">
              Abbrechen
            </button>
            <button
              onClick={handleSave}
              disabled={!isValid || saving}
              className="px-4 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saving ? 'Speichern...' : 'Speichern'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function EtfSectorPanel({ ticker, marketValueChf }) {
  const { data, loading, refetch } = useApi(`/etf-sectors/${ticker}`)
  const [showModal, setShowModal] = useState(false)
  const toast = useToast()

  if (loading) return null

  const sectors = data?.sectors || []
  const hasWeights = sectors.length > 0 && data?.is_complete

  const handleDelete = async () => {
    try {
      await apiDelete(`/etf-sectors/${ticker}`)
      toast('Sektorverteilung gelöscht', 'success')
      refetch()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <PieChart size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">Sektorverteilung</h3>
        </div>
        {hasWeights ? (
          <div className="flex gap-2">
            <button
              onClick={() => setShowModal(true)}
              className="text-xs text-primary hover:text-primary/80 transition-colors"
            >
              Bearbeiten
            </button>
            <button
              onClick={handleDelete}
              className="text-xs text-danger hover:text-danger/80 transition-colors"
            >
              Löschen
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowModal(true)}
            className="px-3 py-1 text-xs bg-primary/15 text-primary border border-primary/30 rounded-lg hover:bg-primary/25 transition-colors"
          >
            Sektorverteilung erfassen
          </button>
        )}
      </div>

      {hasWeights ? (
        <div className="space-y-1.5">
          {sectors.map((s) => (
            <div key={s.sector} className="flex items-center justify-between text-xs">
              <span className="text-text-secondary">{s.sector}</span>
              <div className="flex items-center gap-3">
                <span className="text-text-primary tabular-nums font-medium">{s.weight_pct.toFixed(1)}%</span>
                {marketValueChf > 0 && (
                  <span className="text-text-muted tabular-nums w-24 text-right">
                    {formatCHF(marketValueChf * s.weight_pct / 100)}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-text-muted">
          Keine Sektorverteilung hinterlegt. Für korrekte Sektor-Allokation bitte pflegen.
        </p>
      )}

      {showModal && (
        <EditModal
          ticker={ticker}
          initial={sectors}
          onClose={() => setShowModal(false)}
          onSaved={refetch}
        />
      )}
    </div>
  )
}
