import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePortfolioData } from '../contexts/DataContext'
import { useApi, apiPost, apiPut, apiDelete } from '../hooks/useApi'
import { formatCHFExact, formatNumber, formatDate } from '../lib/format'
import {
  Plus, X, Loader2, Trash2, Edit3, Search, Filter, Upload, RefreshCw,
} from 'lucide-react'
import ImportWizard from '../components/ImportWizard'
import useFocusTrap from '../hooks/useFocusTrap'
import useScrollLock from '../hooks/useScrollLock'
import LoadingSpinner from '../components/LoadingSpinner'
import G from '../components/GlossarTooltip'
import DateInput from '../components/DateInput'
import TransactionCreateModal from '../components/TransactionCreateModal'
import PageHeader from '../components/ui/PageHeader'
import StatTile from '../components/ui/StatTile'
import FilterChips from '../components/ui/FilterChips'
import Button from '../components/ui/Button'
import TickerChip from '../components/ui/TickerChip'

const TYPE_LABELS = {
  buy: 'Kauf', sell: 'Verkauf', dividend: 'Dividende', fee: 'Gebühren',
  deposit: 'Einzahlung', withdrawal: 'Auszahlung',
  capital_gain: 'Kapitalgewinn', interest: 'Zinsertrag',
  fx_credit: 'FX Gutschrift', fx_debit: 'FX Belastung',
  fee_correction: 'Gebühren', tax: 'Steuer', tax_refund: 'Steuererstattung',
}
const TYPE_COLORS = {
  buy: 'bg-success/15 text-success', sell: 'bg-danger/15 text-danger',
  dividend: 'bg-success/15 text-success', fee: 'bg-text-muted/15 text-text-muted',
  deposit: 'bg-etf/15 text-etf', withdrawal: 'bg-text-muted/15 text-text-muted',
  capital_gain: 'bg-success/15 text-success', interest: 'bg-primary/15 text-primary',
  fx_credit: 'bg-text-muted/15 text-text-muted', fx_debit: 'bg-text-muted/15 text-text-muted',
  fee_correction: 'bg-text-muted/15 text-text-muted', tax: 'bg-danger/15 text-danger',
  tax_refund: 'bg-success/15 text-success',
}
const TYPES = ['buy', 'sell', 'dividend', 'fee_correction', 'capital_gain', 'deposit', 'withdrawal']

const INPUT = 'bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors'
const LABEL = 'block text-xs font-medium text-text-muted mb-1'

function TypeBadge({ type }) {
  return (
    <span className={`inline-block px-[7px] py-[3px] rounded-[5px] text-[10.5px] font-medium leading-none ${TYPE_COLORS[type] || TYPE_COLORS.fee}`}>
      {TYPE_LABELS[type] || type}
    </span>
  )
}

