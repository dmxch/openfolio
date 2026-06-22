import { useState, useEffect } from 'react'
import { apiPatch } from '../hooks/useApi'

/**
 * Inline-Formular fuer die User-spezifischen Filter-Schwellenwerte.
 * Persistiert per PATCH /api/eps-scanner/thresholds (user_id-scoped).
 */
export default function EpsThresholdSettings({ thresholds, onSaved }) {
  const [yoy, setYoy] = useState('')
  const [accel, setAccel] = useState('')
  const [outlier, setOutlier] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [savedMsg, setSavedMsg] = useState(false)

  useEffect(() => {
    if (thresholds) {
      setYoy(String(thresholds.super_quarter_yoy_pct ?? 25))
      setAccel(String(thresholds.acceleration_margin_pp ?? 5))
      setOutlier(String(thresholds.outlier_multiplier ?? 5))
    }
  }, [thresholds])

  const save = async (e) => {
    e.preventDefault()
    setError(null)
    setSavedMsg(false)
    const yoyN = Number(yoy)
    const accelN = Number(accel)
    const outlierN = Number(outlier)
    if (!(yoyN > 0 && yoyN <= 200)) return setError('YoY-Schwelle muss zwischen 0 und 200 liegen.')
    if (!(accelN > 0 && accelN <= 200)) return setError('Beschleunigungs-Marge muss zwischen 0 und 200 liegen.')
    if (!(outlierN > 0 && outlierN <= 20)) return setError('Outlier-Multiplikator muss zwischen 0 und 20 liegen.')
    setSaving(true)
    try {
      const res = await apiPatch('/eps-scanner/thresholds', {
        super_quarter_yoy_pct: yoyN,
        acceleration_margin_pp: accelN,
        outlier_multiplier: outlierN,
      })
      setSavedMsg(true)
      onSaved?.(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={save} className="space-y-2">
      <label className="block text-xs uppercase text-text-muted">Schwellenwerte</label>
      <div className="space-y-2">
        <div>
          <label htmlFor="eps-yoy" className="block text-xs text-text-secondary mb-0.5">
            YoY-Mindestwachstum (%)
          </label>
          <input
            id="eps-yoy"
            type="number"
            min="0.1"
            max="200"
            step="0.5"
            value={yoy}
            onChange={(e) => setYoy(e.target.value)}
            className="w-full bg-card-alt border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label htmlFor="eps-accel" className="block text-xs text-text-secondary mb-0.5">
            Beschleunigungs-Marge (pp)
          </label>
          <input
            id="eps-accel"
            type="number"
            min="0.1"
            max="200"
            step="0.5"
            value={accel}
            onChange={(e) => setAccel(e.target.value)}
            className="w-full bg-card-alt border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label htmlFor="eps-outlier" className="block text-xs text-text-secondary mb-0.5">
            Outlier-Multiplikator (× Median)
          </label>
          <input
            id="eps-outlier"
            type="number"
            min="0.1"
            max="20"
            step="0.5"
            value={outlier}
            onChange={(e) => setOutlier(e.target.value)}
            className="w-full bg-card-alt border border-border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
      </div>
      {error && <div className="text-xs text-danger">{error}</div>}
      {savedMsg && <div className="text-xs text-success">Gespeichert.</div>}
      <button
        type="submit"
        disabled={saving}
        className="w-full px-3 py-1.5 text-sm rounded bg-primary/20 text-primary hover:bg-primary/30 focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
      >
        {saving ? 'Speichert…' : 'Schwellenwerte speichern'}
      </button>
    </form>
  )
}
