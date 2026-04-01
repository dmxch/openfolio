import { useState, useMemo, useCallback } from 'react'
import { useApi, apiPost, apiPut, apiDelete } from '../hooks/useApi'
import { useToast } from './Toast'
import { formatCHF, formatPct, formatDate } from '../lib/format'
import { Building2, Plus, Pencil, Trash2, X, TrendingUp, Banknote, MoreVertical } from 'lucide-react'
import DateInput from './DateInput'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'

function MetricCard({ label, value, sub }) {
  return (
    <div className="bg-card-alt/50 rounded-lg p-3 border border-border">
      <div className="text-xs text-text-muted mb-1">{label}</div>
      <div className="text-base font-bold text-text-primary">{value}</div>
      {sub && <div className="text-xs text-text-secondary mt-0.5">{sub}</div>}
    </div>
  )
}

export default function PrivateEquityWidget({ onRefresh }) {
  const { data, loading, refetch } = useApi('/private-equity')
  const [showAdd, setShowAdd] = useState(false)
  const [detail, setDetail] = useState(null)
  const [editHolding, setEditHolding] = useState(null)

  const refresh = useCallback(() => { refetch(); onRefresh?.() }, [refetch, onRefresh])

  if (loading) return <div className="animate-pulse h-20 bg-card rounded-lg" />
  if (!data?.holdings?.length && !showAdd) {
    return (
      <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-emerald-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)] p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-text-primary flex items-center gap-2">
            <Building2 size={20} className="text-emerald-500" />
            Direktbeteiligungen
          </h3>
          <button onClick={() => setShowAdd(true)} className="flex items-center gap-1 px-3 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90">
            <Plus size={14} /> Beteiligung
          </button>
        </div>
        <p className="text-sm text-text-muted">Noch keine Direktbeteiligungen erfasst.</p>
        {showAdd && <HoldingForm onClose={() => setShowAdd(false)} onSave={refresh} />}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-emerald-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)] p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-text-primary flex items-center gap-2">
          <Building2 size={20} className="text-emerald-500" />
          Direktbeteiligungen
          {data?.total_gross_value > 0 && (
            <span className="text-sm font-normal text-text-secondary ml-2">{formatCHF(data.total_gross_value)}</span>
          )}
        </h3>
        <button onClick={() => setShowAdd(true)} className="flex items-center gap-1 px-3 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90">
          <Plus size={14} /> Beteiligung
        </button>
      </div>

      {showAdd && <HoldingForm onClose={() => setShowAdd(false)} onSave={refresh} />}

      <div className="space-y-2">
        {data.holdings.map((h) => (
          <HoldingRow key={h.id} holding={h} onRefresh={refresh} onDetail={setDetail} onEdit={setEditHolding} />
        ))}
      </div>

      {editHolding && <HoldingForm holding={editHolding} onClose={() => setEditHolding(null)} onSave={() => { setEditHolding(null); refresh() }} />}
      {detail && <HoldingDetail holdingId={detail} onClose={() => setDetail(null)} onRefresh={refresh} />}
    </div>
  )
}

