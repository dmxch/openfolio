import { useEffect, useState } from 'react'
import { X, AlertTriangle, ArrowRight } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { useToast } from './Toast'
import useEscClose from '../hooks/useEscClose'

// Position-Wechsel-Modal mit Risk-Rules-Diff.
// Aufrufer setzt position + target_bucket_id; das Modal laedt das Diff selbst.
export default function BucketChangeConfirmModal({
  positionId,
  ticker,
  targetBucketId,
  onClose,
  onConfirmed,
}) {
  const toast = useToast()
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  useEscClose(onClose)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await authFetch(
          `/api/portfolio/positions/${positionId}/bucket-change-preview?to_bucket=${targetBucketId}`,
        )
        if (!res.ok) throw new Error('Preview nicht ladbar')
        const data = await res.json()
        if (!cancelled) setPreview(data)
      } catch (e) {
        if (!cancelled) toast(e.message, 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [positionId, targetBucketId])

  async function confirm() {
    setBusy(true)
    try {
      const res = await authFetch(
        `/api/portfolio/positions/${positionId}/move-to-bucket`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_bucket_id: targetBucketId }),
        },
      )
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || 'Wechsel fehlgeschlagen')
      }
      toast(`${ticker || 'Position'} verschoben`, 'success')
      onConfirmed && onConfirmed()
      onClose()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  function formatValue(v) {
    if (v === null || v === undefined) return '—'
    if (typeof v === 'boolean') return v ? 'Ja' : 'Nein'
    if (typeof v === 'number') return v.toString()
    return String(v)
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bucket-change-title"
    >
      <div className="bg-card border border-border rounded-xl max-w-xl w-full shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 id="bucket-change-title" className="text-lg font-semibold">
            Position verschieben
          </h2>
          <button
            onClick={onClose}
            aria-label="Schliessen"
            className="text-text-muted hover:text-text"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 text-sm">
          {loading && <div className="text-text-muted">Lade Preview...</div>}

          {!loading && preview && (
            <>
              <p>
                Du verschiebst <strong>{preview.ticker}</strong> von{' '}
                <strong>{preview.from_bucket?.name || '— (kein Bucket)'}</strong>{' '}
                <ArrowRight size={14} className="inline mx-1" />{' '}
                <strong>{preview.to_bucket.name}</strong>.
              </p>

              <div className="border border-border rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-card-hover">
                    <tr>
                      <th className="text-left px-3 py-2">Regel</th>
                      <th className="text-left px-3 py-2">Alt</th>
                      <th className="text-left px-3 py-2">Neu</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(preview.diff || []).map((row) => (
                      <tr
                        key={row.key}
                        className={`border-t border-border ${
                          row.changed ? 'bg-warning/5' : ''
                        }`}
                      >
                        <td className="px-3 py-2 flex items-center gap-2">
                          {row.changed && (
                            <AlertTriangle
                              size={12}
                              className="text-warning shrink-0"
                              aria-label="Geaendert"
                            />
                          )}
                          {row.label}
                        </td>
                        <td className="px-3 py-2 text-text-muted">
                          {formatValue(row.old)}
                        </td>
                        <td className="px-3 py-2">{formatValue(row.new)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="text-xs text-text-muted">
                Aenderungen gelten ab sofort fuer diese Position. Historische
                Performance bleibt im alten Bucket dokumentiert.
              </p>
            </>
          )}
        </div>

        <div className="px-5 py-4 border-t border-border flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 bg-card-hover border border-border rounded-lg hover:bg-card-hover/70"
          >
            Abbrechen
          </button>
          <button
            onClick={confirm}
            disabled={busy || loading}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50"
          >
            Verschieben
          </button>
        </div>
      </div>
    </div>
  )
}
