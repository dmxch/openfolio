import { useState } from 'react'
import { X, FolderTree, Eye, Clock, Trash2 } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { useToast } from './Toast'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'

// Einmaliges Modal fuer Bestandsuser nach Bucket-Migration.
// Trigger-Logik: GET /api/portfolio/buckets liefert show_onboarding_modal=true.
// Drei Optionen:
//   1) Behalten + ansehen → redirect zu Settings/Buckets
//   2) Behalten + spaeter (Default + ESC + X) → POST /buckets/onboarding-dismiss
//   3) Aufheben → POST /buckets/migration-rollback (Soft-Delete user buckets)
export default function BucketsOnboardingModal({ data, onClose, onNavigate }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  useEscClose(() => dismiss())
  const trapRef = useFocusTrap(true)

  const userBuckets = (data?.buckets || []).filter(
    (b) => b.kind === 'user' && !b.deleted_at,
  )

  async function dismiss() {
    if (busy) return
    setBusy(true)
    try {
      await authFetch('/api/portfolio/buckets/onboarding-dismiss', {
        method: 'POST',
      })
    } catch (e) {
      // best-effort; modal schliesst trotzdem
    } finally {
      setBusy(false)
      onClose()
    }
  }

  async function rollback() {
    if (busy) return
    if (
      !window.confirm(
        'Alle User-Buckets werden gelöscht. Positionen wandern zu "Alle Positionen". Sicher?'
      )
    ) {
      return
    }
    setBusy(true)
    try {
      const res = await authFetch('/api/portfolio/buckets/migration-rollback', {
        method: 'POST',
      })
      if (!res.ok) throw new Error('Rollback fehlgeschlagen')
      const result = await res.json()
      toast(
        `${result.buckets_deleted} Buckets entfernt, ${result.positions_moved} Positionen verschoben`,
        'success',
      )
    } catch (e) {
      toast('Buckets konnten nicht aufgehoben werden', 'error')
    } finally {
      setBusy(false)
      onClose()
    }
  }

  function keepAndView() {
    dismiss()
    if (onNavigate) onNavigate()
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bucket-onboarding-title"
    >
      <div ref={trapRef} className="bg-modal border border-border-hover rounded-[14px] max-w-lg w-full shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <h2
            id="bucket-onboarding-title"
            className="text-sm font-semibold text-text-primary flex items-center gap-2"
          >
            <FolderTree size={18} className="text-primary" />
            Dein Portfolio ist jetzt in Buckets organisiert
          </h2>
          <button
            onClick={dismiss}
            disabled={busy}
            aria-label="Schliessen"
            className="w-[30px] h-[30px] rounded-lg bg-border-row border border-border-hover flex items-center justify-center text-text-muted hover:text-text-primary transition-colors shrink-0"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 text-sm">
          <p className="text-text-secondary">
            Wir haben dein Portfolio basierend auf deinen Core/Satellite-Markierungen
            in Buckets aufgeteilt:
          </p>

          <ul className="border border-border-2 rounded-lg divide-y divide-border-2">
            {userBuckets.map((b) => (
              <li
                key={b.id}
                className="px-3 py-2 flex items-center gap-3"
              >
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ background: b.color || '#64748b' }}
                />
                <span className="font-medium text-text-primary">{b.name}</span>
                {b.benchmark && (
                  <span className="text-xs text-text-muted ml-auto">
                    Benchmark: {b.benchmark}
                  </span>
                )}
              </li>
            ))}
          </ul>

          <p className="text-text-secondary">
            Buckets erlauben dir getrennte Performance-Verfolgung, eigene
            Benchmarks und eine Drawdown-Bremse pro Bucket. System-Buckets
            (Immobilien, Vorsorge, Private Equity) bleiben unverändert.
          </p>
        </div>

        <div className="px-5 py-4 border-t border-border-2 space-y-2">
          <button
            onClick={keepAndView}
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-primary-btn border border-primary-btn-border text-white font-semibold rounded-lg hover:bg-primary-btn-border transition-colors disabled:opacity-50"
          >
            <Eye size={16} /> Buckets behalten und ansehen
          </button>
          <button
            onClick={dismiss}
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-surface border border-border text-text-secondary rounded-lg hover:border-border-hover transition-colors disabled:opacity-50"
          >
            <Clock size={16} /> Buckets behalten, später anschauen
          </button>
          <button
            onClick={rollback}
            disabled={busy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-danger border border-danger/50 rounded-lg hover:bg-danger/10 transition-colors disabled:opacity-50"
          >
            <Trash2 size={16} /> Buckets aufheben (alle Positionen in &quot;Alle Positionen&quot;)
          </button>
        </div>
      </div>
    </div>
  )
}
