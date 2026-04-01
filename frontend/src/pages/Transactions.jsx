import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePortfolioData } from '../contexts/DataContext'
import { useApi, apiPost, apiPut, apiDelete, authFetch } from '../hooks/useApi'
import { formatCHFExact, formatNumber, formatDate } from '../lib/format'
import {
  Plus, X, Loader2, ArrowLeftRight, Edit3, Trash2, Check, Search, Calendar, Filter, Upload,
} from 'lucide-react'
import ImportWizard from '../components/ImportWizard'
import useEscClose from '../hooks/useEscClose'
import useScrollLock from '../hooks/useScrollLock'
import useFocusTrap from '../hooks/useFocusTrap'
import LoadingSpinner from '../components/LoadingSpinner'
import G from '../components/GlossarTooltip'
import DateInput from '../components/DateInput'

const TYPES = ['buy', 'sell', 'dividend', 'fee_correction', 'capital_gain', 'deposit', 'withdrawal']
const TYPE_LABELS = {
  buy: 'Kauf', sell: 'Verkauf', dividend: 'Dividende', fee: 'Gebühren',
  deposit: 'Einzahlung', withdrawal: 'Auszahlung',
  capital_gain: 'Kapitalgewinn', interest: 'Zinsertrag',
  fx_credit: 'FX Gutschrift', fx_debit: 'FX Belastung',
  fee_correction: 'Gebühren', tax: 'Steuer', tax_refund: 'Steuererstattung',
}
const TYPE_COLORS = {
  buy: 'bg-success/15 text-success border-success/30',
  sell: 'bg-danger/15 text-danger border-danger/30',
  dividend: 'bg-primary/15 text-primary border-primary/30',
  fee: 'bg-warning/15 text-warning border-warning/30',
  deposit: 'bg-card-alt text-text-secondary border-border',
  withdrawal: 'bg-card-alt text-text-secondary border-border',
  capital_gain: 'bg-success/15 text-success border-success/30',
  interest: 'bg-primary/15 text-primary border-primary/30',
  fx_credit: 'bg-text-muted/15 text-text-muted border-text-muted/30',
  fx_debit: 'bg-text-muted/15 text-text-muted border-text-muted/30',
  fee_correction: 'bg-warning/15 text-warning border-warning/30',
  tax: 'bg-warning/15 text-warning border-warning/30',
  tax_refund: 'bg-success/15 text-success border-success/30',
}

const INPUT = 'bg-card border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

