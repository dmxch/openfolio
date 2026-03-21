import { useState } from 'react'
import { AlertTriangle, X, Loader2 } from 'lucide-react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'

export default function DeleteConfirm({ name, onConfirm, onCancel }) {
  const [deleting, setDeleting] = useState(false)
  useEscClose(onCancel)
  useScrollLock(true)

  const handleConfirm = async () => {
    setDeleting(true)
    try { await onConfirm() } finally { setDeleting(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Löschen bestätigen"
        className="bg-card border border-border rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          <div className="p-2 rounded-full bg-danger/10">
            <AlertTriangle size={20} className="text-danger" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-text-primary">Position löschen?</h3>
            <p className="text-sm text-text-secondary mt-1">
              <span className="font-medium">{name}</span> wird unwiderruflich gelöscht.
            </p>
          </div>
          <button onClick={onCancel} className="text-text-muted hover:text-text-primary" aria-label="Schliessen">
            <X size={16} />
          </button>
        </div>
        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:text-text-primary hover:border-border/80 transition-colors disabled:opacity-40"
          >
            Abbrechen
          </button>
          <button
            onClick={handleConfirm}
            disabled={deleting}
            className="px-4 py-2 text-sm rounded-lg bg-danger text-white hover:bg-danger/90 transition-colors font-medium disabled:opacity-40 flex items-center gap-2"
          >
            {deleting && <Loader2 size={14} className="animate-spin" />}
            Löschen
          </button>
        </div>
      </div>
    </div>
  )
}
