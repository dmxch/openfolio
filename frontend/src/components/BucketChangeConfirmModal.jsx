import { useEffect, useState } from 'react'
import { X, AlertTriangle, ArrowRight } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { useToast } from './Toast'
import useEscClose from '../hooks/useEscClose'
import useFocusTrap from '../hooks/useFocusTrap'

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
  const [keepRules, setKeepRules] = useState(false)
  const [mode, setMode] = useState('full') // 'full' | 'partial'
  const [splitPct, setSplitPct] = useState(50)
  useEscClose(onClose)
  const trapRef = useFocusTrap(true)

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
      let res
      if (mode === 'partial') {
        const pct = Number(splitPct) / 100
        if (!(pct > 0 && pct < 1)) {
          throw new Error('Anteil muss zwischen 1 und 99 % liegen')
        }
        res = await authFetch(
          `/api/portfolio/positions/${positionId}/split-to-bucket`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_bucket_id: targetBucketId,
              split_pct: pct,
            }),
          },
        )
      } else {
        res = await authFetch(
          `/api/portfolio/positions/${positionId}/move-to-bucket`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              target_bucket_id: targetBucketId,
              keep_risk_rules: keepRules,
            }),
          },
        )
      }
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || 'Wechsel fehlgeschlagen')
      }
      toast(
        mode === 'partial'
          ? `${splitPct}% von ${ticker || 'Position'} verschoben`
          : `${ticker || 'Position'} verschoben`,
        'success',
      )
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
      className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bucket-change-title"
    >
      <div ref={trapRef} className="bg-modal border border-border-hover rounded-[14px] max-w-xl w-full shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2">
          <h2 id="bucket-change-title" className="text-sm font-semibold text-text-primary">
            Position verschieben
          </h2>
          <button
            onClick={onClose}
            aria-label="Schliessen"
            className="w-[30px] h-[30px] rounded-lg bg-border-row border border-border-hover flex items-center justify-center text-text-muted hover:text-text-primary transition-colors shrink-0"
          >
            <X size={16} />
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

              <div className="border border-border-2 rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-table-head">
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
                        className={`border-t border-border-row ${
                          row.changed ? 'bg-warning/5' : ''
                        }`}
                      >
                        <td className="px-3 py-2 flex items-center gap-2">
                          {row.changed && (
                            <AlertTriangle
                              size={12}
                              className="text-warning shrink-0"
                              aria-label="Geändert"
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
                Änderungen gelten ab sofort für diese Position. Historische
                Performance bleibt im alten Bucket dokumentiert.
              </p>

              <div className="border border-border-2 rounded-lg p-2 space-y-2">
                <div className="flex gap-1 p-1 bg-card-2 rounded-lg text-xs">
                  <button
                    onClick={() => setMode('full')}
                    className={`flex-1 py-1 rounded transition-colors ${
                      mode === 'full' ? 'bg-primary text-white' : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    Ganz verschieben
                  </button>
                  <button
                    onClick={() => setMode('partial')}
                    className={`flex-1 py-1 rounded transition-colors ${
                      mode === 'partial' ? 'bg-primary text-white' : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    Teilweise
                  </button>
                </div>
                {mode === 'partial' && (
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min="1"
                        max="99"
                        value={splitPct}
                        onChange={(e) => setSplitPct(e.target.value)}
                        className="flex-1"
                      />
                      <input
                        type="number"
                        min="1"
                        max="99"
                        value={splitPct}
                        onChange={(e) => setSplitPct(e.target.value)}
                        className="w-16 px-2 py-1 text-xs bg-surface border border-border rounded-lg text-right text-text-primary tabular-nums"
                      />
                      <span className="text-xs">%</span>
                    </div>
                    <p className="text-[11px] text-text-muted">
                      Original-Position behält {100 - Number(splitPct)}%. Eine
                      neue Position-Row mit {splitPct}% der Shares + Cost-Basis
                      wird im Ziel-Bucket angelegt. Ziel-Bucket darf noch keine
                      aktive Position dieses Tickers haben.
                    </p>
                  </div>
                )}
              </div>

              {mode === 'full' && (
                <label className="flex items-center gap-2 text-xs bg-card-2 rounded-lg p-2 border border-border-2">
                  <input
                    type="checkbox"
                    checked={keepRules}
                    onChange={(e) => setKeepRules(e.target.checked)}
                  />
                  <span>
                    Aktuelle Risk-Rules für diese Position beibehalten
                    (Position-Override). Bucket-Wechsel ändert dann nur die
                    Zuordnung, nicht die Schwellen.
                  </span>
                </label>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-4 border-t border-border-2 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 text-sm rounded-lg bg-surface border border-border text-text-secondary hover:border-border-hover transition-colors disabled:opacity-50"
          >
            Abbrechen
          </button>
          <button
            onClick={confirm}
            disabled={busy || loading}
            className="px-4 py-2 text-sm rounded-lg bg-primary-btn border border-primary-btn-border text-white font-semibold hover:bg-primary-btn-border transition-colors disabled:opacity-50"
          >
            {mode === 'partial' ? `${splitPct}% verschieben` : 'Verschieben'}
          </button>
        </div>
      </div>
    </div>
  )
}
