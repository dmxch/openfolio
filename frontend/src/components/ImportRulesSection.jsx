import { useEffect, useState } from 'react'
import { Plus, Trash2, Wand2 } from 'lucide-react'
import { authFetch } from '../hooks/useApi'
import { useToast } from './Toast'

const SOURCE_PRESETS = [
  { value: '', label: '— keine —' },
  { value: 'swissquote', label: 'Swissquote' },
  { value: 'ibkr', label: 'Interactive Brokers' },
  { value: 'pocket', label: 'Pocket' },
]

// UI fuer Import-Bucket-Mapping-Regeln (F-15 Backend, F-18 Frontend).
// Eingebettet in BucketsTab; nutzt /api/portfolio/buckets/import-rules.
export default function ImportRulesSection({ buckets }) {
  const toast = useToast()
  const [rules, setRules] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    bucket_id: '',
    source: '',
    ticker_pattern: '',
    priority: 100,
  })
  const [busy, setBusy] = useState(false)

  const userBuckets = (buckets || []).filter(
    (b) => b.kind === 'user' && !b.deleted_at,
  )
  const bucketName = (id) => (buckets || []).find((b) => b.id === id)?.name || '?'

  async function reload() {
    setLoading(true)
    try {
      const res = await authFetch('/api/portfolio/buckets/import-rules')
      if (!res.ok) throw new Error('Regeln nicht ladbar')
      const data = await res.json()
      setRules(data.rules || [])
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function save() {
    if (!form.bucket_id) {
      toast('Bucket auswaehlen', 'error')
      return
    }
    if (!form.source && !form.ticker_pattern) {
      toast('Mindestens Source oder Ticker-Pattern setzen', 'error')
      return
    }
    setBusy(true)
    try {
      const res = await authFetch('/api/portfolio/buckets/import-rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bucket_id: form.bucket_id,
          source: form.source || null,
          ticker_pattern: form.ticker_pattern || null,
          priority: Number(form.priority) || 100,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || 'Speichern fehlgeschlagen')
      }
      toast('Regel angelegt', 'success')
      setShowForm(false)
      setForm({ bucket_id: '', source: '', ticker_pattern: '', priority: 100 })
      reload()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function deleteRule(ruleId) {
    if (!window.confirm('Regel loeschen?')) return
    try {
      const res = await authFetch(
        `/api/portfolio/buckets/import-rules/${ruleId}`,
        { method: 'DELETE' },
      )
      if (!res.ok) throw new Error('Loeschen fehlgeschlagen')
      toast('Regel geloescht', 'success')
      reload()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-text-secondary flex items-center gap-2">
          <Wand2 size={14} className="text-primary" /> Import-Mapping-Regeln
        </h3>
        {userBuckets.length > 0 && (
          <button
            onClick={() => setShowForm(!showForm)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-border rounded hover:bg-card-hover"
          >
            <Plus size={12} />
            {showForm ? 'Abbrechen' : 'Neue Regel'}
          </button>
        )}
      </div>
      <p className="text-xs text-text-muted">
        Beim CSV-Import werden neue Positionen automatisch in den passenden
        Bucket eingeordnet. Erste passende Regel (niedrige Prioritaet zuerst)
        gewinnt — sonst fallback auf den im Import-Wizard gewaehlten Bucket
        oder &quot;Alle Positionen&quot;.
      </p>

      {showForm && (
        <div className="border border-border rounded-lg p-3 bg-card-hover space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-text-secondary block mb-1">
                Bucket *
              </label>
              <select
                value={form.bucket_id}
                onChange={(e) => setForm({ ...form, bucket_id: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-body border border-border rounded"
              >
                <option value="">— waehlen —</option>
                {userBuckets.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-text-secondary block mb-1">
                Prioritaet
              </label>
              <input
                type="number"
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-body border border-border rounded"
                placeholder="100"
              />
            </div>
            <div>
              <label className="text-xs text-text-secondary block mb-1">
                Quelle (Substring)
              </label>
              <input
                list="source-presets"
                value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-body border border-border rounded"
                placeholder="z.B. swissquote"
              />
              <datalist id="source-presets">
                {SOURCE_PRESETS.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </datalist>
            </div>
            <div>
              <label className="text-xs text-text-secondary block mb-1">
                Ticker-Pattern (Glob)
              </label>
              <input
                value={form.ticker_pattern}
                onChange={(e) => setForm({ ...form, ticker_pattern: e.target.value })}
                className="w-full px-2 py-1.5 text-sm bg-body border border-border rounded"
                placeholder="z.B. BTC* oder *.SW"
              />
            </div>
          </div>
          <p className="text-[11px] text-text-muted">
            Mindestens ein Filter (Source oder Ticker-Pattern) muss gesetzt sein.
            Beide gesetzt = beide muessen matchen.
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={save}
              disabled={busy}
              className="px-3 py-1.5 text-xs bg-primary text-white rounded disabled:opacity-50"
            >
              Speichern
            </button>
          </div>
        </div>
      )}

      {loading && <div className="text-xs text-text-muted">Lade...</div>}
      {!loading && rules.length === 0 && (
        <div className="text-xs text-text-muted py-2">
          Keine Regeln definiert.
          {userBuckets.length === 0 && ' Lege zuerst einen User-Bucket an.'}
        </div>
      )}
      {!loading && rules.length > 0 && (
        <ul className="border border-border rounded-lg divide-y divide-border">
          {rules.map((r) => (
            <li key={r.id} className="px-3 py-2 flex items-center gap-2 text-xs">
              <span className="text-text-muted w-10 tabular-nums">P{r.priority}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  {r.source && (
                    <span className="px-1.5 py-0.5 bg-card-hover rounded">
                      source ~ {r.source}
                    </span>
                  )}
                  {r.ticker_pattern && (
                    <span className="px-1.5 py-0.5 bg-card-hover rounded font-mono">
                      ticker = {r.ticker_pattern}
                    </span>
                  )}
                  <span className="text-text-muted">→</span>
                  <span className="font-medium text-text-primary">{bucketName(r.bucket_id)}</span>
                </div>
              </div>
              <button
                onClick={() => deleteRule(r.id)}
                aria-label="Loeschen"
                className="p-1.5 text-danger hover:bg-danger/10 rounded"
              >
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