function TypeBadge({ type }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold border ${TYPE_COLORS[type] || TYPE_COLORS.fee}`}>
      {TYPE_LABELS[type] || type}
    </span>
  )
}

// ---- Ticker Autocomplete ----
function TickerAutocomplete({ positions, value, onChange, disabled }) {
  const [query, setQuery] = useState(value?.ticker || '')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const searchTimer = useRef(null)
  const wrapperRef = useRef(null)

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Search logic: local positions first, then API
  const doSearch = useCallback((q) => {
    if (!q || q.length < 1) { setResults([]); setOpen(false); return }

    const term = q.toUpperCase()

    // Local matches from existing positions
    const local = (positions || [])
      .filter((p) => p.ticker.toUpperCase().includes(term) || (p.name || '').toUpperCase().includes(term))
      .slice(0, 5)
      .map((p) => ({ ticker: p.ticker, name: p.name, type: p.type, currency: p.currency, position_id: p.id, is_existing: true }))

    setResults(local)
    setOpen(true)

    // Remote search (debounced)
    clearTimeout(searchTimer.current)
    if (q.length >= 2) {
      searchTimer.current = setTimeout(async () => {
        setSearching(true)
        try {
          const res = await authFetch(`/api/stock/search?q=${encodeURIComponent(q)}`)
          if (res.ok) {
            const data = await res.json()
            setResults(data)
            setOpen(true)
          }
        } catch { /* ignore */ } finally {
          setSearching(false)
        }
      }, 300)
    }
  }, [positions])

  useEffect(() => () => clearTimeout(searchTimer.current), [])

  const handleSelect = (item) => {
    setQuery(`${item.ticker} — ${item.name}`)
    setOpen(false)
    onChange(item)
  }

  const handleInputChange = (e) => {
    const v = e.target.value
    setQuery(v)
    // If user clears or changes text, reset selection
    onChange(null)
    doSearch(v)
  }

  return (
    <div ref={wrapperRef} className="relative">
      <label htmlFor="txnpage-ticker" className={LABEL}>Ticker / Position *</label>
      <div className="relative">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
        <input
          id="txnpage-ticker"
          value={query}
          onChange={handleInputChange}
          onFocus={() => { if (query.length >= 1) doSearch(query) }}
          placeholder="z.B. AAPL, Novartis, BTC..."
          disabled={disabled}
          autoComplete="off"
          className={`${INPUT} w-full pl-8 ${disabled ? 'opacity-60' : ''}`}
        />
        {searching && <Loader2 size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-text-muted" />}
      </div>
      {open && results.length > 0 && (
        <ul className="absolute z-50 w-full mt-1 bg-card border border-border rounded-lg shadow-lg max-h-56 overflow-y-auto">
          {results.map((item, i) => (
            <li key={`${item.ticker}-${i}`}>
              <button
                type="button"
                onClick={() => handleSelect(item)}
                className="w-full text-left px-3 py-2 hover:bg-card-alt/60 transition-colors flex items-center gap-2"
              >
                <span className="font-mono text-primary font-medium text-sm">{item.ticker}</span>
                <span className="text-text-secondary text-xs truncate flex-1">{item.name}</span>
                {item.is_existing ? (
                  <span className="text-[10px] text-success bg-success/10 border border-success/20 rounded px-1.5 py-0.5 shrink-0">Vorhanden</span>
                ) : (
                  <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 rounded px-1.5 py-0.5 shrink-0">Neu</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && query.length >= 2 && results.length === 0 && !searching && (
        <div className="absolute z-50 w-full mt-1 bg-card border border-border rounded-lg shadow-lg px-3 py-3 text-sm text-text-muted">
          Kein Ergebnis für «{query}»
        </div>
      )}
    </div>
  )
}

// ---- Transaction Modal ----
function TransactionModal({ positions, initial, onSave, onClose }) {
  const isEdit = !!initial
  useEscClose(onClose)
  useScrollLock(true)
  const trapRef = useFocusTrap(true)

  // Selected ticker item from autocomplete (null = nothing selected yet)
  const [selectedItem, setSelectedItem] = useState(
    isEdit && initial?.position_id
      ? { ticker: initial.ticker || '', name: initial.position_name || '', position_id: initial.position_id, is_existing: true }
      : null
  )

  const [form, setForm] = useState({
    type: initial?.type || 'buy',
    date: initial?.date || new Date().toISOString().slice(0, 10),
    shares: initial?.shares?.toString() || '',
    price_per_share: initial?.price_per_share?.toString() || '',
    currency: initial?.currency || 'CHF',
    fx_rate_to_chf: initial?.fx_rate_to_chf?.toString() || '1',
    fees_chf: initial?.fees_chf?.toString() || '0',
    total_chf: initial?.total_chf?.toString() || '',
    notes: initial?.notes || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [fxLoading, setFxLoading] = useState(false)

  // Auto-fill currency when selecting a position/ticker
  useEffect(() => {
    if (selectedItem?.currency && !isEdit) {
      setForm((f) => ({ ...f, currency: selectedItem.currency }))
    }
  }, [selectedItem, isEdit])

  // Auto-fetch FX rate when currency changes
  useEffect(() => {
    if (form.currency === 'CHF') {
      setForm((f) => ({ ...f, fx_rate_to_chf: '1' }))
      return
    }
    let cancelled = false
    const fetchFx = async () => {
      setFxLoading(true)
      try {
        const res = await authFetch(`/api/market/fx/${form.currency}`)
        if (res.ok && !cancelled) {
          const data = await res.json()
          setForm((f) => ({ ...f, fx_rate_to_chf: data.rate.toString() }))
        }
      } catch { /* ignore */ } finally {
        if (!cancelled) setFxLoading(false)
      }
    }
    fetchFx()
    return () => { cancelled = true }
  }, [form.currency])

  // Auto-calculate total CHF
  useEffect(() => {
    const shares = parseFloat(form.shares) || 0
    const price = parseFloat(form.price_per_share) || 0
    const fx = parseFloat(form.fx_rate_to_chf) || 1
    if (shares > 0 && price > 0) {
      setForm((f) => ({ ...f, total_chf: (shares * price * fx).toFixed(2) }))
    }
  }, [form.shares, form.price_per_share, form.fx_rate_to_chf])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!selectedItem) return
    setSaving(true)
    setError(null)
    try {
      const payload = {
        ...form,
        shares: parseFloat(form.shares) || 0,
        price_per_share: parseFloat(form.price_per_share) || 0,
        fx_rate_to_chf: parseFloat(form.fx_rate_to_chf) || 1,
        fees_chf: parseFloat(form.fees_chf) || 0,
        total_chf: parseFloat(form.total_chf) || 0,
      }
      if (selectedItem.is_existing && selectedItem.position_id) {
        payload.position_id = selectedItem.position_id
      } else {
        payload.ticker = selectedItem.ticker
        payload.asset_type = selectedItem.type || 'stock'
      }
      await onSave(payload)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-body/80 backdrop-blur-sm" onClick={onClose}>
      <div ref={trapRef} role="dialog" aria-modal="true" aria-label={isEdit ? 'Transaktion bearbeiten' : 'Neue Transaktion'} className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-xl mx-4" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h3 className="text-lg font-bold text-text-primary">
            {isEdit ? 'Transaktion bearbeiten' : 'Neue Transaktion'}
          </h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors" aria-label="Schliessen">
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Row 1: Ticker Autocomplete + Type */}
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2 sm:col-span-1">
              <TickerAutocomplete
                positions={positions}
                value={selectedItem}
                onChange={setSelectedItem}
                disabled={isEdit}
              />
              {selectedItem && !selectedItem.is_existing && (
                <p className="text-[11px] text-primary mt-1">Neue Position wird automatisch erstellt</p>
              )}
            </div>
            <div>
              <label className={LABEL}>Typ *</label>
              <div className="flex gap-1 flex-wrap">
                {TYPES.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setForm({ ...form, type: t })}
                    className={`px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      form.type === t
                        ? TYPE_COLORS[t]
                        : 'bg-card-alt/50 text-text-muted border-border hover:border-text-muted'
                    }`}
                  >
                    {TYPE_LABELS[t]}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Row 2: Date + Shares + Price */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div>
              <label htmlFor="txnpage-date" className={LABEL}>Datum *</label>
              <DateInput
                id="txnpage-date"
                value={form.date}
                onChange={(v) => setForm({ ...form, date: v })}
                required
                className={`${INPUT} w-full`}
              />
            </div>
            <div>
              <label htmlFor="txnpage-shares" className={LABEL}>Anzahl *</label>
              <input
                id="txnpage-shares"
                type="number"
                step="any"
                min="0"
                value={form.shares}
                onChange={(e) => setForm({ ...form, shares: e.target.value })}
                required
                placeholder="z.B. 55"
                className={`${INPUT} w-full`}
              />
            </div>
            <div>
              <label htmlFor="txnpage-price" className={LABEL}>Preis/Einheit *</label>
              <input
                id="txnpage-price"
                type="number"
                step="any"
                min="0"
                value={form.price_per_share}
                onChange={(e) => setForm({ ...form, price_per_share: e.target.value })}
                required
                placeholder="z.B. 232.91"
                className={`${INPUT} w-full`}
              />
            </div>
          </div>

          {/* Row 3: Currency + FX + Fees + Total */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label htmlFor="txnpage-currency" className={LABEL}>Währung</label>
              <select
                id="txnpage-currency"
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className={`${INPUT} w-full`}
              >
                {['CHF', 'USD', 'EUR', 'CAD', 'GBP', 'GBp', 'JPY', 'SEK', 'NOK', 'DKK', 'AUD', 'HKD', 'SGD'].map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="txnpage-fx" className={LABEL}>
                FX → CHF
                {fxLoading && <Loader2 size={10} className="inline animate-spin ml-1" />}
              </label>
              <input
                id="txnpage-fx"
                type="number"
                step="any"
                min="0"
                value={form.fx_rate_to_chf}
                onChange={(e) => setForm({ ...form, fx_rate_to_chf: e.target.value })}
                className={`${INPUT} w-full`}
              />
            </div>
            <div>
              <label htmlFor="txnpage-fees" className={LABEL}>Gebühren CHF</label>
              <input
                id="txnpage-fees"
                type="number"
                step="any"
                min="0"
                value={form.fees_chf}
                onChange={(e) => setForm({ ...form, fees_chf: e.target.value })}
                placeholder="0"
                className={`${INPUT} w-full`}
              />
            </div>
            <div>
              <label htmlFor="txnpage-total" className={LABEL}>Total CHF</label>
              <input
                id="txnpage-total"
                type="number"
                step="any"
                value={form.total_chf}
                onChange={(e) => setForm({ ...form, total_chf: e.target.value })}
                className={`${INPUT} w-full font-medium`}
              />
            </div>
          </div>

          {/* Row 4: Notes */}
          <div>
            <label htmlFor="txnpage-notes" className={LABEL}>Notizen</label>
            <input
              id="txnpage-notes"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Optional"
              className={`${INPUT} w-full`}
            />
          </div>

          {/* Error */}
          {error && (
            <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary transition-colors">
              Abbrechen
            </button>
            <button
              type="submit"
              disabled={saving || !selectedItem || !form.date}
              className="flex items-center gap-2 bg-primary text-white rounded-lg px-5 py-2 text-sm font-medium hover:bg-primary/80 transition-colors disabled:opacity-40"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {isEdit ? 'Speichern' : 'Erstellen'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---- Delete Confirmation ----
function DeleteConfirm({ txn, onConfirm, onCancel }) {
  const [deleting, setDeleting] = useState(false)
  const deleteTrapRef = useFocusTrap(true)
  useScrollLock(true)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-body/80 backdrop-blur-sm" onClick={onCancel}>
      <div ref={deleteTrapRef} role="dialog" aria-modal="true" aria-label="Transaktion löschen" className="bg-card border border-danger/30 rounded-xl shadow-2xl w-full max-w-sm mx-4 p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-text-primary mb-2">Transaktion löschen?</h3>
        <p className="text-sm text-text-secondary mb-1">
          {TYPE_LABELS[txn.type]} — {txn.ticker} — {txn.date}
        </p>
        <p className="text-xs text-text-muted mb-4">
          {txn.type === 'buy' || txn.type === 'sell'
            ? 'Die Position wird automatisch angepasst (Anzahl + Einstandswert).'
            : 'Diese Aktion kann nicht rückgängig gemacht werden.'}
        </p>
        <div className="flex justify-end gap-3">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">
            Abbrechen
          </button>
          <button
            onClick={async () => {
              setDeleting(true)
              await onConfirm()
            }}
            disabled={deleting}
            className="flex items-center gap-2 bg-danger text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-danger/80 disabled:opacity-40"
          >
            {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
            Löschen
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- Summary Stats ----
function SummaryStats({ data, positions }) {
  if (!data?.items?.length) return null

  const items = data.items
  const buys = items.filter((t) => t.type === 'buy')
  const sells = items.filter((t) => t.type === 'sell')
  const dividends = items.filter((t) => t.type === 'dividend')

  const totalBuy = buys.reduce((s, t) => s + t.total_chf, 0)
  const totalSell = sells.reduce((s, t) => s + t.total_chf, 0)
  const totalDiv = dividends.reduce((s, t) => s + t.total_chf, 0)
  const totalFees = items.reduce((s, t) => s + (t.fees_chf || 0), 0)

  const stats = [
    { label: 'Transaktionen', value: data.total, color: 'text-text-primary' },
    { label: 'Käufe', value: formatCHFExact(totalBuy), color: 'text-success' },
    { label: 'Verkäufe', value: formatCHFExact(totalSell), color: 'text-danger' },
    { label: <G term="Dividende">Dividenden</G>, value: formatCHFExact(totalDiv), color: 'text-primary' },
    { label: 'Gebühren', value: formatCHFExact(totalFees), color: 'text-warning' },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      {stats.map((s) => (
        <div key={s.label} className="rounded-lg border border-border bg-card p-3">
          <div className="text-xs text-text-muted">{s.label}</div>
          <div className={`text-lg font-bold mt-0.5 ${s.color}`}>{s.value}</div>
        </div>
      ))}
    </div>
  )
}

// ---- Main Page ----
export default function Transactions() {
  const { refetch: refetchPortfolio } = usePortfolioData()
  const [page, setPage] = useState(1)
  const [filterType, setFilterType] = useState('')
  const [filterTicker, setFilterTicker] = useState('')
  const [filterDateFrom, setFilterDateFrom] = useState('')
  const [filterDateTo, setFilterDateTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const searchTimer = useRef(null)

  // Debounced search (300ms)
  const handleSearchChange = useCallback((value) => {
    setSearchInput(value)
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => {
      setSearchQuery(value)
      setPage(1)
    }, 300)
  }, [])

  useEffect(() => () => clearTimeout(searchTimer.current), [])

  // Build query string
  const qs = useMemo(() => {
    const params = [`page=${page}`]
    if (filterType) params.push(`type=${filterType}`)
    if (filterTicker) params.push(`ticker=${filterTicker}`)
    if (filterDateFrom) params.push(`date_from=${filterDateFrom}`)
    if (filterDateTo) params.push(`date_to=${filterDateTo}`)
    if (searchQuery) params.push(`search=${encodeURIComponent(searchQuery)}`)
    return params.join('&')
  }, [page, filterType, filterTicker, filterDateFrom, filterDateTo, searchQuery])

  const { data, loading, refetch } = useApi(`/transactions?${qs}`)
  const { data: positions } = useApi('/portfolio/positions')

  const [showModal, setShowModal] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editTxn, setEditTxn] = useState(null)
  const [deleteTxn, setDeleteTxn] = useState(null)

  // Handle deep-link actions from Portfolio page
  const [searchParams, setSearchParams] = useSearchParams()
  useEffect(() => {
    const action = searchParams.get('action')
    if (action) {
      setSearchParams({}, { replace: true })
      if (action === 'add') setShowModal(true)
      if (action === 'import') setShowImport(true)
    }
  }, [searchParams, setSearchParams])

  const handleCreate = async (formData) => {
    await apiPost('/transactions', formData)
    setShowModal(false)
    refetch()
    refetchPortfolio()
  }

  const handleUpdate = async (formData) => {
    await apiPut(`/transactions/${editTxn.id}`, formData)
    setEditTxn(null)
    refetch()
    refetchPortfolio()
  }

  const handleDelete = async () => {
    await apiDelete(`/transactions/${deleteTxn.id}`)
    setDeleteTxn(null)
    refetch()
    refetchPortfolio()
  }

  const resetFilters = () => {
    setFilterType('')
    setFilterTicker('')
    setFilterDateFrom('')
    setFilterDateTo('')
    setSearchInput('')
    setSearchQuery('')
    setPage(1)
  }

  const hasFilters = filterType || filterTicker || filterDateFrom || filterDateTo || searchQuery

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ArrowLeftRight size={22} className="text-primary" />
          <h2 className="text-xl font-bold text-text-primary">Transaktionen</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-2 bg-card border border-border text-text-secondary rounded-lg px-4 py-2.5 text-sm font-medium hover:text-text-primary hover:border-primary/50 transition-colors"
          >
            <Upload size={16} />
            Import
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 bg-primary text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-primary/80 transition-colors"
          >
            <Plus size={16} />
            Neue Transaktion
          </button>
        </div>
      </div>

      {/* Stats */}
      <SummaryStats data={data} positions={positions} />

      {/* Filters */}
      <div className="space-y-3">
        {/* Type filter pills */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => { setFilterType(''); setPage(1) }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              !filterType ? 'bg-primary text-white' : 'bg-card border border-border text-text-secondary hover:text-text-primary'
            }`}
          >
            Alle
          </button>
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => { setFilterType(filterType === t ? '' : t); setPage(1) }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                filterType === t ? TYPE_COLORS[t] : 'bg-card border-border text-text-secondary hover:text-text-primary'
              }`}
            >
              {TYPE_LABELS[t]}
            </button>
          ))}

          <div className="flex-1" />

          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Suchen..."
              aria-label="Transaktionen durchsuchen"
              className={`${INPUT} pl-8 w-44 h-[30px] text-xs`}
            />
            {searchInput && (
              <button
                onClick={() => { setSearchInput(''); setSearchQuery(''); setPage(1) }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                aria-label="Suche löschen"
              >
                <X size={12} />
              </button>
            )}
          </div>

          <button
            onClick={() => setShowFilters(!showFilters)}
            aria-expanded={showFilters}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              showFilters || hasFilters
                ? 'bg-primary/10 text-primary border-primary/30'
                : 'bg-card border-border text-text-muted hover:text-text-primary'
            }`}
          >
            <Filter size={13} />
            Filter
            {hasFilters && <span className="w-1.5 h-1.5 rounded-full bg-primary" />}
          </button>
        </div>

        {/* Extended filters */}
        {showFilters && (
          <div className="flex items-end gap-3 flex-wrap rounded-lg border border-border bg-card-alt/30 p-4">
            <div>
              <label className={LABEL}>Ticker</label>
              <div className="relative">
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
                <input
                  value={filterTicker}
                  onChange={(e) => { setFilterTicker(e.target.value); setPage(1) }}
                  placeholder="z.B. WM"
                  className={`${INPUT} pl-8 w-32`}
                />
              </div>
            </div>
            <div>
              <label className={LABEL}>Von</label>
              <DateInput
                value={filterDateFrom}
                onChange={(v) => { setFilterDateFrom(v); setPage(1) }}
                className={`${INPUT} w-40`}
              />
            </div>
            <div>
              <label className={LABEL}>Bis</label>
              <DateInput
                value={filterDateTo}
                onChange={(v) => { setFilterDateTo(v); setPage(1) }}
                className={`${INPUT} w-40`}
              />
            </div>
            {hasFilters && (
              <button
                onClick={resetFilters}
                className="text-xs text-danger hover:underline pb-2"
              >
                Zurücksetzen
              </button>
            )}
          </div>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="p-12">
          <LoadingSpinner />
        </div>
      ) : !data?.items?.length ? (
        <div className="rounded-lg border border-border bg-card p-12 text-center">
          {hasFilters ? (
            <p className="text-text-muted text-sm">Keine Transaktionen für diese Filter.</p>
          ) : (
            <>
              <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
                <Upload className="w-7 h-7 text-primary" />
              </div>
              <h3 className="text-base font-semibold text-text-primary mb-1">Noch keine Transaktionen</h3>
              <p className="text-sm text-text-muted mb-5 max-w-md mx-auto">
                Importiere deine Transaktionen per CSV-Datei oder erfasse sie manuell.
              </p>
              <div className="flex gap-3 justify-center">
                <button
                  onClick={() => setShowImport(true)}
                  className="px-4 py-2 text-sm rounded-lg font-medium bg-primary text-white hover:bg-primary/90 transition-colors flex items-center gap-2"
                >
                  <Upload className="w-4 h-4" />
                  CSV importieren
                </button>
                <button
                  onClick={() => setShowModal(true)}
                  className="px-4 py-2 text-sm rounded-lg border border-border text-text-secondary hover:bg-card-alt transition-colors flex items-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  Manuell erfassen
                </button>
              </div>
              <p className="text-xs text-text-muted mt-4">
                Unterstützte Formate: Swissquote, IBKR, Pocket, Relai, oder universelles CSV
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-text-muted">
                  <th className="text-left p-3 font-medium">Datum</th>
                  <th className="text-left p-3 font-medium">Typ</th>
                  <th className="text-left p-3 font-medium">Ticker</th>
                  <th className="text-right p-3 font-medium">Anzahl</th>
                  <th className="text-right p-3 font-medium">Preis</th>
                  <th className="text-center p-3 font-medium">Whg</th>
                  <th className="text-right p-3 font-medium">FX</th>
                  <th className="text-right p-3 font-medium">Total CHF</th>
                  <th className="text-right p-3 font-medium">Gebühren</th>
                  <th className="text-left p-3 font-medium">Notizen</th>
                  <th className="p-3 w-20" />
                </tr>
              </thead>
              <tbody>
                {data.items.map((t) => (
                  <tr key={t.id} className="border-b border-border/50 hover:bg-card-alt/50 transition-colors group">
                    <td className="p-3 text-text-primary whitespace-nowrap tabular-nums">{formatDate(t.date)}</td>
                    <td className="p-3"><TypeBadge type={t.type} /></td>
                    <td className="p-3">
                      <span className="font-mono text-primary font-medium">{t.ticker}</span>
                      <span className="text-text-muted text-xs ml-1.5 hidden lg:inline">{t.position_name}</span>
                    </td>
                    <td className="p-3 text-right text-text-primary tabular-nums">
                      {formatNumber(t.shares, t.shares % 1 ? 4 : 0)}
                    </td>
                    <td className="p-3 text-right text-text-secondary tabular-nums">
                      {t.price_per_share > 0 ? formatNumber(t.price_per_share, 2) : '–'}
                    </td>
                    <td className="p-3 text-center text-text-muted text-xs">{t.currency}</td>
                    <td className="p-3 text-right text-text-muted tabular-nums text-xs">
                      {t.fx_rate_to_chf !== 1 ? t.fx_rate_to_chf.toFixed(4) : '–'}
                    </td>
                    <td className="p-3 text-right text-text-primary font-medium tabular-nums">
                      {formatCHFExact(t.total_chf)}
                    </td>
                    <td className="p-3 text-right text-text-muted tabular-nums text-xs">
                      {t.fees_chf > 0 ? formatCHFExact(t.fees_chf) : '—'}
                    </td>
                    <td className="p-3 text-text-muted text-xs max-w-[150px] truncate" title={t.notes || ''}>
                      {t.notes || '–'}
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-0.5 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => setEditTxn(t)}
                          className="p-1.5 rounded text-text-muted hover:text-primary hover:bg-primary/10 transition-colors"
                          title="Bearbeiten"
                          aria-label="Bearbeiten"
                        >
                          <Edit3 size={13} />
                        </button>
                        <button
                          onClick={() => setDeleteTxn(t)}
                          className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors"
                          title="Löschen"
                          aria-label="Löschen"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="p-3 border-t border-border flex items-center justify-between text-sm">
            <span className="text-text-muted">
              {data.total} Transaktion{data.total !== 1 ? 'en' : ''}
              {hasFilters && ' (gefiltert)'}
            </span>
            {data.pages > 1 && (
              <div className="flex items-center gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                  className="px-3 py-1 rounded-lg bg-card-alt text-text-secondary hover:text-text-primary disabled:opacity-40 transition-colors text-xs"
                >
                  Zurück
                </button>
                <span className="text-text-secondary text-xs tabular-nums px-2">
                  {page} / {data.pages}
                </span>
                <button
                  disabled={page >= data.pages}
                  onClick={() => setPage(page + 1)}
                  className="px-3 py-1 rounded-lg bg-card-alt text-text-secondary hover:text-text-primary disabled:opacity-40 transition-colors text-xs"
                >
                  Weiter
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* New Transaction Modal */}
      {showModal && (
        <TransactionModal
          positions={positions}
          onSave={handleCreate}
          onClose={() => setShowModal(false)}
        />
      )}

      {/* Edit Transaction Modal */}
      {editTxn && (
        <TransactionModal
          positions={positions}
          initial={editTxn}
          onSave={handleUpdate}
          onClose={() => setEditTxn(null)}
        />
      )}

      {/* Import Wizard */}
      {showImport && (
        <ImportWizard
          onClose={() => setShowImport(false)}
          onSuccess={() => { refetch(); refetchPortfolio() }}
        />
      )}

      {/* Delete Confirmation */}
      {deleteTxn && (
        <DeleteConfirm
          txn={deleteTxn}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTxn(null)}
        />
      )}
    </div>
  )
}
