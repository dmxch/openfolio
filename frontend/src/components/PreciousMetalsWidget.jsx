import { useState, useCallback, useMemo, useRef, useEffect, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, apiPost, apiPut, apiDelete, authFetch } from '../hooks/useApi'
import { formatCHF, formatNumber, formatPct, pnlColor } from '../lib/format'
import EditPositionModal from './EditPositionModal'
import G from './GlossarTooltip'
import ContextMenu from './ContextMenu'
import { Gem, Pencil, Trash2, MoreVertical, Plus, ChevronRight, X, Copy, CheckCircle } from 'lucide-react'
import DeleteConfirm from './DeleteConfirm'
import { useToast } from './Toast'
import DateInput from './DateInput'

const METAL_LABELS = { gold: 'Gold', silver: 'Silber', platinum: 'Platin', palladium: 'Palladium' }
const FORM_LABELS = { bar: 'Barren', coin: 'Münze', other: 'Sonstiges' }
const FINENESS_OPTIONS = ['999.9', '999', '995', '990', '986', '916.7', '900', '750', '585']
const MANUFACTURERS = ['Degussa', 'Heraeus', 'PAMP Suisse', 'Valcambi', 'Argor-Heraeus', 'Perth Mint', 'Royal Canadian Mint', 'Umicore']

function MetalCard({ label, price, changePct, currency }) {
  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="text-xs text-text-muted mb-1">{label}</div>
      <div className="text-lg font-bold text-text-primary tabular-nums">
        {price != null
          ? `${currency} ${price.toLocaleString('de-CH', { minimumFractionDigits: currency === 'CHF' ? 0 : 2, maximumFractionDigits: 2 })}`
          : '–'}
      </div>
      {changePct != null && (
        <div className={`text-xs font-medium tabular-nums ${pnlColor(changePct)}`}>
          {changePct > 0 ? '+' : ''}{changePct.toFixed(2)}%
        </div>
      )}
    </div>
  )
}

function RatioCard({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-card-alt/30 p-4">
      <div className="text-xs text-text-muted mb-1">{label}</div>
      <div className="text-lg font-bold text-text-primary tabular-nums">
        {value != null ? value.toFixed(1) : '–'}
      </div>
    </div>
  )
}

/* ── Tiny inline dropdown for item rows ── */
function ItemMenu({ item, onEdit, onSold, onDuplicate, onDelete }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors"
      >
        <MoreVertical size={14} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 min-w-[150px] rounded-lg border border-border bg-card shadow-xl py-1 text-xs">
          <button onClick={() => { setOpen(false); onEdit(item) }} className="w-full text-left px-3 py-1.5 hover:bg-card-alt/50 text-text-secondary hover:text-text-primary">Bearbeiten</button>
          <button onClick={() => { setOpen(false); onSold(item) }} className="w-full text-left px-3 py-1.5 hover:bg-card-alt/50 text-text-secondary hover:text-text-primary">Verkauft markieren</button>
          <button onClick={() => { setOpen(false); onDuplicate(item) }} className="w-full text-left px-3 py-1.5 hover:bg-card-alt/50 text-text-secondary hover:text-text-primary">Duplizieren</button>
          <div className="border-t border-border my-1" />
          <button onClick={() => { setOpen(false); onDelete(item) }} className="w-full text-left px-3 py-1.5 hover:bg-danger/10 text-danger">Löschen</button>
        </div>
      )}
    </div>
  )
}

