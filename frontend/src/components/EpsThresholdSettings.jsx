import { useState, useEffect } from 'react'
import { apiPatch } from '../hooks/useApi'

const INPUT = 'w-full bg-surface border border-border rounded-lg px-2.5 py-1.5 text-sm font-mono tabular-nums text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'

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
    <form onSubmit={save} className="space-y-3">
      <div>
        <label htmlFor="eps-yoy" className="block text-[11px] text-text-secondary mb-1">
          Min. YoY-Wachstum (%)
        </label>
        <input
          id="eps-yoy"
          type="number"
          min="0.1"
          max="200"
          step="0.5"
          value={yoy}
          onChange={(e) => setYoy(e.target.value)}
          className={INPUT}
        />
      </div>
      <div>
        <label htmlFor="eps-accel" className="block text-[11px] text-text-secondary mb-1">
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
          className={INPUT}
        />
      </div>
      <div>
        <label htmlFor="eps-outlier" className="block text-[11px] text-text-secondary mb-1">
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
          className={INPUT}
        />
      </div>
      {error && <div className="text-[11px] text-danger">{error}</div>}
      {savedMsg && <div className="text-[11px] text-success">Gespeichert.</div>}
      <button
        type="submit"
        disabled={saving}
        className="w-full px-3 py-1.5 text-[12.5px] font-medium rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 focus:outline-none focus:ring-1 focus:ring-primary/40 disabled:opacity-50 transition-colors"
      >
        {saving ? 'Speichert…' : 'Speichern'}
      </button>
    </form>
  )
}
