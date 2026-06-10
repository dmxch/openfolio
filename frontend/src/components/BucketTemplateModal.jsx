import { useEffect, useState } from 'react'
import { X, Sparkles, AlertTriangle } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { useToast } from './Toast'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'

export default function BucketTemplateModal({ onClose, onCreated }) {
  const toast = useToast()
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyKey, setBusyKey] = useState(null)
  const [conflict, setConflict] = useState(null) // { templateKey, message }
  useEscClose(onClose)
  const trapRef = useFocusTrap(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await authFetch('/api/portfolio/buckets/templates')
        if (!res.ok) throw new Error()
        const data = await res.json()
        if (!cancelled) setTemplates(data.templates || [])
      } catch {
        if (!cancelled) toast('Templates nicht ladbar', 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  async function apply(key, { replaceExisting = false } = {}) {
    setBusyKey(key)
    try {
      const res = await authFetch('/api/portfolio/buckets/from-template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_key: key,
          replace_existing: replaceExisting,
        }),
      })
      if (res.status === 409) {
        const err = await res.json().catch(() => null)
        const detail = err?.detail || {}
        setConflict({
          templateKey: key,
          message: detail.message || 'Bucket-Namen existieren bereits',
        })
        return
      }
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        const msg =
          typeof err?.detail === 'string'
            ? err.detail
            : 'Template konnte nicht angewendet werden'
        throw new Error(msg)
      }
      const data = await res.json()
      toast(
        replaceExisting
          ? `Template gewechselt: ${data.count} Buckets neu angelegt`
          : `${data.count} Buckets erstellt`,
        'success',
      )
      onCreated && onCreated(data.created)
      onClose()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusyKey(null)
    }
  }

  function confirmReplace() {
    if (!conflict) return
    const key = conflict.templateKey
    setConflict(null)
    apply(key, { replaceExisting: true })
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
    >
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="bucket-template-title"
        className="bg-card border border-border rounded-xl max-w-2xl w-full shadow-2xl"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 id="bucket-template-title" className="text-lg font-semibold flex items-center gap-2">
            <Sparkles size={18} className="text-primary" /> Bucket aus Template
          </h2>
          <button
            onClick={onClose}
            aria-label="Schliessen"
            className="text-text-muted hover:text-text"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          {conflict && (
            <div className="border border-warning/50 bg-warning/10 rounded-lg p-3 text-sm space-y-2">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="text-warning shrink-0 mt-0.5" />
                <div>
                  <div className="font-medium">Bestehende Buckets ersetzen?</div>
                  <div className="text-text-secondary mt-1">{conflict.message}</div>
                  <div className="text-xs text-text-muted mt-1">
                    Positionen wandern zu &quot;Alle Positionen&quot; und werden danach neu angelegt.
                    Historische Snapshots der alten Buckets bleiben für Audit erhalten.
                  </div>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setConflict(null)}
                  className="px-3 py-1.5 text-sm bg-card-hover border border-border rounded hover:bg-card-hover/70"
                >
                  Abbrechen
                </button>
                <button
                  onClick={confirmReplace}
                  className="px-3 py-1.5 text-sm bg-warning text-black rounded hover:bg-warning/90"
                >
                  Bestehende ersetzen
                </button>
              </div>
            </div>
          )}
          {loading && <div className="text-text-muted text-sm">Lade...</div>}
          {!loading && templates.length === 0 && (
            <div className="text-text-muted text-sm">Keine Templates verfügbar.</div>
          )}
          {!loading &&
            templates.map((tpl) => (
              <button
                key={tpl.key}
                onClick={() => apply(tpl.key)}
                disabled={busyKey != null}
                className="w-full text-left border border-border rounded-lg p-4 hover:bg-card-hover transition disabled:opacity-50"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold">{tpl.label}</span>
                  <span className="text-xs text-text-muted">
                    {tpl.bucket_count} Buckets
                  </span>
                </div>
                <p className="text-sm text-text-secondary mb-2">
                  {tpl.description}
                </p>
                <div className="flex flex-wrap gap-1">
                  {tpl.bucket_names.map((n) => (
                    <span
                      key={n}
                      className="text-xs px-2 py-0.5 bg-card-hover rounded"
                    >
                      {n}
                    </span>
                  ))}
                </div>
              </button>
            ))}
        </div>
      </div>
    </div>
  )
}
