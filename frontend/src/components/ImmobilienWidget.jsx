import { useState, useCallback, cloneElement, isValidElement, Children } from 'react'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import G from './GlossarTooltip'
import { useApi, apiPost, apiPut, apiDelete } from '../hooks/useApi'
import { formatCHF, formatCHFExact, formatPct } from '../lib/format'
import { Home, ChevronDown, ChevronUp, Plus, Pencil, Trash2, X, Info, MoreVertical } from 'lucide-react'
import DateInput from './DateInput'
import { useToast } from './Toast'
import DeleteConfirm from './DeleteConfirm'

const PROPERTY_TYPE_LABELS = { efh: 'EFH', mfh: 'MFH', stockwerk: 'StWE', grundstueck: 'Grundstück' }
const MORTGAGE_TYPE_LABELS = { fixed: 'Fixed', saron: 'SARON', variable: 'Variabel' }
const MORTGAGE_TYPE_STYLES = {
  fixed: 'bg-primary/10 text-primary border-primary/20',
  saron: 'bg-success/10 text-success border-success/20',
  variable: 'bg-warning/10 text-warning border-warning/20',
}
const EXPENSE_CAT_LABELS = {
  insurance: 'Versicherung', utilities: 'Nebenkosten', maintenance: 'Unterhalt',
  repair: 'Reparatur', tax: 'Steuern', other: 'Sonstiges',
}
const FREQ_LABELS = { monthly: 'Monatlich', quarterly: 'Quartal', yearly: 'Jährlich', once: 'Einmalig' }