/* ── Sold dialog ── */
function SoldDialog({ item, onClose, onConfirm }) {
  const [soldDate, setSoldDate] = useState(new Date().toISOString().split('T')[0])
  const [soldPrice, setSoldPrice] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    await onConfirm(item.id, soldDate, parseFloat(soldPrice))
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-card border border-border rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-text-primary">Verkauft markieren</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={16} /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label htmlFor="pm-sold-date" className="block text-xs text-text-muted mb-1">Verkaufsdatum</label>
            <DateInput id="pm-sold-date" value={soldDate} onChange={(v) => setSoldDate(v)} required
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" />
          </div>
          <div>
            <label htmlFor="pm-sold-price" className="block text-xs text-text-muted mb-1">Verkaufspreis CHF</label>
            <input id="pm-sold-price" type="number" step="0.01" value={soldPrice} onChange={(e) => setSoldPrice(e.target.value)} required
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" placeholder="0.00" />
          </div>
          <div className="flex gap-2 justify-end pt-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:text-text-primary transition-colors">Abbrechen</button>
            <button type="submit" disabled={saving}
              className="px-4 py-2 text-sm rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors font-medium disabled:opacity-50">
              {saving ? 'Speichern...' : 'Speichern'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

/* ── Add / Edit Modal ── */
function AddPreciousMetalModal({ onClose, onSaved, editItem }) {
  const isEdit = !!editItem
  const [form, setForm] = useState({
    metal_type: editItem?.metal_type || 'gold',
    form: editItem?.form || 'bar',
    manufacturer: editItem?.manufacturer || '',
    weight: editItem ? String(editItem.weight_grams) : '',
    weight_unit: 'g',
    fineness: editItem?.fineness || '999.9',
    serial_number: editItem?.serial_number || '',
    purchase_date: editItem?.purchase_date ? editItem.purchase_date.split('T')[0] : new Date().toISOString().split('T')[0],
    purchase_price_chf: editItem?.purchase_price_chf != null ? String(editItem.purchase_price_chf) : '',
    storage_location: editItem?.storage_location || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [showMfr, setShowMfr] = useState(false)
  const mfrRef = useRef(null)
  const toast = useToast()

  useEffect(() => {
    if (!showMfr) return
    const handler = (e) => { if (mfrRef.current && !mfrRef.current.contains(e.target)) setShowMfr(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showMfr])

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const weightGrams = useMemo(() => {
    const w = parseFloat(form.weight) || 0
    if (form.weight_unit === 'oz') return w * 31.1035
    if (form.weight_unit === 'kg') return w * 1000
    return w
  }, [form.weight, form.weight_unit])

  const doSave = async (keepOpen) => {
    setSaving(true)
    setError(null)
    try {
      const payload = {
        metal_type: form.metal_type,
        form: form.form,
        manufacturer: form.manufacturer || null,
        weight_grams: weightGrams,
        fineness: form.fineness || null,
        serial_number: form.serial_number || null,
        purchase_date: form.purchase_date,
        purchase_price_chf: parseFloat(form.purchase_price_chf) || 0,
        storage_location: form.storage_location || null,
      }
      if (isEdit) {
        await apiPut(`/precious-metals/${editItem.id}`, payload)
      } else {
        await apiPost('/precious-metals', payload)
      }
      onSaved()
      if (keepOpen) {
        setForm((f) => ({ ...f, serial_number: '' }))
        toast('Gespeichert', 'success')
      } else {
        onClose()
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const filteredMfrs = MANUFACTURERS.filter((m) => m.toLowerCase().includes(form.manufacturer.toLowerCase()))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-card border border-border rounded-xl shadow-2xl p-6 max-w-lg w-full mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-sm font-semibold text-text-primary">
            {isEdit ? 'Edelmetall bearbeiten' : 'Edelmetall hinzufügen'}
          </h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={16} /></button>
        </div>

        {error && <div className="mb-4 p-2 rounded-lg bg-danger/10 border border-danger/30 text-danger text-xs">{error}</div>}

        <div className="grid grid-cols-2 gap-3">
          {/* Row 1 */}
          <div>
            <label htmlFor="pm-metal-type" className="block text-xs text-text-muted mb-1">Metall</label>
            <select id="pm-metal-type" value={form.metal_type} onChange={set('metal_type')}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary">
              {Object.entries(METAL_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="pm-form" className="block text-xs text-text-muted mb-1">Form</label>
            <select id="pm-form" value={form.form} onChange={set('form')}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary">
              {Object.entries(FORM_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>

          {/* Row 2 */}
          <div className="relative" ref={mfrRef}>
            <label htmlFor="pm-manufacturer" className="block text-xs text-text-muted mb-1">Hersteller</label>
            <input id="pm-manufacturer" type="text" value={form.manufacturer} onChange={set('manufacturer')}
              onFocus={() => setShowMfr(true)}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" placeholder="z.B. Heraeus" />
            {showMfr && form.manufacturer && filteredMfrs.length > 0 && (
              <div className="absolute z-20 left-0 right-0 top-full mt-1 rounded-lg border border-border bg-card shadow-xl max-h-32 overflow-y-auto py-1">
                {filteredMfrs.map((m) => (
                  <button key={m} onClick={() => { setForm((f) => ({ ...f, manufacturer: m })); setShowMfr(false) }}
                    className="w-full text-left px-3 py-1.5 text-xs hover:bg-card-alt/50 text-text-secondary hover:text-text-primary">{m}</button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label htmlFor="pm-fineness" className="block text-xs text-text-muted mb-1">Feingehalt</label>
            <select id="pm-fineness" value={form.fineness} onChange={set('fineness')}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary">
              {FINENESS_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>

          {/* Row 3 */}
          <div>
            <label htmlFor="pm-weight" className="block text-xs text-text-muted mb-1">Gewicht</label>
            <div className="flex gap-1">
              <input id="pm-weight" type="number" step="any" value={form.weight} onChange={set('weight')} required
                className="flex-1 min-w-0 px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" placeholder="0" />
              <select value={form.weight_unit} onChange={set('weight_unit')}
                className="w-16 px-1 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary">
                <option value="g">g</option>
                <option value="oz">oz</option>
                <option value="kg">kg</option>
              </select>
            </div>
          </div>
          <div>
            <label htmlFor="pm-serial" className="block text-xs text-text-muted mb-1">Seriennummer</label>
            <input id="pm-serial" type="text" value={form.serial_number} onChange={set('serial_number')}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" placeholder="optional" />
          </div>

          {/* Row 4 */}
          <div>
            <label htmlFor="pm-purchase-date" className="block text-xs text-text-muted mb-1">Kaufdatum</label>
            <DateInput id="pm-purchase-date" value={form.purchase_date} onChange={(v) => setForm(f => ({...f, purchase_date: v}))} required
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" />
          </div>
          <div>
            <label htmlFor="pm-purchase-price" className="block text-xs text-text-muted mb-1">Kaufpreis CHF</label>
            <input id="pm-purchase-price" type="number" step="0.01" value={form.purchase_price_chf} onChange={set('purchase_price_chf')} required
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" placeholder="0.00" />
          </div>

          {/* Row 5 - full width */}
          <div className="col-span-2">
            <label htmlFor="pm-storage" className="block text-xs text-text-muted mb-1">Lagerort</label>
            <input id="pm-storage" type="text" value={form.storage_location} onChange={set('storage_location')}
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-card-alt text-text-primary" placeholder="z.B. Tresor, Bankschliessfach" />
          </div>
        </div>

        <div className="flex gap-2 justify-end pt-5">
          <button onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:text-text-primary transition-colors">Abbrechen</button>
          {!isEdit && (
            <button onClick={() => doSave(true)} disabled={saving}
              className="px-4 py-2 text-sm rounded-lg border border-primary text-primary hover:bg-primary/10 transition-colors font-medium disabled:opacity-50">
              Erstellen &amp; weiteres Stück
            </button>
          )}
          <button onClick={() => doSave(false)} disabled={saving}
            className="px-4 py-2 text-sm rounded-lg bg-primary text-white hover:bg-primary/90 transition-colors font-medium disabled:opacity-50">
            {saving ? 'Speichern...' : isEdit ? 'Speichern' : 'Erstellen'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Main Widget ── */
export default function PreciousMetalsWidget({ positions, onRefresh }) {
  const { data: metals } = useApi('/market/precious-metals')
  const { data: items, refetch: refetchItems } = useApi('/precious-metals')
  const [ctxMenu, setCtxMenu] = useState(null)
  const [editPosition, setEditPosition] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [editItem, setEditItem] = useState(null)
  const [soldItem, setSoldItem] = useState(null)
  const [deleteItem, setDeleteItem] = useState(null)
  const [expanded, setExpanded] = useState({})
  const navigate = useNavigate()
  const toast = useToast()

  /* ── Spot price helpers ── */
  const getSpotPrice = useCallback((metalType) => {
    if (!metals) return null
    if (metalType === 'gold') return metals.gold_spot_chf?.price
    if (metalType === 'silver' && metals.silver_comex_usd?.price && metals.gold_spot_chf?.price && metals.gold_comex_usd?.price) {
      return metals.silver_comex_usd.price * (metals.gold_spot_chf.price / metals.gold_comex_usd.price)
    }
    if (metalType === 'platinum') return metals.platinum_spot_chf?.price || null
    if (metalType === 'palladium') return metals.palladium_spot_chf?.price || null
    return null
  }, [metals])

  const calcMarketValue = useCallback((item) => {
    const spot = getSpotPrice(item.metal_type)
    if (!spot) return null
    const fineness = parseFloat(item.fineness || '999.9') / 999.9
    const weightOz = item.weight_grams / 31.1035
    return weightOz * spot * fineness
  }, [getSpotPrice])

  /* ── Group items by metal_type ── */
  const groupedItems = useMemo(() => {
    // API returns {groups: [{metal_type, items, ...}]} — extract and enrich
    const apiGroups = items?.groups || []
    if (!apiGroups.length) return []
    return apiGroups.map((g) => ({
      ...g,
      item_count: g.items?.length || 0,
      total_weight_oz: (g.total_weight_grams || 0) / 31.1035,
      total_market_value_chf: (g.items || []).reduce((s, i) => s + (calcMarketValue(i) || 0), 0),
      pnl_chf: 0,
      pnl_pct: 0,
    })).map((g) => ({
      ...g,
      pnl_chf: g.total_market_value_chf - (g.total_cost_chf || 0),
      pnl_pct: g.total_cost_chf > 0 ? ((g.total_market_value_chf - g.total_cost_chf) / g.total_cost_chf) * 100 : 0,
    })).sort((a, b) => b.total_market_value_chf - a.total_market_value_chf)
  }, [items, calcMarketValue])

  const toggleExpand = useCallback((type) => {
    setExpanded((prev) => ({ ...prev, [type]: !prev[type] }))
  }, [])

  /* ── Existing position handlers ── */
  const handleContextMenu = useCallback((e, position) => {
    e.preventDefault()
    setCtxMenu({ x: e.clientX, y: e.clientY, position })
  }, [])

  const openCtxFor = useCallback((e, position) => {
    e.stopPropagation()
    const rect = e.currentTarget.getBoundingClientRect()
    setCtxMenu({ x: rect.left, y: rect.bottom + 4, position })
  }, [])

  const handleAction = useCallback(async (action) => {
    const pos = ctxMenu?.position
    if (!pos) return
    setCtxMenu(null)

    if (action === 'edit') {
      try {
        const res = await authFetch(`/api/portfolio/positions/${pos.id}`)
        const full = await res.json()
        setEditPosition(full)
      } catch {
        setEditPosition(pos)
      }
    } else if (action === 'delete') {
      setDeleteTarget(pos)
    }
  }, [ctxMenu])

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return
    try {
      await apiDelete(`/portfolio/positions/${deleteTarget.id}`)
      onRefresh?.()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
    setDeleteTarget(null)
  }, [deleteTarget, onRefresh, toast])

  /* ── Item action handlers ── */
  const handleItemDuplicate = useCallback(async (item) => {
    try {
      await apiPost('/precious-metals', {
        metal_type: item.metal_type,
        form: item.form,
        manufacturer: item.manufacturer,
        weight_grams: item.weight_grams,
        fineness: item.fineness,
        serial_number: null,
        purchase_date: item.purchase_date,
        purchase_price_chf: item.purchase_price_chf,
        storage_location: item.storage_location,
      })
      toast('Dupliziert', 'success')
      refetchItems()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
  }, [refetchItems, toast])

  const handleItemSold = useCallback(async (id, soldDate, soldPrice) => {
    try {
      await apiPut(`/precious-metals/${id}`, { sold_date: soldDate, sold_price_chf: soldPrice })
      toast('Als verkauft markiert', 'success')
      setSoldItem(null)
      refetchItems()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
  }, [refetchItems, toast])

  const handleItemDelete = useCallback(async () => {
    if (!deleteItem) return
    try {
      await apiDelete(`/precious-metals/${deleteItem.id}`)
      toast('Gelöscht', 'success')
      refetchItems()
    } catch (e) {
      toast('Fehler: ' + e.message, 'error')
    }
    setDeleteItem(null)
  }, [deleteItem, refetchItems, toast])

  const totalValue = positions.reduce((s, p) => s + p.market_value_chf, 0)
  const totalPnl = positions.reduce((s, p) => s + p.pnl_chf, 0)
  const totalCost = positions.reduce((s, p) => s + p.cost_basis_chf, 0)
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0

  return (
    <div className="rounded-lg border border-white/[0.06] border-t-2 border-t-amber-500/60 bg-card overflow-hidden shadow-[0_1px_3px_rgba(0,0,0,0.3)]">
      <div className="p-4 border-b border-white/[0.08]">
        <div className="flex items-center gap-2">
          <Gem size={16} className="text-primary" />
          <h3 className="text-sm font-medium text-text-secondary">Edelmetalle</h3>
          <div className="flex-1" />
          <button onClick={() => setShowAddForm(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-border text-text-muted hover:border-primary hover:text-primary transition-colors">
            <Plus size={13} />
            Edelmetall hinzufügen
          </button>
        </div>
      </div>

      {/* Market Data Cards */}
      <div className="grid grid-cols-3 gap-3 p-4">
        <MetalCard
          label={<>Silber <G term="COMEX">COMEX</G></>}
          price={metals?.silver_comex_usd?.price}
          changePct={metals?.silver_comex_usd?.change_pct}
          currency="USD"
        />
        <MetalCard
          label="Gold COMEX"
          price={metals?.gold_comex_usd?.price}
          changePct={metals?.gold_comex_usd?.change_pct}
          currency="USD"
        />
        <RatioCard
          label={<G term="Gold/Silber Ratio">Gold/Silber Ratio</G>}
          value={metals?.gold_silver_ratio}
        />
      </div>

      {/* Positions Table with expandable item details */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/[0.08] text-slate-400 text-[11px] uppercase tracking-wider">
              <th className="text-left p-3 font-medium">Metall</th>
              <th className="text-left p-3 font-medium">Hersteller</th>
              <th className="text-right p-3 font-medium">Gewicht</th>
              <th className="text-left p-3 font-medium">Seriennr.</th>
              <th className="text-left p-3 font-medium">Kaufdatum</th>
              <th className="text-right p-3 font-medium"><G term="Einstand">Einstand</G> CHF</th>
              <th className="text-right p-3 font-medium">Kurs <G term="CHF/oz">CHF/oz</G></th>
              <th className="text-right p-3 font-medium">Marktwert CHF</th>
              <th className="text-right p-3 font-medium"><G term="Perf %">Perf %</G></th>
              <th className="text-right p-3 font-medium">Perf CHF</th>
              <th className="text-left p-3 font-medium">Lagerort</th>
              <th className="p-3 w-10" />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const isExp = expanded[p.id] !== false
              const metalType = p.gold_org ? 'gold' : p.ticker?.includes('XAG') ? 'silver' : p.ticker?.includes('XPT') ? 'platinum' : 'gold'
              const group = groupedItems.find((g) => g.metal_type === metalType)
              const itemsList = group?.items || []
              return (
                <Fragment key={p.id}>
                  {/* Aggregate row — clickable to expand */}
                  <tr
                    className="border-b border-border/50 hover:bg-card-alt/50 transition-colors cursor-pointer"
                    onClick={() => setExpanded((prev) => ({ ...prev, [p.id]: !isExp }))}
                    onContextMenu={(e) => handleContextMenu(e, p)}
                  >
                    <td className="p-3 text-text-primary font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        <ChevronRight size={14} className={`transition-transform ${isExp ? 'rotate-90 text-primary' : 'text-text-muted'}`} />
                        {p.name}
                        {itemsList.length > 0 && <span className="text-xs text-text-muted">({itemsList.length})</span>}
                      </span>
                    </td>
                    <td className="p-3 text-text-muted">—</td>
                    <td className="p-3 text-right text-text-secondary tabular-nums">
                      {formatNumber(p.shares, 2)} oz
                    </td>
                    <td className="p-3 text-text-muted">—</td>
                    <td className="p-3 text-text-muted">—</td>
                    <td className="p-3 text-right text-text-secondary tabular-nums">{formatCHF(p.cost_basis_chf)}</td>
                    <td className="p-3 text-right text-text-secondary tabular-nums">
                      {p.current_price != null ? formatCHF(p.current_price) : '–'}
                    </td>
                    <td className="p-3 text-right text-text-primary font-medium tabular-nums">{formatCHF(p.market_value_chf)}</td>
                    <td className={`p-3 text-right font-medium tabular-nums ${pnlColor(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</td>
                    <td className={`p-3 text-right tabular-nums ${pnlColor(p.pnl_chf)}`}>{formatCHF(p.pnl_chf)}</td>
                    <td className="p-3"></td>
                    <td className="p-3 text-center">
                      <button onClick={(e) => { e.stopPropagation(); openCtxFor(e, p) }} className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-card-alt transition-colors" title="Aktionen" aria-label="Aktionen öffnen">
                        <MoreVertical size={15} />
                      </button>
                    </td>
                  </tr>
                  {/* Detail rows — individual items */}
                  {isExp && itemsList.map((item) => {
                    const mv = calcMarketValue(item)
                    const pnl = mv != null ? mv - item.purchase_price_chf : null
                    const pnlPct = item.purchase_price_chf > 0 && pnl != null ? (pnl / item.purchase_price_chf) * 100 : null
                    return (
                      <tr key={item.id} className="border-b border-border/30 bg-card-alt/10 hover:bg-card-alt/30 transition-colors">
                        <td className="p-3 pl-9 text-text-secondary text-xs">
                          {FORM_LABELS[item.form] || item.form}
                        </td>
                        <td className="p-3 text-text-secondary text-xs">{item.manufacturer || '–'}</td>
                        <td className="p-3 text-right text-text-secondary tabular-nums text-xs">{formatNumber(item.weight_grams, 1)} g</td>
                        <td className="p-3 text-text-secondary text-xs font-mono">{item.serial_number || '–'}</td>
                        <td className="p-3 text-text-secondary text-xs">{item.purchase_date ? new Date(item.purchase_date).toLocaleDateString('de-CH') : '–'}</td>
                        <td className="p-3 text-right text-text-secondary tabular-nums text-xs">{formatCHF(item.purchase_price_chf)}</td>
                        <td className="p-3 text-right text-text-muted tabular-nums text-xs">
                          {p.current_price != null ? formatCHF(p.current_price) : '–'}
                        </td>
                        <td className="p-3 text-right text-text-primary tabular-nums text-xs">{mv != null ? formatCHF(mv) : '–'}</td>
                        <td className={`p-3 text-right tabular-nums text-xs ${pnlPct != null ? pnlColor(pnlPct) : ''}`}>
                          {pnlPct != null ? formatPct(pnlPct) : '–'}
                        </td>
                        <td className={`p-3 text-right tabular-nums text-xs ${pnl != null ? pnlColor(pnl) : ''}`}>
                          {pnl != null ? formatCHF(pnl) : '–'}
                        </td>
                        <td className="p-3 text-text-muted text-xs">{item.storage_location || '–'}</td>
                        <td className="p-3">
                          <ItemMenu
                            item={item}
                            onEdit={() => setEditItem(item)}
                            onSold={() => setSoldItem(item)}
                            onDuplicate={async () => {
                              try {
                                await apiPost('/precious-metals', { ...item, serial_number: null, id: undefined, created_at: undefined, notes: undefined })
                                refetchItems()
                                onRefresh?.()
                              } catch (e) { toast('Fehler: ' + e.message, 'error') }
                            }}
                            onDelete={() => setDeleteItem(item)}
                          />
                        </td>
                      </tr>
                    )
                  })}
                </Fragment>
              )
            })}
            {positions.length > 0 && (
              <tr className="bg-card-alt/30 border-t border-border">
                <td className="p-3 text-text-primary font-medium" colSpan={5}>Total</td>
                <td className="p-3 text-right text-text-secondary font-bold tabular-nums">{formatCHF(totalCost)}</td>
                <td className="p-3"></td>
                <td className="p-3 text-right text-text-primary font-bold tabular-nums">{formatCHF(totalValue)}</td>
                <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnlPct)}`}>{formatPct(totalPnlPct)}</td>
                <td className={`p-3 text-right font-bold tabular-nums ${pnlColor(totalPnl)}`}>{formatCHF(totalPnl)}</td>
                <td className="p-3" colSpan={2}></td>
              </tr>
            )}
            {positions.length === 0 && groupedItems.length === 0 && (
              <tr>
                <td colSpan={12} className="p-6 text-center text-text-muted text-sm">
                  Keine Edelmetall-Positionen vorhanden.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* ── Modals / Overlays ── */}
      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          onAction={handleAction}
          onClose={() => setCtxMenu(null)}
        />
      )}

      {editPosition && (
        <EditPositionModal
          position={editPosition}
          onClose={() => setEditPosition(null)}
          onSaved={() => onRefresh?.()}
        />
      )}

      {deleteTarget && (
        <DeleteConfirm
          name={deleteTarget.name}
          onConfirm={confirmDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {(showAddForm || editItem) && (
        <AddPreciousMetalModal
          editItem={editItem || null}
          onClose={() => { setShowAddForm(false); setEditItem(null) }}
          onSaved={() => { refetchItems() }}
        />
      )}

      {soldItem && (
        <SoldDialog
          item={soldItem}
          onClose={() => setSoldItem(null)}
          onConfirm={handleItemSold}
        />
      )}

      {deleteItem && (
        <DeleteConfirm
          name={`${METAL_LABELS[deleteItem.metal_type] || deleteItem.metal_type} – ${deleteItem.manufacturer || 'Edelmetall'}`}
          onConfirm={handleItemDelete}
          onCancel={() => setDeleteItem(null)}
        />
      )}
    </div>
  )
}