function HoldingCtxMenu({ holding, pos, onClose, onEdit, onAddValuation, onAddDividend, onDelete }) {
  const left = pos.x + 200 > window.innerWidth ? pos.x - 200 : pos.x
  const top = pos.y + 200 > window.innerHeight ? pos.y - 200 : pos.y

  return (
    <div className="fixed inset-0 z-40" onClick={onClose}>
      <div
        style={{ position: 'fixed', left, top, zIndex: 50 }}
        className="bg-card border border-border rounded-lg shadow-xl py-1 min-w-[200px]"
        onClick={(e) => e.stopPropagation()}
      >
        <button onClick={() => { onClose(); onAddValuation() }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors">
          <TrendingUp size={15} className="text-primary" /> Bewertung hinzufügen
        </button>
        <button onClick={() => { onClose(); onAddDividend() }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors">
          <Banknote size={15} className="text-primary" /> Dividende hinzufügen
        </button>
        <div className="border-t border-border my-1" />
        <button onClick={() => { onClose(); onEdit() }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-text-primary hover:bg-card-alt transition-colors">
          <Pencil size={15} className="text-primary" /> Bearbeiten
        </button>
        <button onClick={() => { onClose(); onDelete() }} className="w-full flex items-center gap-3 px-4 py-2 text-sm text-danger hover:bg-card-alt transition-colors">
          <Trash2 size={15} /> Löschen
        </button>
      </div>
    </div>
  )
}

function HoldingRow({ holding: h, onRefresh, onDetail, onEdit }) {
  const toast = useToast()
  const [ctxMenu, setCtxMenu] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const deleteDialogRef = useFocusTrap(confirmDelete)
  useScrollLock(confirmDelete)
  const [inlineForm, setInlineForm] = useState(null) // 'valuation' | 'dividend'

  function openCtx(e) {
    e.stopPropagation()
    const rect = e.currentTarget.getBoundingClientRect()
    setCtxMenu({ x: rect.right, y: rect.bottom + 4 })
  }

  async function handleDelete() {
    try {
      await apiDelete(`/private-equity/${h.id}`)
      toast('Beteiligung gelöscht', 'success')
      onRefresh()
    } catch { toast('Fehler beim Löschen', 'error') }
  }

  return (
    <>
      <div className="flex items-center gap-4 py-3 px-3 rounded-lg hover:bg-card-alt/30 transition-colors group">
        <div className="flex-1 min-w-0 cursor-pointer" onClick={() => onDetail(h.id)}>
          <div className="text-sm font-medium text-text-primary truncate">{h.company_name}</div>
          <div className="text-xs text-text-muted">
            {h.num_shares.toLocaleString('de-CH')} Aktien · Nennwert {h.currency} {h.nominal_value.toFixed(2)}
            {h.uid_number && <span className="ml-2">· {h.uid_number}</span>}
          </div>
        </div>
        <div className="text-right shrink-0">
          {h.total_gross_value != null ? (
            <>
              <div className="text-sm font-bold text-text-primary">{formatCHF(h.total_gross_value)}</div>
              <div className="text-xs text-text-muted">
                {h.currency} {h.gross_value_per_share?.toFixed(2)}/Aktie
                {h.dividend_yield_pct != null && <span className="ml-1 text-success">· {h.dividend_yield_pct.toFixed(1)}% Rendite</span>}
              </div>
            </>
          ) : (
            <div className="text-xs text-text-muted">Keine Bewertung</div>
          )}
        </div>
        <button
          onClick={openCtx}
          className="p-1.5 rounded text-text-secondary hover:text-text-primary hover:bg-white/10 transition-colors"
          title="Aktionen"
          aria-label="Aktionen öffnen"
        >
          <MoreVertical size={16} />
        </button>
      </div>

      {inlineForm === 'valuation' && (
        <ValuationForm holdingId={h.id} onClose={() => setInlineForm(null)} onSave={() => { setInlineForm(null); onRefresh() }} />
      )}
      {inlineForm === 'dividend' && (
        <DividendForm holdingId={h.id} numShares={h.num_shares} onClose={() => setInlineForm(null)} onSave={() => { setInlineForm(null); onRefresh() }} />
      )}

      {ctxMenu && (
        <HoldingCtxMenu
          holding={h}
          pos={ctxMenu}
          onClose={() => setCtxMenu(null)}
          onEdit={() => onEdit(h)}
          onAddValuation={() => setInlineForm('valuation')}
          onAddDividend={() => setInlineForm('dividend')}
          onDelete={() => setConfirmDelete(true)}
        />
      )}

      {confirmDelete && (
        <div ref={deleteDialogRef} className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-label="Löschen bestätigen">
          <div className="fixed inset-0 bg-black/50" onClick={() => setConfirmDelete(false)} />
          <div className="relative bg-card border border-border rounded-xl shadow-2xl p-6 z-10 max-w-sm">
            <p className="text-sm text-text-primary mb-4">Beteiligung <strong>{h.company_name}</strong> wirklich löschen? Alle Bewertungen und Dividenden werden ebenfalls gelöscht.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmDelete(false)} className="px-3 py-1.5 text-xs text-text-muted hover:text-text-primary">Abbrechen</button>
              <button onClick={handleDelete} className="px-3 py-1.5 text-xs bg-danger text-white rounded-lg hover:bg-danger/90">Löschen</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function HoldingForm({ holding, onClose, onSave }) {
  const toast = useToast()
  const isEdit = !!holding
  const [form, setForm] = useState({
    company_name: holding?.company_name || '',
    num_shares: holding?.num_shares || '',
    nominal_value: holding?.nominal_value ?? '',
    purchase_price_per_share: holding?.purchase_price_per_share ?? '',
    purchase_date: holding?.purchase_date || '',
    currency: holding?.currency || 'CHF',
    uid_number: holding?.uid_number || '',
    register_nr: holding?.register_nr || '',
    notes: holding?.notes || '',
  })
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.company_name || !form.num_shares) return
    setSaving(true)
    try {
      const payload = {
        company_name: form.company_name,
        num_shares: parseInt(form.num_shares),
        nominal_value: parseFloat(form.nominal_value) || 0,
        purchase_price_per_share: form.purchase_price_per_share ? parseFloat(form.purchase_price_per_share) : null,
        purchase_date: form.purchase_date || null,
        currency: form.currency,
        uid_number: form.uid_number || null,
        register_nr: form.register_nr || null,
        notes: form.notes || null,
      }
      if (isEdit) {
        await apiPut(`/private-equity/${holding.id}`, payload)
        toast('Beteiligung aktualisiert', 'success')
      } else {
        await apiPost('/private-equity', payload)
        toast('Beteiligung erstellt', 'success')
      }
      onSave()
    } catch { toast('Fehler beim Speichern', 'error') }
    finally { setSaving(false) }
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="border border-border rounded-lg bg-card-alt/30 p-4 mb-4">
      <div className="flex justify-between items-center mb-3">
        <h4 className="text-sm font-medium text-text-primary">{isEdit ? 'Beteiligung bearbeiten' : 'Neue Beteiligung'}</h4>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={16} /></button>
      </div>
      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label htmlFor="pe-name" className="text-xs text-text-secondary">Firmenname *</label>
          <input id="pe-name" value={form.company_name} onChange={set('company_name')} required className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
        </div>
        <div>
          <label htmlFor="pe-shares" className="text-xs text-text-secondary">Anzahl Aktien *</label>
          <input id="pe-shares" type="number" min="1" value={form.num_shares} onChange={set('num_shares')} required className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
        </div>
        <div>
          <label htmlFor="pe-nominal" className="text-xs text-text-secondary">Nennwert/Aktie</label>
          <input id="pe-nominal" type="number" min="0" step="0.01" value={form.nominal_value} onChange={set('nominal_value')} className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
        </div>
        <div>
          <label htmlFor="pe-price" className="text-xs text-text-secondary">Kaufpreis/Aktie</label>
          <input id="pe-price" type="number" min="0" step="0.01" value={form.purchase_price_per_share} onChange={set('purchase_price_per_share')} className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
        </div>
        <div>
          <label htmlFor="pe-date" className="text-xs text-text-secondary">Kaufdatum</label>
          <DateInput id="pe-date" value={form.purchase_date} onChange={(v) => setForm((f) => ({ ...f, purchase_date: v }))} className="w-full mt-0.5" />
        </div>
        <div>
          <label htmlFor="pe-ccy" className="text-xs text-text-secondary">Währung</label>
          <select id="pe-ccy" value={form.currency} onChange={set('currency')} className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary">
            <option value="CHF">CHF</option><option value="EUR">EUR</option><option value="USD">USD</option>
          </select>
        </div>
        <div>
          <label htmlFor="pe-uid" className="text-xs text-text-secondary">UID (Unternehmen)</label>
          <input id="pe-uid" value={form.uid_number} onChange={set('uid_number')} placeholder="CHE-..." className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
        </div>
        <div>
          <label htmlFor="pe-reg" className="text-xs text-text-secondary">Register-Nr.</label>
          <input id="pe-reg" value={form.register_nr} onChange={set('register_nr')} className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
        </div>
        <div className="md:col-span-2">
          <label htmlFor="pe-notes" className="text-xs text-text-secondary">Notizen</label>
          <textarea id="pe-notes" value={form.notes} onChange={set('notes')} rows={2} className="w-full mt-0.5 px-2.5 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary resize-none" />
        </div>
        <div className="md:col-span-2 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-xs text-text-muted hover:text-text-primary">Abbrechen</button>
          <button type="submit" disabled={saving} className="px-4 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50">
            {saving ? 'Speichern...' : isEdit ? 'Speichern' : 'Erstellen'}
          </button>
        </div>
      </form>
    </div>
  )
}

function HoldingDetail({ holdingId, onClose, onRefresh }) {
  const { data: h, loading, refetch } = useApi(`/private-equity/${holdingId}`)
  const toast = useToast()
  const [showValForm, setShowValForm] = useState(false)
  const [showDivForm, setShowDivForm] = useState(false)
  const detailTrapRef = useFocusTrap(true)
  useScrollLock(true)

  const refresh = useCallback(() => { refetch(); onRefresh?.() }, [refetch, onRefresh])

  if (loading || !h) return <div className="animate-pulse h-40 bg-card rounded-lg mt-4" />

  return (
    <div ref={detailTrapRef} className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4" role="dialog" aria-modal="true" aria-label={`Detail ${h.company_name}`}>
      <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-card border border-border rounded-xl shadow-2xl w-full max-w-3xl max-h-[80vh] overflow-y-auto p-6 z-10">
        <div className="flex justify-between items-start mb-4">
          <div>
            <h3 className="text-lg font-bold text-text-primary">{h.company_name}</h3>
            <div className="text-xs text-text-muted mt-0.5">
              {h.num_shares.toLocaleString('de-CH')} Aktien · Nennwert {h.currency} {h.nominal_value.toFixed(2)}
              {h.uid_number && <span> · {h.uid_number}</span>}
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={20} /></button>
        </div>

        {/* Metric cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <MetricCard label="Steuerwert (brutto)" value={h.total_gross_value != null ? formatCHF(h.total_gross_value) : '—'} sub={h.gross_value_per_share != null ? `${h.currency} ${h.gross_value_per_share.toFixed(2)}/Aktie` : null} />
          <MetricCard label="Steuerwert (netto)" value={h.total_net_value != null ? formatCHF(h.total_net_value) : '—'} sub={h.latest_valuation ? `${h.latest_valuation.discount_pct}% Abzug` : null} />
          <MetricCard label="Total Dividenden (netto)" value={formatCHF(h.total_dividends_net)} />
          <MetricCard label="Dividendenrendite" value={h.dividend_yield_pct != null ? `${h.dividend_yield_pct.toFixed(1)}%` : '—'} sub="Letzte Div. / Steuerwert" />
        </div>

        {/* Valuations */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold text-text-primary flex items-center gap-1.5"><TrendingUp size={14} /> Bewertungshistorie</h4>
            <button onClick={() => setShowValForm(!showValForm)} className="text-xs text-primary hover:text-primary/80 flex items-center gap-1"><Plus size={12} /> Bewertung</button>
          </div>
          {showValForm && <ValuationForm holdingId={h.id} onClose={() => setShowValForm(false)} onSave={() => { setShowValForm(false); refresh() }} />}
          {h.valuations?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-text-muted border-b border-border">
                  <th className="text-left py-1.5 font-medium">Datum</th>
                  <th className="text-right py-1.5 font-medium">Brutto/Aktie</th>
                  <th className="text-right py-1.5 font-medium">Abzug</th>
                  <th className="text-right py-1.5 font-medium">Netto/Aktie</th>
                  <th className="text-left py-1.5 font-medium">Quelle</th>
                  <th className="w-8"></th>
                </tr></thead>
                <tbody>
                  {h.valuations.map((v) => (
                    <ValuationRow key={v.id} v={v} holdingId={h.id} onRefresh={refresh} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="text-xs text-text-muted">Noch keine Bewertungen erfasst.</p>}
        </div>

        {/* Dividends */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold text-text-primary flex items-center gap-1.5"><Banknote size={14} /> Dividendenhistorie</h4>
            <button onClick={() => setShowDivForm(!showDivForm)} className="text-xs text-primary hover:text-primary/80 flex items-center gap-1"><Plus size={12} /> Dividende</button>
          </div>
          {showDivForm && <DividendForm holdingId={h.id} numShares={h.num_shares} onClose={() => setShowDivForm(false)} onSave={() => { setShowDivForm(false); refresh() }} />}
          {h.dividends?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-text-muted border-b border-border">
                  <th className="text-left py-1.5 font-medium">Datum</th>
                  <th className="text-right py-1.5 font-medium">GJ</th>
                  <th className="text-right py-1.5 font-medium">Div./Aktie</th>
                  <th className="text-right py-1.5 font-medium">Brutto</th>
                  <th className="text-right py-1.5 font-medium">VSt</th>
                  <th className="text-right py-1.5 font-medium">Netto</th>
                  <th className="w-8"></th>
                </tr></thead>
                <tbody>
                  {h.dividends.map((d) => (
                    <DividendRow key={d.id} d={d} holdingId={h.id} onRefresh={refresh} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="text-xs text-text-muted">Noch keine Dividenden erfasst.</p>}
        </div>
      </div>
    </div>
  )
}

function ValuationRow({ v, holdingId, onRefresh }) {
  const toast = useToast()
  async function handleDelete() {
    try {
      await apiDelete(`/private-equity/${holdingId}/valuations/${v.id}`)
      toast('Bewertung gelöscht', 'success')
      onRefresh()
    } catch { toast('Fehler beim Löschen', 'error') }
  }
  return (
    <tr className="border-b border-border/30 hover:bg-card-alt/20">
      <td className="py-1.5 text-text-primary">{formatDate(v.valuation_date)}</td>
      <td className="py-1.5 text-right text-text-primary font-medium">{parseFloat(v.gross_value_per_share).toFixed(2)}</td>
      <td className="py-1.5 text-right text-text-muted">{parseFloat(v.discount_pct).toFixed(0)}%</td>
      <td className="py-1.5 text-right text-text-primary">{parseFloat(v.net_value_per_share).toFixed(2)}</td>
      <td className="py-1.5 text-text-muted truncate max-w-[120px]">{v.source || '—'}</td>
      <td><button onClick={handleDelete} className="p-0.5 text-text-muted hover:text-danger"><Trash2 size={12} /></button></td>
    </tr>
  )
}

function DividendRow({ d, holdingId, onRefresh }) {
  const toast = useToast()
  async function handleDelete() {
    try {
      await apiDelete(`/private-equity/${holdingId}/dividends/${d.id}`)
      toast('Dividende gelöscht', 'success')
      onRefresh()
    } catch { toast('Fehler beim Löschen', 'error') }
  }
  return (
    <tr className="border-b border-border/30 hover:bg-card-alt/20">
      <td className="py-1.5 text-text-primary">{formatDate(d.payment_date)}</td>
      <td className="py-1.5 text-right text-text-muted">{d.fiscal_year}</td>
      <td className="py-1.5 text-right text-text-primary">{parseFloat(d.dividend_per_share).toFixed(2)}</td>
      <td className="py-1.5 text-right text-text-primary">{formatCHF(d.gross_amount)}</td>
      <td className="py-1.5 text-right text-text-muted">{formatCHF(d.withholding_tax_amount)}</td>
      <td className="py-1.5 text-right text-success font-medium">{formatCHF(d.net_amount)}</td>
      <td><button onClick={handleDelete} className="p-0.5 text-text-muted hover:text-danger"><Trash2 size={12} /></button></td>
    </tr>
  )
}

function ValuationForm({ holdingId, onClose, onSave }) {
  const toast = useToast()
  const [form, setForm] = useState({ valuation_date: '', gross_value_per_share: '', discount_pct: '30', source: '', notes: '' })
  const [saving, setSaving] = useState(false)
  const net = form.gross_value_per_share ? (parseFloat(form.gross_value_per_share) * (1 - parseFloat(form.discount_pct || 0) / 100)).toFixed(2) : '—'
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await apiPost(`/private-equity/${holdingId}/valuations`, {
        valuation_date: form.valuation_date,
        gross_value_per_share: parseFloat(form.gross_value_per_share),
        discount_pct: parseFloat(form.discount_pct),
        source: form.source || null,
        notes: form.notes || null,
      })
      toast('Bewertung erfasst', 'success')
      onSave()
    } catch { toast('Fehler beim Speichern', 'error') }
    finally { setSaving(false) }
  }

  return (
    <form onSubmit={handleSubmit} className="border border-border rounded-lg bg-card-alt/20 p-3 mb-3 grid grid-cols-2 md:grid-cols-4 gap-2">
      <div>
        <label htmlFor="val-date" className="text-xs text-text-secondary">Stichtag *</label>
        <DateInput id="val-date" value={form.valuation_date} onChange={(v) => setForm((f) => ({ ...f, valuation_date: v }))} required className="w-full mt-0.5" />
      </div>
      <div>
        <label htmlFor="val-gross" className="text-xs text-text-secondary">Brutto/Aktie *</label>
        <input id="val-gross" type="number" min="0" step="0.01" value={form.gross_value_per_share} onChange={set('gross_value_per_share')} required className="w-full mt-0.5 px-2 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
      </div>
      <div>
        <label htmlFor="val-disc" className="text-xs text-text-secondary">Abzug %</label>
        <input id="val-disc" type="number" min="0" max="100" step="0.5" value={form.discount_pct} onChange={set('discount_pct')} className="w-full mt-0.5 px-2 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
      </div>
      <div>
        <label className="text-xs text-text-secondary">Netto/Aktie</label>
        <div className="mt-0.5 px-2 py-1.5 text-sm text-text-muted bg-body/50 border border-border rounded-lg">{net}</div>
      </div>
      <div className="md:col-span-2">
        <label htmlFor="val-src" className="text-xs text-text-secondary">Quelle</label>
        <input id="val-src" value={form.source} onChange={set('source')} placeholder="z.B. Kt. St. Gallen Steueramt" className="w-full mt-0.5 px-2 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
      </div>
      <div className="md:col-span-2 flex items-end gap-2">
        <button type="button" onClick={onClose} className="px-3 py-1.5 text-xs text-text-muted">Abbrechen</button>
        <button type="submit" disabled={saving} className="px-3 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50">{saving ? '...' : 'Erfassen'}</button>
      </div>
    </form>
  )
}

function DividendForm({ holdingId, numShares, onClose, onSave }) {
  const toast = useToast()
  const [form, setForm] = useState({ payment_date: '', dividend_per_share: '', withholding_tax_pct: '35', fiscal_year: String(new Date().getFullYear() - 1), notes: '' })
  const [saving, setSaving] = useState(false)
  const gross = form.dividend_per_share ? (parseFloat(form.dividend_per_share) * numShares).toFixed(2) : '—'
  const wht = form.dividend_per_share ? (parseFloat(form.dividend_per_share) * numShares * parseFloat(form.withholding_tax_pct || 0) / 100).toFixed(2) : '—'
  const net = form.dividend_per_share ? (parseFloat(gross) - parseFloat(wht)).toFixed(2) : '—'
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      await apiPost(`/private-equity/${holdingId}/dividends`, {
        payment_date: form.payment_date,
        dividend_per_share: parseFloat(form.dividend_per_share),
        withholding_tax_pct: parseFloat(form.withholding_tax_pct),
        fiscal_year: parseInt(form.fiscal_year),
        notes: form.notes || null,
      })
      toast('Dividende erfasst', 'success')
      onSave()
    } catch { toast('Fehler beim Speichern', 'error') }
    finally { setSaving(false) }
  }

  return (
    <form onSubmit={handleSubmit} className="border border-border rounded-lg bg-card-alt/20 p-3 mb-3 grid grid-cols-2 md:grid-cols-4 gap-2">
      <div>
        <label htmlFor="div-date" className="text-xs text-text-secondary">Valutadatum *</label>
        <DateInput id="div-date" value={form.payment_date} onChange={(v) => setForm((f) => ({ ...f, payment_date: v }))} required className="w-full mt-0.5" />
      </div>
      <div>
        <label htmlFor="div-fy" className="text-xs text-text-secondary">Geschäftsjahr *</label>
        <input id="div-fy" type="number" min="1900" max="2100" value={form.fiscal_year} onChange={set('fiscal_year')} required className="w-full mt-0.5 px-2 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
      </div>
      <div>
        <label htmlFor="div-dps" className="text-xs text-text-secondary">Dividende/Aktie *</label>
        <input id="div-dps" type="number" min="0" step="0.01" value={form.dividend_per_share} onChange={set('dividend_per_share')} required className="w-full mt-0.5 px-2 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
      </div>
      <div>
        <label htmlFor="div-wht" className="text-xs text-text-secondary">VSt %</label>
        <input id="div-wht" type="number" min="0" max="100" step="0.5" value={form.withholding_tax_pct} onChange={set('withholding_tax_pct')} className="w-full mt-0.5 px-2 py-1.5 text-sm bg-body border border-border rounded-lg text-text-primary" />
      </div>
      <div>
        <label className="text-xs text-text-secondary">Brutto</label>
        <div className="mt-0.5 px-2 py-1.5 text-sm text-text-muted bg-body/50 border border-border rounded-lg">{gross}</div>
      </div>
      <div>
        <label className="text-xs text-text-secondary">VSt-Betrag</label>
        <div className="mt-0.5 px-2 py-1.5 text-sm text-text-muted bg-body/50 border border-border rounded-lg">{wht}</div>
      </div>
      <div>
        <label className="text-xs text-text-secondary">Netto</label>
        <div className="mt-0.5 px-2 py-1.5 text-sm text-success bg-body/50 border border-border rounded-lg font-medium">{net}</div>
      </div>
      <div className="flex items-end gap-2">
        <button type="button" onClick={onClose} className="px-3 py-1.5 text-xs text-text-muted">Abbrechen</button>
        <button type="submit" disabled={saving} className="px-3 py-1.5 text-xs bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50">{saving ? '...' : 'Erfassen'}</button>
      </div>
    </form>
  )
}