function LtvBadge({ ltv, status }) {
  const colors = {
    green: 'bg-success/10 text-success border-success/20',
    yellow: 'bg-warning/10 text-warning border-warning/20',
    red: 'bg-danger/10 text-danger border-danger/20',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${colors[status] || colors.green}`}>
      {ltv.toFixed(1)}%
    </span>
  )
}

function MetricCard({ label, value, sub, color }) {
  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-3">
      <div className="text-xs text-text-muted mb-1">{label}</div>
      <div className={`text-base font-bold tabular-nums ${color || 'text-text-primary'}`}>{value}</div>
      {sub && <div className="text-xs text-text-muted mt-0.5">{sub}</div>}
    </div>
  )
}

function EquityBar({ equity, mortgage, value }) {
  if (!value || value <= 0) return null
  const eqPct = (equity / value) * 100
  return (
    <div className="h-2 rounded-full bg-border overflow-hidden flex">
      <div className="h-full bg-success rounded-l-full transition-all" style={{ width: `${eqPct}%` }} />
      <div className="h-full bg-danger/60 rounded-r-full transition-all" style={{ width: `${100 - eqPct}%` }} />
    </div>
  )
}

function RefinancingCountdown({ days, endDate }) {
  if (days == null) return null
  const totalDays = 365 * 2
  const pct = Math.max(0, Math.min(100, ((totalDays - days) / totalDays) * 100))
  const urgency = days <= 180 ? 'bg-danger' : days <= 365 ? 'bg-warning' : 'bg-primary'
  return (
    <div className="mt-3">
      <div className="flex justify-between text-xs text-text-muted mb-1">
        <span>Nächste Refinanzierung</span>
        <span>{endDate} ({days} Tage)</span>
      </div>
      <div className="h-2 rounded-full bg-border overflow-hidden">
        <div className={`h-full rounded-full ${urgency} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// --- Modals ---

function ModalWrapper({ title, onClose, children }) {
  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="text-sm font-medium text-text-primary">{title}</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary" aria-label="Schliessen"><X size={18} /></button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  )
}

function FormField({ id, label, children }) {
  const fieldId = id || `immo-${label.toLowerCase().replace(/[^a-z0-9]/g, '-')}`
  const childArr = Children.toArray(children)
  const firstChild = childArr[0]
  return (
    <div>
      <label htmlFor={fieldId} className="block text-xs text-text-muted mb-1">{label}</label>
      {childArr.length === 1 && isValidElement(firstChild)
        ? cloneElement(firstChild, { id: firstChild.props.id || fieldId })
        : children}
    </div>
  )
}

const inputCls = 'w-full bg-card-alt border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:border-primary focus:outline-none'
const selectCls = inputCls
const btnPrimary = 'px-4 py-2 bg-primary text-white text-sm rounded-lg hover:bg-primary/90 transition-colors'
const btnSecondary = 'px-4 py-2 border border-border text-text-muted text-sm rounded-lg hover:border-primary hover:text-primary transition-colors'

function PropertyEditModal({ property, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({
    name: property.name || '',
    address: property.address || '',
    estimated_value: property.estimated_value || '',
    estimated_value_date: property.estimated_value_date || '',
    canton: property.canton || '',
    notes: property.notes || '',
    property_type: property.property_type || 'efh',
    purchase_price: property.purchase_price || '',
    purchase_date: property.purchase_date || '',
  })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiPut(`/properties/${property.id}`, {
        ...form,
        estimated_value: form.estimated_value ? Number(form.estimated_value) : null,
        purchase_price: form.purchase_price ? Number(form.purchase_price) : undefined,
      })
      onSaved?.()
      onClose()
    } catch (e) { toast('Fehler: ' + (e.message || 'Unbekannter Fehler'), 'error') } finally { setSaving(false) }
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <ModalWrapper title="Immobilie bearbeiten" onClose={onClose}>
      <div className="space-y-3">
        <FormField label="Name"><input className={inputCls} value={form.name} onChange={set('name')} /></FormField>
        <FormField label="Adresse"><input className={inputCls} value={form.address} onChange={set('address')} /></FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Typ">
            <select className={selectCls} value={form.property_type} onChange={set('property_type')}>
              {Object.entries(PROPERTY_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </FormField>
          <FormField label="Kanton"><input className={inputCls} value={form.canton} onChange={set('canton')} maxLength={2} /></FormField>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Schätzwert"><input type="number" className={inputCls} value={form.estimated_value} onChange={set('estimated_value')} /></FormField>
          <FormField label="Schätzdatum"><DateInput className={inputCls} value={form.estimated_value_date} onChange={(v) => setForm(f => ({...f, estimated_value_date: v}))} /></FormField>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Kaufpreis"><input type="number" className={inputCls} value={form.purchase_price} onChange={set('purchase_price')} /></FormField>
          <FormField label="Kaufdatum"><DateInput className={inputCls} value={form.purchase_date} onChange={(v) => setForm(f => ({...f, purchase_date: v}))} /></FormField>
        </div>
        <FormField label="Notizen"><textarea className={inputCls} rows={2} value={form.notes} onChange={set('notes')} /></FormField>
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnSecondary} onClick={onClose}>Abbrechen</button>
          <button className={btnPrimary} onClick={handleSave} disabled={saving}>{saving ? 'Speichere...' : 'Speichern'}</button>
        </div>
      </div>
    </ModalWrapper>
  )
}

function MortgageModal({ propertyId, mortgage, saronRate, onClose, onSaved }) {
  const toast = useToast()
  const isEdit = !!mortgage
  const [form, setForm] = useState({
    name: mortgage?.name || '',
    type: mortgage?.type || 'fixed',
    amount: mortgage?.amount || '',
    interest_rate: mortgage?.interest_rate || '',
    margin_rate: mortgage?.margin_rate ?? '',
    start_date: mortgage?.start_date || '',
    end_date: mortgage?.end_date || '',
    amortization_annual: mortgage?.amortization_annual || '',
    bank: mortgage?.bank || '',
    notes: mortgage?.notes || '',
  })
  const [saving, setSaving] = useState(false)

  const isSaron = form.type === 'saron'
  const marginVal = parseFloat(form.margin_rate) || 0
  const effectiveRate = isSaron && form.margin_rate !== ''
    ? Math.max(marginVal, marginVal + (saronRate || 0))
    : null

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload = {
        ...form,
        amount: Number(form.amount),
        amortization_annual: form.amortization_annual ? Number(form.amortization_annual) : null,
      }
      if (isSaron && form.margin_rate !== '') {
        payload.margin_rate = Number(form.margin_rate)
        payload.interest_rate = effectiveRate != null ? Math.round(effectiveRate * 1000) / 1000 : Number(form.interest_rate)
      } else {
        payload.interest_rate = Number(form.interest_rate)
        payload.margin_rate = null
      }
      if (isEdit) {
        await apiPut(`/properties/mortgages/${mortgage.id}`, payload)
      } else {
        await apiPost(`/properties/${propertyId}/mortgages`, payload)
      }
      onSaved?.()
      onClose()
    } catch (e) { toast('Fehler: ' + (e.message || 'Unbekannter Fehler'), 'error') } finally { setSaving(false) }
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <ModalWrapper title={isEdit ? 'Hypothek bearbeiten' : 'Hypothek hinzufügen'} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Name"><input className={inputCls} value={form.name} onChange={set('name')} /></FormField>
          <FormField label="Typ">
            <select className={selectCls} value={form.type} onChange={set('type')}>
              {Object.entries(MORTGAGE_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </FormField>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Betrag"><input type="number" className={inputCls} value={form.amount} onChange={set('amount')} /></FormField>
          {isSaron ? (
            <FormField label="Marge %">
              <input type="number" step="0.001" className={inputCls} value={form.margin_rate} onChange={set('margin_rate')} placeholder="z.B. 0.780" />
            </FormField>
          ) : (
            <FormField label="Zinssatz %"><input type="number" step="0.001" className={inputCls} value={form.interest_rate} onChange={set('interest_rate')} /></FormField>
          )}
        </div>
        {isSaron && form.margin_rate !== '' && (
          <div className="rounded-lg bg-card-alt/40 border border-border px-3 py-2 text-xs text-text-secondary">
            Effektiver Zinssatz: <span className="font-semibold text-text-primary">{effectiveRate != null ? effectiveRate.toFixed(3) : '–'}%</span>
            <span className="text-text-muted ml-2">(Marge {marginVal.toFixed(3)}% + SARON {saronRate != null ? `${saronRate >= 0 ? '+' : ''}${saronRate.toFixed(2)}` : '–'}%)</span>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Start"><DateInput className={inputCls} value={form.start_date} onChange={(v) => setForm(f => ({...f, start_date: v}))} /></FormField>
          <FormField label="Ende"><DateInput className={inputCls} value={form.end_date} onChange={(v) => setForm(f => ({...f, end_date: v}))} /></FormField>
        </div>
        <FormField label="Amortisation jährl."><input type="number" className={inputCls} value={form.amortization_annual} onChange={set('amortization_annual')} placeholder="0" /></FormField>
        <FormField label="Bank"><input className={inputCls} value={form.bank} onChange={set('bank')} /></FormField>
        <FormField label="Notizen"><textarea className={inputCls} rows={2} value={form.notes} onChange={set('notes')} /></FormField>
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnSecondary} onClick={onClose}>Abbrechen</button>
          <button className={btnPrimary} onClick={handleSave} disabled={saving}>{saving ? 'Speichere...' : 'Speichern'}</button>
        </div>
      </div>
    </ModalWrapper>
  )
}

function ExpenseModal({ propertyId, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    category: 'other',
    description: '',
    amount: '',
    recurring: false,
    frequency: 'once',
  })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiPost(`/properties/${propertyId}/expenses`, { ...form, amount: Number(form.amount) })
      onSaved?.()
      onClose()
    } catch (e) { toast('Fehler: ' + (e.message || 'Unbekannter Fehler'), 'error') } finally { setSaving(false) }
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  return (
    <ModalWrapper title="Ausgabe erfassen" onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Datum"><DateInput className={inputCls} value={form.date} onChange={(v) => setForm(f => ({...f, date: v}))} /></FormField>
          <FormField label="Kategorie">
            <select className={selectCls} value={form.category} onChange={set('category')}>
              {Object.entries(EXPENSE_CAT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </FormField>
        </div>
        <FormField label="Beschreibung"><input className={inputCls} value={form.description} onChange={set('description')} /></FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Betrag CHF"><input type="number" className={inputCls} value={form.amount} onChange={set('amount')} /></FormField>
          <FormField label="Häufigkeit">
            <select className={selectCls} value={form.frequency} onChange={set('frequency')}>
              {Object.entries(FREQ_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </FormField>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnSecondary} onClick={onClose}>Abbrechen</button>
          <button className={btnPrimary} onClick={handleSave} disabled={saving}>{saving ? 'Speichere...' : 'Speichern'}</button>
        </div>
      </div>
    </ModalWrapper>
  )
}

function IncomeModal({ propertyId, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    description: '',
    amount: '',
    tenant: '',
    recurring: false,
    frequency: 'monthly',
  })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await apiPost(`/properties/${propertyId}/income`, { ...form, amount: Number(form.amount) })
      onSaved?.()
      onClose()
    } catch (e) { toast('Fehler: ' + (e.message || 'Unbekannter Fehler'), 'error') } finally { setSaving(false) }
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  return (
    <ModalWrapper title="Einnahme erfassen" onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Datum"><DateInput className={inputCls} value={form.date} onChange={(v) => setForm(f => ({...f, date: v}))} /></FormField>
          <FormField label="Mieter"><input className={inputCls} value={form.tenant} onChange={set('tenant')} /></FormField>
        </div>
        <FormField label="Beschreibung"><input className={inputCls} value={form.description} onChange={set('description')} /></FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Betrag CHF"><input type="number" className={inputCls} value={form.amount} onChange={set('amount')} /></FormField>
          <FormField label="Häufigkeit">
            <select className={selectCls} value={form.frequency} onChange={set('frequency')}>
              {Object.entries(FREQ_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </FormField>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnSecondary} onClick={onClose}>Abbrechen</button>
          <button className={btnPrimary} onClick={handleSave} disabled={saving}>{saving ? 'Speichere...' : 'Speichern'}</button>
        </div>
      </div>
    </ModalWrapper>
  )
}

// --- Property Block ---

function PropertyBlock({ property, onRefresh, saronRate }) {
  const toast = useToast()
  const [expanded, setExpanded] = useState(true)
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editModal, setEditModal] = useState(null) // 'property' | 'mortgage' | 'expense' | 'income'
  const [editMortgage, setEditMortgage] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null) // { type, id, label }

  const [deleteProperty, setDeleteProperty] = useState(false)

  const openCtxFor = useCallback((e) => {
    e.stopPropagation()
    const rect = e.currentTarget.getBoundingClientRect()
    setCtxMenu({ x: rect.left, y: rect.bottom + 4 })
  }, [])

  const confirmDelete = async () => {
    if (!deleteTarget) return
    try {
      const { type, id } = deleteTarget
      await apiDelete(`/properties/${type === 'mortgage' ? 'mortgages' : type === 'expense' ? 'expenses' : 'income'}/${id}`)
      onRefresh?.()
    } catch (e) {
      toast('Fehler: ' + (e.message || 'Unbekannter Fehler'), 'error')
    }
    setDeleteTarget(null)
  }

  const handleDelete = (type, id) => {
    const labels = { mortgage: 'Hypothek', expense: 'Ausgabe', income: 'Einnahme' }
    setDeleteTarget({ type, id, label: labels[type] })
  }

  const p = property
  const mortgages = p.mortgages || []
  const expenses = p.expenses || []
  const income = p.income || []

  return (
    <div className="border-b border-border last:border-b-0">
      {/* Header - always visible */}
      <div
        className="p-4 cursor-pointer hover:bg-card-alt/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-text-primary font-medium">{p.name}</span>
            <span className={`text-xs px-2 py-0.5 rounded border bg-card-alt/50 text-text-muted border-border`}>
              {PROPERTY_TYPE_LABELS[p.property_type] || p.property_type}
            </span>
            {p.canton && <span className="text-xs text-text-muted">{p.canton}</span>}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={(e) => { e.stopPropagation(); openCtxFor(e) }}
              className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
              title="Aktionen"
              aria-label="Aktionen öffnen"
            >
              <MoreVertical size={16} />
            </button>
            {expanded ? <ChevronUp size={16} className="text-text-muted" /> : <ChevronDown size={16} className="text-text-muted" />}
          </div>
        </div>

        <div className="grid grid-cols-4 gap-3">
          <MetricCard label={<G term="Marktwert">Marktwert</G>} value={formatCHF(p.estimated_value)} />
          <MetricCard label={<G term="Hypothek">Hypotheken</G>} value={formatCHF(p.current_mortgage)} sub={`Original: ${formatCHF(p.total_mortgage_original)}`} />
          <MetricCard label={<G term="Eigenkapital">Eigenkapital</G>} value={formatCHF(p.equity)} sub={`${p.equity_pct.toFixed(1)}%`} color="text-success" />
          <MetricCard label={<G term="LTV">LTV</G>} value={<LtvBadge ltv={p.ltv} status={p.ltv_status} />} />
        </div>

        <div className="mt-3">
          <EquityBar equity={p.equity} mortgage={p.current_mortgage} value={p.estimated_value} />
        </div>
      </div>

      {/* Expanded section */}
      {expanded && (
        <div className="px-4 pb-4 space-y-4">
          {/* Mortgage table */}
          {mortgages.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
                    <th className="text-left p-3 font-medium">Name</th>
                    <th className="text-left p-3 font-medium">Typ</th>
                    <th className="text-right p-3 font-medium">Betrag</th>
                    <th className="text-right p-3 font-medium">Zinssatz</th>
                    <th className="text-right p-3 font-medium">Jährl. Kosten</th>
                    <th className="text-right p-3 font-medium">Fälligkeit</th>
                    <th className="text-right p-3 font-medium">Verbleibend</th>
                    <th className="p-3 w-8"></th>
                  </tr>
                </thead>
                <tbody>
                  {mortgages.map((m) => (
                    <tr key={m.id} className="border-b border-border/50 hover:bg-card-alt/30">
                      <td className="p-3 text-text-primary">{m.name}</td>
                      <td className="p-3">
                        <span className={`text-xs px-2 py-0.5 rounded border ${MORTGAGE_TYPE_STYLES[m.type] || ''}`}>
                          {MORTGAGE_TYPE_LABELS[m.type] || m.type}
                        </span>
                      </td>
                      <td className="p-3 text-right text-text-primary tabular-nums">{formatCHF(m.amount)}</td>
                      <td className="p-3 text-right text-text-secondary tabular-nums">
                        {(m.effective_rate ?? m.interest_rate).toFixed(3)}%
                        {m.type === 'saron' && m.margin_rate != null && (
                          <div className="text-[10px] text-text-muted">Marge {m.margin_rate.toFixed(3)}%</div>
                        )}
                      </td>
                      <td className="p-3 text-right text-text-secondary tabular-nums">{formatCHF((m.amount * (m.effective_rate ?? m.interest_rate) / 100) + (m.amortization_annual || 0))}</td>
                      <td className="p-3 text-right text-text-secondary tabular-nums">{m.end_date || '–'}</td>
                      <td className="p-3 text-right text-text-secondary tabular-nums">
                        {m.days_until_maturity != null ? `${m.days_until_maturity}d` : '–'}
                      </td>
                      <td className="p-3">
                        <div className="flex gap-1">
                          <button onClick={() => { setEditMortgage(m); setEditModal('mortgage') }} className="text-text-muted hover:text-primary"><Pencil size={13} /></button>
                          <button onClick={() => handleDelete('mortgage', m.id)} className="text-text-muted hover:text-danger"><Trash2 size={13} /></button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  <tr className="bg-card-alt/30">
                    <td className="p-3 text-text-primary font-medium" colSpan={2}>Total</td>
                    <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(p.total_mortgage_original)}</td>
                    <td className="p-3"></td>
                    <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF((p.annual_interest || 0) + (p.annual_amortization || 0))}</td>
                    <td colSpan={3}></td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          {/* Refinancing countdown */}
          <RefinancingCountdown days={p.days_until_maturity} endDate={p.next_maturity} />

          {/* Annual cost summary */}
          <div className="rounded-lg border border-border bg-card-alt/20 p-3">
            <h4 className="text-xs font-medium text-text-muted mb-2">Jährliche Kosten</h4>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <div className="text-text-muted text-xs">Zinsen</div>
                <div className="text-text-primary font-medium tabular-nums">{formatCHF(p.annual_interest)}</div>
              </div>
              <div>
                <div className="text-text-muted text-xs">Amortisation</div>
                <div className="text-text-primary font-medium tabular-nums">{formatCHF(p.annual_amortization)}</div>
              </div>
              <div>
                <div className="text-text-muted text-xs">Total Hypothekarkosten</div>
                <div className="text-text-primary font-bold tabular-nums">{formatCHF(p.annual_interest + p.annual_amortization)}</div>
              </div>
            </div>
            {(p.annual_expenses > 0 || p.annual_income > 0) && (
              <div className="grid grid-cols-3 gap-4 text-sm mt-2 pt-2 border-t border-border">
                <div>
                  <div className="text-text-muted text-xs">Ausgaben</div>
                  <div className="text-danger font-medium tabular-nums">{formatCHF(p.annual_expenses)}</div>
                </div>
                <div>
                  <div className="text-text-muted text-xs">Einnahmen</div>
                  <div className="text-success font-medium tabular-nums">{formatCHF(p.annual_income)}</div>
                </div>
                <div>
                  <div className="text-text-muted text-xs">Netto</div>
                  <div className={`font-bold tabular-nums ${p.net_annual >= 0 ? 'text-success' : 'text-danger'}`}>{formatCHF(p.net_annual)}</div>
                </div>
              </div>
            )}
          </div>

          {/* Expenses */}
          {expenses.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-text-muted mb-2">Ausgaben (aktuelles Jahr)</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
                      <th className="text-left p-3 font-medium">Datum</th>
                      <th className="text-left p-3 font-medium">Kategorie</th>
                      <th className="text-left p-3 font-medium">Beschreibung</th>
                      <th className="text-right p-3 font-medium">Betrag</th>
                      <th className="p-3 w-8"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {expenses.map((e) => (
                      <tr key={e.id} className="border-b border-border/50">
                        <td className="p-3 text-text-secondary tabular-nums">{e.date}</td>
                        <td className="p-3 text-text-secondary">{EXPENSE_CAT_LABELS[e.category] || e.category}</td>
                        <td className="p-3 text-text-primary">{e.description || '–'}</td>
                        <td className="p-3 text-right text-danger tabular-nums">{formatCHF(e.amount)}</td>
                        <td className="p-3">
                          <button onClick={() => handleDelete('expense', e.id)} className="text-text-muted hover:text-danger"><Trash2 size={13} /></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Income */}
          {income.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-text-muted mb-2">Einnahmen (aktuelles Jahr)</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
                      <th className="text-left p-3 font-medium">Datum</th>
                      <th className="text-left p-3 font-medium">Beschreibung</th>
                      <th className="text-left p-3 font-medium">Mieter</th>
                      <th className="text-right p-3 font-medium">Betrag</th>
                      <th className="p-3 w-8"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {income.map((i) => (
                      <tr key={i.id} className="border-b border-border/50">
                        <td className="p-3 text-text-secondary tabular-nums">{i.date}</td>
                        <td className="p-3 text-text-primary">{i.description || '–'}</td>
                        <td className="p-3 text-text-secondary">{i.tenant || '–'}</td>
                        <td className="p-3 text-right text-success tabular-nums">{formatCHF(i.amount)}</td>
                        <td className="p-3">
                          <button onClick={() => handleDelete('income', i.id)} className="text-text-muted hover:text-danger"><Trash2 size={13} /></button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </div>
      )}

      {/* Context menu */}
      {ctxMenu && (
        <div className="fixed inset-0 z-40" onClick={() => setCtxMenu(null)}>
          <div
            style={{ position: 'fixed', left: ctxMenu.x + 200 > window.innerWidth ? ctxMenu.x - 200 : ctxMenu.x, top: ctxMenu.y + 230 > window.innerHeight ? ctxMenu.y - 230 : ctxMenu.y, zIndex: 50 }}
            className="bg-card border border-border rounded-lg shadow-xl py-1 min-w-[170px]"
            onClick={(e) => e.stopPropagation()}
          >
            <button onClick={() => { setCtxMenu(null); setEditModal('property') }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors">
              <Pencil size={15} className="text-primary" /> Editieren
            </button>
            <button onClick={() => { setCtxMenu(null); setEditMortgage(null); setEditModal('mortgage') }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors">
              <Plus size={15} className="text-primary" /> Hypothek hinzufügen
            </button>
            <button onClick={() => { setCtxMenu(null); setEditModal('expense') }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors">
              <Plus size={15} className="text-primary" /> Ausgabe erfassen
            </button>
            <button onClick={() => { setCtxMenu(null); setEditModal('income') }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors">
              <Plus size={15} className="text-primary" /> Einnahme erfassen
            </button>
            <div className="border-t border-border my-1" />
            <button onClick={() => { setCtxMenu(null); setDeleteProperty(true) }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-danger hover:bg-card-alt transition-colors">
              <Trash2 size={15} /> Immobilie löschen
            </button>
          </div>
        </div>
      )}

      {/* Modals */}
      {editModal === 'property' && (
        <PropertyEditModal property={p} onClose={() => setEditModal(null)} onSaved={onRefresh} />
      )}
      {editModal === 'mortgage' && (
        <MortgageModal propertyId={p.id} mortgage={editMortgage} saronRate={saronRate} onClose={() => setEditModal(null)} onSaved={onRefresh} />
      )}
      {editModal === 'expense' && (
        <ExpenseModal propertyId={p.id} onClose={() => setEditModal(null)} onSaved={onRefresh} />
      )}
      {editModal === 'income' && (
        <IncomeModal propertyId={p.id} onClose={() => setEditModal(null)} onSaved={onRefresh} />
      )}

      {deleteTarget && (
        <DeleteConfirm
          name={deleteTarget.label}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {deleteProperty && (
        <DeleteConfirm
          name={p.name}
          onConfirm={async () => {
            try {
              await apiDelete(`/properties/${p.id}`)
              onRefresh?.()
            } catch (e) {
              toast('Fehler: ' + (e.message || 'Unbekannter Fehler'), 'error')
            }
            setDeleteProperty(false)
          }}
          onCancel={() => setDeleteProperty(false)}
        />
      )}
    </div>
  )
}

const CANTONS = ['AG','AI','AR','BE','BL','BS','FR','GE','GL','GR','JU','LU','NE','NW','OW','SG','SH','SO','SZ','TG','TI','UR','VD','VS','ZG','ZH']

function AddPropertyModal({ onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({
    name: '', address: '', property_type: 'efh', purchase_date: '',
    purchase_price: '', estimated_value: '', canton: '',
    living_area_m2: '', land_area_m2: '', rooms: '', year_built: '',
  })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload = {
        ...form,
        purchase_price: Number(form.purchase_price),
        estimated_value: form.estimated_value ? Number(form.estimated_value) : Number(form.purchase_price),
        living_area_m2: form.living_area_m2 ? Number(form.living_area_m2) : null,
        land_area_m2: form.land_area_m2 ? Number(form.land_area_m2) : null,
        rooms: form.rooms ? Number(form.rooms) : null,
        year_built: form.year_built ? Number(form.year_built) : null,
        estimated_value_date: form.purchase_date || null,
      }
      await apiPost('/properties', payload)
      onSaved?.()
      onClose()
    } catch (e) { toast('Fehler: ' + (e.message || 'Unbekannter Fehler'), 'error') } finally { setSaving(false) }
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <ModalWrapper title="Immobilie hinzufügen" onClose={onClose}>
      <div className="space-y-3">
        <FormField label="Name"><input className={inputCls} value={form.name} onChange={set('name')} placeholder="z.B. MFH Hauptstrasse Zürich" /></FormField>
        <FormField label="Adresse"><input className={inputCls} value={form.address} onChange={set('address')} /></FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Typ">
            <select className={selectCls} value={form.property_type} onChange={set('property_type')}>
              {Object.entries(PROPERTY_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </FormField>
          <FormField label="Kanton">
            <select className={selectCls} value={form.canton} onChange={set('canton')}>
              <option value="">–</option>
              {CANTONS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </FormField>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Kaufdatum"><DateInput className={inputCls} value={form.purchase_date} onChange={(v) => setForm(f => ({...f, purchase_date: v}))} /></FormField>
          <FormField label="Kaufpreis CHF"><input type="number" className={inputCls} value={form.purchase_price} onChange={set('purchase_price')} /></FormField>
        </div>
        <FormField label="Geschätzter Marktwert CHF (leer = Kaufpreis)">
          <input type="number" className={inputCls} value={form.estimated_value} onChange={set('estimated_value')} />
        </FormField>
        <div className="grid grid-cols-3 gap-3">
          <FormField label="Wohnfläche m²"><input type="number" className={inputCls} value={form.living_area_m2} onChange={set('living_area_m2')} /></FormField>
          <FormField label="Grundstück m²"><input type="number" className={inputCls} value={form.land_area_m2} onChange={set('land_area_m2')} /></FormField>
          <FormField label="Zimmer"><input type="number" step="0.5" className={inputCls} value={form.rooms} onChange={set('rooms')} /></FormField>
        </div>
        <FormField label="Baujahr"><input type="number" className={inputCls} value={form.year_built} onChange={set('year_built')} /></FormField>
        <div className="flex justify-end gap-2 pt-2">
          <button className={btnSecondary} onClick={onClose}>Abbrechen</button>
          <button className={btnPrimary} onClick={handleSave} disabled={saving || !form.name || !form.purchase_price}>{saving ? 'Speichere...' : 'Speichern'}</button>
        </div>
      </div>
    </ModalWrapper>
  )
}

// --- Main Widget ---

function SaronCard({ marketData }) {
  if (!marketData) return null

  const rate = marketData.saron_rate
  const dateStr = marketData.saron_date
  const source = marketData.saron_source || 'SNB'
  const sourceLabel = source === 'SNB' ? 'automatisch' : source

  // Stale if date is > 7 days old
  let isStale = false
  if (dateStr) {
    const d = new Date(dateStr)
    const diffDays = (Date.now() - d.getTime()) / (1000 * 60 * 60 * 24)
    isStale = diffDays > 7
  }

  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="text-xs text-text-muted mb-1"><G term="SARON">SARON</G> Leitzins</div>
      <div className="text-lg font-bold text-text-primary tabular-nums">
        {rate != null ? `${rate.toFixed(2)}%` : '–'}
      </div>
      <div className="text-xs text-text-muted mt-1 flex items-center gap-1">
        {dateStr && <span>Stand: {dateStr}</span>}
        {dateStr && <span>|</span>}
        <span>{sourceLabel}</span>
        {isStale && <span className="text-warning">(veraltet)</span>}
      </div>
    </div>
  )
}

export default function ImmobilienWidget({ onRefresh }) {
  const { data, refetch } = useApi('/properties')
  const { data: marketData } = useApi('/market/real-estate')
  const [showAddProperty, setShowAddProperty] = useState(false)

  const handleRefresh = useCallback(() => {
    refetch()
    onRefresh?.()
  }, [refetch, onRefresh])

  const properties = data?.properties || []

  return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-teal-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Home size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">Immobilien</h3>
        </div>
        <button
          onClick={() => setShowAddProperty(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-border text-text-secondary hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
        >
          <Plus size={13} />
          Immobilie hinzufügen
        </button>
      </div>

      {/* SARON rate */}
      <div className="p-4">
        <SaronCard marketData={marketData} />
      </div>

      {/* Properties */}
      {properties.map((p) => (
        <PropertyBlock key={p.id} property={p} onRefresh={handleRefresh} saronRate={marketData?.saron_rate} />
      ))}

      {properties.length === 0 && (
        <div className="p-6 text-center">
          <p className="text-text-muted text-sm">Keine Immobilien vorhanden.</p>
          <button onClick={() => setShowAddProperty(true)} className="mt-2 text-primary text-sm hover:underline">
            Immobilie hinzufügen
          </button>
        </div>
      )}

      {showAddProperty && (
        <AddPropertyModal
          onClose={() => setShowAddProperty(false)}
          onSaved={handleRefresh}
        />
      )}
    </div>
  )
}
