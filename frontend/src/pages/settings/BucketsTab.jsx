import { useEffect, useState } from 'react'
import { Plus, Trash2, Edit2, FolderTree, X, Sparkles } from 'lucide-react'
import { authFetch } from '../../hooks/useApi'
import { useToast } from '../../components/Toast'
import BucketTemplateModal from '../../components/BucketTemplateModal'

const PALETTE = [
  '#3b82f6', // blue
  '#f59e0b', // amber
  '#10b981', // emerald
  '#ef4444', // red
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#14b8a6', // teal
  '#f97316', // orange
  '#06b6d4', // cyan
  '#a855f7', // purple
  '#84cc16', // lime
  '#64748b', // slate (default system)
]

const BENCHMARK_OPTIONS = [
  { value: '', label: 'Kein Benchmark' },
  { value: '^GSPC', label: 'S&P 500 (^GSPC)' },
  { value: 'URTH', label: 'MSCI World (URTH)' },
  { value: '^STOXX50E', label: 'EuroStoxx 50' },
  { value: '^SSMI', label: 'SMI' },
  { value: '^IXIC', label: 'NASDAQ Composite' },
]

export default function BucketsTab() {
  const toast = useToast()
  const [buckets, setBuckets] = useState([])
  const [limit, setLimit] = useState(15)
  const [activeCount, setActiveCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showTemplate, setShowTemplate] = useState(false)

  async function reload() {
    setLoading(true)
    try {
      const res = await authFetch('/api/portfolio/buckets')
      if (!res.ok) throw new Error('Buckets nicht ladbar')
      const data = await res.json()
      setBuckets(data.buckets || [])
      setLimit(data.limit || 15)
      setActiveCount(data.active_user_buckets || 0)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function deleteBucket(b) {
    if (!window.confirm(`Bucket "${b.name}" loeschen? Positionen wandern zu "Alle Positionen".`))
      return
    try {
      const res = await authFetch(`/api/portfolio/buckets/${b.id}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || 'Loeschen fehlgeschlagen')
      }
      const result = await res.json()
      toast(`Bucket geloescht, ${result.positions_moved} Positionen verschoben`, 'success')
      reload()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const userBuckets = buckets.filter((b) => b.kind === 'user' && !b.deleted_at)
  const systemBuckets = buckets.filter((b) => b.kind === 'system' && !b.deleted_at)
  const limitReached = activeCount >= limit

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <FolderTree size={18} className="text-primary" /> Buckets
          </h2>
          <p className="text-sm text-text-secondary mt-1">
            Segmentiere dein liquides Portfolio in Buckets mit eigenen Benchmarks
            und Drawdown-Bremsen. {activeCount}/{limit} User-Buckets aktiv.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowTemplate(true)}
            disabled={limitReached}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-border rounded-lg hover:bg-card-hover disabled:opacity-50"
            title="Buckets aus Template erstellen"
          >
            <Sparkles size={14} /> Template
          </button>
          <button
            onClick={() => setShowCreate(true)}
            disabled={limitReached}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50"
          >
            <Plus size={14} /> Neuer Bucket
          </button>
        </div>
      </div>

      {loading && <div className="text-text-muted text-sm">Lade...</div>}

      {!loading && (
        <>
          <section>
            <h3 className="text-sm font-medium text-text-secondary mb-2">
              Deine Buckets
            </h3>
            {userBuckets.length === 0 ? (
              <div className="border border-dashed border-border rounded-lg p-6 text-center text-sm text-text-muted">
                Noch keine User-Buckets. Erstelle einen via Template oder &quot;Neuer Bucket&quot;.
              </div>
            ) : (
              <ul className="border border-border rounded-lg divide-y divide-border">
                {userBuckets.map((b) => (
                  <BucketRow
                    key={b.id}
                    bucket={b}
                    onEdit={() => setEditing(b)}
                    onDelete={() => deleteBucket(b)}
                  />
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="text-sm font-medium text-text-secondary mb-2">
              System-Buckets
            </h3>
            <p className="text-xs text-text-muted mb-2">
              Werden automatisch verwaltet, Name nicht editierbar. Benchmark
              und Farbe koennen angepasst werden.
            </p>
            <ul className="border border-border rounded-lg divide-y divide-border">
              {systemBuckets.map((b) => (
                <BucketRow
                  key={b.id}
                  bucket={b}
                  onEdit={() => setEditing(b)}
                  onDelete={null}
                />
              ))}
            </ul>
          </section>
        </>
      )}

      {editing && (
        <BucketEditModal
          bucket={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            reload()
          }}
        />
      )}

      {showCreate && (
        <BucketEditModal
          bucket={null}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false)
            reload()
          }}
        />
      )}

      {showTemplate && (
        <BucketTemplateModal
          onClose={() => setShowTemplate(false)}
          onCreated={() => {
            setShowTemplate(false)
            reload()
          }}
        />
      )}
    </div>
  )
}

function BucketRow({ bucket, onEdit, onDelete }) {
  const [bench, setBench] = useState(null)
  useEffect(() => {
    if (!bucket.benchmark || bucket.system_role) return
    let cancelled = false
    authFetch(`/api/portfolio/buckets/${bucket.id}/benchmark-comparison?period=ytd`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (!cancelled && data) setBench(data) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [bucket.id, bucket.benchmark])

  const fmtPct = (v) => v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
  const deltaColor = bench?.delta_pct == null ? 'text-text-muted'
    : bench.delta_pct >= 0 ? 'text-success' : 'text-danger'

  return (
    <li className="px-4 py-3 flex items-center gap-3">
      <span
        className="w-3 h-3 rounded-full shrink-0"
        style={{ background: bucket.color || '#64748b' }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium">{bucket.name}</span>
          {bucket.system_role && (
            <span className="text-xs px-1.5 py-0.5 bg-card-hover rounded">
              System
            </span>
          )}
        </div>
        <div className="text-xs text-text-muted flex flex-wrap gap-3 mt-0.5">
          {bucket.benchmark && <span>Benchmark: {bucket.benchmark}</span>}
          {bench?.bucket_return_pct != null && (
            <span className="tabular-nums" title="Year-to-Date vs Benchmark">
              YTD: <span className="text-text-primary">{fmtPct(bench.bucket_return_pct)}</span>
              {' / '}
              <span>{bench.benchmark_name || bench.benchmark_ticker}: {fmtPct(bench.benchmark_return_pct)}</span>
              {bench.delta_pct != null && (
                <span className={`ml-1 ${deltaColor}`}>(Δ {fmtPct(bench.delta_pct)})</span>
              )}
            </span>
          )}
          {bucket.risk_rules?.drawdown_brake_pct != null && (
            <span>
              Drawdown-Bremse: {bucket.risk_rules.drawdown_brake_pct}%
              {bucket.risk_rules.drawdown_brake_active === false && ' (inaktiv)'}
            </span>
          )}
          {bucket.target_pct != null && <span>Ziel: {bucket.target_pct}%</span>}
          {bucket.target_chf != null && (
            <span>Ziel: {bucket.target_chf.toLocaleString('de-CH')} CHF</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={onEdit}
          aria-label="Bearbeiten"
          className="p-2 text-text-muted hover:text-text rounded hover:bg-card-hover"
        >
          <Edit2 size={14} />
        </button>
        {onDelete && (
          <button
            onClick={onDelete}
            aria-label="Loeschen"
            className="p-2 text-danger hover:bg-danger/10 rounded"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </li>
  )
}

function BucketEditModal({ bucket, onClose, onSaved }) {
  const toast = useToast()
  const isNew = bucket == null
  const isSystem = bucket?.kind === 'system'

  const [name, setName] = useState(bucket?.name || '')
  const [color, setColor] = useState(bucket?.color || PALETTE[0])
  const [benchmark, setBenchmark] = useState(bucket?.benchmark || '')
  const [targetType, setTargetType] = useState(
    bucket?.target_chf != null ? 'chf' : 'pct',
  )
  const [targetValue, setTargetValue] = useState(
    bucket?.target_chf ?? bucket?.target_pct ?? '',
  )
  const [drawdownPct, setDrawdownPct] = useState(
    bucket?.risk_rules?.drawdown_brake_pct ?? 6,
  )
  const [drawdownActive, setDrawdownActive] = useState(
    bucket?.risk_rules?.drawdown_brake_active ?? true,
  )
  const [maxPositionPct, setMaxPositionPct] = useState(
    bucket?.risk_rules?.max_position_pct ?? '',
  )
  const [alertLossPct, setAlertLossPct] = useState(
    bucket?.risk_rules?.alert_loss_pct ?? '',
  )
  const [maxSectorPct, setMaxSectorPct] = useState(
    bucket?.risk_rules?.max_sector_pct ?? '',
  )
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    try {
      const parseOrNull = (v) => {
        if (v === '' || v == null) return null
        const n = Number(v)
        return Number.isFinite(n) ? n : null
      }
      const body = {
        color: color || null,
        benchmark: benchmark || null,
        risk_rules: {
          ...(bucket?.risk_rules || {}),
          drawdown_brake_pct: Number(drawdownPct),
          drawdown_brake_active: !!drawdownActive,
          max_position_pct: parseOrNull(maxPositionPct),
          alert_loss_pct: parseOrNull(alertLossPct),
          max_sector_pct: parseOrNull(maxSectorPct),
        },
      }
      if (!isSystem) {
        body.name = name
      }
      const num = targetValue === '' ? null : Number(targetValue)
      if (num != null && !Number.isNaN(num)) {
        if (targetType === 'pct') body.target_pct = num
        else body.target_chf = num
      } else {
        body.target_pct = null
        body.target_chf = null
      }

      const path = isNew
        ? '/api/portfolio/buckets'
        : `/api/portfolio/buckets/${bucket.id}`
      const method = isNew ? 'POST' : 'PATCH'
      if (isNew) {
        body.name = name
      }
      const res = await authFetch(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || 'Speichern fehlgeschlagen')
      }
      toast(isNew ? 'Bucket erstellt' : 'Bucket aktualisiert', 'success')
      onSaved()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="bg-card border border-border rounded-xl max-w-lg w-full shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 className="text-lg font-semibold">
            {isNew ? 'Neuer Bucket' : `Bucket: ${bucket.name}`}
          </h3>
          <button onClick={onClose} aria-label="Schliessen">
            <X size={20} className="text-text-muted hover:text-text" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {!isSystem && (
            <div>
              <label className="text-xs text-text-secondary block mb-1">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={50}
                className="w-full px-3 py-2 bg-body border border-border rounded-lg"
              />
            </div>
          )}

          <div>
            <label className="text-xs text-text-secondary block mb-1">Farbe</label>
            <div className="flex flex-wrap gap-2">
              {PALETTE.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  aria-label={`Farbe ${c}`}
                  className={`w-7 h-7 rounded-full border-2 ${
                    color === c ? 'border-text' : 'border-transparent'
                  }`}
                  style={{ background: c }}
                />
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-text-secondary block mb-1">Benchmark</label>
            <select
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
              className="w-full px-3 py-2 bg-body border border-border rounded-lg"
            >
              {BENCHMARK_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-text-secondary block mb-1">
              Ziel-Allokation
            </label>
            <div className="flex gap-2">
              <select
                value={targetType}
                onChange={(e) => setTargetType(e.target.value)}
                className="px-3 py-2 bg-body border border-border rounded-lg"
              >
                <option value="pct">in Prozent</option>
                <option value="chf">in CHF</option>
              </select>
              <input
                type="number"
                value={targetValue}
                onChange={(e) => setTargetValue(e.target.value)}
                placeholder={targetType === 'pct' ? '0-100' : 'z.B. 100000'}
                className="flex-1 px-3 py-2 bg-body border border-border rounded-lg"
              />
            </div>
            <p className="text-xs text-text-muted mt-1">
              Pro Bucket nur ein Ziel-Typ aktiv.
            </p>
          </div>

          <div className="border-t border-border pt-4 space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={drawdownActive}
                onChange={(e) => setDrawdownActive(e.target.checked)}
              />
              Drawdown-Bremse aktiv
            </label>
            <div>
              <label className="text-xs text-text-secondary block mb-1">
                Schwellwert (%)
              </label>
              <input
                type="number"
                step="0.5"
                min="0"
                value={drawdownPct}
                onChange={(e) => setDrawdownPct(e.target.value)}
                disabled={!drawdownActive}
                className="w-32 px-3 py-2 bg-body border border-border rounded-lg disabled:opacity-50"
              />
            </div>
            <p className="text-xs text-text-muted">
              Alert wird einmal pro Tag ausgeloest, wenn der Bucket-Drawdown
              diese Schwelle erreicht. Mindestalter 7 Tage.
            </p>
          </div>

          <div className="border-t border-border pt-4 space-y-3">
            <p className="text-sm font-medium text-text-secondary">
              Weitere Risk-Rules (Phase 2)
            </p>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-text-secondary block mb-1">
                  Max Position-%
                </label>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={maxPositionPct}
                  onChange={(e) => setMaxPositionPct(e.target.value)}
                  placeholder="z.B. 10"
                  className="w-full px-3 py-2 bg-body border border-border rounded-lg"
                />
              </div>
              <div>
                <label className="text-xs text-text-secondary block mb-1">
                  Max Sektor-%
                </label>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={maxSectorPct}
                  onChange={(e) => setMaxSectorPct(e.target.value)}
                  placeholder="z.B. 25"
                  className="w-full px-3 py-2 bg-body border border-border rounded-lg"
                />
              </div>
              <div>
                <label className="text-xs text-text-secondary block mb-1">
                  Loss-Alert (%)
                </label>
                <input
                  type="number"
                  step="0.5"
                  value={alertLossPct}
                  onChange={(e) => setAlertLossPct(e.target.value)}
                  placeholder="z.B. -15"
                  className="w-full px-3 py-2 bg-body border border-border rounded-lg"
                />
              </div>
            </div>
            <p className="text-xs text-text-muted">
              Leer lassen, um den globalen Default zu verwenden. Max
              Position-% bezieht sich auf den Anteil am liquiden Portfolio,
              Max Sektor-% auf den Anteil eines Sektors am Bucket, Loss-Alert
              auf den Verlust einer einzelnen Position ohne Stop-Loss.
            </p>
          </div>
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
            onClick={save}
            disabled={busy || (isNew && !name.trim())}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50"
          >
            Speichern
          </button>
        </div>
      </div>
    </div>
  )
}
