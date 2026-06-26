import { useState } from 'react'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import { useToast } from './Toast'
import { apiPost } from '../hooks/useApi'
import { formatCHFExact } from '../lib/format'
import { RefreshCw } from 'lucide-react'

/**
 * "Neu berechnen"-Button inkl. Bestaetigungsdialog. Rechnet Cost-Basis aller
 * Positionen aus dem Transaktions-Ledger neu und stoesst die Snapshot-Regen an
 * (speist Performance/Charts). Wird auf der Portfolio- UND der Performance-Seite
 * verwendet — beide zeigen Daten, die diese Aktion auffrischt.
 *
 * onRecalculate: Callback nach erfolgreichem Recalc (Seiten-Refetch).
 */
export default function RecalculateButton({ onRecalculate }) {
  const [recalculating, setRecalculating] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const confirmTrapRef = useFocusTrap(showConfirm)
  useScrollLock(showConfirm)
  const toast = useToast()

  const handleRecalculate = async () => {
    setRecalculating(true)
    setShowConfirm(false)
    try {
      const res = await apiPost('/portfolio/recalculate', {})
      await onRecalculate?.()
      const count = res.recalculated || 0
      const positions = res.positions || []
      const maxDelta = positions.reduce(
        (max, p) => (Math.abs(p.delta_chf) > Math.abs(max.delta_chf) ? p : max),
        { delta_chf: 0 },
      )
      let msg = `${count} Positionen neu berechnet`
      if (maxDelta.ticker && Math.abs(maxDelta.delta_chf) >= 0.01) {
        msg += ` · Grösste Änderung: ${maxDelta.ticker} ${formatCHFExact(maxDelta.delta_chf)}`
      }
      toast(msg, 'success')
    } catch (err) {
      toast('Neuberechnung fehlgeschlagen', 'error')
    } finally {
      setRecalculating(false)
    }
  }

  return (
    <>
      <button
        onClick={() => setShowConfirm(true)}
        disabled={recalculating}
        className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary transition-colors disabled:opacity-50"
      >
        <RefreshCw size={14} className={recalculating ? 'animate-spin' : ''} />
        {recalculating ? 'Berechne...' : 'Neu berechnen'}
      </button>

      {showConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setShowConfirm(false)}
        >
          <div
            ref={confirmTrapRef}
            className="bg-card border border-border rounded-xl p-6 max-w-md mx-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Neuberechnung bestätigen"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 rounded-lg bg-primary/10">
                <RefreshCw size={18} className="text-primary" />
              </div>
              <h3 className="text-lg font-semibold text-text-primary">Positionen neu berechnen?</h3>
            </div>
            <p className="text-sm text-text-secondary mb-6">
              Alle Positionen neu berechnen? Dies aktualisiert Cost Basis, Performance und Gebühren
              basierend auf den aktuellen Transaktionsdaten.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors"
              >
                Abbrechen
              </button>
              <button
                onClick={handleRecalculate}
                className="px-4 py-2 text-sm rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors"
              >
                Neu berechnen
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