function DeleteConfirm({ txn, onConfirm, onCancel }) {
  const [deleting, setDeleting] = useState(false)
  const deleteTrapRef = useFocusTrap(true)
  useScrollLock(true)
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#04070c]/[0.72] backdrop-blur-sm" onClick={onCancel}>
      <div ref={deleteTrapRef} role="dialog" aria-modal="true" aria-label="Transaktion löschen" className="bg-modal border border-danger/40 rounded-[14px] shadow-2xl w-full max-w-sm mx-4 p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-text-primary mb-2">Transaktion löschen?</h3>
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
            onClick={async () => { setDeleting(true); await onConfirm() }}
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

function SummaryStats({ data }) {
  if (!data?.items?.length) return null
  const items = data.items
  const totalBuy = items.filter((t) => t.type === 'buy').reduce((s, t) => s + t.total_chf, 0)
  const totalSell = items.filter((t) => t.type === 'sell').reduce((s, t) => s + t.total_chf, 0)
  const totalDiv = items.filter((t) => t.type === 'dividend').reduce((s, t) => s + t.total_chf, 0)
  const totalFees = items.reduce((s, t) => s + (t.fees_chf || 0), 0)

  const stats = [
    { label: 'Transaktionen', value: data.total, tone: 'default' },
    { label: 'Käufe', value: formatCHFExact(totalBuy), tone: 'success' },
    { label: 'Verkäufe', value: formatCHFExact(totalSell), tone: 'danger' },
    { label: <G term="Dividende">Dividenden</G>, value: formatCHFExact(totalDiv), tone: 'success' },
    { label: 'Gebühren', value: formatCHFExact(totalFees), tone: 'warning' },
  ]
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-[14px]">
      {stats.map((s, i) => <StatTile key={i} {...s} />)}
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

  const handleSearchChange = useCallback((value) => {
    setSearchInput(value)
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => { setSearchQuery(value); setPage(1) }, 300)
  }, [])

  useEffect(() => () => clearTimeout(searchTimer.current), [])

  const qs = useMemo(() => {
    const params = [`page=${page}`]
    if (filterType) params.push(`type=${filterType}`)
    if (filterTicker) params.push(`ticker=${filterTicker}`)
    if (filterDateFrom) params.push(`date_from=${filterDateFrom}`)
    if (filterDateTo) params.push(`date_to=${filterDateTo}`)
    if (searchQuery) params.push(`search=${encodeURIComponent(searchQuery)}`)
    return params.join('&')
  }, [page, filterType, filterTicker, filterDateFrom, filterDateTo, searchQuery])

  const { data, loading, error, refetch } = useApi(`/transactions?${qs}`)
  const { data: positions } = useApi('/portfolio/positions')

  const [showModal, setShowModal] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editTxn, setEditTxn] = useState(null)
  const [deleteTxn, setDeleteTxn] = useState(null)

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
    setShowModal(false); refetch(); refetchPortfolio()
  }
  const handleUpdate = async (formData) => {
    await apiPut(`/transactions/${editTxn.id}`, formData)
    setEditTxn(null); refetch(); refetchPortfolio()
  }
  const handleDelete = async () => {
    await apiDelete(`/transactions/${deleteTxn.id}`)
    setDeleteTxn(null); refetch(); refetchPortfolio()
  }

  const resetFilters = () => {
    setFilterType(''); setFilterTicker(''); setFilterDateFrom(''); setFilterDateTo('')
    setSearchInput(''); setSearchQuery(''); setPage(1)
  }

  const hasFilters = filterType || filterTicker || filterDateFrom || filterDateTo || searchQuery

  const typeOptions = [{ key: '', label: 'Alle' }, ...TYPES.map((t) => ({ key: t, label: TYPE_LABELS[t] }))]

  return (
    <div className="pb-10">
      <PageHeader
        title="Transaktionen"
        subtitle="Ledger aller Buchungen"
        actions={
          <>
            <Button variant="secondary" icon={Upload} onClick={() => setShowImport(true)}>Batch-Import</Button>
            <Button variant="primary" icon={Plus} onClick={() => setShowModal(true)}>Buchung</Button>
          </>
        }
        showBell={false}
      />

      <div className="flex flex-col gap-4">
        <SummaryStats data={data} />

        {/* Filters */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <FilterChips
              options={typeOptions}
              value={filterType}
              onChange={(k) => { setFilterType(k === filterType && k !== '' ? '' : k); setPage(1) }}
            />
            <div className="flex-1" />
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                value={searchInput}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="Suchen..."
                aria-label="Transaktionen durchsuchen"
                className={`${INPUT} pl-8 w-44 h-[34px] text-xs`}
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
              className={`flex items-center gap-1.5 px-3 py-[7px] rounded-lg text-[12.5px] font-medium border transition-colors ${
                showFilters || hasFilters
                  ? 'bg-active-tint text-text-bright border-border-active'
                  : 'bg-surface border-border-2 text-text-muted hover:border-border-hover'
              }`}
            >
              <Filter size={13} />
              Filter
              {hasFilters && <span className="w-1.5 h-1.5 rounded-full bg-primary" />}
            </button>
          </div>

          {showFilters && (
            <div className="flex items-end gap-3 flex-wrap rounded-card border border-border bg-card-2 p-4">
              <div>
                <label className={LABEL}>Ticker</label>
                <div className="relative">
                  <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input
                    aria-label="Ticker filtern"
                    value={filterTicker}
                    onChange={(e) => { setFilterTicker(e.target.value); setPage(1) }}
                    placeholder="z.B. WM"
                    className={`${INPUT} pl-8 w-32`}
                  />
                </div>
              </div>
              <div>
                <label className={LABEL}>Von</label>
                <DateInput value={filterDateFrom} onChange={(v) => { setFilterDateFrom(v); setPage(1) }} className={`${INPUT} w-40`} />
              </div>
              <div>
                <label className={LABEL}>Bis</label>
                <DateInput value={filterDateTo} onChange={(v) => { setFilterDateTo(v); setPage(1) }} className={`${INPUT} w-40`} />
              </div>
              {hasFilters && (
                <button onClick={resetFilters} className="text-xs text-danger hover:underline pb-2">Zurücksetzen</button>
              )}
            </div>
          )}
        </div>

        {/* Table */}
        {loading ? (
          <div className="p-12"><LoadingSpinner /></div>
        ) : error ? (
          <div className="rounded-card border border-danger/30 bg-danger/10 p-6 flex items-center justify-between">
            <span className="text-danger text-sm">Fehler beim Laden: {error}</span>
            <Button variant="primary" icon={RefreshCw} onClick={refetch}>Erneut laden</Button>
          </div>
        ) : !data?.items?.length ? (
          <div className="rounded-card border border-border bg-card p-12 text-center">
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
                  <Button variant="primary" icon={Upload} onClick={() => setShowImport(true)}>CSV importieren</Button>
                  <Button variant="secondary" icon={Plus} onClick={() => setShowModal(true)}>Manuell erfassen</Button>
                </div>
                <p className="text-xs text-text-faint mt-4">
                  Unterstützte Formate: Swissquote, IBKR, Pocket, Relai, oder universelles CSV
                </p>
              </>
            )}
          </div>
        ) : (
          <div className="rounded-card border border-border bg-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-table-head border-b border-border-2 font-mono text-[10px] tracking-[0.05em] uppercase text-text-faint">
                    <th className="text-left px-[18px] py-[11px] font-medium">Datum</th>
                    <th className="text-left px-3 py-[11px] font-medium">Typ</th>
                    <th className="text-left px-3 py-[11px] font-medium">Titel</th>
                    <th className="text-right px-3 py-[11px] font-medium">Stück</th>
                    <th className="text-right px-3 py-[11px] font-medium">Kurs</th>
                    <th className="text-center px-3 py-[11px] font-medium">Whg</th>
                    <th className="text-right px-3 py-[11px] font-medium">FX</th>
                    <th className="text-right px-3 py-[11px] font-medium">Betrag CHF</th>
                    <th className="text-right px-3 py-[11px] font-medium">Gebühren CHF</th>
                    <th className="text-left px-3 py-[11px] font-medium">Notizen</th>
                    <th className="px-3 py-[11px] w-20" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((t) => (
                    <tr key={t.id} className="border-b border-border-row hover:bg-hover transition-colors group">
                      <td className="px-[18px] py-3 font-mono text-[11.5px] text-text-secondary whitespace-nowrap">{formatDate(t.date)}</td>
                      <td className="px-3 py-3"><TypeBadge type={t.type} /></td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2.5 min-w-0">
                          {t.ticker && <TickerChip>{t.ticker}</TickerChip>}
                          <span className="text-text-muted text-xs truncate hidden lg:inline">{t.position_name}</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-text-secondary tabular-nums">
                        {t.shares ? formatNumber(t.shares, t.shares % 1 ? 4 : 0) : '—'}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums">
                        {t.price_per_share > 0 ? formatNumber(t.price_per_share, 2) : '—'}
                      </td>
                      <td className="px-3 py-3 text-center text-text-muted text-xs">{t.currency}</td>
                      <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums text-xs">
                        {t.fx_rate_to_chf !== 1 ? t.fx_rate_to_chf.toFixed(4) : '—'}
                      </td>
                      <td className={`px-3 py-3 text-right font-mono font-medium tabular-nums ${t.total_chf < 0 ? 'text-danger' : 'text-text-primary'}`}>
                        {formatNumber(t.total_chf, 2)}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-text-muted tabular-nums text-xs">
                        {t.fees_chf > 0 ? formatNumber(t.fees_chf, 2) : '—'}
                      </td>
                      <td className="px-3 py-3 text-text-muted text-xs max-w-[150px] truncate" title={t.notes || ''}>
                        {t.notes || '–'}
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-0.5 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
                          <button onClick={() => setEditTxn(t)} className="p-1.5 rounded text-text-muted hover:text-primary hover:bg-primary/10 transition-colors" title="Bearbeiten" aria-label="Bearbeiten">
                            <Edit3 size={13} />
                          </button>
                          <button onClick={() => setDeleteTxn(t)} className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors" title="Löschen" aria-label="Löschen">
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="px-[18px] py-3 border-t border-border-2 flex items-center justify-between text-sm">
              <span className="text-text-muted text-xs">
                {data.total} Transaktion{data.total !== 1 ? 'en' : ''}{hasFilters && ' (gefiltert)'}
              </span>
              {data.pages > 1 && (
                <div className="flex items-center gap-2">
                  <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="px-3 py-1 rounded-lg bg-surface border border-border-2 text-text-secondary hover:border-border-hover disabled:opacity-40 transition-colors text-xs">Zurück</button>
                  <span className="text-text-secondary text-xs font-mono tabular-nums px-2">{page} / {data.pages}</span>
                  <button disabled={page >= data.pages} onClick={() => setPage(page + 1)} className="px-3 py-1 rounded-lg bg-surface border border-border-2 text-text-secondary hover:border-border-hover disabled:opacity-40 transition-colors text-xs">Weiter</button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {showModal && (
        <TransactionCreateModal positions={positions} onSave={handleCreate} onClose={() => setShowModal(false)} />
      )}
      {editTxn && (
        <TransactionCreateModal positions={positions} initial={editTxn} onSave={handleUpdate} onClose={() => setEditTxn(null)} />
      )}
      {showImport && (
        <ImportWizard onClose={() => setShowImport(false)} onSuccess={() => { refetch(); refetchPortfolio() }} />
      )}
      {deleteTxn && (
        <DeleteConfirm txn={deleteTxn} onConfirm={handleDelete} onCancel={() => setDeleteTxn(null)} />
      )}
    </div>
  )
}
