import { useEffect, useId, useState } from 'react'
import { Plus, Trash2, Edit2, FolderTree, X, Sparkles, History, Loader2, AlertTriangle } from 'lucide-react'
import { authFetch } from '../../hooks/useApi'
import { formatNumber, formatDateShort } from '../../lib/format'
import { useToast } from '../../components/Toast'
import BucketTemplateModal from '../../components/BucketTemplateModal'
import BucketCorrelationCard from '../../components/BucketCorrelationCard'
import ImportRulesSection from '../../components/ImportRulesSection'
import useEscClose from '../../hooks/useEscClose'
import useFocusTrap from '../../hooks/useFocusTrap'
import Button from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { Toggle } from './shared'

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
  { value: 'MTUM', label: 'MSCI USA Momentum (MTUM)' },
  { value: '^STOXX50E', label: 'EuroStoxx 50' },
  { value: '^SSMI', label: 'SMI' },
  { value: '^IXIC', label: 'NASDAQ Composite' },
]

const MODAL_INPUT = 'w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'

export default function BucketsTab() {
  const toast = useToast()
  const [buckets, setBuckets] = useState([])
  const [limit, setLimit] = useState(15)
  const [activeCount, setActiveCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showTemplate, setShowTemplate] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [showBackfillConfirm, setShowBackfillConfirm] = useState(false)

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

  async function confirmDeleteBucket() {
    const b = deleteTarget
    if (!b) return
    try {
      const res = await authFetch(`/api/portfolio/buckets/${b.id}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || 'Löschen fehlgeschlagen')
      }
      const result = await res.json()
      toast(`Bucket gelöscht, ${result.positions_moved} Positionen verschoben`, 'success')
      reload()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setDeleteTarget(null)
    }
  }

  const userBuckets = buckets.filter((b) => b.kind === 'user' && !b.deleted_at)
  const systemBuckets = buckets.filter((b) => b.kind === 'system' && !b.deleted_at)
  const limitReached = activeCount >= limit
  const [backfilling, setBackfilling] = useState(false)

  async function runBackfill() {
    setShowBackfillConfirm(false)
    setBackfilling(true)
    try {
      const res = await authFetch('/api/portfolio/buckets/backfill-snapshots', {
        method: 'POST',
      })
      if (!res.ok) throw new Error('Backfill fehlgeschlagen')
      const data = await res.json()
      toast(
        `Backfill OK: ${data.days_filled} Einträge für ${data.buckets_touched} Buckets (${data.skipped_existing} bestehend)`,
        'success',
      )
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBackfilling(false)
    }
  }

  return (
    <div className="space-y-[18px]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <FolderTree size={16} className="text-primary" /> Buckets
          </h2>
          <p className="text-sm text-text-secondary mt-1">
            Segmentiere dein liquides Portfolio in Buckets mit eigenen Benchmarks
            und Drawdown-Bremsen. {activeCount}/{limit} User-Buckets aktiv.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button
            variant="secondary"
            icon={Sparkles}
            onClick={() => setShowTemplate(true)}
            disabled={limitReached}
            className="disabled:opacity-50"
            title="Buckets aus Template erstellen"
          >
            Template
          </Button>
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => setShowCreate(true)}
            disabled={limitReached}
            className="disabled:opacity-50"
          >
            Bucket
          </Button>
        </div>
      </div>

      {loading && <div className="text-text-muted text-sm">Lade...</div>}

      {!loading && (
        <>
          <section>
            <h3 className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-2">
              Deine Buckets
            </h3>
            {userBuckets.length === 0 ? (
              <div className="border border-dashed border-border rounded-card p-6 text-center text-sm text-text-muted">
                Noch keine User-Buckets. Erstelle einen via Template oder &quot;Bucket&quot;.
              </div>
            ) : (
              <ul className="bg-card border border-border rounded-card divide-y divide-border-row overflow-hidden">
                {userBuckets.map((b) => (
                  <BucketRow
                    key={b.id}
                    bucket={b}
                    onEdit={() => setEditing(b)}
                    onDelete={() => setDeleteTarget(b)}
                  />
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label mb-2">
              System-Buckets
            </h3>
            <p className="text-xs text-text-muted mb-2">
              Werden automatisch verwaltet, Name nicht editierbar. Benchmark
              und Farbe können angepasst werden.
            </p>
            <ul className="bg-card border border-border rounded-card divide-y divide-border-row overflow-hidden">
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

          {userBuckets.length >= 2 && <BucketCorrelationCard />}

          <ImportRulesSection buckets={buckets} />

          <section className="border-t border-border pt-4 space-y-2">
            <h3 className="font-mono text-[10.5px] tracking-[0.06em] uppercase text-text-label flex items-center gap-2">
              <History size={13} className="text-text-muted" /> Erweiterte Aktionen
            </h3>
            <div className="flex items-center justify-between gap-3 bg-card border border-border rounded-card p-3">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-text-primary">Bucket-Snapshots rückwirkend befüllen</div>
                <p className="text-xs text-text-muted mt-0.5">
                  Erzeugt fehlende bucket_snapshots aus portfolio_snapshots,
                  proportional zur aktuellen Bucket-Allokation. Non-destructive
                  (bestehende Snapshots bleiben). Sinnvoll für User ohne
                  Bucket-Wechsel-Historie.
                </p>
              </div>
              <Button
                variant="secondary"
                onClick={() => setShowBackfillConfirm(true)}
                disabled={backfilling}
                className="shrink-0 disabled:opacity-50"
              >
                {backfilling ? <Loader2 size={13} className="animate-spin" /> : <History size={13} />}
                {backfilling ? 'Läuft...' : 'Backfill starten'}
              </Button>
            </div>
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

      {deleteTarget && (
        <ConfirmModal
          title="Bucket löschen?"
          message={
            <>
              Bucket <span className="font-semibold">{deleteTarget.name}</span> wird
              gelöscht. Die Positionen wandern automatisch in den System-Bucket
              &laquo;Alle Positionen&raquo;. Historische Snapshots bleiben für
              Audit-Zwecke erhalten.
            </>
          }
          confirmLabel="Löschen"
          confirmTone="danger"
          onConfirm={confirmDeleteBucket}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {showBackfillConfirm && (
        <ConfirmModal
          title="Snapshots rückwirkend befüllen?"
          message={
            <>
              Es werden fehlende tägliche Bucket-Werte aus den bestehenden
              Portfolio-Snapshots abgeleitet, anteilig zur aktuellen
              Bucket-Allokation. Bestehende Bucket-Snapshots werden nicht
              überschrieben. Sinnvoll für User ohne Bucket-Wechsel-Historie.
            </>
          }
          confirmLabel="Backfill starten"
          confirmTone="primary"
          onConfirm={runBackfill}
          onCancel={() => setShowBackfillConfirm(false)}
        />
      )}
    </div>
  )
}

function ConfirmModal({ title, message, confirmLabel, confirmTone = 'primary', onConfirm, onCancel }) {
  useEscClose(onCancel)
  const trapRef = useFocusTrap(true)
  const tone = confirmTone === 'danger'
    ? 'bg-danger text-white hover:bg-danger/90'
    : 'bg-primary-btn border border-primary-btn-border text-white hover:bg-primary-btn-border'
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm p-4"
      onClick={onCancel}
    >
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="bucket-confirm-title"
        className="bg-modal border border-border-hover rounded-[14px] shadow-2xl max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 px-5 py-4 border-b border-border-2">
          <div className="p-2 rounded-full bg-warning/10 shrink-0">
            <AlertTriangle size={18} className="text-warning" />
          </div>
          <h3 id="bucket-confirm-title" className="text-sm font-semibold text-text-primary pt-1.5">
            {title}
          </h3>
        </div>
        <div className="px-5 py-4 text-sm text-text-secondary">{message}</div>
        <div className="px-5 py-4 border-t border-border-2 flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onCancel}>Abbrechen</Button>
          <button
            type="button"
            onClick={onConfirm}
            className={`inline-flex items-center gap-[7px] px-4 py-2 text-[12.5px] rounded-lg font-medium transition-colors ${tone}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
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
  // Wenn das Fenster auf das Bucket-Erstellungsdatum geklemmt wurde (Backfill-
  // Historie davor ist nicht bucket-spezifisch), nicht als "YTD" labeln.
  const benchClamped = bench?.clamped
  const benchStart = bench?.effective_start
    ? formatDateShort(`${bench.effective_start}T00:00:00`)
    : null
  const perfLabel = benchClamped ? `seit ${benchStart}` : 'YTD'
  const perfTitle = benchClamped
    ? 'Vergleich ab Bucket-Erstellung — frühere Werte stammen aus proportionalem Backfill und sind nicht bucket-spezifisch.'
    : 'Year-to-Date vs Benchmark'

  return (
    <li className="px-4 py-3 flex items-center gap-3 hover:bg-hover transition-colors">
      <span
        className="w-3 h-3 rounded-full shrink-0"
        style={{ background: bucket.color || '#64748b' }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-text-primary">{bucket.name}</span>
          {bucket.system_role && (
            <Badge color="#7a8698" bg="rgba(122,134,152,0.13)">System</Badge>
          )}
        </div>
        <div className="text-xs text-text-muted flex flex-wrap gap-3 mt-0.5">
          {bucket.benchmark && <span>Benchmark: {bucket.benchmark}</span>}
          {bench?.bucket_return_pct != null && (
            <span className="tabular-nums" title={perfTitle}>
              {perfLabel}: <span className="text-text-primary">{fmtPct(bench.bucket_return_pct)}</span>
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
            <span>Ziel: {formatNumber(bucket.target_chf)} CHF</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={onEdit}
          aria-label="Bearbeiten"
          className="p-2 text-text-muted hover:text-text-primary rounded hover:bg-hover transition-colors"
        >
          <Edit2 size={14} />
        </button>
        {onDelete && (
          <button
            onClick={onDelete}
            aria-label="Löschen"
            className="p-2 text-danger hover:bg-danger/10 rounded transition-colors"
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

  useEscClose(onClose)
  const trapRef = useFocusTrap(true)
  const uid = useId()
  const ids = {
    name: `${uid}-name`,
    benchmark: `${uid}-benchmark`,
    targetType: `${uid}-target-type`,
    targetValue: `${uid}-target-value`,
    drawdownActive: `${uid}-drawdown-active`,
    drawdownPct: `${uid}-drawdown-pct`,
    maxPosition: `${uid}-max-position`,
    maxSector: `${uid}-max-sector`,
    maxTotal: `${uid}-max-total`,
    alertLoss: `${uid}-alert-loss`,
    title: `${uid}-title`,
  }

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
  const [maxTotalPct, setMaxTotalPct] = useState(
    bucket?.risk_rules?.max_total_pct ?? '',
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
          max_total_pct: parseOrNull(maxTotalPct),
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
      className="fixed inset-0 z-[80] bg-[#04070c]/[0.72] backdrop-blur-sm flex items-center justify-center p-4"
    >
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={ids.title}
        className="bg-modal border border-border-hover rounded-[14px] max-w-lg w-full shadow-2xl max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-2 sticky top-0 bg-modal">
          <h3 id={ids.title} className="text-sm font-semibold text-text-primary">
            {isNew ? 'Neuer Bucket' : `Bucket: ${bucket.name}`}
          </h3>
          <button onClick={onClose} aria-label="Schliessen" className="text-text-muted hover:text-text-primary">
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {!isSystem && (
            <div>
              <label htmlFor={ids.name} className="text-xs font-medium text-text-muted block mb-1">
                Name
              </label>
              <input
                id={ids.name}
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={50}
                className={MODAL_INPUT}
              />
            </div>
          )}

          <div role="group" aria-label="Farbe">
            <span className="text-xs font-medium text-text-muted block mb-1.5">Farbe</span>
            <div className="flex flex-wrap gap-2">
              {PALETTE.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  aria-label={`Farbe ${c}`}
                  aria-pressed={color === c}
                  className={`w-7 h-7 rounded-full border-2 transition-colors ${
                    color === c ? 'border-text-primary' : 'border-transparent'
                  }`}
                  style={{ background: c }}
                />
              ))}
            </div>
          </div>

          <div>
            <label htmlFor={ids.benchmark} className="text-xs font-medium text-text-muted block mb-1">
              Benchmark
            </label>
            <select
              id={ids.benchmark}
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
              className={MODAL_INPUT}
            >
              {BENCHMARK_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor={ids.targetValue} className="text-xs font-medium text-text-muted block mb-1">
              Ziel-Allokation
            </label>
            <div className="flex gap-2">
              <select
                id={ids.targetType}
                aria-label="Ziel-Typ"
                value={targetType}
                onChange={(e) => setTargetType(e.target.value)}
                className="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
              >
                <option value="pct">in Prozent</option>
                <option value="chf">in CHF</option>
              </select>
              <input
                id={ids.targetValue}
                type="number"
                value={targetValue}
                onChange={(e) => setTargetValue(e.target.value)}
                placeholder={targetType === 'pct' ? '0-100' : 'z.B. 100000'}
                className={`flex-1 ${MODAL_INPUT}`}
              />
            </div>
            <p className="text-xs text-text-muted mt-1">
              Pro Bucket nur ein Ziel-Typ aktiv.
            </p>
          </div>

          <div className="border-t border-border-2 pt-4 space-y-2.5">
            <label className="flex items-center gap-2.5 text-sm text-text-primary">
              <Toggle
                checked={drawdownActive}
                onChange={(v) => setDrawdownActive(v)}
                ariaLabel="Drawdown-Bremse aktiv"
              />
              Drawdown-Bremse aktiv
            </label>
            <div>
              <label htmlFor={ids.drawdownPct} className="text-xs font-medium text-text-muted block mb-1">
                Schwellwert (%)
              </label>
              <input
                id={ids.drawdownPct}
                type="number"
                step="0.5"
                min="0"
                value={drawdownPct}
                onChange={(e) => setDrawdownPct(e.target.value)}
                disabled={!drawdownActive}
                className="w-32 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors disabled:opacity-50"
              />
            </div>
            <p className="text-xs text-text-muted">
              Alert wird einmal pro Tag ausgelöst, wenn der Bucket-Drawdown
              diese Schwelle erreicht. Mindestalter 7 Tage.
            </p>
          </div>

          <div className="border-t border-border-2 pt-4 space-y-3">
            <p className="text-sm font-medium text-text-secondary">
              Weitere Risk-Rules (Phase 2)
            </p>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label htmlFor={ids.maxPosition} className="text-xs font-medium text-text-muted block mb-1">
                  Max Position-%
                </label>
                <input
                  id={ids.maxPosition}
                  type="number"
                  step="0.5"
                  min="0"
                  value={maxPositionPct}
                  onChange={(e) => setMaxPositionPct(e.target.value)}
                  placeholder="z.B. 10"
                  className={MODAL_INPUT}
                />
              </div>
              <div>
                <label htmlFor={ids.maxSector} className="text-xs font-medium text-text-muted block mb-1">
                  Max Sektor-%
                </label>
                <input
                  id={ids.maxSector}
                  type="number"
                  step="0.5"
                  min="0"
                  value={maxSectorPct}
                  onChange={(e) => setMaxSectorPct(e.target.value)}
                  placeholder="z.B. 25"
                  className={MODAL_INPUT}
                />
              </div>
              <div>
                <label htmlFor={ids.alertLoss} className="text-xs font-medium text-text-muted block mb-1">
                  Loss-Alert (%)
                </label>
                <input
                  id={ids.alertLoss}
                  type="number"
                  step="0.5"
                  value={alertLossPct}
                  onChange={(e) => setAlertLossPct(e.target.value)}
                  placeholder="z.B. -15"
                  className={MODAL_INPUT}
                />
              </div>
              <div>
                <label htmlFor={ids.maxTotal} className="text-xs font-medium text-text-muted block mb-1">
                  Max % am Gesamtportfolio
                </label>
                <input
                  id={ids.maxTotal}
                  type="number"
                  step="0.5"
                  min="0"
                  max="100"
                  value={maxTotalPct}
                  onChange={(e) => setMaxTotalPct(e.target.value)}
                  placeholder="z.B. 30"
                  className={MODAL_INPUT}
                />
                <p className="text-[10px] text-text-muted mt-0.5">
                  Cross-Bucket-Constraint: Mail wenn Bucket-Anteil &gt; Limit.
                </p>
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

        <div className="px-5 py-4 border-t border-border-2 flex justify-end gap-2 sticky bottom-0 bg-modal">
          <Button variant="secondary" onClick={onClose} disabled={busy}>Abbrechen</Button>
          <Button
            variant="primary"
            onClick={save}
            disabled={busy || (isNew && !name.trim())}
            className="disabled:opacity-50"
          >
            Speichern
          </Button>
        </div>
      </div>
    </div>
  )
}
